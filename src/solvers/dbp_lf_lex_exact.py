from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

from src.config.gap_tol import DEFAULT
from src.models.instance_loader import InstanceData
from src.models.shared_models import (
    build_fixed_tax_follower_master,
    SolveResult,
    solve_fixed_tax_lexicographic,
)
from src.solvers.dbp_exact import (
    BilevelSolveResult,
    BoundCertificate,
    FinalRefinementAttempt,
    FinalRefinementSummary,
    IncumbentSolution,
    _coerce_instance,
    _is_gap_exact,
    _required_value,
    _solve_with_wall_time,
)
from src.solvers.dbp_f_lex_exact import solve_bilevel_dbp_f_lex_exact


def solve_bilevel_dbp_lf_lex_exact(
    instance_or_path: InstanceData | str | Path,
    *,
    max_iterations: int | None = None,
    output_flag: bool = False,
    time_limit: float | None = None,
) -> BilevelSolveResult:
    """DBP with a true lexicographic leader (min Emis, then min hat_tau) and lex follower.

    Phase 1: emissions-only DBP via solve_bilevel_dbp_f_lex_exact.
    Phase 2: tau-tiebreak bisection on the monotone predicate
             ``e*(τ) ≤ target + tol`` over hat_tau ∈ [lower_hat_tau, incumbent.hat_tau].
             Returns the smallest hat_tau satisfying the predicate. Bounds and
             iteration trace from phase 1 are preserved; phase 2 is recorded in
             BilevelSolveResult.final_refinement.
    """
    instance = _coerce_instance(instance_or_path)

    inner = solve_bilevel_dbp_f_lex_exact(
        instance,
        max_iterations=max_iterations,
        output_flag=output_flag,
        time_limit=time_limit,
    )

    refined_incumbent, refined_solution, refinement = _refine_hat_tau_tiebreak(
        instance,
        incumbent=inner.incumbent,
        incumbent_solution=inner.incumbent_solution,
        output_flag=output_flag,
        time_limit=time_limit,
        lower_bound=inner.lower_bound,
        upper_bound=inner.upper_bound,
    )

    if refinement.changed_incumbent:
        # The refined incumbent is a valid feasible solution; its emissions form
        # a fresh upper bound. Take the tighter of (inner UB, refined emissions)
        # so we never weaken a bound that phase 1 already proved.
        refined_upper_bound = min(inner.upper_bound, refined_incumbent.emissions)
        upper_bound_certificate = BoundCertificate(
            value=refined_upper_bound,
            exact=inner.upper_bound_certificate.exact and _lex_stage_gaps_exact(refined_solution),
            mip_gap=inner.upper_bound_certificate.mip_gap,
            slack=inner.upper_bound_certificate.slack,
            source="lexicographic_tau_tiebreak",
        )
    else:
        refined_upper_bound = inner.upper_bound
        upper_bound_certificate = BoundCertificate(
            value=inner.upper_bound_certificate.value,
            exact=inner.upper_bound_certificate.exact and _lex_stage_gaps_exact(refined_solution),
            mip_gap=inner.upper_bound_certificate.mip_gap,
            slack=inner.upper_bound_certificate.slack,
            source=inner.upper_bound_certificate.source,
        )

    lex_stages_exact = _lex_stage_gaps_exact(refined_solution)

    return replace(
        inner,
        method="dbp_lf_lex_exact",
        exact=inner.exact and lex_stages_exact,
        upper_bound=refined_upper_bound,
        upper_bound_certificate=upper_bound_certificate,
        incumbent=refined_incumbent,
        incumbent_solution=refined_solution,
        final_refinement=refinement,
    )


