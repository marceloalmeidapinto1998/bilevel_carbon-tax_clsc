"""Deterministic Bounding Procedure for the lexicographic carbon-tax leader.

CORRESPONDENCE WITH Soares, Alves & Henggeler Antunes (2021), EJOR 291, 52-66
-- kept here, in one place, so the module can be read with the paper open.

  Their notation          Here                              Built / solved by
  ---------------------------------------------------------------------------
  x^u                     tax_index (integer)               the leader's choice
  y                       the whole supply chain            the model's own variables,
                                                            built in _build_supply_chain_model *
  F(x, y)                 total physical emissions          leader's objective
  f(x, y)                 cost + tax_rate * tax_base        follower's objective
  g(y) <= 0               the chain's physical constraints  _build_supply_chain_model
                          -- independent of the tax
  (P2)   HPR              leader master, no cuts yet        build_leader_master
  (P5)   HPR + cuts       the SAME master, k cuts later     add_value_function_cut
  (P3)+(P4-eps')          follower at a fixed tax           solve_follower_lexicographic
  y_k                     the point that generates cut k    ValueFunctionCut
  eps                     loop stopping criterion           dbp_relative_gap
  eps'                    subproblem feasibility slack      lex_freeze_tolerance
  Lemma 1                 the follower's point is           where the follower's answer
                          bilevel-feasible, so it bounds    sets emissions_follower_ub_
                                                            certificate **
  Lemma 2                 cuts remove nothing optimal       add_value_function_cut
  Lemma 3                 master re-proposes the same       _min_tax_confirmed
                          tax => optimum

  Section 7-8: subproblems that cannot be solved to optimality inside their budget
  UB_F = F (1 + gap_HPR)  the master's DUAL bound            solve_leader_master_lexicographic
                          (ObjBound), also when it times    (leader_lower_bound)
                          out -- the exact form of the
                          same correction
  F <= UB_F  (Mitsos)     E >= LB on the master (off by     set_emissions_floor
                          default: measured to slow it)
  (P5-D)  elastic HPR     one penalised slack per cut,      enable_elastic_cuts
                          switched on the first time the
                          master returns no point
  (P4-D)  elastic P4      Stage 2 finds nothing => keep     solve_follower_lexicographic
                          the Step-2 response
  (P6)                    improve a timed-out follower      _improve_follower_value
  auxiliary stop          bounds unchanged 10 iterations    DEFAULT.stagnation_limit

  * y has no collective name in the code, and needs none. SolveResult.variable_values is a
    SNAPSHOT of one solution of those variables (Gurobi VarName -> value, non-zeros only),
    captured after a solve and used for solution.json and the next warm start. It is filled by
    the leader master as readily as by the follower, so it is not "y" and is not the follower's.

  ** _is_better_candidate is NOT Lemma 1. It is the leader's lexicographic comparator --
     lexmin(emissions, tax_index) within an indifference band -- and it has no counterpart in
     the reference at all, whose leader is scalar. It is one of the things this procedure adds.

(P2) and (P5) are the SAME Python object -- one LeaderMaster that starts without
cuts and accumulates one per iteration. The distinction is how many cuts it carries,
not what type it is, which is why no function is named after either.

THE BOUNDS ARE INVERTED against the paper, and this trips everyone. Soares et al.
MAXIMISE profit, so their relaxation gives an upper bound and their feasible point a
lower one. This leader MINIMISES emissions, so both flip: the master gives
emissions_leader_lb and the follower gives emissions_follower_ub. Their LB_F is this
module's emissions_follower_ub.

WHAT THIS ADDS to the reference procedure: a lexicographic second criterion (least
intervention) that their scalar leader has no counterpart for, the bounded tax-descent
phase that certifies it, and the exact one-hot linearisation of tax_rate * emissions --
needed because this tax multiplies continuous flows, where theirs multiplied binaries.
"""
from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
from pathlib import Path
import time

from clsc.config.gap_tol import DEFAULT
from clsc.models.instance import TAX_SCALE_FACTOR, InstanceData
from clsc.models.subproblems import (
    ValueFunctionCut,
    SolveResult,
    add_value_function_cut,
    build_leader_master,
    build_follower_master,
    enable_elastic_cuts,
    set_emissions_floor,
    set_leader_master_start,
    set_emissions_cap,
    solve_leader_master_lexicographic,
    solve_follower_lexicographic,
)


