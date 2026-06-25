from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import time
from typing import Literal

from src.config.gap_tol import DEFAULT
from src.models.shared_models import (
    DbpFollowerCut,
    SolveResult,
    add_dbp_relaxation_cut,
    build_dbp_relaxation_master,
    lex_freeze_tolerance,
    set_dbp_relaxation_objective_upper_bound,
    solve_dbp_relaxation,
    solve_fixed_tax_follower,
    solve_fixed_tax_optimistic,
)
from src.models.instance_loader import CARBON_TAX_SCALE, InstanceData


DEFAULT_DBP_MODE: "DbpMode" = "exact"
STAGNATION_GAP_NOT_CLOSED_REASON = "stagnation_limit_gap_not_closed"

DbpMode = Literal["exact", "certified"]


@dataclass(frozen=True, slots=True)
class IncumbentSolution:
    hat_tau: int
    cost: float
    emissions: float
    follower_objective: float

    @property
    def effective_tax(self) -> float:
        return CARBON_TAX_SCALE * self.hat_tau


@dataclass(frozen=True, slots=True)
class TaxSolveSnapshot:
    iteration: int
    hat_tau: int
    solve_seconds: float
    objective_value: float | None
    cost: float
    emissions: float
    follower_objective: float
    mip_gap: float | None
    lex_primary_mip_gap: float | None = None
    lex_secondary_mip_gap: float | None = None
    variable_values: dict[str, float] | None = None

    @property
    def effective_tax(self) -> float:
        return CARBON_TAX_SCALE * self.hat_tau


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
    relaxation_hat_tau: int
    relaxation_lower_bound: float
    follower_seconds: float
    follower_objective: float
    optimistic_seconds: float
    optimistic_cost: float
    optimistic_emissions: float
    incumbent_emissions: float
    relaxation_seconds: float
    next_relaxation_hat_tau: int
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
class FinalRefinementAttempt:
    hat_tau: int
    solve_seconds: float
    emissions: float
    follower_objective: float
    matched_incumbent_emissions: bool


@dataclass(frozen=True, slots=True)
class FinalRefinementSummary:
    initial_hat_tau: int
    selected_hat_tau: int
    lower_hat_tau: int
    total_seconds: float
    changed_incumbent: bool
    attempts: tuple[FinalRefinementAttempt, ...]
    termination_reason: str | None = None
    exact: bool | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    emissions_target: float | None = None
    emissions_cap: float | None = None

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


@dataclass(frozen=True, slots=True)
class BilevelSolveResult:
    method: str
    mode: DbpMode
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
    final_refinement: FinalRefinementSummary | None = None
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


def solve_bilevel_dbp(
    instance_or_path: InstanceData | str | Path,
    *,
    max_iterations: int | None = None,
    output_flag: bool = False,
    time_limit: float | None = None,
    mode: DbpMode = DEFAULT_DBP_MODE,
) -> BilevelSolveResult:
    instance = _coerce_instance(instance_or_path)
    max_iterations = max_iterations or (len(instance.iter_hat_tau()) + 1)
    if mode not in {"exact", "certified"}:
        raise ValueError("mode must be 'exact' or 'certified'")
    if mode == "exact":
        return _solve_bilevel_dbp_exact(
            instance,
            max_iterations=max_iterations,
            output_flag=output_flag,
            time_limit=time_limit,
        )
    from src.solvers.dbp_certified import solve_bilevel_dbp_certified

    return solve_bilevel_dbp_certified(
        instance,
        max_iterations=max_iterations,
        output_flag=output_flag,
        time_limit=time_limit,
    )


