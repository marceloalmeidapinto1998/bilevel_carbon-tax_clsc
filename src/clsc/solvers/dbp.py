"""Deterministic Bounding Procedure for the bilevel carbon-tax problem (Soares et al. 2021).

CORRESPONDENCE WITH Soares, Alves & Henggeler Antunes (2021), EJOR 291, 52-66
-- kept here, in one place, so the module can be read with the paper open.

  Their notation          Here                              Built / solved by
  ---------------------------------------------------------------------------
  x^u                     tax_index (integer)               the leader's choice
  y                       the whole supply chain            the model's own variables,
                                                            built in _build_supply_chain_model *
  F(x, y)                 E + w * tax_index                 the leader's single objective **
  f(x, y)                 cost + tax_rate * tax_base        follower's objective
  g(y) <= 0               the chain's physical constraints  _build_supply_chain_model
                          -- independent of the tax
  (P2)   HPR              leader master, no cuts yet        build_leader_master
  (P5)   HPR + cuts       the SAME master, k cuts later     add_value_function_cut
  (P3)+(P4-eps')          follower at a fixed tax           solve_follower_lexicographic ***
  y_k                     the point that generates cut k    ValueFunctionCut
  eps                     loop stopping criterion           dbp_relative_gap
  eps'                    subproblem feasibility slack      lex_freeze_tolerance
  Lemma 1                 the follower's point is           where the follower's answer
                          bilevel-feasible, so it bounds    sets emissions_follower_ub_
                                                            certificate (the UB on F)
  Lemma 2                 cuts remove nothing optimal       add_value_function_cut
  Lemma 3                 master re-proposes the same       the gap-closed branch of the loop
                          tax => optimum

  Section 7-8: subproblems that cannot be solved to optimality inside their budget
  UB_F = F (1 + gap_HPR)  the master's DUAL bound            solve_dbp_master
                          (ObjBound), also when it times    (leader_lower_bound)
                          out -- the exact form of the
                          same correction
  F <= UB_F  (Mitsos)     E + w*tax_index <= UB on the      set_leader_objective_cap
                          master
  (P5-D)  elastic HPR     one penalised slack per cut,      enable_elastic_cuts
                          switched on the first time the
                          master returns no point
  (P4-D)  elastic P4      the tie-break finds nothing =>    solve_follower_lexicographic
                          keep the Step-2 response
  (P6)                    improve a timed-out follower      _improve_follower_value
  auxiliary stop          bounds unchanged 10 iterations    DEFAULT.stagnation_limit

  * y has no collective name in the code, and needs none. SolveResult.variable_values is a
    SNAPSHOT of one solution of those variables (Gurobi VarName -> value, non-zeros only),
    captured after a solve and used for solution.json and the next warm start. It is filled by
    the leader master as readily as by the follower, so it is not "y" and is not the follower's.

 ** THE LEADER HAS ONE OBJECTIVE, F = E + w * tax_index, where E is total physical emissions and
    w (kg CO2e per grid index, derived from ``leader_tax_weight`` in kg per USD/t) is how much
    emissions the regulator gives up to avoid one more index of tax. w is a POLICY assumption, not
    a tolerance. One criterion is what lets this procedure be Soares et al.'s as written: a single
    master stage, the UB_F - LB_F gap, their Step 6 and Lemma 3, with nothing added to the leader
    side. The tax term is also what prefers the lower tax among taxes that abate the same.

*** The follower's two-stage solve (minimise cost + tax * emissions, then emissions among the
    cost-optimal responses) is the OPTIMISTIC tie-break of the bilevel problem, which the
    reference also assumes; it is part of the follower's response, not of the leader's objective.

THE BOUNDS ARE INVERTED against the paper, and this trips everyone. Soares et al.
MAXIMISE profit, so their relaxation gives an upper bound and their feasible point a
lower one. This leader MINIMISES, so both flip: the master gives the lower bound
(``emissions_leader_lb``) and the follower the upper one (``emissions_follower_ub``). Their LB_F is
this module's ``emissions_follower_ub``. Those field names are historical: they hold bounds on the
leader's objective F, and the incumbent's own emissions are in ``incumbent.emissions``.

WHAT THIS ADDS to the reference procedure: the exact one-hot linearisation of
tax_rate * emissions -- needed because this tax multiplies continuous flows, where theirs
multiplied binaries.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import itertools
import math
from pathlib import Path
import time

from clsc.config.defaults import DEFAULT
from clsc.models.instance_data import TAX_SCALE_FACTOR, InstanceData
from clsc.models.subproblems import (
    ValueFunctionCut,
    SolveResult,
    add_value_function_cut,
    build_leader_master,
    build_follower_master,
    enable_elastic_cuts,
    set_leader_master_start,
    set_leader_objective_cap,
    set_leader_tax_weight,
    set_emissions_cap,
    solve_dbp_master,
    solve_follower_lexicographic,
)


# TERMINATION REASONS. The first word is the STATUS of the result -- what you have -- and the
# rest is why the run stopped there. Sorting a results column by this groups by strength of
# claim:
#
#   optimal_*          certified. Gap closed AND Lemma 3 confirmed it.
#   epsilon_optimal    within dbp_relative_gap; Lemma 3 does not apply.
#   incumbent_*        the best point found; the gap did NOT close.
#
# The wording follows the reference: "terminates with the optimal solution(s)" /
# "terminates with the epsilon-optimal solution" (Soares et al. 2021, Step 6).
OPTIMAL_REASON = "optimal"
STAGNATION_REASON = "incumbent_stagnation"
# Soares et al. (2021)'s Step 6 else-branch: the bounds have closed to eps but the master's next
# proposal differs from the point just evaluated, so Lemma 3 does not apply.
EPSILON_OPTIMAL_REASON = "epsilon_optimal"


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
    # The master's own MIP gap at this iteration and whether it stopped on its time limit instead
    # of reaching its gap target. A partial master still yields a valid lower bound (its dual
    # bound) and a tax proposal -- see _is_usable_partial_master. Recorded per iteration so a
    # reader can see how much of a final gap is the master's.
    relaxation_mip_gap: float | None = None
    relaxation_partial: bool = False
    # Sum of the master's elastic cut slacks D_k at the point it returned (P5-D); > 0 means the
    # proposal violates some cut and cannot confirm optimality.
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
    # Weight of the tax in the leader's objective F = E + w*tau, kg CO2e per USD/t. The fields
    # named ``emissions_leader_lb`` / ``emissions_follower_ub`` are bounds on F, not on emissions
    # alone; the incumbent's own emissions are in ``incumbent``.
    leader_tax_weight: float = 0.0


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


def _is_better_scalar(
    candidate: IncumbentSolution,
    incumbent: IncumbentSolution | None,
    tax_weight_per_index: float,
) -> bool:
    """Incumbent comparator for the single-objective leader: the lower ``E + w * tax_index``,
    and at an exact tie (to numerical noise) the lower tax. The tax term is what prefers the
    lower tax within a plateau of equal emissions, so no second criterion is needed."""
    if incumbent is None:
        return True
    candidate_value = candidate.emissions + tax_weight_per_index * candidate.tax_index
    incumbent_value = incumbent.emissions + tax_weight_per_index * incumbent.tax_index
    tolerance = _emissions_tie_tolerance(candidate_value, incumbent_value)
    if candidate_value < incumbent_value - tolerance:
        return True
    if math.isclose(candidate_value, incumbent_value, abs_tol=tolerance):
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
    emissions_follower_ub: float,
    emissions_leader_lb: float,
    dbp_relative_gap: float | None = None,
) -> tuple[str, bool]:
    achieved_gap = relative_optimality_gap(emissions_follower_ub=emissions_follower_ub, emissions_leader_lb=emissions_leader_lb)
    threshold = DEFAULT.dbp_relative_gap if dbp_relative_gap is None else dbp_relative_gap
    if achieved_gap <= threshold:
        # Gap inside tolerance despite the stall. Reported exact, but NOT as plain `optimal`:
        # the loop stopped without ever reaching Step 6, so Lemma 3 never ran. The distinct
        # suffix keeps a gap-driven stop and a stall-driven one apart downstream.
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


def _with_epsilon_context(certificate: BoundCertificate) -> BoundCertificate:
    return BoundCertificate(
        value=certificate.value,
        exact=certificate.exact,
        mip_gap=certificate.mip_gap,
        slack=certificate.slack,
        source=f"{certificate.source}_epsilon_optimal",
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
    whatever the gap (the master is a relaxation, optimal or not), which is
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
        method="dbp",
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
# which the loop checks them; see the call sites in _solve_bilevel_dbp for exactly when each
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
) -> BilevelSolveResult:
    """Soares et al. (2021)'s Step 6, first branch: the gap has closed AND the master re-proposed
    the tax just evaluated, so by their Lemma 3 an optimal solution has been found.
    """
    return _build_bilevel_result(
        method="dbp",
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
        incumbent_solution=incumbent_solution,
    )


def _epsilon_optimal_result(
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
) -> BilevelSolveResult:
    """Soares et al. (2021)'s Step 6, else-branch: ``UB_F - LB_F <= eps`` but the master's next
    proposal is not the point just evaluated (or the master or follower behind it was only
    partially solved), so Lemma 3 does not apply: "terminate with the eps-optimal solution".
    ``exact=False``: the result is certified to eps, not proven optimal.
    """
    emissions_leader_lb_certificate = _with_epsilon_context(
        BoundCertificate(
            value=emissions_leader_lb,
            exact=True,
            mip_gap=relaxation_mip_gap,
            slack=0.0,
            source="relaxation",
        )
    )
    return _build_bilevel_result(
        method="dbp",
        mode="exact",
        termination_reason=EPSILON_OPTIMAL_REASON,
        exact=False,
        iterations=iteration,
        emissions_leader_lb=emissions_leader_lb,
        emissions_follower_ub=emissions_follower_ub_certificate.value,
        emissions_leader_lb_certificate=emissions_leader_lb_certificate,
        emissions_follower_ub_certificate=_with_epsilon_context(emissions_follower_ub_certificate),
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
        method="dbp",
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
# DBP solver (single-objective leader, F = E + w * tax_index)
# ---------------------------------------------------------------------------

def solve_bilevel_dbp(instance_or_path: InstanceData | str | Path, **kwargs) -> BilevelSolveResult:
    """Run the DBP -- see :func:`_solve_bilevel_dbp` for every parameter. A thin wrapper that
    stamps the effective tax weight on the result, because that weight is only known inside
    (it can be derived from the instance's own emissions scale)."""
    sink: dict[str, float] = {}
    result = _solve_bilevel_dbp(instance_or_path, _effective_tax_weight_sink=sink, **kwargs)
    return replace(result, leader_tax_weight=sink.get("usd_per_tonne", 0.0))


def _solve_bilevel_dbp(
    instance_or_path: InstanceData | str | Path,
    *,
    _effective_tax_weight_sink: dict[str, float] | None = None,
    output_flag: bool = False,
    time_limit: float | None = None,
    master_time_limit: float | None = None,
    wall_clock_cap: float | None = None,
    mip_gap: float | None = None,
    master_mip_gap: float | None = None,
    dbp_relative_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
    seed: int | None = None,
    use_warm_start: bool = True,
    use_emissions_cap: bool = True,
    use_follower_improvement: bool = True,
    use_elastic_master: bool = True,
    leader_tax_weight: float | None = None,
    leader_tax_weight_relative: float | None = None,
) -> BilevelSolveResult:
    """Soares et al. (2021)'s DBP for the carbon-tax leader ``F = E + w * tax_index``.

    The loop squeezes a lower bound on F (the relaxation master's dual bound) against an upper
    bound (the least F any evaluated follower response attained) until ``UB - LB <= eps``. At
    that point the result is **optimal** if the master re-proposes the tax just evaluated (their
    Lemma 3) and **epsilon-optimal** otherwise -- Step 6, as written. The incumbent is the
    evaluated point with the least F, and at an exact tie the lower tax.

    THE LEADER'S OBJECTIVE. ``leader_tax_weight`` is ``w`` in kg of emissions per USD/t of tax;
    ``leader_tax_weight_relative`` is the same as a fraction ``q`` of the least emissions the
    cut-free master can reach (so it means the same on every instance), and is the default
    (``DEFAULT.tax_weight_relative``). Give at most one. ``w`` states how much emissions the
    regulator gives up to avoid 1 USD/t of tax: a POLICY assumption, not a tolerance, to be
    declared and varied. ``q = 1e-4`` reads "lose 1% of the minimum emissions to avoid 100 USD/t
    of tax". The run can resolve the tax only to about ``eps / q`` USD/t, because two taxes
    whose F differ by less than eps are indistinguishable to the gap. The bounds, trace values
    and the ``emissions_*`` result fields refer to F; the incumbent's own emissions are in
    ``incumbent.emissions``.

    BUDGETS AND GAPS. Every ``None`` takes its value from :data:`clsc.config.defaults.DEFAULT`,
    which holds the literature-based method (see its docstring). ``time_limit`` bounds ONE follower
    subproblem, and the master too unless ``master_time_limit`` gives it its own (``math.inf``
    removes the limit); ``wall_clock_cap`` optionally bounds the whole run (Soares et al. have
    none -- a run ends on its own stopping criteria). ``mip_gap`` is the follower's target and
    ``master_mip_gap`` the master's. The master's gap only loosens the lower bound, whose dual
    bound stays valid; the follower's gap loosens what counts as a best response.

    SUBPROBLEMS THAT CANNOT BE SOLVED TO OPTIMALITY (Soares et al., Sect. 7-8):

    * a master that stops on its time limit keeps its dual bound as the lower bound and its
      incumbent's tax is proposed next, instead of ending the run;
    * the first time the master returns no point at all (no incumbent, or infeasible), its cuts
      are made elastic in place (P5-D, ``use_elastic_master``) and it is re-solved from the best
      evaluated point, which the elastic master must accept;
    * a follower that stops on its time limit is improved by subproblem P6
      (``use_follower_improvement``); its best response is used, and a tie-break that finds
      nothing keeps the Step-2 response (P4-D). The result can then be epsilon-optimal at best;
    * ``use_emissions_cap`` (ablation A5) adds ``F <= UB`` (Mitsos 2010) to the master;
      ``use_warm_start`` (A3) warm-starts successive follower solves;
    * the run stops after ``DEFAULT.stagnation_limit`` iterations in which neither bound moved
      (their auxiliary stop).

    ``seed`` sets the Gurobi ``Seed`` on every sub-solve (MIP performance-variability probes).
    """
    instance = _coerce_instance(instance_or_path)
    effective_time_limit = DEFAULT.time_limit if time_limit is None else time_limit
    budget = _WallClockBudget(wall_clock_cap, effective_time_limit, master_time_limit)
    effective_dbp_relative_gap = DEFAULT.dbp_relative_gap if dbp_relative_gap is None else dbp_relative_gap
    effective_master_mip_gap = DEFAULT.master_mip_gap if master_mip_gap is None else master_mip_gap
    if leader_tax_weight is not None and leader_tax_weight_relative is not None:
        raise ValueError("give either leader_tax_weight or leader_tax_weight_relative, not both")
    if leader_tax_weight is None and leader_tax_weight_relative is None:
        leader_tax_weight_relative = DEFAULT.tax_weight_relative
    if (leader_tax_weight if leader_tax_weight is not None else leader_tax_weight_relative) <= 0.0:
        raise ValueError(
            "the leader's tax weight must be positive: with w = 0 the leader has no criterion "
            "to choose among taxes that abate the same"
        )

    iteration_records: list[DbpIterationRecord] = []
    iteration_timings: list[DbpIterationTiming] = []
    # Plain cuts to begin with; made elastic in place only if the master ever returns no point.
    relaxation_master = build_leader_master(instance)
    follower_master = build_follower_master(instance)

    def _solve_master():
        return _solve_with_wall_time(
            solve_dbp_master,
            relaxation_master,
            output_flag=output_flag,
            time_limit=budget.subproblem_time_limit(master=True),
            mip_gap=effective_master_mip_gap,
            threads=threads,
            mip_focus=mip_focus,
            seed=seed,
        )

    scale_seconds = 0.0
    usd_per_tonne_per_index = instance.scale_factor * 1000.0  # USD/t that one grid index is
    if leader_tax_weight_relative is not None:
        # The weight is relative to the least emissions the cut-free master can reach, which is a
        # lower bound on the leader's emissions at any tax: a scale that exists before any
        # follower has been solved, and that is the same on every instance. The master has no
        # tax term yet, so this solve returns that emissions bound.
        scale_run, scale_seconds = _solve_master()
        _require_optimal_or_usable_partial_master(scale_run, "initial DBP relaxation (weight scale)")
        reference_emissions = _required_value(scale_run.emissions, "reference emissions")
        weight_usd_per_tonne = leader_tax_weight_relative * float(reference_emissions)
    else:
        weight_usd_per_tonne = float(leader_tax_weight)
    tax_weight_per_index = weight_usd_per_tonne * usd_per_tonne_per_index
    set_leader_tax_weight(relaxation_master, tax_weight_per_index)
    if _effective_tax_weight_sink is not None:
        _effective_tax_weight_sink["usd_per_tonne"] = weight_usd_per_tonne

    relaxation, initial_relaxation_seconds = _solve_master()
    initial_relaxation_seconds += scale_seconds
    _require_optimal_or_usable_partial_master(relaxation, "initial DBP relaxation")

    # From here on `emissions_leader_lb` / `emissions_follower_ub_certificate` are the bounds on
    # the leader's objective F (the names are those of the result fields).
    emissions_leader_lb = _required_value(relaxation.emissions, "initial relaxation bound")
    incumbent: IncumbentSolution | None = None
    incumbent_solution = None
    previous_follower_values: dict[str, float] | None = None
    emissions_follower_ub_certificate: BoundCertificate | None = None
    # The best evaluated point (the one behind the UB certificate): the MIP start the elastic
    # master is re-solved from, because it alone is sure to meet the objective cap.
    best_ub_values: dict[str, float] | None = None
    best_ub_tax_index: int | None = None
    follower_variable_names: list[str] | None = None
    iterations_without_bound_update = 0

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

        follower_response, follower_seconds = _solve_with_wall_time(
            solve_follower_lexicographic,
            follower_master,
            tax_index=tax_index,
            output_flag=output_flag,
            time_limit=budget.subproblem_time_limit(),
            capture_solution=True,
            warm_start_values=previous_follower_values if use_warm_start else None,
            mip_gap=mip_gap,
            threads=threads,
            mip_focus=mip_focus,
            seed=seed,
            use_follower_improvement=use_follower_improvement,
        )
        # A follower that stopped on its time limit WITH a response is used, as Soares et al.
        # (2021, Sect. 7) use a gapped (P3)/(P4-D) solution; only a follower with no response
        # at all ends the run.
        if not follower_response.has_solution and follower_response.status_name == "TIME_LIMIT":
            if incumbent is not None:
                iteration_timings.append(DbpIterationTiming(
                    iteration=iteration,
                    follower_seconds=follower_seconds,
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
                f"follower solve at tax_index={tax_index}", follower_response,
            )
        if not follower_response.has_solution or follower_response.status_name not in ("OPTIMAL", "TIME_LIMIT"):
            raise SubproblemStatusError(
                f"follower solve at tax_index={tax_index}", follower_response,
            )
        follower_time_limited = follower_response.status_name != "OPTIMAL"
        if follower_response.variable_values is not None:
            previous_follower_values = follower_response.variable_values

        candidate = IncumbentSolution(
            tax_index=tax_index,
            cost=_required_value(follower_response.cost, "follower cost"),
            emissions=_required_value(follower_response.emissions, "follower emissions"),
            follower_objective=_required_value(
                follower_response.follower_objective,
                "follower objective",
            ),
            scale_factor=instance.scale_factor,
        )
        # The leader's value at this point, F = E + w * tax_index. The incumbent IS the point that
        # attains the upper bound: the least F evaluated, and at an exact tie the lower tax.
        candidate_value = candidate.emissions + tax_weight_per_index * tax_index
        incumbent_updated = _is_better_scalar(candidate, incumbent, tax_weight_per_index)
        if incumbent_updated:
            incumbent = candidate
            incumbent_solution = follower_response
        if emissions_follower_ub_certificate is None or candidate_value < emissions_follower_ub_certificate.value:
            emissions_follower_ub_certificate = BoundCertificate(
                value=candidate_value,
                # A response from a follower that stopped on its time limit is the best one
                # found, not a proven best response: its F bounds the leader only up to that
                # follower's own gap.
                exact=not follower_time_limited,
                mip_gap=follower_response.mip_gap,
                slack=0.0,
                source="follower" if not follower_time_limited else "follower_time_limited",
            )
            best_ub_values = follower_response.variable_values
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
            tax_base=follower_response.tax_base,
            iteration=iteration,
        )
        add_value_function_cut(relaxation_master, cut)
        if use_emissions_cap:
            # E <= UB holds at any point with F <= UB (the tax term is non-negative), and it is
            # what lets the one-hot gadget's big-M be tightened; set_leader_objective_cap adds the
            # tighter F <= UB (Soares et al. / Mitsos).
            set_emissions_cap(
                relaxation_master, emissions_follower_ub_certificate.value,
            )
            set_leader_objective_cap(relaxation_master, emissions_follower_ub_certificate.value)

        relaxation, relaxation_seconds = _solve_master()
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
            relaxation, elastic_retry_seconds = _solve_master()
            relaxation_seconds += elastic_retry_seconds
        if _is_partial_master(relaxation) and not _is_usable_partial_master(relaxation):
            # Timed out with nothing to propose next (no incumbent point). The dual bound it did
            # prove is still valid, so keep it in the reported gap before stopping.
            if relaxation.leader_lower_bound is not None:
                emissions_leader_lb = max(emissions_leader_lb, relaxation.leader_lower_bound)
            # Follower completed this iteration, so the incumbent is guaranteed set.
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
        # certified lower bound monotone.
        relaxation_lower_bound = _required_value(relaxation.emissions, "relaxation bound")
        previous_lower_bound = emissions_leader_lb
        emissions_leader_lb = max(emissions_leader_lb, relaxation_lower_bound)
        lower_bound_updated = emissions_leader_lb > previous_lower_bound + DEFAULT.eps
        relaxation_elastic_slack = relaxation.slack_value
        # The penalty is in tonnes per USD of violation, so anything above round-off is a real one.
        elastic_active = relaxation_elastic_slack is not None and relaxation_elastic_slack > 1e-6
        next_tax_index = _required_value(relaxation.tax_index, "next relaxation tax_index")
        iteration_records.append(
            DbpIterationRecord(
                iteration=iteration,
                relaxation_tax_index=tax_index,
                relaxation_lower_bound=current_relaxation_lower_bound,
                follower_seconds=follower_seconds,
                follower_objective=candidate.follower_objective,
                optimistic_seconds=0.0,
                optimistic_cost=candidate.cost,
                optimistic_emissions=candidate.emissions,
                incumbent_emissions=emissions_follower_ub_certificate.value,
                relaxation_seconds=relaxation_seconds,
                next_relaxation_tax_index=next_tax_index,
                next_relaxation_lower_bound=emissions_leader_lb,
                relaxation_mip_gap=relaxation.mip_gap,
                relaxation_partial=relaxation_is_partial,
                relaxation_elastic_slack=relaxation_elastic_slack,
                follower_mip_gap=follower_response.mip_gap,
                follower_time_limited=follower_time_limited,
                follower_improved=follower_response.follower_improved,
                follower_stage2_fallback=follower_response.follower_stage2_fallback,
            )
        )
        iteration_timings.append(
            DbpIterationTiming(
                iteration=iteration,
                follower_seconds=follower_seconds,
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
            # Step 6: the gap has closed, so the result is at least epsilon-optimal; if the
            # master re-proposes the tax just evaluated, Lemma 3 makes it optimal. The lemma
            # needs a proper master solution (not a timed-out incumbent, not an elastic point)
            # and a proven best response behind the upper bound.
            if (
                not relaxation_is_partial
                and not elastic_active
                and emissions_follower_ub_certificate.exact
                and next_tax_index == tax_index
            ):
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
                )
            return _epsilon_optimal_result(
                iteration=iteration,
                emissions_leader_lb=emissions_leader_lb,
                incumbent=incumbent,
                incumbent_solution=incumbent_solution,
                emissions_follower_ub_certificate=emissions_follower_ub_certificate,
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
