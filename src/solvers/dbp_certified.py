from __future__ import annotations

import math
from dataclasses import dataclass

from src.models.elastic_models import (
    build_dbp_elastic_relaxation_master,
    solve_fixed_tax_follower_repair,
    solve_fixed_tax_optimistic_elastic,
)
from src.models.shared_models import (
    EMISSIONS_SCALE,
    DbpFollowerCut,
    SolveResult,
    add_dbp_relaxation_cut,
    build_dbp_relaxation_master,
    set_dbp_relaxation_objective_upper_bound,
    solve_dbp_relaxation,
    solve_fixed_tax_follower,
    solve_fixed_tax_optimistic,
)
from src.config.gap_tol import DEFAULT
from src.models.instance_loader import InstanceData
from src.solvers.dbp_exact import (
    BilevelSolveResult,
    BoundCertificate,
    DbpIterationRecord,
    DbpIterationTiming,
    IncumbentSolution,
    SubproblemStatusError,
    _build_bilevel_result,
    _build_dbp_timing_summary,
    _classify_stagnation_stop,
    _is_better_candidate,
    _is_gap_exact,
    _required_value,
    _solve_with_wall_time,
    _with_stagnation_context,
    follower_objective_cap,
    relative_optimality_gap,
)


@dataclass(frozen=True, slots=True)
class _CertifiedRelaxationStep:
    result: SolveResult
    certificate: BoundCertificate | None
    solve_seconds: float


@dataclass(frozen=True, slots=True)
class _CertifiedUpperBoundStep:
    result: SolveResult
    certificate: BoundCertificate
    solve_seconds: float


