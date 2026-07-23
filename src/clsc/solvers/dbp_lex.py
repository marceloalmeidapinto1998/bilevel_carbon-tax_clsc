from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import time

from clsc.config.gap_tol import DEFAULT
from clsc.models.instance import SCALE_FACTOR, InstanceData
from clsc.models.subproblems import (
    DbpFollowerCut,
    FixedTaxFollowerMaster,
    SolveResult,
    add_dbp_relaxation_cut,
    build_dbp_relaxation_master,
    build_fixed_tax_follower_master,
    lex_freeze_tolerance,
    set_dbp_relaxation_objective_upper_bound,
    solve_dbp_relaxation_lexicographic,
    solve_fixed_tax_lexicographic,
)


STAGNATION_GAP_NOT_CLOSED_REASON = "stagnation_limit_gap_not_closed"


# ---------------------------------------------------------------------------
# Shared dataclasses and result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class IncumbentSolution:
    tax_index: int
    cost: float
    emissions: float
    follower_objective: float
    # Grid step used to convert tax_index -> rate; the solving instance's own
    # scale_factor (see InstanceData.scale_factor), so a finer grid reports the
    # correct rate. Defaults to the module constant for legacy callers/tests.
    scale_factor: float = SCALE_FACTOR

    @property
    def tax_rate(self) -> float:
        """Real carbon tax rate (USD/kg CO2e) for this solution's ``tax_index``."""
        return self.scale_factor * self.tax_index


@dataclass(frozen=True, slots=True)
class TaxSolveSnapshot:
    iteration: int
    tax_index: int
    solve_seconds: float
    objective_value: float | None
    cost: float
    emissions: float
    follower_objective: float
    mip_gap: float | None
    scale_factor: float = SCALE_FACTOR
    lex_primary_mip_gap: float | None = None
    lex_secondary_mip_gap: float | None = None
    variable_values: dict[str, float] | None = None

    @property
    def tax_rate(self) -> float:
        """Real carbon tax rate (USD/kg CO2e) for this solution's ``tax_index``."""
        return self.scale_factor * self.tax_index


@dataclass(frozen=True, slots=True)
class BoundCertificate:
    value: float
    exact: bool
    mip_gap: float | None
    slack: float | None
    source: str


@dataclass(frozen=True, slots=True)
class DbpIterationRecord:
    iteration: int
    relaxation_tax_index: int
    relaxation_lower_bound: float
    follower_seconds: float
    follower_objective: float
    optimistic_seconds: float
    optimistic_cost: float
    optimistic_emissions: float
    incumbent_emissions: float
    relaxation_seconds: float
    next_relaxation_tax_index: int
    next_relaxation_lower_bound: float


@dataclass(frozen=True, slots=True)
class DbpIterationTiming:
    iteration: int
    follower_seconds: float
    optimistic_seconds: float
    relaxation_seconds: float


@dataclass(frozen=True, slots=True)
class DbpTimingSummary:
    initial_relaxation_seconds: float
    follower_total_seconds: float
    optimistic_total_seconds: float
    iterative_relaxation_total_seconds: float
    relaxation_total_seconds: float
    total_subproblem_seconds: float
    iteration_timings: tuple[DbpIterationTiming, ...]


@dataclass(frozen=True, slots=True)
class BilevelSolveResult:
    method: str
    mode: str
    termination_reason: str
    exact: bool
    iterations: int
    lower_bound: float
    upper_bound: float
    lower_bound_certificate: BoundCertificate
    upper_bound_certificate: BoundCertificate
    incumbent: IncumbentSolution
    iteration_records: tuple[DbpIterationRecord, ...]
    dbp_timing: DbpTimingSummary
    incumbent_solution: SolveResult | None = None
    enumeration_solutions: tuple[TaxSolveSnapshot, ...] = ()


class BilevelSolveError(RuntimeError):
    """Raised when the DBP workflow cannot justify a publication-safe result."""


