from __future__ import annotations

from dataclasses import dataclass
import itertools
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
# The emissions gap has closed and the bounded tax-descent phase has spent its probes without
# the master re-proposing the incumbent's tax. The emissions optimum is certified; the
# least-intervention tax is not, but the result carries the bracket the descent reached in
# `tax_index_lower_bound`. Soares et al. (2021)'s Step 6 stops at the FIRST unconfirmed proposal --
# correctly for a scalar upper level, which has no second criterion to certify.
TAX_NOT_CONFIRMED_REASON = "relative_gap_tax_unconfirmed"


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
    # How the master's `relaxation_seconds` split between its two lexicographic objectives
    # (emissions, then tax_index). Both are one Gurobi call now, so the split comes from the
    # MULTIOBJ callback rather than from two separate timings; None when the master was not
    # solved lexicographically (ablation A2) or when Gurobi reported no pass boundary.
    relaxation_emissions_seconds: float | None = None
    relaxation_tax_seconds: float | None = None


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
    # Certified LOWER bound on the least-intervention tax index: the smallest tax the master
    # can still reach within the leader's indifference band of the certified emissions floor.
    # With the incumbent's own tax as the attained upper bound, [tax_index_lower_bound, incumbent
    # tax] brackets the true least-intervention tax. Set once the emissions bounds have closed,
    # which is the precondition that makes the master's proposal a valid bound at all (see
    # _min_tax_confirmed); None before that, and on paths that stop for time or stagnation.
    tax_index_lower_bound: int | None = None


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


def _is_better_candidate(
    candidate: IncumbentSolution,
    incumbent: IncumbentSolution | None,
    indifference_relative: float | None = None,
) -> bool:
    """Leader-level incumbent comparator: lexmin(emissions, tax_index), per eq:leader_obj
    (paper/sections/04b_leader.tex). Each candidate's emissions value already reflects the
    follower's optimistic (as:opt) tie-break for its own tax_index, so no further
    follower_objective tier belongs here.

    ``indifference_relative`` is the leader's emissions indifference band as a fraction of the
    compared magnitudes. Without it the comparator falls back to ``_emissions_tie_tolerance``,
    which is sized to floating-point noise -- adequate only where genuinely equal emissions
    occur. They frequently do not: on these instances emissions keep drifting downward by grams
    per scale factor, so a noise-sized band makes every pair of taxes distinguishable and the
    least-intervention tier never fires. The band states, explicitly, the differences the leader
    declines to prefer over -- and it should be no finer than what the run certifies."""
    if incumbent is None:
        return True
    tolerance = _leader_indifference_band(
        candidate.emissions, incumbent.emissions, indifference_relative,
    )
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


def _leader_indifference_band(
    first_emissions: float,
    second_emissions: float,
    indifference_relative: float | None,
) -> float:
    """Emissions difference the leader declines to prefer over.

    Never narrower than ``_emissions_tie_tolerance``: a band below the cross-model
    reconstruction noise floor would deem two identical points different. Above that floor it
    is a POLICY quantity, and the defensible size is the run's own certification tolerance --
    the leader must not rank two configurations by a margin the run cannot prove exists.
    """
    numerical_floor = _emissions_tie_tolerance(first_emissions, second_emissions)
    if indifference_relative is None:
        return numerical_floor
    magnitude = max(abs(first_emissions), abs(second_emissions))
    return max(numerical_floor, indifference_relative * magnitude)


