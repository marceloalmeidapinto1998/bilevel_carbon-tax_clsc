"""Tests of the bounds the HPR keeps on the operands of its bilinear product tax * tax_base.

The bounds only build models; the last test solves the HPR on a tiny generated instance and checks
that they cut off no point the HPR could return. Skipped without a Gurobi licence.
"""
from __future__ import annotations

import pytest

from clsc.models.follower import epsilon_prime_tolerance
from clsc.models.supply_chain import discount_factors


def _gurobi_available() -> bool:
    try:
        import gurobipy as gp

        with gp.Env(params={"OutputFlag": 0}):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _gurobi_available(), reason="no usable Gurobi licence")


@pytest.fixture(scope="module")
def tiny():
    from clsc.generator.config import GeneratorConfig
    from clsc.generator.instance_builder import generate_instance
    from clsc.models.instance_data import InstanceData

    config = GeneratorConfig(
        suppliers=2, factories=1, warehouses=2, retailers=2, airports=1, seaports=1, products=1,
        raw_materials=2, production_technologies=2, remanufacturing_technologies=2, periods=3,
        seed=0, instance_name="tiny0",
    )
    return InstanceData.from_dict(generate_instance(config).to_dict())


def test_the_box_narrows_with_what_the_run_proves(tiny) -> None:
    from clsc.models.hpr import build_hpr, set_emissions_cap, set_emissions_lower_bound, set_leader_objective_cap, set_leader_tax_weight

    hpr = build_hpr(tiny)
    weights = discount_factors(tiny.parameters, tiny.sets["T"]).values()
    tax, base, payment = hpr.artifacts.tax_var, hpr.tax_base_var, hpr.tax_payment_var
    assert hpr.discount_min == pytest.approx(min(weights)) and hpr.discount_max == pytest.approx(max(weights))
    assert tax.UB == tiny.upper_tax and base.LB == 0.0
    assert base.UB == pytest.approx(max(weights) * hpr.tax_base_upper_bound_scaled)

    e_min, weight, ub = 2.0e7, 2.0e4, 2.1e7  # kg, kg per EUR/t, kg: the tax bound is 50 EUR/t
    set_emissions_lower_bound(hpr, e_min)
    e_min_t = (e_min - epsilon_prime_tolerance(e_min)) / 1000.0
    assert hpr.artifacts.emissions_total_var.LB == pytest.approx(e_min_t)
    assert base.LB == pytest.approx(min(weights) * e_min_t)

    set_leader_tax_weight(hpr, weight)
    set_emissions_cap(hpr, ub)
    set_leader_objective_cap(hpr, ub)
    ub_t = (ub + epsilon_prime_tolerance(ub)) / 1000.0
    # F = E + w * tax <= UB and E >= E_min: tax <= (UB - E_min) / w.
    assert tax.UB == pytest.approx((ub_t - e_min_t) / (weight / 1000.0))
    assert base.UB == pytest.approx(max(weights) * ub_t)
    assert payment.UB == pytest.approx(tax.UB * base.UB)
    assert payment.LB == pytest.approx(tiny.lower_tax * base.LB)

    # Removing the emissions cap restores the build-time bound on the tax base.
    set_emissions_cap(hpr, None)
    assert base.UB == pytest.approx(max(weights) * hpr.tax_base_upper_bound_scaled)


def test_the_bounds_keep_every_evaluated_point(tiny) -> None:
    """At an evaluated point (tax, y) with F <= UB, the bounds hold: the HPR started at it accepts it."""
    from clsc.models.follower import solve_follower_lexicographic
    from clsc.models.hpr import (
        ValueFunctionCut, add_value_function_cut, build_hpr, set_emissions_cap, set_emissions_lower_bound,
        set_hpr_start, set_leader_objective_cap, set_leader_tax_weight, solve_hpr,
    )

    hpr = build_hpr(tiny)
    reference = solve_hpr(hpr, threads=1, seed=0)
    set_emissions_lower_bound(hpr, reference.emissions)
    weight = 1e-4 * reference.emissions
    set_leader_tax_weight(hpr, weight)
    response = solve_follower_lexicographic(tiny, 30.0, capture_solution=True, threads=1, seed=0)
    ub = response.emissions + weight * 30.0
    add_value_function_cut(hpr, ValueFunctionCut(tax=30.0, cost=response.cost, emissions=response.emissions,
                                                 tax_base=response.tax_base, iteration=1))
    set_emissions_cap(hpr, ub)
    set_leader_objective_cap(hpr, ub)
    assert hpr.artifacts.tax_var.LB <= 30.0 <= hpr.artifacts.tax_var.UB
    assert hpr.tax_base_var.LB <= response.tax_base / 1000.0 <= hpr.tax_base_var.UB
    set_hpr_start(hpr, response.variable_values, response.variable_values.keys(), 30.0)
    result = solve_hpr(hpr, threads=1, seed=0)
    assert result.status_name == "OPTIMAL"
    # The evaluated point is feasible for the bounded HPR, so its optimum is at most that point's F.
    assert result.leader_lower_bound <= ub * (1 + 1e-6)
