from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import time

from clsc.config.gap_tol import DEFAULT
from clsc.models.instance import SCALE_FACTOR, InstanceData
from clsc.models.subproblems import (
    DbpFollowerCut,
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


def _min_tax_confirmed(
    *,
    incumbent_emissions: float,
    incumbent_tax_index: int,
    best_lower_bound: float,
    next_tax_index: int,
) -> bool:
    """Soares-style confirmation that the incumbent's tax is grid-minimal.

    Two conditions, both required:

    1. The emission bounds have closed to NOISE level (the cross-model tie
       tolerance), not merely to ``dbp_relative_gap``. The master's Stage-2
       minimises the tax over points within a freeze band above its Stage-1
       optimum; only once that optimum sits within tie tolerance of the
       incumbent's emissions does the band provably contain every true point
       tying the certified floor (lem:lb_validity keeps such points feasible),
       making the Stage-2 proposal a valid LOWER bound on the true minimal
       tax. At a looser gap the band can sit strictly below the floor and the
       proposal certifies nothing.
    2. The proposal does not undercut the incumbent (``>=``). Combined with
       (1): true minimal tax >= proposal >= incumbent's tax, and the incumbent
       attains the floor at its tax, so its tax IS the minimum.

    This is Soares et al. (2021)'s termination rule ``x^{u(K+1)} = x^{uK}``
    (their Lemma 3) transplanted to the lexicographic leader: stop when the
    master re-proposes the leader decision the follower has already confirmed.
    """
    bounds_at_noise_level = (
        incumbent_emissions - best_lower_bound
        <= _emissions_tie_tolerance(incumbent_emissions, best_lower_bound)
    )
    return bounds_at_noise_level and next_tax_index >= incumbent_tax_index


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


def _timeout_reason(budget: "_WallClockBudget") -> str:
    """Which budget ran out: the run's wall-clock cap, or one subproblem's own limit."""
    return "wall_clock_cap" if budget.expired() else "time_limit"


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
    termination_reason: str = "time_limit",
) -> BilevelSolveResult:
    """Return the best incumbent found so far when a time budget runs out.

    Used for both budgets: ``time_limit`` (one subproblem hit its Gurobi limit) and
    ``wall_clock_cap`` (the run's total budget expired between iterations). Either way the
    incumbent is a genuine bilevel-feasible point with its cost, emissions and captured
    variable values; the lower bound is the last value certified by an OPTIMAL relaxation, so
    the reported gap is a valid -- if non-zero -- bound on how far the incumbent may be from
    E*. ``exact=False`` signals it is not a provably optimal bilevel solution.
    """
    return _build_bilevel_result(
        method="dbp_lex",
        mode="exact",
        termination_reason=termination_reason,
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


class _WallClockBudget:
    """The run's total wall-clock budget, shared by every subproblem.

    Enforced INSIDE the solve rather than by killing the process, so that an exhausted budget
    still yields the incumbent, its variable values and a certified bound -- a killed process
    yields nothing. Two mechanisms:

    * `subproblem_time_limit()` caps each Gurobi call at the budget that remains, so no single
      subproblem can run past the deadline;
    * `expired()` is checked between iterations, where the DBP loop can stop cleanly.

    A cap of ``None`` disables both (the budget never expires).
    """

    __slots__ = ("deadline", "per_subproblem_limit")

    def __init__(self, cap: float | None, per_subproblem_limit: float | None) -> None:
        self.deadline = None if cap is None else time.perf_counter() + cap
        self.per_subproblem_limit = per_subproblem_limit

    def remaining(self) -> float | None:
        return None if self.deadline is None else self.deadline - time.perf_counter()

    def expired(self) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining <= 0.0

    def subproblem_time_limit(self) -> float | None:
        remaining = self.remaining()
        if remaining is None:
            return self.per_subproblem_limit
        # Never hand Gurobi a non-positive limit: it would be read as "no limit".
        remaining = max(remaining, 1.0)
        if self.per_subproblem_limit is None:
            return remaining
        return min(self.per_subproblem_limit, remaining)


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
# DBP loop termination: one function per exit path, each returning the final
# BilevelSolveResult for that path. Every one is a pure re-packaging of state the loop already
# holds at the point it fires -- none of them changes a condition, threshold, or the order in
# which the loop checks them; see the call sites in solve_bilevel_dbp_lex for exactly when each
# fires. Kept separate from _build_time_limit_result (used by the three time/budget exits above)
# only because those three already shared one shape; these four do not.
# ---------------------------------------------------------------------------

def _infeasibility_certified_result(
    *,
    iteration: int,
    incumbent: IncumbentSolution,
    incumbent_solution: SolveResult | None,
    upper_bound_certificate: BoundCertificate,
    iteration_records: list[DbpIterationRecord],
    iteration_timings: list[DbpIterationTiming],
    initial_relaxation_seconds: float,
) -> BilevelSolveResult:
    """The relaxation master went INFEASIBLE under the incumbent's objective upper bound: every
    remaining tax_index is provably unable to tie or beat the incumbent's emissions (see the call
    site's comment on why this also certifies the TAX when confirm_min_tax is in effect --
    lem:lb_validity). A certificate of optimality by exhaustion: lower_bound == upper_bound ==
    incumbent.emissions with zero slack, not a closed-gap comparison.
    """
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


def _gap_closed_result(
    *,
    iteration: int,
    best_lower_bound: float,
    incumbent: IncumbentSolution,
    incumbent_solution: SolveResult | None,
    upper_bound_certificate: BoundCertificate,
    relaxation_mip_gap: float | None,
    iteration_records: list[DbpIterationRecord],
    iteration_timings: list[DbpIterationTiming],
    initial_relaxation_seconds: float,
) -> BilevelSolveResult:
    """The outer relative gap has closed and, if confirm_min_tax is in effect, the incumbent's tax
    has already been confirmed grid-minimal by ``_min_tax_confirmed`` (the call site does not reach
    here otherwise -- it ``continue``s instead). A provably optimal bilevel result.
    """
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
            mip_gap=relaxation_mip_gap,
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


def _stagnation_result(
    *,
    iteration: int,
    best_lower_bound: float,
    incumbent: IncumbentSolution,
    incumbent_solution: SolveResult | None,
    upper_bound_certificate: BoundCertificate,
    relaxation_mip_gap: float | None,
    effective_dbp_relative_gap: float,
    iteration_records: list[DbpIterationRecord],
    iteration_timings: list[DbpIterationTiming],
    initial_relaxation_seconds: float,
) -> BilevelSolveResult:
    """``DEFAULT.stagnation_limit`` consecutive iterations moved neither bound: give up and report
    the best certificate in hand, classified by whether the achieved gap happens to already be
    within tolerance despite the stall (``_classify_stagnation_stop``) -- in which case this is
    still reported exact, just under a distinct termination_reason/certificate source so a
    gap-driven and a stagnation-driven "relative_gap" stop stay distinguishable downstream.
    """
    termination_reason, gap_closed = _classify_stagnation_stop(
        upper_bound=incumbent.emissions,
        lower_bound=best_lower_bound,
        dbp_relative_gap=effective_dbp_relative_gap,
    )
    lower_bound_certificate = _with_stagnation_context(
        BoundCertificate(
            value=best_lower_bound,
            exact=True,
            mip_gap=relaxation_mip_gap,
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


def _max_iterations_result(
    *,
    max_iterations: int,
    best_lower_bound: float,
    incumbent: IncumbentSolution,
    incumbent_solution: SolveResult | None,
    upper_bound_certificate: BoundCertificate,
    relaxation_mip_gap: float | None,
    iteration_records: list[DbpIterationRecord],
    iteration_timings: list[DbpIterationTiming],
    initial_relaxation_seconds: float,
) -> BilevelSolveResult:
    """The loop exhausted ``max_iterations`` (the grid size plus one, by default -- practically
    unreachable, since the finite-grid argument in ``solve_bilevel_dbp_lex``'s docstring bounds the
    endgame probing sequence well below that) without closing the gap or triggering stagnation.
    Reported, not raised: still a real incumbent with a real certified lower bound, just not one
    this run could prove optimal in the iterations it was given.
    """
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
            mip_gap=relaxation_mip_gap,
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


# ---------------------------------------------------------------------------
# DBP lexicographic solver (leader minimises emissions then tax_index)
# ---------------------------------------------------------------------------

def solve_bilevel_dbp_lex(
    instance_or_path: InstanceData | str | Path,
    *,
    max_iterations: int | None = None,
    output_flag: bool = False,
    time_limit: float | None = None,
    wall_clock_cap: float | None = None,
    mip_gap: float | None = None,
    dbp_relative_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
    confirm_min_tax: bool = True,
    seed: int | None = None,
    use_warm_start: bool = True,
    use_incumbent_cut: bool = True,
    use_lex_master_stage2: bool = True,
) -> BilevelSolveResult:
    """DBP with the leader's lexicographic objective: minimise emissions, then
    minimise ``tax_index`` among the emissions-tied candidates.

    The DBP loop squeezes a lower bound (from the relaxation master) against an
    upper bound (from the follower) until the emissions gap closes, CERTIFYING
    the minimum emissions E*. But that certificate is silent about the tax: the
    incumbent's tax is just the last one evaluated, an UPPER bound on the true
    least-intervention tax (the loop can terminate before ever proposing a
    smaller tax that also reaches E*).

    ``confirm_min_tax=True`` (the default) certifies the minimal tax INSIDE the
    loop: Soares et al. (2021)'s own stopping rule (their Lemma 3,
    ``x^{u(K+1)} = x^{uK}``) applied to the lexicographic leader. When the
    emissions gap closes, the loop keeps iterating until the master's Stage-2
    minimal-tax proposal is CONFIRMED -- either the proposal equals the
    incumbent's own tax with the emission bounds closed to noise level (see
    ``_min_tax_confirmed``), or the incumbent-cut renders the master
    infeasible, which excludes tied points at every other tax outright. Each
    unconfirmed proposal is probed by the next follower solve: it either ties
    the certified floor at a smaller tax (the lexicographic incumbent adopts
    it) or fails and its cut lifts the master there, so the proposal sequence
    is finite on the finite grid. This needs no monotonicity assumption, so it
    works unchanged on discounted instances (where the follower's tax base and
    the leader's physical emissions differ).

    ``confirm_min_tax`` requires ``use_lex_master_stage2``: the Stage-2
    proposal is the object being confirmed. If ``use_lex_master_stage2=False``
    (the A2 ablation), confirmation is silently unavailable regardless of this
    flag -- the certified emissions optimum is unaffected, but the reported
    tax is only an upper bound on the true minimum. Set
    ``confirm_min_tax=False`` explicitly to get that same un-certified tax on
    an otherwise full run (the A1 ablation: certified emissions, unconfirmed
    tax).

    ``mip_gap``/``threads``/``mip_focus`` override the corresponding
    :class:`clsc.config.gap_tol.ToleranceConfig` default (``None`` keeps the
    default) for every Gurobi sub-solve. ``dbp_relative_gap`` overrides the
    DBP loop's own outer stopping criterion the same way -- it is unrelated
    to any Gurobi parameter.

    ``time_limit`` bounds ONE subproblem; ``wall_clock_cap`` bounds the whole DBP run. The cap
    is enforced from inside: each subproblem's limit is clamped to the budget that remains, and
    the loop stops between iterations once it is exhausted, returning
    ``termination_reason="wall_clock_cap"`` with the incumbent, its variable values and the
    certified bounds. This is why the cap is not enforced by killing the process from outside --
    a killed run reports nothing at all.

    ``seed`` sets the Gurobi ``Seed`` parameter on every sub-solve (MIP
    performance-variability probes; Exp1/Exp2). The three ``use_*`` flags select
    Experiment-3 ablation variants (all default True = full DBP): ``use_warm_start``
    (A3) warm-starts successive follower solves; ``use_incumbent_cut`` (A5) tightens
    the relaxation master with the incumbent's emissions as an objective upper bound;
    ``use_lex_master_stage2`` (A2) runs the master's lexicographic Stage-2 tax
    minimisation. Disabling any one leaves the certified emissions optimum unchanged
    but changes the iteration/time path (and, for A1/A2, the reported tax is no
    longer certified minimal).
    """
    effective_confirm_min_tax = confirm_min_tax and use_lex_master_stage2
    instance = _coerce_instance(instance_or_path)
    budget = _WallClockBudget(wall_clock_cap, time_limit)
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
        time_limit=budget.subproblem_time_limit(),
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
        if budget.expired() and incumbent is not None:
            # Stop cleanly at the top of an iteration: the incumbent, its variable values and
            # the last certified lower bound are all in hand, so the run reports a real
            # (cost, emissions, gap) rather than nothing.
            return _build_time_limit_result(
                incumbent=incumbent,
                incumbent_solution=incumbent_solution,
                upper_bound_certificate=upper_bound_certificate,
                best_lower_bound=best_lower_bound,
                iteration=len(iteration_records),
                iteration_records=iteration_records,
                iteration_timings=iteration_timings,
                initial_relaxation_seconds=initial_relaxation_seconds,
                termination_reason="wall_clock_cap",
            )

        current_relaxation_lower_bound = best_lower_bound
        tax_index = _required_value(relaxation.tax_index, "relaxation tax_index")

        lexicographic, lexicographic_seconds = _solve_with_wall_time(
            solve_fixed_tax_lexicographic,
            follower_master,
            tax_index=tax_index,
            output_flag=output_flag,
            time_limit=budget.subproblem_time_limit(),
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
                    termination_reason=_timeout_reason(budget),
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
            # The cut's tau-coefficient must be the quantity the follower was
            # actually taxed on -- the discounted base -- while `emissions`
            # stays physical for the leader's bound. The two coincide when the
            # instance carries no interest rate.
            tax_base=lexicographic.tax_base,
            iteration=iteration,
        )
        add_dbp_relaxation_cut(relaxation_master, cut)
        if use_incumbent_cut:
            set_dbp_relaxation_objective_upper_bound(relaxation_master, incumbent.emissions)

        relaxation, relaxation_seconds = _solve_with_wall_time(
            solve_dbp_relaxation_lexicographic,
            relaxation_master,
            output_flag=output_flag,
            time_limit=budget.subproblem_time_limit(),
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
            # When confirm_min_tax is in effect, this infeasibility certifies
            # the TAX as well as the emissions: the objective upper bound is
            # widened by lex_freeze_tolerance (see
            # set_dbp_relaxation_objective_upper_bound), so any true
            # optimistic point tying the incumbent's emissions at any other
            # tax index would still be feasible here (lem:lb_validity -- cuts
            # never exclude true points). Infeasibility therefore proves no
            # such tied point exists, and in particular none at a smaller tax.
            return _infeasibility_certified_result(
                iteration=iteration,
                incumbent=incumbent,
                incumbent_solution=incumbent_solution,
                upper_bound_certificate=upper_bound_certificate,
                iteration_records=iteration_records,
                iteration_timings=iteration_timings,
                initial_relaxation_seconds=initial_relaxation_seconds,
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
                termination_reason=_timeout_reason(budget),
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
            if effective_confirm_min_tax and not _min_tax_confirmed(
                incumbent_emissions=incumbent.emissions,
                incumbent_tax_index=incumbent.tax_index,
                best_lower_bound=best_lower_bound,
                next_tax_index=next_tax_index,
            ):
                # Endgame: the emissions gap is closed but the master's Stage-2
                # still proposes a smaller tax (or the bounds are not yet at
                # noise level, where the Stage-2 band provably contains every
                # true tie). The next iteration probes that proposal with a
                # follower solve: either it ties the floor at a smaller tax --
                # the lexicographic incumbent adopts it -- or its cut lifts the
                # master there and the proposal moves on. Skipping the
                # stagnation bookkeeping is deliberate: these iterations
                # advance the tax certificate without moving either emissions
                # bound, and their number is finite on the finite grid (the
                # loop-head wall-clock and max_iterations guards still apply).
                continue
            return _gap_closed_result(
                iteration=iteration,
                best_lower_bound=best_lower_bound,
                incumbent=incumbent,
                incumbent_solution=incumbent_solution,
                upper_bound_certificate=upper_bound_certificate,
                relaxation_mip_gap=relaxation.mip_gap,
                iteration_records=iteration_records,
                iteration_timings=iteration_timings,
                initial_relaxation_seconds=initial_relaxation_seconds,
            )

        if incumbent_updated or lower_bound_updated:
            iterations_without_bound_update = 0
        else:
            iterations_without_bound_update += 1

        if iterations_without_bound_update >= DEFAULT.stagnation_limit:
            return _stagnation_result(
                iteration=iteration,
                best_lower_bound=best_lower_bound,
                incumbent=incumbent,
                incumbent_solution=incumbent_solution,
                upper_bound_certificate=upper_bound_certificate,
                relaxation_mip_gap=relaxation.mip_gap,
                effective_dbp_relative_gap=effective_dbp_relative_gap,
                iteration_records=iteration_records,
                iteration_timings=iteration_timings,
                initial_relaxation_seconds=initial_relaxation_seconds,
            )

    if incumbent is None or upper_bound_certificate is None:
        raise RuntimeError("DBP lexicographic exact terminated without an incumbent solution")

    return _max_iterations_result(
        max_iterations=max_iterations,
        best_lower_bound=best_lower_bound,
        incumbent=incumbent,
        incumbent_solution=incumbent_solution,
        upper_bound_certificate=upper_bound_certificate,
        relaxation_mip_gap=relaxation.mip_gap,
        iteration_records=iteration_records,
        iteration_timings=iteration_timings,
        initial_relaxation_seconds=initial_relaxation_seconds,
    )