class SubproblemStatusError(BilevelSolveError):
    def __init__(
        self,
        label: str,
        result: SolveResult,
        *,
        trace_rows: tuple[dict[str, object], ...] = (),
    ) -> None:
        self.label = label
        self.result = result
        self.trace_rows = trace_rows
        status_history = result.status_history or (result.status_name,)
        details = [f"status={' -> '.join(status_history)}", f"has_solution={result.has_solution}"]
        if result.objective_bound is not None:
            details.append(f"objective_bound={result.objective_bound}")
        if result.mip_gap is not None:
            details.append(f"mip_gap={result.mip_gap}")
        super().__init__(f"{label} requires OPTIMAL status ({', '.join(details)})")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def relative_optimality_gap(
    *,
    upper_bound: float,
    lower_bound: float,
) -> float:
    gap = max(0.0, upper_bound - lower_bound)
    return gap / max(1.0, abs(upper_bound))


def follower_objective_cap(follower_objective: float, mip_gap: float | None = None) -> float:
    return follower_objective + lex_freeze_tolerance(follower_objective, mip_gap)


def _coerce_instance(instance_or_path: InstanceData | str | Path) -> InstanceData:
    if isinstance(instance_or_path, InstanceData):
        return instance_or_path
    return InstanceData.from_file(instance_or_path)


def _is_better_candidate(candidate: IncumbentSolution, incumbent: IncumbentSolution | None) -> bool:
    """Leader-level incumbent comparator: lexmin(emissions, tax_index), per eq:leader_obj
    (paper/sections/04b_leader.tex). Each candidate's emissions value already reflects the
    follower's optimistic (as:opt) tie-break for its own tax_index, so no further
    follower_objective tier belongs here. See ``_emissions_tie_tolerance``."""
    if incumbent is None:
        return True
    tolerance = _emissions_tie_tolerance(candidate.emissions, incumbent.emissions)
    if candidate.emissions < incumbent.emissions - tolerance:
        return True
    if math.isclose(candidate.emissions, incumbent.emissions, abs_tol=tolerance):
        return candidate.tax_index < incumbent.tax_index
    return False


def _emissions_tie_tolerance(first_emissions: float, second_emissions: float) -> float:
    """Magnitude-scaled tolerance for comparing two emissions values.

    Emissions are reported on raw kg-CO2e scale (commonly 1e7-1e8 for the
    project's instances), where a bare ``DEFAULT.eps`` (1e-7 absolute) sits
    far below the floating-point reconstruction noise floor between two
    independently built Gurobi models -- effectively never detecting a tie
    that should be one. Scaling by the values' own magnitude, the same
    pattern used by ``lex_freeze_tolerance``, keeps the tolerance meaningful
    regardless of instance scale.
    """
    return max(
        DEFAULT.eps,
        DEFAULT.eps * max(abs(first_emissions), abs(second_emissions)),
    )


def _classify_stagnation_stop(
    *,
    upper_bound: float,
    lower_bound: float,
    dbp_relative_gap: float | None = None,
) -> tuple[str, bool]:
    achieved_gap = relative_optimality_gap(upper_bound=upper_bound, lower_bound=lower_bound)
    threshold = DEFAULT.dbp_relative_gap if dbp_relative_gap is None else dbp_relative_gap
    if achieved_gap <= threshold:
        return "relative_gap", True
    return STAGNATION_GAP_NOT_CLOSED_REASON, False


def _with_stagnation_context(certificate: BoundCertificate) -> BoundCertificate:
    return BoundCertificate(
        value=certificate.value,
        exact=certificate.exact,
        mip_gap=certificate.mip_gap,
        slack=certificate.slack,
        source=f"{certificate.source}_stagnation_limit",
    )


def _require_optimal_result(result: SolveResult, label: str) -> None:
    if not result.has_solution or result.status_name != "OPTIMAL":
        raise SubproblemStatusError(label, result)


