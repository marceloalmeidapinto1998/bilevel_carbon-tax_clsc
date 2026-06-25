from __future__ import annotations

from pathlib import Path

from src.config.gap_tol import DEFAULT
from src.models.instance_loader import InstanceData
from src.models.shared_models import (
    DbpFollowerCut,
    set_dbp_relaxation_objective_upper_bound,
    add_dbp_lex_emissions_cut,
    add_dbp_relaxation_cut,
    build_dbp_relaxation_master,
    build_fixed_tax_follower_master,
    solve_dbp_relaxation,
    solve_fixed_tax_lexicographic,
)
from src.solvers.dbp_exact import (
    BilevelSolveResult,
    BoundCertificate,
    DbpIterationRecord,
    DbpIterationTiming,
    IncumbentSolution,
    _build_bilevel_result,
    _build_dbp_timing_summary,
    _classify_stagnation_stop,
    _coerce_instance,
    _is_better_candidate,
    _require_optimal_result,
    _required_value,
    _solve_with_wall_time,
    _with_stagnation_context,
    follower_objective_cap,
    relative_optimality_gap,
)


def solve_bilevel_dbp_f_lex_exact(
    instance_or_path: InstanceData | str | Path,
    *,
    max_iterations: int | None = None,
    output_flag: bool = False,
    time_limit: float | None = None,
) -> BilevelSolveResult:
    instance = _coerce_instance(instance_or_path)
    max_iterations = max_iterations or (len(instance.iter_hat_tau()) + 1)
    iteration_records: list[DbpIterationRecord] = []
    iteration_timings: list[DbpIterationTiming] = []
    relaxation_master = build_dbp_relaxation_master(instance)
    follower_master = build_fixed_tax_follower_master(instance)

    relaxation, initial_relaxation_seconds = _solve_with_wall_time(
        solve_dbp_relaxation,
        relaxation_master,
        output_flag=output_flag,
        time_limit=time_limit,
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
        hat_tau = _required_value(relaxation.hat_tau, "relaxation hat_tau")

        lexicographic, lexicographic_seconds = _solve_with_wall_time(
            solve_fixed_tax_lexicographic,
            follower_master,
            hat_tau=hat_tau,
            output_flag=output_flag,
            time_limit=time_limit,
            capture_solution=True,
            warm_start_values=previous_lexicographic_values,
        )
        _require_optimal_result(lexicographic, f"lexicographic follower solve at hat_tau={hat_tau}")
        if lexicographic.variable_values is not None:
            previous_lexicographic_values = lexicographic.variable_values

        candidate = IncumbentSolution(
            hat_tau=hat_tau,
            cost=_required_value(lexicographic.cost, "lexicographic cost"),
            emissions=_required_value(lexicographic.emissions, "lexicographic emissions"),
            follower_objective=_required_value(
                lexicographic.follower_objective,
                "lexicographic follower objective",
            ),
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
            hat_tau=hat_tau,
            cost=candidate.cost + max(0.0, follower_objective_upper - candidate.follower_objective),
            emissions=candidate.emissions,
            iteration=iteration,
        )
        add_dbp_relaxation_cut(relaxation_master, cut)
        add_dbp_lex_emissions_cut(
            relaxation_master,
            hat_tau_value=hat_tau,
            lex_emissions=candidate.emissions,
            iteration=iteration,
        )
        set_dbp_relaxation_objective_upper_bound(relaxation_master, incumbent.emissions)

        relaxation, relaxation_seconds = _solve_with_wall_time(
            solve_dbp_relaxation,
            relaxation_master,
            output_flag=output_flag,
            time_limit=time_limit,
        )
        if relaxation.status_name == "INFEASIBLE" and relaxation_master.objective_upper_bound is not None:
            # The objective upper bound combined with the accumulated DBP and lex
            # emissions cuts leaves no feasible point in the relaxation: every
            # remaining hat_tau is provably unable to improve on the current
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
            return _build_bilevel_result(
                method="dbp_f_lex_exact",
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
                follower_seconds=lexicographic_seconds,
                follower_objective=candidate.follower_objective,
                optimistic_seconds=0.0,
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
            <= DEFAULT.dbp_relative_gap
        ):
            return _build_bilevel_result(
                method="dbp_f_lex_exact",
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
                method="dbp_f_lex_exact",
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
        method="dbp_f_lex_exact",
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
