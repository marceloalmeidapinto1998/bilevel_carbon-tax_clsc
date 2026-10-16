"""Independent check of a solved bilevel result's incumbent.

The saved solution is re-evaluated at the point the DBP certified, tax and variable values as
they are, in a freshly built follower model. Nothing is re-optimised and nothing is overwritten:
the result keeps the numbers the DBP bounded, and this module only reports whether the saved
solution reproduces them. It checks that the solution

* satisfies every constraint and variable bound of the follower's feasible set,
* is integral where the model asks for integers,
* has the cost, the emissions and the follower objective the DBP reported, and
* attains the upper bound on the leader's objective: E + w * tax = UB.

It does NOT re-check that the response is optimal for the follower. That is certified by the
follower's solves inside the DBP (two stages, to the stage gaps recorded in the result); repeating
a solve here would only repeat the DBP's own computation.
"""
from __future__ import annotations

import gurobipy as gp
from gurobipy import GRB

from clsc.config.constants import INTEGER_SNAP_TOL
from clsc.models.follower import build_fixed_tax_model
from clsc.models.instance_data import InstanceData


class OutputValidationError(RuntimeError):
    """Raised when a saved incumbent cannot be revalidated because its solution data is missing."""


# A row's violation is relative to the row's scale, max(1, |rhs|, largest |coefficient * value|): a row
# such as load - capacity * trips <= 0 has a zero right-hand side but terms of millions, and an absolute
# miss of 0.01 there is numerical noise, not a violation of 1%. A bound's violation is relative to
# max(1, |bound|). The solver's own feasibility tolerance is 1e-6.
FEASIBILITY_TOLERANCE = 1e-6
# Both sides of these comparisons come from the same expressions evaluated at the same values.
OBJECTIVE_TOLERANCE = 1e-8
# E + w * tax against UB: the incumbent is chosen with a tie tolerance (relative 1e-7, see
# dbp._emissions_tie_tolerance) that the upper bound's strict comparison does not have.
LEADER_OBJECTIVE_TOLERANCE = 1e-6


def _evaluate(expression: gp.LinExpr, values: dict[str, float]) -> float:
    total = expression.getConstant()
    for index in range(expression.size()):
        total += expression.getCoeff(index) * values.get(expression.getVar(index).VarName, 0.0)
    return float(total)


def _largest_term(expression: gp.LinExpr, values: dict[str, float]) -> float:
    return max(
        (abs(expression.getCoeff(index) * values.get(expression.getVar(index).VarName, 0.0)) for index in range(expression.size())),
        default=0.0,
    )


def _relative_difference(value: float, reference: float) -> float:
    return abs(value - reference) / max(1.0, abs(reference))


def validate_result_solution(*, instance: InstanceData, result) -> dict[str, object]:
    """Re-evaluate the saved incumbent and report ``status`` ``validated`` or ``failed``.

    Raises :class:`OutputValidationError` only when the solution data is missing.
    """
    saved = result.incumbent_solution
    if saved is None or not saved.has_solution:
        raise OutputValidationError(f"Missing cached optimistic incumbent solution for {instance.name}")
    if saved.variable_values is None:
        raise OutputValidationError(f"Cached optimistic incumbent solution for {instance.name} has no variable values")

    incumbent = result.incumbent
    artifacts = build_fixed_tax_model(instance, tax=incumbent.tax)
    model = artifacts.model
    model.update()
    values = {variable.VarName: float(saved.variable_values.get(variable.VarName, 0.0)) for variable in model.getVars()}
    unknown = sorted(set(saved.variable_values) - set(values))

    worst_row, worst_row_violation = None, 0.0
    for constraint in model.getConstrs():
        row = model.getRow(constraint)
        activity = _evaluate(row, values)
        right_hand_side = constraint.RHS
        if constraint.Sense == GRB.LESS_EQUAL:
            violation = activity - right_hand_side
        elif constraint.Sense == GRB.GREATER_EQUAL:
            violation = right_hand_side - activity
        else:
            violation = abs(activity - right_hand_side)
        scaled = max(0.0, violation) / max(1.0, abs(right_hand_side), _largest_term(row, values))
        if scaled > worst_row_violation:
            worst_row, worst_row_violation = constraint.ConstrName, scaled

    worst_bound, worst_bound_violation = None, 0.0
    worst_integer, worst_integer_gap = None, 0.0
    for variable in model.getVars():
        value = values[variable.VarName]
        for bound, violation in ((variable.LB, variable.LB - value), (variable.UB, value - variable.UB)):
            if abs(bound) >= 1e20:
                continue
            scaled = max(0.0, violation) / max(1.0, abs(bound))
            if scaled > worst_bound_violation:
                worst_bound, worst_bound_violation = variable.VarName, scaled
        if variable.VType != GRB.CONTINUOUS:
            gap = abs(value - round(value))
            if gap > worst_integer_gap:
                worst_integer, worst_integer_gap = variable.VarName, gap

    cost = _evaluate(artifacts.cost_expr, values)
    emissions = _evaluate(artifacts.emissions_expr, values)
    follower_objective = _evaluate(artifacts.follower_objective_expr, values)
    objective_differences = {
        "cost": _relative_difference(cost, incumbent.cost),
        "emissions": _relative_difference(emissions, incumbent.emissions),
        "follower_objective": _relative_difference(follower_objective, incumbent.follower_objective),
    }
    leader_objective = emissions + result.leader_tax_weight * incumbent.tax
    leader_difference = _relative_difference(leader_objective, result.leader_objective_ub)

    checks = {
        "constraints": {
            "max_scaled_violation": worst_row_violation,
            "worst_constraint": worst_row,
            "ok": worst_row_violation <= FEASIBILITY_TOLERANCE and not unknown,
        },
        "bounds": {
            "max_scaled_violation": worst_bound_violation,
            "worst_variable": worst_bound,
            "ok": worst_bound_violation <= FEASIBILITY_TOLERANCE,
        },
        "integrality": {
            "max_distance_to_integer": worst_integer_gap,
            "worst_variable": worst_integer,
            "ok": worst_integer_gap <= INTEGER_SNAP_TOL,
        },
        "objectives": {
            "recomputed": {"cost": cost, "emissions": emissions, "follower_objective": follower_objective},
            "reported": {
                "cost": incumbent.cost,
                "emissions": incumbent.emissions,
                "follower_objective": incumbent.follower_objective,
            },
            "relative_differences": objective_differences,
            "ok": max(objective_differences.values()) <= OBJECTIVE_TOLERANCE,
        },
        "leader_objective": {
            "emissions_plus_weighted_tax": leader_objective,
            "upper_bound": result.leader_objective_ub,
            "relative_difference": leader_difference,
            "ok": leader_difference <= LEADER_OBJECTIVE_TOLERANCE,
        },
    }
    failed_checks = [name for name, check in checks.items() if not check["ok"]]
    return {
        "status": "validated" if not failed_checks else "failed",
        "method": "the saved solution re-evaluated at the certified point; no re-optimisation",
        "not_checked": "optimality of the response for the follower (certified by the DBP's follower solves)",
        "tolerances": {
            "feasibility": FEASIBILITY_TOLERANCE,
            "integrality": INTEGER_SNAP_TOL,
            "objective": OBJECTIVE_TOLERANCE,
            "leader_objective": LEADER_OBJECTIVE_TOLERANCE,
        },
        "unknown_variables": unknown,
        "failed_checks": failed_checks,
        "checks": checks,
    }