def _build_time_limit_result(
    *,
    incumbent: IncumbentSolution,
    incumbent_solution: SolveResult | None,
    upper_bound_certificate: BoundCertificate,
    best_lower_bound: float,
    iteration: int,
    iteration_records: list[DbpIterationRecord],
    iteration_timings: list[DbpIterationTiming],
    initial_relaxation_seconds: float,
) -> BilevelSolveResult:
    """Return the best incumbent found so far when a subproblem hits the time limit.

    The lower bound is the last value certified by an OPTIMAL relaxation; the gap
    may therefore be non-zero.  ``exact=False`` signals that the result is not a
    provably optimal bilevel solution.
    """
    return _build_bilevel_result(
        method="dbp_lex",
        mode="exact",
        termination_reason="time_limit",
        exact=False,
        iterations=iteration,
        lower_bound=best_lower_bound,
        upper_bound=incumbent.emissions,
        lower_bound_certificate=BoundCertificate(
            value=best_lower_bound,
            exact=True,
            mip_gap=None,
            slack=0.0,
            source="relaxation",
        ),
        upper_bound_certificate=upper_bound_certificate,
        incumbent=incumbent,
        iteration_records=tuple(iteration_records),
        dbp_timing=_build_dbp_timing_summary(
            initial_relaxation_seconds=initial_relaxation_seconds,
            iteration_timings=tuple(iteration_timings),
        ),
        incumbent_solution=incumbent_solution,
    )


def _required_value(value: float | int | None, label: str) -> float | int:
    if value is None:
        raise RuntimeError(f"Missing value for {label}")
    return value


def _solve_with_wall_time(solver_fn, *args, **kwargs):
    started_at = time.perf_counter()
    result = solver_fn(*args, **kwargs)
    return result, round(time.perf_counter() - started_at, 6)


def _build_bilevel_result(
    *,
    method: str,
    mode: str,
    termination_reason: str,
    exact: bool,
    iterations: int,
    lower_bound: float,
    upper_bound: float,
    lower_bound_certificate: BoundCertificate,
    upper_bound_certificate: BoundCertificate,
    incumbent: IncumbentSolution,
    iteration_records: tuple[DbpIterationRecord, ...],
    dbp_timing: DbpTimingSummary,
    incumbent_solution: SolveResult | None,
    enumeration_solutions: tuple[TaxSolveSnapshot, ...] = (),
) -> BilevelSolveResult:
    return BilevelSolveResult(
        method=method,
        mode=mode,
        termination_reason=termination_reason,
        exact=exact,
        iterations=iterations,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        lower_bound_certificate=lower_bound_certificate,
        upper_bound_certificate=upper_bound_certificate,
        incumbent=incumbent,
        iteration_records=iteration_records,
        dbp_timing=dbp_timing,
        incumbent_solution=incumbent_solution,
        enumeration_solutions=enumeration_solutions,
    )


def _build_dbp_timing_summary(
    *,
    initial_relaxation_seconds: float,
    iteration_timings: tuple[DbpIterationTiming, ...],
) -> DbpTimingSummary:
    follower_total_seconds = round(sum(record.follower_seconds for record in iteration_timings), 6)
    optimistic_total_seconds = round(sum(record.optimistic_seconds for record in iteration_timings), 6)
    iterative_relaxation_total_seconds = round(sum(record.relaxation_seconds for record in iteration_timings), 6)
    relaxation_total_seconds = round(initial_relaxation_seconds + iterative_relaxation_total_seconds, 6)
    total_subproblem_seconds = round(
        follower_total_seconds + optimistic_total_seconds + relaxation_total_seconds,
        6,
    )
    return DbpTimingSummary(
        initial_relaxation_seconds=initial_relaxation_seconds,
        follower_total_seconds=follower_total_seconds,
        optimistic_total_seconds=optimistic_total_seconds,
        iterative_relaxation_total_seconds=iterative_relaxation_total_seconds,
        relaxation_total_seconds=relaxation_total_seconds,
        total_subproblem_seconds=total_subproblem_seconds,
        iteration_timings=iteration_timings,
    )