def _solve_bilevel_dbp_exact(
    instance: InstanceData,
    *,
    max_iterations: int,
    output_flag: bool,
    time_limit: float | None,
) -> BilevelSolveResult:
    iteration_records: list[DbpIterationRecord] = []
    iteration_timings: list[DbpIterationTiming] = []
    relaxation_master = build_dbp_relaxation_master(instance)

    relaxation, initial_relaxation_seconds = _solve_with_wall_time(
        solve_dbp_relaxation,
        relaxation_master,
        output_flag=output_flag,
        time_limit=time_limit,
    )
    _require_optimal_result(relaxation, "initial DBP relaxation")

    lower_bound = _required_value(relaxation.emissions, "initial relaxation emissions")
    best_lower_bound = lower_bound
    incumbent: IncumbentSolution | None = None
    incumbent_solution: SolveResult | None = None
    upper_bound_certificate: BoundCertificate | None = None
    iterations_without_bound_update = 0

    for iteration in range(1, max_iterations + 1):
        current_relaxation_lower_bound = best_lower_bound
        hat_tau = _required_value(relaxation.hat_tau, "relaxation hat_tau")

        follower, follower_seconds = _solve_with_wall_time(
            solve_fixed_tax_follower,
            instance,
            hat_tau=hat_tau,
            output_flag=output_flag,
            time_limit=time_limit,
        )
        _require_optimal_result(follower, f"follower problem at hat_tau={hat_tau}")

        follower_objective = _required_value(
            follower.follower_objective,
            f"follower objective at hat_tau={hat_tau}",
        )
        follower_objective_upper = follower_objective_cap(follower_objective, follower.mip_gap)
        optimistic, optimistic_seconds = _solve_with_wall_time(
            solve_fixed_tax_optimistic,
            instance,
            hat_tau=hat_tau,
            follower_objective_upper=follower_objective_upper,
            output_flag=output_flag,
            time_limit=time_limit,
            capture_solution=True,
        )
        _require_optimal_result(optimistic, f"optimistic tie-break at hat_tau={hat_tau}")

        candidate = IncumbentSolution(
            hat_tau=hat_tau,
            cost=_required_value(optimistic.cost, "optimistic cost"),
            emissions=_required_value(optimistic.emissions, "optimistic emissions"),
            follower_objective=_required_value(optimistic.follower_objective, "optimistic follower objective"),
        )
        incumbent_updated = _is_better_candidate(candidate, incumbent)
        if incumbent_updated:
            incumbent = candidate
            incumbent_solution = optimistic
            upper_bound_certificate = BoundCertificate(
                value=candidate.emissions,
                exact=_is_gap_exact(follower.mip_gap) and _is_gap_exact(optimistic.mip_gap),
                mip_gap=optimistic.mip_gap,
                slack=0.0,
                source="optimistic",
            )

        cut_cost = candidate.cost + max(
            0.0,
            follower_objective_upper - candidate.follower_objective,
        )
        cut = DbpFollowerCut(
            hat_tau=hat_tau,
            cost=cut_cost,
            emissions=candidate.emissions,
            iteration=iteration,
        )
        add_dbp_relaxation_cut(relaxation_master, cut)
        set_dbp_relaxation_objective_upper_bound(relaxation_master, incumbent.emissions)

        relaxation, relaxation_seconds = _solve_with_wall_time(
            solve_dbp_relaxation,
            relaxation_master,
            output_flag=output_flag,
            time_limit=time_limit,
        )
        _require_optimal_result(relaxation, f"DBP relaxation after iteration {iteration}")

        lower_bound = _required_value(relaxation.emissions, "relaxation emissions")
        previous_lower_bound = best_lower_bound
        best_lower_bound = lower_bound
        lower_bound_updated = lower_bound > previous_lower_bound + DEFAULT.eps
        next_hat_tau = _required_value(relaxation.hat_tau, "next relaxation hat_tau")
        iteration_records.append(
            DbpIterationRecord(
                iteration=iteration,
                relaxation_hat_tau=hat_tau,
                relaxation_lower_bound=current_relaxation_lower_bound,
                follower_seconds=follower_seconds,
                follower_objective=follower_objective,
                optimistic_seconds=optimistic_seconds,
                optimistic_cost=candidate.cost,
                optimistic_emissions=candidate.emissions,
                incumbent_emissions=incumbent.emissions,
                relaxation_seconds=relaxation_seconds,
                next_relaxation_hat_tau=next_hat_tau,
                next_relaxation_lower_bound=best_lower_bound,
            )
        )
        iteration_timings.append(
            DbpIterationTiming(
                iteration=iteration,
                follower_seconds=follower_seconds,
                optimistic_seconds=optimistic_seconds,
                relaxation_seconds=relaxation_seconds,
            )
        )

        if (
            relative_optimality_gap(
                upper_bound=incumbent.emissions,
                lower_bound=best_lower_bound,
            )
            <= DEFAULT.dbp_relative_gap
        ):
            return _build_bilevel_result(
                method="dbp_exact",
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
                method="dbp_exact",
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
        raise RuntimeError("DBP terminated without an incumbent solution")

    return _build_bilevel_result(
        method="dbp_exact",
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

def _coerce_instance(instance_or_path: InstanceData | str | Path) -> InstanceData:
    if isinstance(instance_or_path, InstanceData):
        return instance_or_path
    return InstanceData.from_file(instance_or_path)


def _build_bilevel_result(
    *,
    method: str,
    mode: DbpMode,
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
    final_refinement: FinalRefinementSummary | None = None,
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
        final_refinement=final_refinement,
        incumbent_solution=incumbent_solution,
        enumeration_solutions=enumeration_solutions,
    )


def relative_optimality_gap(
    *,
    upper_bound: float,
    lower_bound: float,
) -> float:
    gap = max(0.0, upper_bound - lower_bound)
    return gap / max(1.0, abs(upper_bound))


def _classify_stagnation_stop(*, upper_bound: float, lower_bound: float) -> tuple[str, bool]:
    achieved_gap = relative_optimality_gap(upper_bound=upper_bound, lower_bound=lower_bound)
    if achieved_gap <= DEFAULT.dbp_relative_gap:
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


def follower_objective_cap(follower_objective: float, mip_gap: float | None = None) -> float:
    return follower_objective + lex_freeze_tolerance(follower_objective, mip_gap)


def _is_gap_exact(mip_gap: float | None) -> bool:
    """True only if a MIP gap was actually reported and has closed to within
    ``DEFAULT.eps``. Gurobi's ``OPTIMAL`` status only means the gap closed to
    within the *configured* ``MIPGap`` target (``DEFAULT.mip_gap``, currently
    1e-4) -- it does not imply the much tighter exactness bar used to label a
    bilevel result ``exact=True`` for publication-grade claims."""
    return mip_gap is not None and mip_gap <= DEFAULT.eps


def _is_better_candidate(candidate: IncumbentSolution, incumbent: IncumbentSolution | None) -> bool:
    """Leader-level incumbent comparator: lexmin(emissions, hat_tau), per eq:leader_obj
    (paper/sections/04b_leader.tex). Each candidate's emissions value already reflects the
    follower's optimistic (as:opt) tie-break for its own hat_tau, so no further
    follower_objective tier belongs here -- see enum_lf_lex_exact._is_better_emissions_then_tax
    for the equivalent two-level comparator."""
    if incumbent is None:
        return True
    if candidate.emissions < incumbent.emissions - DEFAULT.eps:
        return True
    if math.isclose(candidate.emissions, incumbent.emissions, abs_tol=DEFAULT.eps):
        return candidate.hat_tau < incumbent.hat_tau
    return False


def _require_optimal_result(result: SolveResult, label: str) -> None:
    if not result.has_solution or result.status_name != "OPTIMAL":
        raise SubproblemStatusError(label, result)


def _required_value(value: float | int | None, label: str) -> float | int:
    if value is None:
        raise RuntimeError(f"Missing value for {label}")
    return value


def _solve_with_wall_time(solver_fn, *args, **kwargs):
    started_at = time.perf_counter()
    result = solver_fn(*args, **kwargs)
    return result, round(time.perf_counter() - started_at, 6)


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
