"""Revalidation of a solved bilevel result: rebuild the follower at the incumbent's fixed
discrete decisions and check that the saved solution is feasible and attains the reported
objective.
"""
from __future__ import annotations

from dataclasses import replace

from clsc.config.constants import INTEGER_SNAP_TOL
from clsc.config.defaults import DEFAULT
from clsc.models.follower import (
    build_follower_master,
    solve_follower_lexicographic,
    validate_fixed_tax_solution,
)
from clsc.models.instance_data import InstanceData


DBP_SOLVER_METHODS = {
    "dbp",
}


class OutputValidationError(RuntimeError):
    """Raised when a saved incumbent cannot be revalidated from solution data."""


def canonicalize_result_solution(*, instance: InstanceData, result):
    optimistic = result.incumbent_solution
    if optimistic is None or not optimistic.has_solution or optimistic.variable_values is None:
        return result

    recomputed = validate_fixed_tax_solution(
        instance,
        tax_index=result.incumbent.tax_index,
        variable_values=optimistic.variable_values,
    )
    if (
        (not recomputed.has_solution or recomputed.status_name != "OPTIMAL")
        and result.method in DBP_SOLVER_METHODS
    ):
        repaired = rebuild_solution_with_fixed_discrete_values(
            instance=instance,
            result=result,
        )
        if repaired is not None and repaired.has_solution and repaired.status_name == "OPTIMAL":
            result = replace(
                result,
                incumbent=replace(
                    result.incumbent,
                    cost=float(repaired.cost),
                    emissions=float(repaired.emissions),
                    follower_objective=float(repaired.follower_objective),
                ),
                incumbent_solution=repaired,
            )
            optimistic = repaired
            recomputed = validate_fixed_tax_solution(
                instance,
                tax_index=result.incumbent.tax_index,
                variable_values=optimistic.variable_values or {},
            )
    if not recomputed.has_solution or recomputed.status_name != "OPTIMAL":
        return result

    canonical_incumbent = replace(
        result.incumbent,
        cost=float(recomputed.cost),
        emissions=float(recomputed.emissions),
        follower_objective=float(recomputed.follower_objective),
    )
    canonical_optimistic = replace(
        optimistic,
        cost=float(recomputed.cost),
        emissions=float(recomputed.emissions),
        follower_objective=float(recomputed.follower_objective),
    )
    return replace(
        result,
        incumbent=canonical_incumbent,
        incumbent_solution=canonical_optimistic,
    )


def rebuild_solution_with_fixed_discrete_values(*, instance: InstanceData, result):
    optimistic = result.incumbent_solution
    if optimistic is None or not optimistic.has_solution or optimistic.variable_values is None:
        return None

    follower_master = build_follower_master(instance)
    model = follower_master.artifacts.model
    model.update()
    for variable in model.getVars():
        if variable.VType == "C":
            continue
        target_value = float(optimistic.variable_values.get(variable.VarName, 0.0))
        variable_lb = float(variable.LB)
        variable_ub = float(variable.UB)
        if abs(target_value - round(target_value)) <= INTEGER_SNAP_TOL:
            target_value = float(round(target_value))
        if target_value < variable_lb - DEFAULT.eps or target_value > variable_ub + DEFAULT.eps:
            raise ValueError(
                f"Saved solution value {target_value} for {variable.VarName} violates [{variable_lb}, {variable_ub}]",
            )
        if target_value < variable_lb:
            target_value = variable_lb
        if target_value > variable_ub:
            target_value = variable_ub
        variable.LB = target_value
        variable.UB = target_value

    return solve_follower_lexicographic(
        follower_master,
        result.incumbent.tax_index,
        output_flag=False,
        time_limit=None,
        capture_solution=True,
        warm_start_values=optimistic.variable_values,
        mip_gap=DEFAULT.eps,
    )


def validate_result_solution(*, instance: InstanceData, result) -> dict[str, object]:
    optimistic = result.incumbent_solution
    if optimistic is None or not optimistic.has_solution:
        raise OutputValidationError(f"Missing cached optimistic incumbent solution for {instance.name}")
    if optimistic.variable_values is None:
        raise OutputValidationError(f"Cached optimistic incumbent solution for {instance.name} has no variable values")

    recomputed = validate_fixed_tax_solution(
        instance,
        tax_index=result.incumbent.tax_index,
        variable_values=optimistic.variable_values,
    )
    if not recomputed.has_solution or recomputed.status_name != "OPTIMAL":
        raise OutputValidationError(
            f"Saved incumbent for {instance.name} could not be revalidated (status={recomputed.status_name})",
        )

    deltas = {
        "cost": float(recomputed.cost) - float(result.incumbent.cost),
        "emissions": float(recomputed.emissions) - float(result.incumbent.emissions),
        "follower_objective": float(recomputed.follower_objective) - float(result.incumbent.follower_objective),
    }
    max_abs_delta = max(abs(value) for value in deltas.values())
    if max_abs_delta > DEFAULT.eps:
        raise OutputValidationError(
            f"Saved incumbent metrics for {instance.name} are inconsistent with the recomputed fixed solution: {deltas}",
        )

    return {
        "status": "validated",
        "tolerance": DEFAULT.eps,
        "recomputed": {
            "cost": recomputed.cost,
            "emissions": recomputed.emissions,
            "follower_objective": recomputed.follower_objective,
        },
        "deltas": deltas,
        "max_abs_delta": max_abs_delta,
    }