# TERMINATION REASONS. The first word is the STATUS of the result -- what you have -- and the
# rest is why the run stopped there. Sorting a results column by this groups by strength of
# claim, which is the question a reader of 282 rows actually asks:
#
#   optimal_*          certified. Gap closed AND Lemma 3 confirmed the tax.
#   epsilon_optimal_*  within dbp_relative_gap, with the tax bracket reported.
#   incumbent_*        the best point found; the gap did NOT close.
#
# The wording follows the reference: "terminates with the optimal solution(s)" /
# "terminates with the epsilon-optimal solution" (Soares et al. 2021, Step 6).
OPTIMAL_REASON = "optimal"
STAGNATION_REASON = "incumbent_stagnation"
# The emissions gap has closed and the bounded tax-descent phase has spent its probes without
# the master re-proposing the incumbent's tax. The emissions optimum is certified; the
# least-intervention tax is not, but the result carries the bracket the descent reached in
# `tax_index_lower_bound`. Soares et al. (2021)'s Step 6 stops at the FIRST unconfirmed proposal --
# correctly for a scalar upper level, which has no second criterion to certify.
TAX_NOT_CONFIRMED_REASON = "epsilon_optimal_tax_unconfirmed"


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
    scale_factor: float = TAX_SCALE_FACTOR

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
    # The master's own MIP gap at this iteration (worst of its two stages) and whether it stopped
    # on its time limit instead of reaching its gap target. A partial master still yields a valid
    # lower bound (its dual bound) and a tax proposal, but not a Stage-2 minimum -- see
    # _is_usable_partial_master. Recorded per iteration so a reader can see how much of a final
    # gap is the master's.
    relaxation_mip_gap: float | None = None
    relaxation_partial: bool = False
    # The same gap split by stage. `relaxation_mip_gap` is the WORSE of the two, which hides that
    # only Stage 1's gap bears on the lower bound; Stage 2's is about the proposed tax.
    relaxation_emissions_mip_gap: float | None = None
    relaxation_tax_mip_gap: float | None = None
    # Sum of the master's elastic cut slacks D_k at the point it returned (P5-D); > 0 means the
    # proposal violates some cut and cannot confirm the tax.
    relaxation_elastic_slack: float | None = None
    # How the follower ended this iteration: its worst stage gap, whether it stopped on its time
    # limit, whether (P6) improved it, and whether the tie-break fell back to the Step-2 response.
    follower_mip_gap: float | None = None
    follower_time_limited: bool = False
    follower_improved: bool | None = None
    follower_stage2_fallback: bool = False


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
    emissions_leader_lb: float
    emissions_follower_ub: float
    emissions_leader_lb_certificate: BoundCertificate
    emissions_follower_ub_certificate: BoundCertificate
    incumbent: IncumbentSolution
    iteration_records: tuple[DbpIterationRecord, ...]
    dbp_timing: DbpTimingSummary
    incumbent_solution: SolveResult | None = None
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
    emissions_follower_ub: float,
    emissions_leader_lb: float,
) -> float:
    gap = max(0.0, emissions_follower_ub - emissions_leader_lb)
    return gap / max(1.0, abs(emissions_follower_ub))


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
    emissions_leader_lb: float,
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
    emissions_follower_ub: float,
    emissions_leader_lb: float,
    dbp_relative_gap: float | None = None,
) -> tuple[str, bool]:
    achieved_gap = relative_optimality_gap(emissions_follower_ub=emissions_follower_ub, emissions_leader_lb=emissions_leader_lb)
    threshold = DEFAULT.dbp_relative_gap if dbp_relative_gap is None else dbp_relative_gap
    if achieved_gap <= threshold:
        # Gap inside tolerance despite the stall. Reported exact, but NOT as plain `optimal`:
        # the loop stopped without ever reaching the tax-confirmation branch, so Lemma 3 never
        # ran. Under the naming of b63bcb7 that is an epsilon_optimal_* outcome, and the
        # distinct suffix keeps a gap-driven stop and a stall-driven one apart downstream.
        # (This line still returned the pre-b63bcb7 literal "relative_gap" until 2026-09-10.)
        return "optimal_stagnation", True
    return STAGNATION_REASON, False


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


def _is_partial_master(result: SolveResult) -> bool:
    """The relaxation master stopped on its time limit instead of reaching its gap target."""
    return result.status_name == "TIME_LIMIT"


def _is_usable_partial_master(result: SolveResult) -> bool:
    """A timed-out master the loop can continue from: it proved a finite dual bound AND holds a
    point whose tax can be proposed next. The bound is a valid lower bound on the bilevel optimum
    whatever the gap (lem:lb_validity is about the relaxation, not about its optimality), which is
    Soares et al. (2021, Sect. 7)'s treatment of an unsolved relaxation: use the solver's own
    bound, do not abandon the run. Without a point there is no next proposal; the caller then
    folds the bound in and stops, as it always did on a timeout."""
    return (
        _is_partial_master(result)
        and result.has_solution
        and result.tax_index is not None
        and result.emissions is not None
        and result.leader_lower_bound is not None
    )


def _master_returned_no_point(result: SolveResult) -> bool:
    """The master gave the loop nothing to propose: timed out without an incumbent, or
    reported infeasible (which, with every cut valid and the incumbent meeting the cap, can only
    be numerical). This is Soares et al. (2021)'s Difficulty 1, the trigger for (P5-D)."""
    if result.status_name in ("INFEASIBLE", "INF_OR_UNBD"):
        return True
    return _is_partial_master(result) and not _is_usable_partial_master(result)