def solve_bilevel_dbp_certified(
    instance: InstanceData,
    *,
    max_iterations: int,
    output_flag: bool,
    time_limit: float | None,
) -> BilevelSolveResult:
    iteration_records: list[DbpIterationRecord] = []
    iteration_timings: list[DbpIterationTiming] = []
    relaxation_master = build_dbp_relaxation_master(instance)
    elastic_relaxation_master = build_dbp_elastic_relaxation_master(instance)

    relaxation_step = _solve_certified_relaxation(
        relaxation_master=relaxation_master,
        elastic_relaxation_master=elastic_relaxation_master,
        output_flag=output_flag,
        time_limit=time_limit,
        label="initial DBP relaxation",
    )
    relaxation = relaxation_step.result
    initial_relaxation_seconds = relaxation_step.solve_seconds
    best_lower_bound_certificate = _select_best_certificate(
        _nonnegative_emissions_certificate(),
        relaxation_step.certificate,
    )
    incumbent: IncumbentSolution | None = None
    incumbent_solution: SolveResult | None = None
    upper_bound_certificate: BoundCertificate | None = None
    iterations_without_bound_update = 0

    for iteration in range(1, max_iterations + 1):
        current_relaxation_lower_bound = best_lower_bound_certificate.value
        hat_tau = _required_value(relaxation.hat_tau, "relaxation hat_tau")

        follower, follower_seconds = _solve_with_wall_time(
            solve_fixed_tax_follower,
            instance,
            hat_tau=hat_tau,
            output_flag=output_flag,
            time_limit=time_limit,
        )
        certified_follower, follower_certificate, repair_seconds = _certify_follower_response(
            instance=instance,
            hat_tau=hat_tau,
            result=follower,
            output_flag=output_flag,
            time_limit=time_limit,
        )
        follower_seconds += repair_seconds
        follower_objective = follower_certificate.value
        follower_objective_upper = follower_objective_cap(follower_objective, follower_certificate.mip_gap)
        optimistic, optimistic_seconds = _solve_with_wall_time(
            solve_fixed_tax_optimistic,
            instance,
            hat_tau=hat_tau,
            follower_objective_upper=follower_objective_upper,
            output_flag=output_flag,
            time_limit=time_limit,
            capture_solution=True,
        )
        upper_bound_step = _certify_upper_bound(
            instance=instance,
            hat_tau=hat_tau,
            follower_objective_upper=follower_objective_upper,
            result=optimistic,
            output_flag=output_flag,
            time_limit=time_limit,
            label=f"optimistic tie-break at hat_tau={hat_tau}",
        )
        optimistic = upper_bound_step.result
        optimistic_seconds += upper_bound_step.solve_seconds
        optimistic_certificate = upper_bound_step.certificate

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
            upper_bound_certificate = optimistic_certificate

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
        add_dbp_relaxation_cut(elastic_relaxation_master, cut)
        set_dbp_relaxation_objective_upper_bound(relaxation_master, incumbent.emissions)
        set_dbp_relaxation_objective_upper_bound(elastic_relaxation_master, incumbent.emissions)

        relaxation_step = _solve_certified_relaxation(
            relaxation_master=relaxation_master,
            elastic_relaxation_master=elastic_relaxation_master,
            output_flag=output_flag,
            time_limit=time_limit,
            label=f"DBP relaxation after iteration {iteration}",
        )
        relaxation = relaxation_step.result
        previous_lower_bound = best_lower_bound_certificate.value
        best_lower_bound_certificate = _select_best_certificate(
            best_lower_bound_certificate,
            _filter_certified_lower_bound(
                relaxation_step.certificate,
                upper_bound_certificate=upper_bound_certificate,
            ),
        )
        best_lower_bound_certificate = _select_best_certificate(
            _nonnegative_emissions_certificate(),
            _filter_certified_lower_bound(
                best_lower_bound_certificate,
                upper_bound_certificate=upper_bound_certificate,
            ),
        )
        lower_bound_updated = best_lower_bound_certificate.value > previous_lower_bound + DEFAULT.eps
        next_hat_tau = _required_value(relaxation.hat_tau, "next relaxation hat_tau")
        iteration_records.append(
            DbpIterationRecord(
                iteration=iteration,
                relaxation_hat_tau=hat_tau,
                relaxation_lower_bound=current_relaxation_lower_bound,
                follower_seconds=follower_seconds,
                follower_objective=_required_value(
                    certified_follower.follower_objective,
                    f"certified follower objective at hat_tau={hat_tau}",
                ),
                optimistic_seconds=optimistic_seconds,
                optimistic_cost=candidate.cost,
                optimistic_emissions=candidate.emissions,
                incumbent_emissions=incumbent.emissions,
                relaxation_seconds=relaxation_step.solve_seconds,
                next_relaxation_hat_tau=next_hat_tau,
                next_relaxation_lower_bound=best_lower_bound_certificate.value,
            )
        )
        iteration_timings.append(
            DbpIterationTiming(
                iteration=iteration,
                follower_seconds=follower_seconds,
                optimistic_seconds=optimistic_seconds,
                relaxation_seconds=relaxation_step.solve_seconds,
            )
        )

        if upper_bound_certificate is not None and (
            relative_optimality_gap(
                upper_bound=upper_bound_certificate.value,
                lower_bound=best_lower_bound_certificate.value,
            )
            <= DEFAULT.dbp_relative_gap
        ):
            return _build_bilevel_result(
                method="dbp_certified",
                mode="certified",
                termination_reason="relative_gap",
                exact=best_lower_bound_certificate.exact and upper_bound_certificate.exact,
                iterations=iteration,
                lower_bound=best_lower_bound_certificate.value,
                upper_bound=upper_bound_certificate.value,
                lower_bound_certificate=best_lower_bound_certificate,
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

        if (
            upper_bound_certificate is not None
            and iterations_without_bound_update >= DEFAULT.stagnation_limit
        ):
            termination_reason, gap_closed = _classify_stagnation_stop(
                upper_bound=upper_bound_certificate.value,
                lower_bound=best_lower_bound_certificate.value,
            )
            lower_bound_certificate = _with_stagnation_context(best_lower_bound_certificate)
            stagnation_upper_bound_certificate = _with_stagnation_context(upper_bound_certificate)
            return _build_bilevel_result(
                method="dbp_certified",
                mode="certified",
                termination_reason=termination_reason,
                exact=gap_closed and lower_bound_certificate.exact and stagnation_upper_bound_certificate.exact,
                iterations=iteration,
                lower_bound=best_lower_bound_certificate.value,
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

    if incumbent is None or upper_bound_certificate is None:
        raise RuntimeError("DBP terminated without an incumbent solution")

    return _build_bilevel_result(
        method="dbp_certified",
        mode="certified",
        termination_reason="max_iterations",
        exact=best_lower_bound_certificate.exact and upper_bound_certificate.exact,
        iterations=max_iterations,
        lower_bound=best_lower_bound_certificate.value,
        upper_bound=upper_bound_certificate.value,
        lower_bound_certificate=best_lower_bound_certificate,
        upper_bound_certificate=upper_bound_certificate,
        incumbent=incumbent,
        iteration_records=tuple(iteration_records),
        dbp_timing=_build_dbp_timing_summary(
            initial_relaxation_seconds=initial_relaxation_seconds,
            iteration_timings=tuple(iteration_timings),
        ),
        incumbent_solution=incumbent_solution,
    )


def _nonnegative_emissions_certificate() -> BoundCertificate:
    return BoundCertificate(
        value=0.0,
        exact=False,
        mip_gap=None,
        slack=None,
        source="nonnegative_emissions",
    )


def _select_best_certificate(
    first: BoundCertificate | None,
    second: BoundCertificate | None,
) -> BoundCertificate | None:
    if first is None:
        return second
    if second is None:
        return first
    if second.value > first.value + DEFAULT.eps:
        return second
    if first.value > second.value + DEFAULT.eps:
        return first
    if second.exact and not first.exact:
        return second
    if first.exact and not second.exact:
        return first
    if first.mip_gap is None:
        return second if second.mip_gap is not None else first
    if second.mip_gap is None:
        return first
    if second.mip_gap < first.mip_gap - DEFAULT.eps:
        return second
    return first


def _filter_certified_lower_bound(
    certificate: BoundCertificate | None,
    *,
    upper_bound_certificate: BoundCertificate | None,
) -> BoundCertificate | None:
    if certificate is None:
        return None
    if not math.isfinite(certificate.value):
        return None
    if upper_bound_certificate is None:
        return certificate
    if certificate.value > upper_bound_certificate.value + DEFAULT.eps:
        return None
    return certificate


def _solve_certified_relaxation(
    *,
    relaxation_master,
    elastic_relaxation_master,
    output_flag: bool,
    time_limit: float | None,
    label: str,
) -> _CertifiedRelaxationStep:
    relaxation, relaxation_seconds = _solve_with_wall_time(
        solve_dbp_relaxation,
        relaxation_master,
        output_flag=output_flag,
        time_limit=time_limit,
    )
    certified_lower_bound = _certify_standard_relaxation_bound(relaxation)
    if relaxation.has_solution and relaxation.hat_tau is not None:
        return _CertifiedRelaxationStep(
            result=relaxation,
            certificate=certified_lower_bound,
            solve_seconds=relaxation_seconds,
        )

    elastic_relaxation, elastic_seconds = _solve_with_wall_time(
        solve_dbp_relaxation,
        elastic_relaxation_master,
        output_flag=output_flag,
        time_limit=time_limit,
    )
    if not elastic_relaxation.has_solution or elastic_relaxation.hat_tau is None:
        raise SubproblemStatusError(f"{label} (P4-D)", elastic_relaxation)
    return _CertifiedRelaxationStep(
        result=elastic_relaxation,
        certificate=_select_best_certificate(
            certified_lower_bound,
            _certify_elastic_relaxation_bound(elastic_relaxation),
        ),
        solve_seconds=round(relaxation_seconds + elastic_seconds, 6),
    )


def _certify_standard_relaxation_bound(result: SolveResult) -> BoundCertificate | None:
    if (
        result.status_name == "OPTIMAL"
        and result.emissions is not None
        and math.isfinite(result.emissions)
    ):
        return BoundCertificate(
            value=result.emissions,
            exact=_is_gap_exact(result.mip_gap),
            mip_gap=result.mip_gap,
            slack=0.0,
            source="relaxation",
        )
    if result.objective_bound is not None and math.isfinite(result.objective_bound):
        return BoundCertificate(
            value=result.objective_bound * EMISSIONS_SCALE,
            exact=False,
            mip_gap=result.mip_gap,
            slack=0.0,
            source="relaxation_objective_bound",
        )
    return None


def _certify_elastic_relaxation_bound(result: SolveResult) -> BoundCertificate | None:
    if result.status_name != "OPTIMAL" or result.emissions is None:
        return None
    slack_value = result.slack_value
    if slack_value is None or slack_value > DEFAULT.eps:
        return None
    return BoundCertificate(
        value=result.emissions,
        exact=_is_gap_exact(result.mip_gap),
        mip_gap=result.mip_gap,
        slack=slack_value,
        source="p4d",
    )


def _certify_follower_response(
    *,
    instance: InstanceData,
    hat_tau: int,
    result: SolveResult,
    output_flag: bool,
    time_limit: float | None,
) -> tuple[SolveResult, BoundCertificate, float]:
    if result.has_solution and result.status_name == "OPTIMAL":
        follower_objective = _required_value(
            result.follower_objective,
            f"follower objective at hat_tau={hat_tau}",
        )
        return (
            result,
            BoundCertificate(
                value=follower_objective,
                exact=_is_gap_exact(result.mip_gap),
                mip_gap=result.mip_gap,
                slack=0.0,
                source="follower",
            ),
            0.0,
        )

    follower_objective_lower_bound = _certified_follower_lower_bound(result)
    if follower_objective_lower_bound is None:
        raise SubproblemStatusError(f"follower problem at hat_tau={hat_tau}", result)

    repaired, repair_seconds = _solve_with_wall_time(
        solve_fixed_tax_follower_repair,
        instance,
        hat_tau=hat_tau,
        follower_objective_lower_bound=follower_objective_lower_bound,
        output_flag=output_flag,
        time_limit=time_limit,
    )
    if not repaired.has_solution or repaired.status_name != "OPTIMAL":
        raise SubproblemStatusError(f"follower repair (P6) at hat_tau={hat_tau}", repaired)
    repaired_objective = _required_value(
        repaired.follower_objective,
        f"repaired follower objective at hat_tau={hat_tau}",
    )
    return (
        repaired,
        BoundCertificate(
            value=repaired_objective,
            exact=(
                _is_gap_exact(repaired.mip_gap)
                and repaired.slack_value is not None
                and repaired.slack_value <= DEFAULT.eps
            ),
            mip_gap=repaired.mip_gap,
            slack=repaired.slack_value,
            source="p6",
        ),
        repair_seconds,
    )


def _certified_follower_lower_bound(result: SolveResult) -> float | None:
    if result.objective_bound is not None:
        return result.objective_bound
    if result.has_solution and result.follower_objective is not None and result.mip_gap is not None:
        return result.follower_objective - abs(result.follower_objective) * max(0.0, result.mip_gap)
    return None


def _certify_upper_bound(
    *,
    instance: InstanceData,
    hat_tau: int,
    follower_objective_upper: float,
    result: SolveResult,
    output_flag: bool,
    time_limit: float | None,
    label: str,
) -> _CertifiedUpperBoundStep:
    if result.has_solution and result.emissions is not None:
        emissions = _required_value(result.emissions, f"{label} emissions")
        return _CertifiedUpperBoundStep(
            result=result,
            certificate=BoundCertificate(
                value=emissions,
                exact=_is_gap_exact(result.mip_gap),
                mip_gap=result.mip_gap,
                slack=0.0,
                source="optimistic" if result.status_name == "OPTIMAL" else "optimistic_feasible",
            ),
            solve_seconds=0.0,
        )

    repaired, repair_seconds = _solve_with_wall_time(
        solve_fixed_tax_optimistic_elastic,
        instance,
        hat_tau=hat_tau,
        follower_objective_upper=follower_objective_upper,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=True,
    )
    if not repaired.has_solution or repaired.emissions is None:
        raise SubproblemStatusError(f"{label} (P5-D)", repaired)
    if repaired.slack_value is None or repaired.slack_value > DEFAULT.eps:
        raise SubproblemStatusError(f"{label} (P5-D)", repaired)

    emissions = _required_value(repaired.emissions, f"{label} (P5-D) emissions")
    return _CertifiedUpperBoundStep(
        result=repaired,
        certificate=BoundCertificate(
            value=emissions,
            exact=_is_gap_exact(repaired.mip_gap),
            mip_gap=repaired.mip_gap,
            slack=repaired.slack_value,
            source="p5d",
        ),
        solve_seconds=repair_seconds,
    )
