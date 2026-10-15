"""Tests of the certificates a solved result carries: the signed gap, the result classes, the
validation of the saved incumbent, and the DBP's bounds against a brute-force sweep of the tax on a
tiny generated instance (932 variables, so the follower solves in a fraction of a second).

The gap and class tests need no Gurobi licence. The others build and solve small Gurobi models and
are skipped when no licence is found.
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from clsc.solver_cli.results import classify_result
from clsc.solvers.dbp import IncumbentSolution, relative_optimality_gap


def _gurobi_available() -> bool:
    try:
        import gurobipy as gp

        with gp.Env(params={"OutputFlag": 0}):
            return True
    except Exception:
        return False


requires_gurobi = pytest.mark.skipif(not _gurobi_available(), reason="no usable Gurobi licence")


# ---------------------------------------------------------------------------------------------
# No licence needed
# ---------------------------------------------------------------------------------------------

def test_relative_gap_keeps_its_sign() -> None:
    assert relative_optimality_gap(leader_objective_ub=110.0, leader_objective_lb=100.0) == pytest.approx(10.0 / 110.0)
    # The lower bound above the upper bound is a negative gap, not a zero one.
    assert relative_optimality_gap(leader_objective_ub=100.0, leader_objective_lb=110.0) == pytest.approx(-0.1)
    # Relative to max(1, |UB|): near zero the gap is absolute.
    assert relative_optimality_gap(leader_objective_ub=0.5, leader_objective_lb=0.0) == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("exact", "reason", "expected"),
    [
        (True, "optimal", "optimal"),
        (False, "epsilon_optimal", "epsilon_optimal"),
        (False, "incumbent_stagnation", "bounds"),
        (False, "incumbent_time_limit", "bounds"),
        (False, "incumbent_iteration_limit", "bounds"),
        (False, "bound_inversion", "inconsistent"),
    ],
)
def test_result_classes(exact: bool, reason: str, expected: str) -> None:
    assert classify_result(SimpleNamespace(exact=exact, termination_reason=reason)) == expected


# ---------------------------------------------------------------------------------------------
# A tiny instance, solved with Gurobi
# ---------------------------------------------------------------------------------------------

TAX = 50.0
TAX_WEIGHT = 100.0  # kg CO2e per EUR/t, arbitrary for the validation tests


@pytest.fixture(scope="module")
def tiny_instance():
    from clsc.generator.config import GeneratorConfig
    from clsc.generator.instance_builder import generate_instance
    from clsc.models.instance_data import InstanceData

    config = GeneratorConfig(
        suppliers=2, factories=1, warehouses=2, retailers=2, airports=1, seaports=1, products=1,
        raw_materials=2, production_technologies=2, remanufacturing_technologies=2, periods=3,
        seed=0, instance_name="tiny0",
    )
    return InstanceData.from_dict(generate_instance(config).to_dict())


@pytest.fixture(scope="module")
def tiny_follower(tiny_instance):
    from clsc.models.follower import build_follower_model

    return build_follower_model(tiny_instance)


def _solve_follower(follower, tax: float):
    from clsc.models.follower import solve_follower_lexicographic

    return solve_follower_lexicographic(
        follower, tax=tax, output_flag=False, time_limit=60, capture_solution=True, threads=1, seed=0,
    )


@pytest.fixture(scope="module")
def saved_result(tiny_follower):
    response = _solve_follower(tiny_follower, TAX)
    assert response.status_name == "OPTIMAL"
    incumbent = IncumbentSolution(
        tax=TAX, cost=response.cost, emissions=response.emissions, follower_objective=response.follower_objective,
    )
    return SimpleNamespace(
        incumbent=incumbent,
        incumbent_solution=response,
        leader_tax_weight=TAX_WEIGHT,
        leader_objective_ub=response.emissions + TAX_WEIGHT * TAX,
    )


@requires_gurobi
def test_validation_accepts_a_solved_follower_response(tiny_instance, saved_result) -> None:
    from clsc.solver_cli.validation import validate_result_solution

    validation = validate_result_solution(instance=tiny_instance, result=saved_result)
    assert validation["status"] == "validated", validation["failed_checks"]
    assert validation["failed_checks"] == []
    # Nothing is re-optimised or overwritten: the incumbent is exactly what went in.
    assert saved_result.incumbent.cost == saved_result.incumbent_solution.cost


@requires_gurobi
def test_validation_rejects_an_inconsistent_upper_bound(tiny_instance, saved_result) -> None:
    from clsc.solver_cli.validation import validate_result_solution

    tampered = replace_namespace(saved_result, leader_objective_ub=saved_result.leader_objective_ub * 1.01)
    validation = validate_result_solution(instance=tiny_instance, result=tampered)
    assert validation["status"] == "failed"
    assert validation["failed_checks"] == ["leader_objective"]


@requires_gurobi
def test_validation_rejects_reported_metrics_that_the_solution_does_not_attain(tiny_instance, saved_result) -> None:
    from clsc.solver_cli.validation import validate_result_solution

    incumbent = replace_namespace(saved_result.incumbent, emissions=saved_result.incumbent.emissions * 0.999)
    tampered = replace_namespace(saved_result, incumbent=incumbent)
    validation = validate_result_solution(instance=tiny_instance, result=tampered)
    assert validation["status"] == "failed"
    assert "objectives" in validation["failed_checks"]


@requires_gurobi
def test_validation_rejects_an_infeasible_solution(tiny_instance, saved_result) -> None:
    from clsc.solver_cli.validation import validate_result_solution

    values = dict(saved_result.incumbent_solution.variable_values)
    flow = max((name for name in values if name.startswith("x[")), key=lambda name: values[name])
    values[flow] *= 3.0  # breaks a flow balance
    tampered = replace_namespace(
        saved_result, incumbent_solution=replace(saved_result.incumbent_solution, variable_values=values),
    )
    validation = validate_result_solution(instance=tiny_instance, result=tampered)
    assert validation["status"] == "failed"
    assert "constraints" in validation["failed_checks"]


def replace_namespace(namespace, **changes):
    """``dataclasses.replace`` for the dataclass results and for the SimpleNamespace stand-in."""
    if isinstance(namespace, SimpleNamespace):
        return SimpleNamespace(**{**vars(namespace), **changes})
    return replace(namespace, **changes)


# ---------------------------------------------------------------------------------------------
# The DBP against a brute-force sweep of the tax
# ---------------------------------------------------------------------------------------------

@requires_gurobi
def test_dbp_bounds_enclose_the_brute_force_optimum(tiny_instance, tiny_follower) -> None:
    """On the tiny instance the follower is solved at every whole EUR/t of the range. The best
    F = E + w * tax over that sweep is the optimum restricted to a grid, so it is at least the
    continuous optimum, and the DBP's bounds must enclose it: LB below it, UB at most the stopping
    tolerance above it."""
    from clsc.solvers.dbp import solve_bilevel_dbp

    result = solve_bilevel_dbp(tiny_instance, threads=1, seed=0, time_limit=60)
    weight = result.leader_tax_weight
    sweep = []
    for tax in range(int(tiny_instance.lower_tax), int(tiny_instance.upper_tax) + 1):
        response = _solve_follower(tiny_follower, float(tax))
        assert response.status_name == "OPTIMAL"
        sweep.append(response.emissions + weight * tax)
    best_on_grid = min(sweep)

    tolerance = 1e-4
    assert result.leader_objective_lb <= best_on_grid * (1.0 + 1e-6)
    assert result.leader_objective_ub <= best_on_grid * (1.0 + tolerance)
    assert result.termination_reason in {"optimal", "epsilon_optimal"}, result.termination_reason
    assert relative_optimality_gap(
        leader_objective_ub=result.leader_objective_ub, leader_objective_lb=result.leader_objective_lb,
    ) <= tolerance

    # The upper bound never rises and the lower bound never falls across the iterations.
    upper = [record.leader_objective_ub for record in result.iteration_records]
    lower = [record.next_relaxation_lower_bound for record in result.iteration_records]
    assert all(later <= earlier + 1e-9 for earlier, later in zip(upper, upper[1:]))
    assert all(later >= earlier - 1e-9 for earlier, later in zip(lower, lower[1:]))