def _min_tax_confirmed(
    *,
    incumbent_emissions: float,
    incumbent_tax_index: int,
    best_lower_bound: float,
    next_tax_index: int,
    indifference_relative: float | None = None,
) -> bool:
    """Soares et al. (2021)'s Lemma 3, transplanted to the lexicographic leader: the master,
    re-solved with every cut accumulated so far, proposes a tax no lower than the one the
    follower has already confirmed. One condition, as in the paper.

    Their Lemma 3 reads ``if x^{u(K+1)} = x^{uK} then an optimal optimistic solution to (P1)
    has been found`` -- and that is the whole of it. Bound coincidence is the CONCLUSION of its
    proof (``LB_F = F(x^{uK}, y_K) = F(x^{uK}, y_{u(K+1)}) = UB_F``), never a premise. The gap
    is the gate that precedes this check, exactly as in their Step 6: a run that reaches here
    has already closed ``UB - LB <= dbp_relative_gap`` and is ε-optimal whatever this returns.
    What this adds is the upgrade from ε-optimal to certified.

    This deliberately drops a second condition carried until 2026-09-10, which additionally
    required the emission bounds to have converged to the cross-model NOISE floor. The concern
    behind it is real and has no counterpart in Soares, whose leader has no Stage 2: this
    master's Stage-2 minimises the tax over a freeze band above its Stage-1 optimum, and that
    optimum is a lower bound, so a band sitting well below the true floor need not contain the
    points whose tax is being ranked. But the gap gate already bounds that displacement by
    ``dbp_relative_gap``, and the freeze band is sized to the same quantity, so the containment
    the argument needs is what the gate already delivers. Demanding the noise floor on top asked
    for a convergence three orders tighter than anything else the run certifies, and refused the
    upgrade on runs that had plainly earned it -- STD_I17_M4_T6 closed its bounds to 1.6e-07
    relative with the tax bracket shut at [15, 15] and was still reported unconfirmed.

    A separate attempt to soften that condition to the indifference band while WIDENING the
    Stage-2 freeze to twice the band is what broke STD_TOY4 (stagnated at tax_index 0 after 12
    iterations instead of certifying 277 in 2). The freeze stays at one band; only the extra
    condition goes.
    """
    return next_tax_index >= incumbent_tax_index


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


def _with_tax_unconfirmed_context(certificate: BoundCertificate) -> BoundCertificate:
    return BoundCertificate(
        value=certificate.value,
        exact=certificate.exact,
        mip_gap=certificate.mip_gap,
        slack=certificate.slack,
        source=f"{certificate.source}_tax_unconfirmed",
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
        upper_bound=upper_bound_certificate.value,
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
    tax_index_lower_bound: int | None = None,
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
        tax_index_lower_bound=tax_index_lower_bound,
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
    tax_index_lower_bound: int,
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
        upper_bound=upper_bound_certificate.value,
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
        tax_index_lower_bound=tax_index_lower_bound,
        incumbent_solution=incumbent_solution,
    )


