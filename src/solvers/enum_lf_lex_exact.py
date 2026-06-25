from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math

from src.config.gap_tol import DEFAULT
from src.models.instance_loader import InstanceData
from src.models.shared_models import build_fixed_tax_follower_master, solve_fixed_tax_lexicographic
from src.solvers.dbp_exact import (
    BilevelSolveResult,
    BoundCertificate,
    DbpIterationRecord,
    DbpIterationTiming,
    DbpTimingSummary,
    IncumbentSolution,
    TaxSolveSnapshot,
    _build_bilevel_result,
    _coerce_instance,
    _require_optimal_result,
    _required_value,
    _solve_with_wall_time,
)


@dataclass(frozen=True, slots=True)
class EnumerationOracleValidation:
    status: str
    oracle_method: str
    oracle_iterations: int
    candidate_hat_tau: int
    oracle_hat_tau: int
    candidate_emissions: float
    oracle_emissions: float
    emissions_delta: float
    emissions_tolerance: float
    candidate_follower_objective: float
    oracle_follower_objective: float
    hat_tau_match: bool
    emissions_match: bool
    solve_seconds: float

    @property
    def matched(self) -> bool:
        return self.status == "validated"


def solve_bilevel_enumeration_lf_lex_exact(
    instance_or_path: InstanceData | str | Path,
    *,
    output_flag: bool = False,
    time_limit: float | None = None,
) -> BilevelSolveResult:
    """Pure enumeration oracle for the true lex leader and lex follower.

    For every integer ``hat_tau`` allowed by the instance, this solves the
    explicit two-stage lex follower. The selected leader solution is the best
    pair ``(emissions, hat_tau)``: minimum lex-follower emissions first, then
    minimum tax. No DBP relaxation or weighted scalarisation is used.
    """
    instance = _coerce_instance(instance_or_path)

    incumbent: IncumbentSolution | None = None
    incumbent_solution = None
    previous_lexicographic_values: dict[str, float] | None = None
    iteration_records: list[DbpIterationRecord] = []
    iteration_timings: list[DbpIterationTiming] = []
    enumeration_solutions: list[TaxSolveSnapshot] = []
    primary_gaps: list[float] = []
    secondary_gaps: list[float] = []
    follower_master = build_fixed_tax_follower_master(instance)

    hat_tau_values = tuple(instance.iter_hat_tau())
    for iteration, hat_tau in enumerate(hat_tau_values, start=1):
        lexicographic, follower_seconds = _solve_with_wall_time(
            solve_fixed_tax_lexicographic,
            follower_master,
            hat_tau=hat_tau,
            output_flag=output_flag,
            time_limit=time_limit,
            capture_solution=True,
            warm_start_values=previous_lexicographic_values,
        )
        _require_optimal_result(lexicographic, f"enumeration lex follower solve at hat_tau={hat_tau}")
        if lexicographic.variable_values is not None:
            previous_lexicographic_values = lexicographic.variable_values
        else:
            raise RuntimeError(f"Enumeration solve at hat_tau={hat_tau} did not capture decision variables")
        if lexicographic.lex_primary_mip_gap is not None:
            primary_gaps.append(lexicographic.lex_primary_mip_gap)
        if lexicographic.lex_secondary_mip_gap is not None:
            secondary_gaps.append(lexicographic.lex_secondary_mip_gap)

        candidate = IncumbentSolution(
            hat_tau=hat_tau,
            cost=float(_required_value(lexicographic.cost, "enumeration cost")),
            emissions=float(_required_value(lexicographic.emissions, "enumeration emissions")),
            follower_objective=float(
                _required_value(lexicographic.follower_objective, "enumeration follower objective")
            ),
        )
        enumeration_solutions.append(
            TaxSolveSnapshot(
                iteration=iteration,
                hat_tau=hat_tau,
                solve_seconds=follower_seconds,
                objective_value=lexicographic.objective_value,
                cost=candidate.cost,
                emissions=candidate.emissions,
                follower_objective=candidate.follower_objective,
                mip_gap=lexicographic.mip_gap,
                lex_primary_mip_gap=lexicographic.lex_primary_mip_gap,
                lex_secondary_mip_gap=lexicographic.lex_secondary_mip_gap,
                variable_values=lexicographic.variable_values,
            )
        )
        if _is_better_emissions_then_tax(candidate, incumbent):
            incumbent = candidate
            incumbent_solution = lexicographic

        selected_emissions = incumbent.emissions if incumbent is not None else math.nan
        next_hat_tau = hat_tau_values[iteration] if iteration < len(hat_tau_values) else -1
        iteration_records.append(
            DbpIterationRecord(
                iteration=iteration,
                relaxation_hat_tau=hat_tau,
                relaxation_lower_bound=selected_emissions,
                follower_seconds=follower_seconds,
                follower_objective=candidate.follower_objective,
                optimistic_seconds=0.0,
                optimistic_cost=candidate.cost,
                optimistic_emissions=candidate.emissions,
                incumbent_emissions=selected_emissions,
                relaxation_seconds=0.0,
                next_relaxation_hat_tau=next_hat_tau,
                next_relaxation_lower_bound=selected_emissions,
            )
        )
        iteration_timings.append(
            DbpIterationTiming(
                iteration=iteration,
                follower_seconds=follower_seconds,
                optimistic_seconds=0.0,
                relaxation_seconds=0.0,
            )
        )

    if incumbent is None or incumbent_solution is None:
        raise RuntimeError("Enumeration oracle terminated without an incumbent solution")

    worst_mip_gap = _max_optional((*primary_gaps, *secondary_gaps))
    certificate = BoundCertificate(
        value=incumbent.emissions,
        exact=worst_mip_gap is None or worst_mip_gap <= DEFAULT.eps,
        mip_gap=worst_mip_gap,
        slack=0.0,
        source="enumeration_lex_follower",
    )
    return _build_bilevel_result(
        method="enumeration_lf_lex_exact",
        mode="exact",
        termination_reason="enumerated_tax_range",
        exact=certificate.exact,
        iterations=len(hat_tau_values),
        lower_bound=incumbent.emissions,
        upper_bound=incumbent.emissions,
        lower_bound_certificate=certificate,
        upper_bound_certificate=certificate,
        incumbent=incumbent,
        iteration_records=tuple(iteration_records),
        dbp_timing=_build_enumeration_timing(tuple(iteration_timings)),
        incumbent_solution=incumbent_solution,
        enumeration_solutions=tuple(enumeration_solutions),
    )