def _require_optimal_or_usable_partial_master(result: SolveResult, label: str) -> None:
    if _is_usable_partial_master(result):
        return
    _require_optimal_result(result, label)


def _timeout_reason(budget: "_WallClockBudget") -> str:
    """Which budget ran out: the run's wall-clock cap, or one subproblem's own limit."""
    return "incumbent_wall_clock_cap" if budget.expired() else "incumbent_time_limit"


def _build_time_limit_result(
    *,
    incumbent: IncumbentSolution,
    incumbent_solution: SolveResult | None,
    emissions_follower_ub_certificate: BoundCertificate,
    emissions_leader_lb: float,
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
        emissions_leader_lb=emissions_leader_lb,
        emissions_follower_ub=emissions_follower_ub_certificate.value,
        emissions_leader_lb_certificate=BoundCertificate(
            value=emissions_leader_lb,
            exact=True,
            mip_gap=None,
            slack=0.0,
            source="relaxation",
        ),
        emissions_follower_ub_certificate=emissions_follower_ub_certificate,
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

    __slots__ = ("deadline", "per_subproblem_limit", "master_limit")

    def __init__(
        self,
        cap: float | None,
        per_subproblem_limit: float | None,
        master_limit: float | None = None,
    ) -> None:
        self.deadline = None if cap is None else time.perf_counter() + cap
        self.per_subproblem_limit = per_subproblem_limit
        # The relaxation master and the follower are different problems with different cost
        # profiles, so they may carry different limits. None keeps one shared limit.
        self.master_limit = per_subproblem_limit if master_limit is None else master_limit

    def remaining(self) -> float | None:
        return None if self.deadline is None else self.deadline - time.perf_counter()

    def expired(self) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining <= 0.0

    def subproblem_time_limit(self, *, master: bool = False) -> float | None:
        limit = self.master_limit if master else self.per_subproblem_limit
        remaining = self.remaining()
        if remaining is None:
            return limit
        # Never hand Gurobi a non-positive limit: it would be read as "no limit".
        remaining = max(remaining, 1.0)
        if limit is None:
            return remaining
        return min(limit, remaining)


def _build_bilevel_result(
    *,
    method: str,
    mode: str,
    termination_reason: str,
    exact: bool,
    iterations: int,
    emissions_leader_lb: float,
    emissions_follower_ub: float,
    emissions_leader_lb_certificate: BoundCertificate,
    emissions_follower_ub_certificate: BoundCertificate,
    incumbent: IncumbentSolution,
    iteration_records: tuple[DbpIterationRecord, ...],
    dbp_timing: DbpTimingSummary,
    incumbent_solution: SolveResult | None,
    tax_index_lower_bound: int | None = None,
) -> BilevelSolveResult:
    return BilevelSolveResult(
        method=method,
        mode=mode,
        termination_reason=termination_reason,
        exact=exact,
        iterations=iterations,
        emissions_leader_lb=emissions_leader_lb,
        emissions_follower_ub=emissions_follower_ub,
        emissions_leader_lb_certificate=emissions_leader_lb_certificate,
        emissions_follower_ub_certificate=emissions_follower_ub_certificate,
        incumbent=incumbent,
        iteration_records=iteration_records,
        dbp_timing=dbp_timing,
        incumbent_solution=incumbent_solution,
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
    emissions_leader_lb: float,
    incumbent: IncumbentSolution,
    incumbent_solution: SolveResult | None,
    emissions_follower_ub_certificate: BoundCertificate,
    relaxation_mip_gap: float | None,
    iteration_records: list[DbpIterationRecord],
    iteration_timings: list[DbpIterationTiming],
    initial_relaxation_seconds: float,
    tax_index_lower_bound: int,
) -> BilevelSolveResult:
    """The outer relative gap has closed and, if use_tax_confirmation is in effect, the incumbent's tax
    has already been confirmed grid-minimal by ``_min_tax_confirmed`` (the call site does not reach
    here otherwise -- it ``continue``s instead). A provably optimal bilevel result.
    """
    return _build_bilevel_result(
        method="dbp_lex",
        mode="exact",
        termination_reason=OPTIMAL_REASON,
        exact=True,
        iterations=iteration,
        emissions_leader_lb=emissions_leader_lb,
        emissions_follower_ub=emissions_follower_ub_certificate.value,
        emissions_leader_lb_certificate=BoundCertificate(
            value=emissions_leader_lb,
            exact=True,
            mip_gap=relaxation_mip_gap,
            slack=0.0,
            source="relaxation",
        ),
        emissions_follower_ub_certificate=emissions_follower_ub_certificate,
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
    emissions_leader_lb: float,
    incumbent: IncumbentSolution,
    incumbent_solution: SolveResult | None,
    emissions_follower_ub_certificate: BoundCertificate,
    relaxation_mip_gap: float | None,
    iteration_records: list[DbpIterationRecord],
    iteration_timings: list[DbpIterationTiming],
    initial_relaxation_seconds: float,
    tax_index_lower_bound: int | None,
) -> BilevelSolveResult:
    """The emissions gap has closed -- this result's emissions_leader_lb_certificate is exact, E* itself
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
    emissions_leader_lb_certificate = _with_tax_unconfirmed_context(
        BoundCertificate(
            value=emissions_leader_lb,
            exact=True,
            mip_gap=relaxation_mip_gap,
            slack=0.0,
            source="relaxation",
        )
    )
    tax_unconfirmed_upper_bound_certificate = _with_tax_unconfirmed_context(emissions_follower_ub_certificate)
    return _build_bilevel_result(
        method="dbp_lex",
        mode="exact",
        termination_reason=TAX_NOT_CONFIRMED_REASON,
        exact=False,
        iterations=iteration,
        emissions_leader_lb=emissions_leader_lb,
        emissions_follower_ub=emissions_follower_ub_certificate.value,
        emissions_leader_lb_certificate=emissions_leader_lb_certificate,
        emissions_follower_ub_certificate=tax_unconfirmed_upper_bound_certificate,
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
    emissions_leader_lb: float,
    incumbent: IncumbentSolution,
    incumbent_solution: SolveResult | None,
    emissions_follower_ub_certificate: BoundCertificate,
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
        emissions_follower_ub=emissions_follower_ub_certificate.value,
        emissions_leader_lb=emissions_leader_lb,
        dbp_relative_gap=effective_dbp_relative_gap,
    )
    emissions_leader_lb_certificate = _with_stagnation_context(
        BoundCertificate(
            value=emissions_leader_lb,
            exact=True,
            mip_gap=relaxation_mip_gap,
            slack=0.0,
            source="relaxation",
        )
    )
    stagnation_upper_bound_certificate = _with_stagnation_context(emissions_follower_ub_certificate)
    return _build_bilevel_result(
        method="dbp_lex",
        mode="exact",
        termination_reason=termination_reason,
        exact=gap_closed and emissions_leader_lb_certificate.exact and stagnation_upper_bound_certificate.exact,
        iterations=iteration,
        emissions_leader_lb=emissions_leader_lb,
        emissions_follower_ub=emissions_follower_ub_certificate.value,
        emissions_leader_lb_certificate=emissions_leader_lb_certificate,
        emissions_follower_ub_certificate=stagnation_upper_bound_certificate,
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
    master_time_limit: float | None = None,
    master_tax_time_limit: float | None = None,
    wall_clock_cap: float | None = None,
    mip_gap: float | None = None,
    master_mip_gap: float | None = None,
    dbp_relative_gap: float | None = None,
    leader_indifference_relative: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
    use_tax_confirmation: bool = True,
    seed: int | None = None,
    use_warm_start: bool = True,
    use_emissions_cap: bool = True,
    use_lex_master_stage2: bool = True,
    use_follower_improvement: bool = True,
    use_elastic_master: bool = True,
    use_emissions_floor: bool = False,
) -> BilevelSolveResult:
    """DBP with the leader's lexicographic objective: minimise emissions, then
    minimise ``tax_index`` among the emissions-tied candidates.

    The DBP loop squeezes a lower bound (from the relaxation master) against an
    upper bound (from the follower) until the emissions gap closes, CERTIFYING
    the minimum emissions E*. But that certificate is silent about the tax: the
    incumbent's tax is just the last one evaluated, an UPPER bound on the true
    least-intervention tax (the loop can terminate before ever proposing a
    smaller tax that also reaches E*).

    ``use_tax_confirmation=True`` (the default) checks the minimal tax INSIDE the
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

    ``use_tax_confirmation`` requires ``use_lex_master_stage2``: the Stage-2
    proposal is the object being confirmed. If ``use_lex_master_stage2=False``
    (the A2 ablation), confirmation is silently unavailable regardless of this
    flag -- the certified emissions optimum is unaffected, but the reported
    tax is only an upper bound on the true minimum. Set
    ``use_tax_confirmation=False`` explicitly to get that same un-certified tax on
    an otherwise full run (the A1 ablation: certified emissions, unconfirmed
    tax).

    ``mip_gap``/``threads``/``mip_focus`` override the corresponding
    :class:`clsc.config.gap_tol.ToleranceConfig` default (``None`` keeps the
    default) for every Gurobi sub-solve. ``mip_gap`` is the FOLLOWER's target: it sizes the
    freeze band that decides which responses count as optimal, so it is what the leader's
    emissions are measured against. ``master_mip_gap`` is the relaxation master's own target and
    defaults to ``mip_gap`` (``None``), which reproduces the single-gap behaviour. The two are
    different quantities: the master's gap only loosens the lower bound (its dual bound stays
    valid), while the follower's gap loosens what counts as a best response. A master that
    stops on its time limit does not end the run: its dual bound is taken as the lower bound and
    its incumbent's tax is proposed next, as in Soares et al. (2021, Sect. 7); such an iteration
    cannot confirm the least-intervention tax (``epsilon_optimal_tax_unconfirmed``).
    ``master_tax_time_limit`` caps the master's Stage 2 (the tax minimisation) on its own; Stage 1,
    which supplies the lower bound, keeps the full master limit. ``None`` leaves Stage 2 under the
    same limit as Stage 1.
    ``dbp_relative_gap`` overrides the
    DBP loop's own outer stopping criterion the same way -- it is unrelated
    to any Gurobi parameter.

    ``time_limit`` bounds ONE follower subproblem (and the master too unless ``master_time_limit``
    is given, which bounds ONE relaxation-master solve on its own); ``wall_clock_cap`` bounds the whole DBP run. The cap
    is enforced from inside: each subproblem's limit is clamped to the budget that remains, and
    the loop stops between iterations once it is exhausted, returning
    ``termination_reason="incumbent_wall_clock_cap"`` with the incumbent, its variable values and the
    certified bounds. This is why the cap is not enforced by killing the process from outside --
    a killed run reports nothing at all.

    ``seed`` sets the Gurobi ``Seed`` parameter on every sub-solve (MIP
    performance-variability probes; Exp1/Exp2). The three ``use_*`` flags select
    Experiment-3 ablation variants (all default True = full DBP): ``use_warm_start``
    (A3) warm-starts successive follower solves; ``use_emissions_cap`` (A5) tightens
    the relaxation master with the incumbent's emissions as an objective upper bound;
    ``use_lex_master_stage2`` (A2) runs the master's lexicographic Stage-2 tax
    minimisation. Disabling any one leaves the certified emissions optimum unchanged
    but changes the iteration/time path (and, for A1/A2, the reported tax is no
    longer certified minimal).

    Three flags carry Soares et al. (2021, Sect. 7-8)'s treatment of subproblems that cannot be
    solved to optimality inside their budget. ``use_follower_improvement`` (default True) runs
    (P6) when the follower stops on its time limit. ``use_elastic_master`` (default True) is
    their (P5-D) used as they introduce it, as a remedy: the master starts with plain cuts, and
    only the first time it returns no point at all (timed out with no incumbent, or infeasible)
    are the cuts made elastic in place and the master re-solved from the best evaluated point,
    which the elastic master must accept -- from then on it always has a point.
    ``use_emissions_floor`` (default False) adds E >= LB, their ``F <= UB_F`` written for a
    minimising leader; it is off by default because on STD_I17_M4_T3 it slowed every master
    solve (419 s vs 162 s for the same certified answer, 2026-10-08). A follower
    that stops on its time limit no longer ends the run: its best response is used, as Soares et
    al. use a gapped (P3)/(P4-D) solution, and the run can then report at most an epsilon-optimal
    interval, never a certified optimum.

    ``leader_indifference_relative`` (epsilon) is the LEADER'S POLICY PARAMETER: the
    relative emissions margin the regulator treats as immaterial when choosing the least
    tax that still attains the optimum. It sets the Stage-2 freeze band, decides which
    candidate is the incumbent, and gates min-tax confirmation, so ``tax_index`` is a
    function of it and it belongs in the manifest beside the tolerances rather than among
    them. It must be at least ``dbp_relative_gap`` -- below that the leader would be
    preferring taxes on emissions differences the run cannot certify -- and defaults to
    exactly that floor, which leaves every existing result unchanged. Raise it to state a
    policy band, or sweep it to report tau*(epsilon); the emissions optimum E* does not
    depend on it, only the tax selected from the plateau does.
    """
    effective_use_tax_confirmation = use_tax_confirmation and use_lex_master_stage2
    instance = _coerce_instance(instance_or_path)
    budget = _WallClockBudget(wall_clock_cap, time_limit, master_time_limit)
    effective_dbp_relative_gap = DEFAULT.dbp_relative_gap if dbp_relative_gap is None else dbp_relative_gap
    effective_master_mip_gap = mip_gap if master_mip_gap is None else master_mip_gap
    # THE LEADER'S INDIFFERENCE BAND IS A POLICY PARAMETER, NOT A TOLERANCE.
    #
    # epsilon answers "how much emissions is the regulator willing to forgo to avoid
    # intervening further?". It decides the Stage-2 freeze, which candidate becomes the
    # incumbent (_is_better_candidate) and when the least tax is confirmed
    # (_min_tax_confirmed) -- it is threaded through all three of the leader's decisions,
    # and tau* is a function of it. It therefore has to be declared, recorded and varied
    # like any other modelling assumption.
    #
    # The certification tolerance is a genuine FLOOR under it: preferring a lower tax on the
    # strength of an emissions margin the run cannot prove exists would be ranking noise. That
    # argument bounds epsilon from below and is why the default is the run's own gap.
    #
    # It does NOT pin epsilon to that value, which is what this line used to do. The old
    # rationale added "any coarser and it would discard abatement the run does certify" --
    # but declining to intervene further for an emissions difference the regulator considers
    # immaterial is exactly what an indifference band is FOR, not an error. That half of the
    # argument smuggled a value judgement in as a numerical constraint, and it had a visible
    # consequence: at a noise-sized band the emissions curve still drifts down by grams per
    # grid step, so Stage 2 minimises the tax over a set of one element -- the HIGHEST tax --
    # and the least-intervention criterion returns maximum intervention.
    #
    # Default is unchanged (the run's certification tolerance), so no existing result moves.
    # Pass it explicitly to state a policy band, or to trace tau*(epsilon).
    leader_indifference_relative = (
        effective_dbp_relative_gap
        if leader_indifference_relative is None
        else leader_indifference_relative
    )
    if leader_indifference_relative < effective_dbp_relative_gap:
        raise ValueError(
            f"leader_indifference_relative ({leader_indifference_relative:g}) is below the "
            f"run's certification tolerance ({effective_dbp_relative_gap:g}): the leader would "
            f"be ranking taxes by emissions margins this run cannot prove exist"
        )
    iteration_records: list[DbpIterationRecord] = []
    iteration_timings: list[DbpIterationTiming] = []
    # Plain cuts to begin with; made elastic in place only if the master ever returns no point.
    relaxation_master = build_leader_master(instance)
    follower_master = build_follower_master(instance)

    relaxation, initial_relaxation_seconds = _solve_with_wall_time(
        solve_leader_master_lexicographic,
        relaxation_master,
        output_flag=output_flag,
        time_limit=budget.subproblem_time_limit(master=True),
        mip_gap=effective_master_mip_gap,
        threads=threads,
        mip_focus=mip_focus,
        seed=seed,
        lex_stage2=use_lex_master_stage2,
        leader_indifference_relative=leader_indifference_relative,
        tax_stage_time_limit=master_tax_time_limit,
    )
    _require_optimal_or_usable_partial_master(relaxation, "initial DBP relaxation")

    emissions_leader_lb = _required_value(relaxation.emissions, "initial relaxation emissions")
    incumbent: IncumbentSolution | None = None
    incumbent_solution = None
    previous_lexicographic_values: dict[str, float] | None = None
    emissions_follower_ub_certificate: BoundCertificate | None = None
    # The best-emissions evaluated point (the one behind the UB certificate): the MIP start the
    # elastic master is re-solved from, because it alone is sure to meet the emissions cap.
    best_ub_values: dict[str, float] | None = None
    best_ub_tax_index: int | None = None
    follower_variable_names: list[str] | None = None
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
                emissions_follower_ub_certificate=emissions_follower_ub_certificate,
                emissions_leader_lb=emissions_leader_lb,
                iteration=len(iteration_records),
                iteration_records=iteration_records,
                iteration_timings=iteration_timings,
                initial_relaxation_seconds=initial_relaxation_seconds,
                termination_reason="incumbent_wall_clock_cap",
            )

        current_relaxation_lower_bound = emissions_leader_lb
        tax_index = _required_value(relaxation.tax_index, "relaxation tax_index")

        lexicographic, lexicographic_seconds = _solve_with_wall_time(
            solve_follower_lexicographic,
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
            use_follower_improvement=use_follower_improvement,
        )
        # A follower that stopped on its time limit WITH a response is used, as Soares et al.
        # (2021, Sect. 7) use a gapped (P3)/(P4-D) solution; only a follower with no response
        # at all ends the run.
        if not lexicographic.has_solution and lexicographic.status_name == "TIME_LIMIT":
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
                    emissions_follower_ub_certificate=emissions_follower_ub_certificate,
                    emissions_leader_lb=emissions_leader_lb,
                    iteration=len(iteration_records),
                    iteration_records=iteration_records,
                    iteration_timings=iteration_timings,
                    initial_relaxation_seconds=initial_relaxation_seconds,
                    termination_reason=_timeout_reason(budget),
                )
            raise SubproblemStatusError(
                f"lexicographic follower solve at tax_index={tax_index}", lexicographic,
            )
        if not lexicographic.has_solution or lexicographic.status_name not in ("OPTIMAL", "TIME_LIMIT"):
            raise SubproblemStatusError(
                f"lexicographic follower solve at tax_index={tax_index}", lexicographic,
            )
        follower_time_limited = lexicographic.status_name != "OPTIMAL"
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
        # `emissions_follower_ub_certificate` is the EMISSIONS BOUND: the least emissions any evaluated
        # point attained. This is what pairs with emissions_leader_lb to certify the leader's first
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
        if emissions_follower_ub_certificate is None or candidate.emissions < emissions_follower_ub_certificate.value:
            emissions_follower_ub_certificate = BoundCertificate(
                value=candidate.emissions,
                # A response from a follower that stopped on its time limit is the best one
                # found, not a proven best response: its emissions bound the leader only up to
                # that follower's own gap.
                exact=not follower_time_limited,
                mip_gap=lexicographic.mip_gap,
                slack=0.0,
                source="lexicographic" if not follower_time_limited else "lexicographic_time_limited",
            )
            best_ub_values = lexicographic.variable_values
            best_ub_tax_index = tax_index

        # (P5-eps'): f(x, y) <= f(x, y_k) + eps', with eps' added by add_value_function_cut. Not
        # loosened by the follower's MIP gap: the cut is valid for ANY feasible y_k (Soares et
        # al.'s Lemma 2 -- the follower's constraints do not depend on x), proven best response
        # or not, so widening it only weakens the master.
        cut = ValueFunctionCut(
            tax_index=tax_index,
            cost=candidate.cost,
            emissions=candidate.emissions,
            # The cut's tau-coefficient must be the quantity the follower was
            # actually taxed on -- the discounted base -- while `emissions`
            # stays physical for the leader's bound. The two coincide when the
            # instance carries no interest rate.
            tax_base=lexicographic.tax_base,
            iteration=iteration,
        )
        add_value_function_cut(relaxation_master, cut)
        if use_emissions_cap:
            set_emissions_cap(
                relaxation_master, emissions_follower_ub_certificate.value,
            )

        relaxation, relaxation_seconds = _solve_with_wall_time(
            solve_leader_master_lexicographic,
            relaxation_master,
            output_flag=output_flag,
            time_limit=budget.subproblem_time_limit(master=True),
            mip_gap=effective_master_mip_gap,
            threads=threads,
            mip_focus=mip_focus,
            seed=seed,
            lex_stage2=use_lex_master_stage2,
            leader_indifference_relative=leader_indifference_relative,
            tax_stage_time_limit=master_tax_time_limit,
        )
        if (
            use_elastic_master
            and _master_returned_no_point(relaxation)
            and not relaxation_master.elastic
            and best_ub_values is not None
            and best_ub_tax_index is not None
        ):
            # (P5-D) as a remedy (Soares et al. 2021, Difficulty 1): the plain master returned
            # no point, so make its cuts elastic and re-solve from the best evaluated point,
            # which the elastic master is bound to accept. Its time counts toward this
            # iteration's relaxation_seconds.
            enable_elastic_cuts(relaxation_master)
            if follower_variable_names is None:
                follower_variable_names = [
                    variable.VarName for variable in follower_master.artifacts.model.getVars()
                ]
            set_leader_master_start(
                relaxation_master, best_ub_values, follower_variable_names, best_ub_tax_index,
            )
            relaxation, elastic_retry_seconds = _solve_with_wall_time(
                solve_leader_master_lexicographic,
                relaxation_master,
                output_flag=output_flag,
                time_limit=budget.subproblem_time_limit(master=True),
                mip_gap=effective_master_mip_gap,
                threads=threads,
                mip_focus=mip_focus,
                seed=seed,
                lex_stage2=use_lex_master_stage2,
                leader_indifference_relative=leader_indifference_relative,
                tax_stage_time_limit=master_tax_time_limit,
            )
            relaxation_seconds += elastic_retry_seconds
        if _is_partial_master(relaxation) and not _is_usable_partial_master(relaxation):
            # Timed out with nothing to propose next (no incumbent point). The dual bound it did
            # prove is still valid, so keep it in the reported gap before stopping.
            if relaxation.leader_lower_bound is not None:
                emissions_leader_lb = max(emissions_leader_lb, relaxation.leader_lower_bound)
            # Follower completed OPTIMAL this iteration, so incumbent is guaranteed set.
            return _build_time_limit_result(
                incumbent=incumbent,
                incumbent_solution=incumbent_solution,
                emissions_follower_ub_certificate=emissions_follower_ub_certificate,
                emissions_leader_lb=emissions_leader_lb,
                iteration=iteration,
                iteration_records=iteration_records,
                iteration_timings=iteration_timings,
                initial_relaxation_seconds=initial_relaxation_seconds,
                termination_reason=_timeout_reason(budget),
            )
        _require_optimal_or_usable_partial_master(relaxation, f"DBP relaxation after iteration {iteration}")
        relaxation_is_partial = _is_partial_master(relaxation)

        # The master only ever GAINS constraints, so its optimum cannot fall -- but the value
        # read off it is ObjBound at mip_gap, which oscillates within that gap (measured: a
        # 15 kg drop between consecutive iterations on STD_I17_M4_T3). Each iteration's value is
        # individually a valid bound, so their maximum is too, and keeping it makes the
        # certified floor monotone. That monotonicity is what the tax phase below rests on: only
        # with a stable floor is the master's freeze band stable, and only then is its Stage-2
        # proposal a non-decreasing lower bound on the least-intervention tax.
        relaxation_lower_bound = _required_value(relaxation.emissions, "relaxation emissions")
        previous_lower_bound = emissions_leader_lb
        emissions_leader_lb = max(emissions_leader_lb, relaxation_lower_bound)
        lower_bound_updated = emissions_leader_lb > previous_lower_bound + DEFAULT.eps
        if use_emissions_floor and lower_bound_updated:
            set_emissions_floor(relaxation_master, emissions_leader_lb)
        relaxation_elastic_slack = relaxation.slack_value
        # The penalty is in tonnes per USD of violation, so anything above round-off is a real one.
        elastic_active = relaxation_elastic_slack is not None and relaxation_elastic_slack > 1e-6
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
                incumbent_emissions=emissions_follower_ub_certificate.value,
                relaxation_seconds=relaxation_seconds,
                next_relaxation_tax_index=next_tax_index,
                next_relaxation_lower_bound=emissions_leader_lb,
                relaxation_emissions_seconds=relaxation.lex_primary_seconds,
                relaxation_tax_seconds=relaxation.lex_secondary_seconds,
                relaxation_mip_gap=relaxation.mip_gap,
                relaxation_partial=relaxation_is_partial,
                relaxation_emissions_mip_gap=relaxation.lex_primary_mip_gap,
                relaxation_tax_mip_gap=relaxation.lex_secondary_mip_gap,
                relaxation_elastic_slack=relaxation_elastic_slack,
                follower_mip_gap=lexicographic.mip_gap,
                follower_time_limited=follower_time_limited,
                follower_improved=lexicographic.follower_improved,
                follower_stage2_fallback=lexicographic.follower_stage2_fallback,
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
                emissions_follower_ub=emissions_follower_ub_certificate.value,
                emissions_leader_lb=emissions_leader_lb,
            )
            <= effective_dbp_relative_gap
        ):
            if relaxation_is_partial or elastic_active or not emissions_follower_ub_certificate.exact:
                # The emissions gap closed on a valid dual bound. But at least one ingredient of
                # a certificate is missing: the master never reached its Stage-2 minimum, or its
                # point violates a cut (elastic slack > 0), so its tax is a proposal rather than
                # a lower bound on the least-intervention tax; or the upper bound comes from a
                # follower that stopped on its time limit, so it is not a proven best response.
                # Soares et al. (2021)'s Step 6 else-branch applies -- report the epsilon-optimal
                # result, never a certified one.
                return _gap_closed_tax_unconfirmed_result(
                    iteration=iteration,
                    emissions_leader_lb=emissions_leader_lb,
                    incumbent=incumbent,
                    incumbent_solution=incumbent_solution,
                    emissions_follower_ub_certificate=emissions_follower_ub_certificate,
                    relaxation_mip_gap=relaxation.mip_gap,
                    iteration_records=iteration_records,
                    iteration_timings=iteration_timings,
                    initial_relaxation_seconds=initial_relaxation_seconds,
                    tax_index_lower_bound=None,
                )
            tax_proposal_confirms = next_tax_index >= incumbent.tax_index
            if effective_use_tax_confirmation and not _min_tax_confirmed(
                incumbent_emissions=emissions_follower_ub_certificate.value,
                incumbent_tax_index=incumbent.tax_index,
                emissions_leader_lb=emissions_leader_lb,
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
                    emissions_leader_lb=emissions_leader_lb,
                    incumbent=incumbent,
                    incumbent_solution=incumbent_solution,
                    emissions_follower_ub_certificate=emissions_follower_ub_certificate,
                    relaxation_mip_gap=relaxation.mip_gap,
                    iteration_records=iteration_records,
                    iteration_timings=iteration_timings,
                    initial_relaxation_seconds=initial_relaxation_seconds,
                    tax_index_lower_bound=next_tax_index,
                )
            return _gap_closed_result(
                iteration=iteration,
                emissions_leader_lb=emissions_leader_lb,
                incumbent=incumbent,
                incumbent_solution=incumbent_solution,
                emissions_follower_ub_certificate=emissions_follower_ub_certificate,
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
                emissions_leader_lb=emissions_leader_lb,
                incumbent=incumbent,
                incumbent_solution=incumbent_solution,
                emissions_follower_ub_certificate=emissions_follower_ub_certificate,
                relaxation_mip_gap=relaxation.mip_gap,
                effective_dbp_relative_gap=effective_dbp_relative_gap,
                iteration_records=iteration_records,
                iteration_timings=iteration_timings,
                initial_relaxation_seconds=initial_relaxation_seconds,
            )