# ---------------------------------------------------------------------------
# Phase 2: least-intervention tax bisection
# ---------------------------------------------------------------------------

# Phase 2 always solves the follower tightly: emissions must be accurate enough
# to separate the floor config from the one just above it (their gap sets the
# tax's identifiability), and a loose gap would bias emissions via the freeze
# amplification. This is independent of the loop's own ``mip_gap``.
_REFINE_MIP_GAP = 1e-6
# Two emissions are "the same floor" within this relative tolerance -- looser
# than the tight follower's numerical noise, tighter than a genuine config gap.
_REFINE_TIE_REL = 1e-4


def _bisect_min_tax(
    follower_master: FixedTaxFollowerMaster,
    e_star: float,
    *,
    lo: int,
    hi: int,
    threads: int | None,
    mip_focus: int | None,
    time_limit: float | None,
    seed: int | None = None,
    use_warm_start: bool = True,
) -> int:
    """Smallest tax_index in ``[lo, hi]`` whose follower response reaches the
    certified emissions floor ``e_star``, assuming P(hi) is True. Binary search
    over the monotone predicate ``emissions(idx) <= e_star + tol`` -- ~log2(hi-lo)
    follower solves."""
    tol = max(DEFAULT.eps, _REFINE_TIE_REL * abs(e_star))
    warm: dict[str, float] | None = None

    def at_floor(idx: int) -> bool:
        nonlocal warm
        result = solve_fixed_tax_lexicographic(
            follower_master,
            tax_index=idx,
            time_limit=time_limit,
            mip_gap=_REFINE_MIP_GAP,
            threads=threads,
            mip_focus=mip_focus,
            seed=seed,
            capture_solution=True,
            warm_start_values=warm if use_warm_start else None,  # adjacent taxes share near-identical solutions
        )
        if not result.has_solution or result.status_name != "OPTIMAL" or result.emissions is None:
            # Can't confirm the floor here -> treat as NOT at floor, which keeps
            # the reported tax higher (conservative: never under-reports tau*).
            return False
        if result.variable_values is not None:
            warm = result.variable_values
        return result.emissions <= e_star + tol

    if at_floor(lo):
        return lo
    # Invariant: P(lo) False, P(hi) True. Narrow to adjacent indices.
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if at_floor(mid):
            hi = mid
        else:
            lo = mid
    return hi


def _refine_min_tax(
    follower_master: FixedTaxFollowerMaster,
    instance: InstanceData,
    incumbent: IncumbentSolution,
    incumbent_solution: SolveResult | None,
    *,
    threads: int | None,
    mip_focus: int | None,
    time_limit: float | None,
    seed: int | None = None,
    use_warm_start: bool = True,
) -> tuple[IncumbentSolution, SolveResult | None]:
    """Phase 2 wrapper: bisect for the smallest tax reaching the incumbent's
    (certified-minimum) emissions, and re-report the incumbent at that tax.
    Leaves emissions unchanged (still E*); only lowers the tax. No-op when the
    incumbent is already at the lower grid bound."""
    lower_index = instance.lower_tax_index
    if incumbent.tax_index <= lower_index:
        return incumbent, incumbent_solution

    tau_star = _bisect_min_tax(
        follower_master,
        incumbent.emissions,
        lo=lower_index,
        hi=incumbent.tax_index,
        threads=threads,
        mip_focus=mip_focus,
        time_limit=time_limit,
        seed=seed,
        use_warm_start=use_warm_start,
    )
    if tau_star >= incumbent.tax_index:
        return incumbent, incumbent_solution

    refined = solve_fixed_tax_lexicographic(
        follower_master,
        tax_index=tau_star,
        capture_solution=True,
        mip_gap=_REFINE_MIP_GAP,
        threads=threads,
        mip_focus=mip_focus,
        time_limit=time_limit,
        seed=seed,
    )
    if not refined.has_solution or refined.status_name != "OPTIMAL":
        return incumbent, incumbent_solution

    new_incumbent = IncumbentSolution(
        tax_index=tau_star,
        cost=_required_value(refined.cost, "refined cost"),
        emissions=_required_value(refined.emissions, "refined emissions"),
        follower_objective=_required_value(refined.follower_objective, "refined follower objective"),
        scale_factor=instance.scale_factor,
    )
    return new_incumbent, refined