def validate_result_against_enumeration_oracle(
    instance_or_path: InstanceData | str | Path,
    result: BilevelSolveResult,
    *,
    output_flag: bool = False,
    time_limit: float | None = None,
) -> tuple[EnumerationOracleValidation, BilevelSolveResult]:
    oracle, solve_seconds = _solve_with_wall_time(
        solve_bilevel_enumeration_lf_lex_exact,
        instance_or_path,
        output_flag=output_flag,
        time_limit=time_limit,
    )
    tolerance = max(
        DEFAULT.eps,
        DEFAULT.eps * abs(oracle.incumbent.emissions),
        DEFAULT.eps,
    )
    emissions_delta = result.incumbent.emissions - oracle.incumbent.emissions
    emissions_match = abs(emissions_delta) <= tolerance
    hat_tau_match = result.incumbent.hat_tau == oracle.incumbent.hat_tau
    validation = EnumerationOracleValidation(
        status="validated" if emissions_match and hat_tau_match else "mismatch",
        oracle_method=oracle.method,
        oracle_iterations=oracle.iterations,
        candidate_hat_tau=result.incumbent.hat_tau,
        oracle_hat_tau=oracle.incumbent.hat_tau,
        candidate_emissions=result.incumbent.emissions,
        oracle_emissions=oracle.incumbent.emissions,
        emissions_delta=emissions_delta,
        emissions_tolerance=tolerance,
        candidate_follower_objective=result.incumbent.follower_objective,
        oracle_follower_objective=oracle.incumbent.follower_objective,
        hat_tau_match=hat_tau_match,
        emissions_match=emissions_match,
        solve_seconds=solve_seconds,
    )
    return validation, oracle


def _is_better_emissions_then_tax(
    candidate: IncumbentSolution,
    incumbent: IncumbentSolution | None,
) -> bool:
    if incumbent is None:
        return True
    tolerance = max(
        DEFAULT.eps,
        DEFAULT.eps * max(abs(candidate.emissions), abs(incumbent.emissions)),
    )
    if candidate.emissions < incumbent.emissions - tolerance:
        return True
    if math.isclose(candidate.emissions, incumbent.emissions, abs_tol=tolerance):
        return candidate.hat_tau < incumbent.hat_tau
    return False


def _build_enumeration_timing(iteration_timings: tuple[DbpIterationTiming, ...]) -> DbpTimingSummary:
    follower_total = sum(timing.follower_seconds for timing in iteration_timings)
    return DbpTimingSummary(
        initial_relaxation_seconds=0.0,
        follower_total_seconds=follower_total,
        optimistic_total_seconds=0.0,
        iterative_relaxation_total_seconds=0.0,
        relaxation_total_seconds=0.0,
        total_subproblem_seconds=follower_total,
        iteration_timings=iteration_timings,
    )


def _max_optional(values: tuple[float, ...]) -> float | None:
    return max(values) if values else None