def _refine_hat_tau_tiebreak(
    instance: InstanceData,
    *,
    incumbent: IncumbentSolution,
    incumbent_solution: SolveResult | None,
    output_flag: bool,
    time_limit: float | None,
    lower_bound: float,
    upper_bound: float,
) -> tuple[IncumbentSolution, SolveResult | None, FinalRefinementSummary]:
    """Bisection over ``hat_tau ∈ [lower_hat_tau, incumbent.hat_tau]`` on the
    monotone predicate ``P(τ) := e*(τ) ≤ target + tol``.

    Soundness: ``e*(·)`` (the lex follower's optimal emissions) is non-increasing
    in ``τ`` by the parametric-MILP cross-adding argument, so ``P`` is False on
    a prefix and True on a suffix. The boundary is the smallest τ that is
    indistinguishable from the certified optimum within MIP precision.
    """
    lower_hat_tau = instance.lower_hat_tau
    target_emissions = incumbent.emissions
    tol = max(DEFAULT.eps * abs(target_emissions), DEFAULT.eps)

    attempts: list[FinalRefinementAttempt] = []
    started_at = time.perf_counter()

    hi = incumbent.hat_tau
    hi_solution: SolveResult | None = incumbent_solution
    lo = lower_hat_tau - 1
    previous_lexicographic_values = (
        incumbent_solution.variable_values
        if incumbent_solution is not None
        else None
    )
    follower_master = build_fixed_tax_follower_master(instance)

    while hi - lo > 1:
        mid = (lo + hi) // 2
        result, seconds = _solve_with_wall_time(
            solve_fixed_tax_lexicographic,
            follower_master,
            hat_tau=mid,
            output_flag=output_flag,
            time_limit=time_limit,
            capture_solution=True,
            warm_start_values=previous_lexicographic_values,
        )
        if result.variable_values is not None:
            previous_lexicographic_values = result.variable_values

        if not result.has_solution or result.status_name != "OPTIMAL":
            attempts.append(
                FinalRefinementAttempt(
                    hat_tau=mid,
                    solve_seconds=seconds,
                    emissions=float("nan"),
                    follower_objective=float("nan"),
                    matched_incumbent_emissions=False,
                )
            )
            lo = mid
            continue

        candidate_emissions = float(
            _required_value(result.emissions, "tau-tiebreak candidate emissions")
        )
        candidate_follower_objective = float(
            _required_value(result.follower_objective, "tau-tiebreak candidate follower objective")
        )
        matched = candidate_emissions <= target_emissions + tol
        attempts.append(
            FinalRefinementAttempt(
                hat_tau=mid,
                solve_seconds=seconds,
                emissions=candidate_emissions,
                follower_objective=candidate_follower_objective,
                matched_incumbent_emissions=matched,
            )
        )
        if matched:
            hi = mid
            hi_solution = result
        else:
            lo = mid

    found_smaller = hi < incumbent.hat_tau and hi_solution is not None and hi_solution is not incumbent_solution
    if found_smaller and hi_solution is not None:
        selected_incumbent = IncumbentSolution(
            hat_tau=hi,
            cost=float(_required_value(hi_solution.cost, "tau-tiebreak cost")),
            emissions=float(_required_value(hi_solution.emissions, "tau-tiebreak emissions")),
            follower_objective=float(
                _required_value(hi_solution.follower_objective, "tau-tiebreak follower objective")
            ),
        )
        selected_solution: SolveResult | None = hi_solution
    else:
        selected_incumbent = incumbent
        selected_solution = incumbent_solution

    summary = FinalRefinementSummary(
        initial_hat_tau=incumbent.hat_tau,
        selected_hat_tau=selected_incumbent.hat_tau,
        lower_hat_tau=lower_hat_tau,
        total_seconds=round(time.perf_counter() - started_at, 6),
        changed_incumbent=found_smaller,
        attempts=tuple(attempts),
        termination_reason="tau_tiebreak_found" if found_smaller else "tau_tiebreak_exhausted",
        exact=_lex_stage_gaps_exact(selected_solution),
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        emissions_target=target_emissions,
        emissions_cap=target_emissions + tol,
    )

    return selected_incumbent, selected_solution, summary


def _lex_stage_gaps_exact(solution: SolveResult | None) -> bool:
    if solution is None:
        return False
    return _is_gap_exact(solution.lex_primary_mip_gap) and _is_gap_exact(solution.lex_secondary_mip_gap)