# ---------------------------------------------------------------------------
# DBP lexicographic solver (leader minimises emissions then tax_index)
# ---------------------------------------------------------------------------

def solve_bilevel_dbp_lex(
    instance_or_path: InstanceData | str | Path,
    *,
    max_iterations: int | None = None,
    output_flag: bool = False,
    time_limit: float | None = None,
    mip_gap: float | None = None,
    dbp_relative_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
    refine_min_tax: bool = True,
    seed: int | None = None,
    use_warm_start: bool = True,
    use_incumbent_cut: bool = True,
    use_lex_master_stage2: bool = True,
) -> BilevelSolveResult:
    """DBP with the leader's lexicographic objective: minimise emissions
    (Phase 1, the DBP loop below), then minimise ``tax_index`` among the
    emissions-tied candidates (Phase 2, a bisection appended after the loop).

    Phase 1 squeezes a lower bound (from the relaxation master) against an upper
    bound (from the follower) until the emissions gap closes, CERTIFYING the
    minimum emissions E*. But that certificate is silent about the tax: the
    incumbent's tax is just the last one evaluated, an UPPER bound on the true
    least-intervention tax (the loop can terminate before ever proposing a
    smaller tax that also reaches E*).

    Phase 2 (``refine_min_tax=True``, the default) fixes this. Because the
    follower's optimistic emissions are non-increasing in the tax, the predicate
    "emissions(tax) == E*" is monotone, so the smallest grid tax reaching E* is
    found by a bisection over ``[lower_tax_index, incumbent.tax_index]`` -- about
    log2 follower solves. Only runs on the two EXACT exits (emissions gap closed
    / INFEASIBLE certificate); time-limit and stagnation exits keep the raw
    incumbent. Set ``refine_min_tax=False`` for the un-refined behaviour.

    ``mip_gap``/``threads``/``mip_focus`` override the corresponding
    :class:`clsc.config.gap_tol.ToleranceConfig` default (``None`` keeps the
    default) for every Gurobi sub-solve. ``dbp_relative_gap`` overrides the
    DBP loop's own outer stopping criterion the same way -- it is unrelated
    to any Gurobi parameter.

    ``seed`` sets the Gurobi ``Seed`` parameter on every sub-solve (MIP
    performance-variability probes; Exp1/Exp2). The three ``use_*`` flags select
    Experiment-3 ablation variants (all default True = full DBP): ``use_warm_start``
    (A3) warm-starts successive follower solves; ``use_incumbent_cut`` (A5) tightens
    the relaxation master with the incumbent's emissions as an objective upper bound;
    ``use_lex_master_stage2`` (A2) runs the master's lexicographic Stage-2 tax
    minimisation. Disabling any one leaves the certified emissions optimum unchanged
    but changes the iteration/time path (and, for A2 without Phase 2, the reported tax).
    """
    instance = _coerce_instance(instance_or_path)
    max_iterations = max_iterations or (len(instance.iter_tax_index()) + 1)
    effective_dbp_relative_gap = DEFAULT.dbp_relative_gap if dbp_relative_gap is None else dbp_relative_gap
    iteration_records: list[DbpIterationRecord] = []
    iteration_timings: list[DbpIterationTiming] = []
    relaxation_master = build_dbp_relaxation_master(instance)
    follower_master = build_fixed_tax_follower_master(instance)

    relaxation, initial_relaxation_seconds = _solve_with_wall_time(
        solve_dbp_relaxation_lexicographic,
        relaxation_master,
        output_flag=output_flag,
        time_limit=time_limit,
        mip_gap=mip_gap,
        threads=threads,
        mip_focus=mip_focus,
        seed=seed,
        lex_stage2=use_lex_master_stage2,
    )
    _require_optimal_result(relaxation, "initial DBP relaxation")

    best_lower_bound = _required_value(relaxation.emissions, "initial relaxation emissions")
    incumbent: IncumbentSolution | None = None
    incumbent_solution = None
    previous_lexicographic_values: dict[str, float] | None = None
    upper_bound_certificate: BoundCertificate | None = None
    iterations_without_bound_update = 0

    for iteration in range(1, max_iterations + 1):
        current_relaxation_lower_bound = best_lower_bound
        tax_index = _required_value(relaxation.tax_index, "relaxation tax_index")

        lexicographic, lexicographic_seconds = _solve_with_wall_time(
            solve_fixed_tax_lexicographic,
            follower_master,
            tax_index=tax_index,
            output_flag=output_flag,
            time_limit=time_limit,
            capture_solution=True,
            warm_start_values=previous_lexicographic_values if use_warm_start else None,
            mip_gap=mip_gap,
            threads=threads,
            mip_focus=mip_focus,
            seed=seed,
        )
        if lexicographic.status_name == "TIME_LIMIT":
            if incumbent is not None:
                iteration_timings.append(DbpIterationTiming(
                    iteration=iteration,
                    follower_seconds=lexicographic_seconds,
                    optimistic_seconds=0.0,
                    relaxation_seconds=0.0,
                ))
                return _build_time_limit_result(
                    incumbent=incumbent,
                    incumbent_solution=incumbent_solution,
                    upper_bound_certificate=upper_bound_certificate,
                    best_lower_bound=best_lower_bound,
                    iteration=len(iteration_records),
                    iteration_records=iteration_records,
                    iteration_timings=iteration_timings,
                    initial_relaxation_seconds=initial_relaxation_seconds,
                )
            raise SubproblemStatusError(
                f"lexicographic follower solve at tax_index={tax_index}", lexicographic,
            )
        _require_optimal_result(lexicographic, f"lexicographic follower solve at tax_index={tax_index}")
        if lexicographic.variable_values is not None:
            previous_lexicographic_values = lexicographic.variable_values

        candidate = IncumbentSolution(
            tax_index=tax_index,
            cost=_required_value(lexicographic.cost, "lexicographic cost"),
            emissions=_required_value(lexicographic.emissions, "lexicographic emissions"),
            follower_objective=_required_value(
                lexicographic.follower_objective,
                "lexicographic follower objective",
            ),
            scale_factor=instance.scale_factor,
        )
        incumbent_updated = _is_better_candidate(candidate, incumbent)
        if incumbent_updated:
            incumbent = candidate
            incumbent_solution = lexicographic
            upper_bound_certificate = BoundCertificate(
                value=candidate.emissions,
                exact=True,
                mip_gap=lexicographic.mip_gap,
                slack=0.0,
                source="lexicographic",
            )

        follower_objective_upper = follower_objective_cap(candidate.follower_objective, lexicographic.mip_gap)
        cut = DbpFollowerCut(
            tax_index=tax_index,
            cost=candidate.cost + max(0.0, follower_objective_upper - candidate.follower_objective),
            emissions=candidate.emissions,
            iteration=iteration,
        )
        add_dbp_relaxation_cut(relaxation_master, cut)
        if use_incumbent_cut:
            set_dbp_relaxation_objective_upper_bound(relaxation_master, incumbent.emissions)

        relaxation, relaxation_seconds = _solve_with_wall_time(
            solve_dbp_relaxation_lexicographic,
            relaxation_master,
            output_flag=output_flag,
            time_limit=time_limit,
            mip_gap=mip_gap,
            threads=threads,
            mip_focus=mip_focus,
            seed=seed,
            lex_stage2=use_lex_master_stage2,
        )
        if relaxation.status_name == "INFEASIBLE" and relaxation_master.objective_upper_bound is not None:
            # The objective upper bound combined with the accumulated DBP and lex
            # emissions cuts leaves no feasible point in the relaxation: every
            # remaining tax_index is provably unable to improve on the current
            # incumbent's emissions.  This is a certificate of optimality — the
            # incumbent IS the global optimum (lower bound = upper bound = 0 gap).
            iteration_timings.append(
                DbpIterationTiming(
                    iteration=iteration,
                    follower_seconds=lexicographic_seconds,
                    optimistic_seconds=0.0,
                    relaxation_seconds=relaxation_seconds,
                )
            )
            if refine_min_tax:
                incumbent, incumbent_solution = _refine_min_tax(
                    follower_master, instance, incumbent, incumbent_solution,
                    threads=threads, mip_focus=mip_focus, time_limit=time_limit,
                    seed=seed, use_warm_start=use_warm_start,
                )
            return _build_bilevel_result(
                method="dbp_lex",
                mode="exact",
                termination_reason="relative_gap",
                exact=True,
                iterations=iteration,
                lower_bound=incumbent.emissions,
                upper_bound=incumbent.emissions,
                lower_bound_certificate=BoundCertificate(
                    value=incumbent.emissions,
                    exact=True,
                    mip_gap=None,
                    slack=0.0,
                    source="relaxation_infeasible",
                ),
                upper_bound_certificate=upper_bound_certificate,
                incumbent=incumbent,
                iteration_records=tuple(iteration_records),
                dbp_timing=_build_dbp_timing_summary(
                    initial_relaxation_seconds=initial_relaxation_seconds,
                    iteration_timings=tuple(iteration_timings),
                ),
                incumbent_solution=incumbent_solution,
            )
        if relaxation.status_name == "TIME_LIMIT":
            # Follower completed OPTIMAL this iteration, so incumbent is guaranteed set.
            return _build_time_limit_result(
                incumbent=incumbent,
                incumbent_solution=incumbent_solution,
                upper_bound_certificate=upper_bound_certificate,
                best_lower_bound=best_lower_bound,
                iteration=iteration,
                iteration_records=iteration_records,
                iteration_timings=iteration_timings,
                initial_relaxation_seconds=initial_relaxation_seconds,
            )
        _require_optimal_result(relaxation, f"DBP relaxation after iteration {iteration}")

        lower_bound = _required_value(relaxation.emissions, "relaxation emissions")
        previous_lower_bound = best_lower_bound
        best_lower_bound = lower_bound
        lower_bound_updated = lower_bound > previous_lower_bound + DEFAULT.eps
        next_tax_index = _required_value(relaxation.tax_index, "next relaxation tax_index")
        iteration_records.append(
            DbpIterationRecord(
                iteration=iteration,
                relaxation_tax_index=tax_index,
                relaxation_lower_bound=current_relaxation_lower_bound,
                follower_seconds=lexicographic_seconds,
                follower_objective=candidate.follower_objective,
                optimistic_seconds=0.0,
                optimistic_cost=candidate.cost,
                optimistic_emissions=candidate.emissions,
                incumbent_emissions=incumbent.emissions,
                relaxation_seconds=relaxation_seconds,
                next_relaxation_tax_index=next_tax_index,
                next_relaxation_lower_bound=best_lower_bound,
            )
        )
        iteration_timings.append(
            DbpIterationTiming(
                iteration=iteration,
                follower_seconds=lexicographic_seconds,
                optimistic_seconds=0.0,
                relaxation_seconds=relaxation_seconds,
            )
        )

        if (
            relative_optimality_gap(
                upper_bound=incumbent.emissions,
                lower_bound=best_lower_bound,
            )
            <= effective_dbp_relative_gap
        ):
            if refine_min_tax:
                incumbent, incumbent_solution = _refine_min_tax(
                    follower_master, instance, incumbent, incumbent_solution,
                    threads=threads, mip_focus=mip_focus, time_limit=time_limit,
                    seed=seed, use_warm_start=use_warm_start,
                )
            return _build_bilevel_result(
                method="dbp_lex",
                mode="exact",
                termination_reason="relative_gap",
                exact=True,
                iterations=iteration,
                lower_bound=best_lower_bound,
                upper_bound=incumbent.emissions,
                lower_bound_certificate=BoundCertificate(
                    value=best_lower_bound,
                    exact=True,
                    mip_gap=relaxation.mip_gap,
                    slack=0.0,
                    source="relaxation",
                ),
                upper_bound_certificate=upper_bound_certificate,
                incumbent=incumbent,
                iteration_records=tuple(iteration_records),
                dbp_timing=_build_dbp_timing_summary(
                    initial_relaxation_seconds=initial_relaxation_seconds,
                    iteration_timings=tuple(iteration_timings),
                ),
                incumbent_solution=incumbent_solution,
            )

        if incumbent_updated or lower_bound_updated:
            iterations_without_bound_update = 0
        else:
            iterations_without_bound_update += 1

        if iterations_without_bound_update >= DEFAULT.stagnation_limit:
            termination_reason, gap_closed = _classify_stagnation_stop(
                upper_bound=incumbent.emissions,
                lower_bound=best_lower_bound,
                dbp_relative_gap=effective_dbp_relative_gap,
            )
            lower_bound_certificate = _with_stagnation_context(
                BoundCertificate(
                    value=best_lower_bound,
                    exact=True,
                    mip_gap=relaxation.mip_gap,
                    slack=0.0,
                    source="relaxation",
                )
            )
            stagnation_upper_bound_certificate = _with_stagnation_context(upper_bound_certificate)
            return _build_bilevel_result(
                method="dbp_lex",
                mode="exact",
                termination_reason=termination_reason,
                exact=gap_closed and lower_bound_certificate.exact and stagnation_upper_bound_certificate.exact,
                iterations=iteration,
                lower_bound=best_lower_bound,
                upper_bound=incumbent.emissions,
                lower_bound_certificate=lower_bound_certificate,
                upper_bound_certificate=stagnation_upper_bound_certificate,
                incumbent=incumbent,
                iteration_records=tuple(iteration_records),
                dbp_timing=_build_dbp_timing_summary(
                    initial_relaxation_seconds=initial_relaxation_seconds,
                    iteration_timings=tuple(iteration_timings),
                ),
                incumbent_solution=incumbent_solution,
            )

    if incumbent is None or upper_bound_certificate is None:
        raise RuntimeError("DBP lexicographic exact terminated without an incumbent solution")

    return _build_bilevel_result(
        method="dbp_lex",
        mode="exact",
        termination_reason="max_iterations",
        exact=False,
        iterations=max_iterations,
        lower_bound=best_lower_bound,
        upper_bound=incumbent.emissions,
        lower_bound_certificate=BoundCertificate(
            value=best_lower_bound,
            exact=True,
            mip_gap=relaxation.mip_gap,
            slack=0.0,
            source="relaxation",
        ),
        upper_bound_certificate=upper_bound_certificate,
        incumbent=incumbent,
        iteration_records=tuple(iteration_records),
        dbp_timing=_build_dbp_timing_summary(
            initial_relaxation_seconds=initial_relaxation_seconds,
            iteration_timings=tuple(iteration_timings),
        ),
        incumbent_solution=incumbent_solution,
    )