def _gap_closed_tax_unconfirmed_result(
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
    tax_index_lower_bound: int,
) -> BilevelSolveResult:
    """The emissions gap has closed -- this result's lower_bound_certificate is exact, E* itself
    is certified -- but the tax-descent phase spent its probe budget without the master
    re-proposing the incumbent's tax.

    ``exact=False`` is deliberate: the reported tax is an upper bound on the true
    least-intervention tax. What this result adds over simply saying so is ``tax_index_lower_bound``,
    the master's last proposal, which is a certified LOWER bound on that same quantity: the
    answer is known to lie in [tax_index_lower_bound, incumbent.tax_index] rather than merely being
    "unconfirmed".

    Two distinct situations end here. Where the emissions curve has a genuine plateau, the
    descent normally closes the bracket well inside its budget and this path is not taken.
    Where the curve drifts monotonically instead -- STD_I17_M4_T6 loses ~16 g per scale factor with
    no exact tie anywhere -- no proposal can ever confirm, and the budget is what stops the
    descent from walking the entire grid. An earlier unbounded version of that probe did walk
    it: 2002 iterations on STD_TOY6, and one campaign cell killed at 14 wall-clock hours.
    """
    lower_bound_certificate = _with_tax_unconfirmed_context(
        BoundCertificate(
            value=best_lower_bound,
            exact=True,
            mip_gap=relaxation_mip_gap,
            slack=0.0,
            source="relaxation",
        )
    )
    tax_unconfirmed_upper_bound_certificate = _with_tax_unconfirmed_context(upper_bound_certificate)
    return _build_bilevel_result(
        method="dbp_lex",
        mode="exact",
        termination_reason=TAX_NOT_CONFIRMED_REASON,
        exact=False,
        iterations=iteration,
        lower_bound=best_lower_bound,
        upper_bound=upper_bound_certificate.value,
        lower_bound_certificate=lower_bound_certificate,
        upper_bound_certificate=tax_unconfirmed_upper_bound_certificate,
        incumbent=incumbent,
        iteration_records=tuple(iteration_records),
        dbp_timing=_build_dbp_timing_summary(
            initial_relaxation_seconds=initial_relaxation_seconds,
            iteration_timings=tuple(iteration_timings),
        ),
        tax_index_lower_bound=tax_index_lower_bound,
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
        upper_bound=upper_bound_certificate.value,
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
        upper_bound=upper_bound_certificate.value,
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


# ---------------------------------------------------------------------------
# DBP lexicographic solver (leader minimises emissions then tax_index)
# ---------------------------------------------------------------------------

def solve_bilevel_dbp_lex(
    instance_or_path: InstanceData | str | Path,
    *,
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

    ``confirm_min_tax=True`` (the default) checks the minimal tax INSIDE the
    loop, at the same point the emissions gap closes: Soares et al. (2021)'s
    own Step 6 (their Lemma 3, ``x^{u(K+1)} = x^{uK}``) applied to the
    lexicographic leader. Either the master's Stage-2 proposal equals the
    incumbent's own tax with the emission bounds closed to noise level (see
    ``_min_tax_confirmed``) -- terminate with a certified optimum
    (``_gap_closed_result``, ``exact=True``) -- or the incumbent-cut renders
    the master infeasible, which excludes tied points at every other tax
    outright. If it does not hold, this follows Soares et al.'s Step 6
    else-branch exactly: terminate anyway, reporting the incumbent as an
    epsilon-optimal solution (``_gap_closed_tax_unconfirmed_result``,
    ``exact=False``) rather than probing the smaller proposal with a further
    follower solve. That probe was tried and dropped: it had no bound of its
    own short of the grid size, which is what made STD_TOY6 take 2002
    iterations on the campaign's fine grid before this change. This needs no
    monotonicity assumption, so it works unchanged on discounted instances
    (where the follower's tax base and the leader's physical emissions
    differ).

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
    effective_dbp_relative_gap = DEFAULT.dbp_relative_gap if dbp_relative_gap is None else dbp_relative_gap
    # The leader's emissions indifference band IS the run's certification tolerance. Any finer
    # and the least-intervention criterion would be ranking configurations by margins this run
    # cannot prove exist; any coarser and it would discard abatement the run does certify.
    leader_indifference_relative = effective_dbp_relative_gap
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
        leader_indifference_relative=leader_indifference_relative,
    )
    _require_optimal_result(relaxation, "initial DBP relaxation")

    best_lower_bound = _required_value(relaxation.emissions, "initial relaxation emissions")
    incumbent: IncumbentSolution | None = None
    incumbent_solution = None
    previous_lexicographic_values: dict[str, float] | None = None
    upper_bound_certificate: BoundCertificate | None = None
    iterations_without_bound_update = 0
    # Probes spent in the tax-descent phase (see the confirmation branch below).
    tax_descent_probes = 0

    for iteration in itertools.count(1):
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
        # TWO distinct quantities, which a scalar upper level never has to tell apart.
        #
        # `incumbent` is the LEADER'S ANSWER: the lexicographic pick, lowest tax among the points
        # within the indifference band of the best emissions seen. Because that band admits
        # slightly worse emissions in exchange for a lower tax, the incumbent's emissions are NOT
        # a bound on anything -- they are the emissions of the chosen policy.
        #
        # `upper_bound_certificate` is the EMISSIONS BOUND: the least emissions any evaluated
        # point attained. This is what pairs with best_lower_bound to certify the leader's first
        # criterion, what the gap test compares, and what caps the master. Conflating the two --
        # as this loop did while the band was noise-sized and the distinction never showed -- lets
        # the reported "upper bound" drift above the lower bound as soon as the band is wide
        # enough to matter (measured on STD_TOY5 the moment the band became the certification
        # tolerance).
        incumbent_updated = _is_better_candidate(
            candidate, incumbent, leader_indifference_relative,
        )
        if incumbent_updated:
            incumbent = candidate
            incumbent_solution = lexicographic
        if upper_bound_certificate is None or candidate.emissions < upper_bound_certificate.value:
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
            set_dbp_relaxation_objective_upper_bound(
                relaxation_master, upper_bound_certificate.value,
            )

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
            leader_indifference_relative=leader_indifference_relative,
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

        # The master only ever GAINS constraints, so its optimum cannot fall -- but the value
        # read off it is ObjBound at mip_gap, which oscillates within that gap (measured: a
        # 15 kg drop between consecutive iterations on STD_I17_M4_T3). Each iteration's value is
        # individually a valid bound, so their maximum is too, and keeping it makes the
        # certified floor monotone. That monotonicity is what the tax phase below rests on: only
        # with a stable floor is the master's freeze band stable, and only then is its Stage-2
        # proposal a non-decreasing lower bound on the least-intervention tax.
        relaxation_lower_bound = _required_value(relaxation.emissions, "relaxation emissions")
        previous_lower_bound = best_lower_bound
        best_lower_bound = max(best_lower_bound, relaxation_lower_bound)
        lower_bound_updated = best_lower_bound > previous_lower_bound + DEFAULT.eps
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
                incumbent_emissions=upper_bound_certificate.value,
                relaxation_seconds=relaxation_seconds,
                next_relaxation_tax_index=next_tax_index,
                next_relaxation_lower_bound=best_lower_bound,
                relaxation_emissions_seconds=relaxation.lex_primary_seconds,
                relaxation_tax_seconds=relaxation.lex_secondary_seconds,
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
                upper_bound=upper_bound_certificate.value,
                lower_bound=best_lower_bound,
            )
            <= effective_dbp_relative_gap
        ):
            tax_proposal_confirms = next_tax_index >= incumbent.tax_index
            if effective_confirm_min_tax and not _min_tax_confirmed(
                incumbent_emissions=upper_bound_certificate.value,
                incumbent_tax_index=incumbent.tax_index,
                best_lower_bound=best_lower_bound,
                next_tax_index=next_tax_index,
                indifference_relative=leader_indifference_relative,
            ):
                # PHASE 2 -- the tax descent. The emissions gap has closed, so by
                # _min_tax_confirmed's own argument the master's Stage-2 proposal is now a valid
                # LOWER bound on the least-intervention tax, while the incumbent's tax is an
                # attained upper bound: the answer is bracketed by [next_tax_index,
                # incumbent.tax_index]. A proposal that undercuts the incumbent is therefore not
                # a reason to stop -- it is a direction to search, and the next iteration
                # evaluates exactly that tax, because the loop reads its tax_index off
                # `relaxation`. Soares et al. (2021)'s Step 6 stops here instead, and rightly so
                # for a scalar upper level: their leader has no second criterion for this phase
                # to serve. Measured on STD_I17_M4_T3, two probes carry the incumbent from
                # tax_index 399 (199.5 USD/t) to 52 (26.0 USD/t) and turn an unconfirmed report
                # into a certified one.
                #
                # The budget is what makes this safe. The earlier implementation probed without
                # one and had no bound short of the grid size: 2002 iterations on STD_TOY6, and
                # one campaign cell killed at 14 wall-clock hours. Where the emissions curve is
                # purely monotone (STD_I17_M4_T6 drifts ~16 g per scale factor with no tie anywhere)
                # confirmation may never arrive, so the descent gets a fixed number of probes and
                # then reports the bracket it reached instead of chasing one.
                # ONLY when the TAX is what is unconfirmed. _min_tax_confirmed has two
                # conditions, and probing addresses exactly one of them: evaluating the master's
                # proposal can move the incumbent's tax, and cannot move the emission bounds. On
                # STD_I17_M4_T6 the tax bracket closed at iteration 3 and the run then spent
                # iterations 4 through 12 -- nine solves, half an hour -- re-evaluating the same
                # tax_index 15 while waiting for a bounds convergence that probing was never
                # going to deliver. When the bounds are the blocker, fall through and report.
                if not tax_proposal_confirms and tax_descent_probes < DEFAULT.stagnation_limit:
                    tax_descent_probes += 1
                    continue
                return _gap_closed_tax_unconfirmed_result(
                    iteration=iteration,
                    best_lower_bound=best_lower_bound,
                    incumbent=incumbent,
                    incumbent_solution=incumbent_solution,
                    upper_bound_certificate=upper_bound_certificate,
                    relaxation_mip_gap=relaxation.mip_gap,
                    iteration_records=iteration_records,
                    iteration_timings=iteration_timings,
                    initial_relaxation_seconds=initial_relaxation_seconds,
                    tax_index_lower_bound=next_tax_index,
                )
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
                tax_index_lower_bound=min(next_tax_index, incumbent.tax_index),
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

