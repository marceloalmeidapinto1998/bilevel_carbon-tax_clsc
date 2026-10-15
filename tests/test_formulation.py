"""Tests of the formulation strengthening of the supply-chain model: the valid inequalities must keep the
integer optimum and may only raise the linear relaxation's bound.

They solve small Gurobi models (the tiny generated instance, under 1 000 variables) and are skipped when
no Gurobi licence is found. The remanufacturing bound's arithmetic is tested without a licence.
"""
from __future__ import annotations

import pytest

import clsc.models.supply_chain as supply_chain
from clsc.models.supply_chain import FORMULATION_STRENGTHENING_OPTIONS, _remanufacturing_flow_bounds


def _gurobi_available() -> bool:
    try:
        import gurobipy as gp

        with gp.Env(params={"OutputFlag": 0}):
            return True
    except Exception:
        return False


requires_gurobi = pytest.mark.skipif(not _gurobi_available(), reason="no usable Gurobi licence")


def test_remanufacturing_bound_is_the_smallest_collectable_quantity_per_bill_of_materials() -> None:
    # One retailer, two periods, two products, a recovered product per product (diagonal bill), lag 1.
    params = {
        "bom_rem_r_p": {"rp1": {"p1": 4.0, "p2": 0.0}, "rp2": {"p1": 0.0, "p2": 5.0}},
        "ret_max_frac_r_p_t": {"r1": {"p1": {"t1": 0.1, "t2": 0.1}, "p2": {"t1": 0.2, "t2": 0.2}}},
        "d_r_p_t": {"r1": {"p1": {"t1": 100.0, "t2": 200.0}, "p2": {"t1": 50.0, "t2": 60.0}}},
        "theta_p": {"p1": 1, "p2": 1},
    }
    return_yield = {"rp1": {"p1": 1.0, "p2": 0.0}, "rp2": {"p1": 0.0, "p2": 1.0}}
    bounds = _remanufacturing_flow_bounds(
        params, ("p1", "p2"), ("rp1", "rp2"), ("r1",), ("t1", "t2"), return_yield, {"p1": 1, "p2": 1},
    )
    # Nothing is returned in the first period (the demand it comes from is lagged by one period); in the
    # second, rp1 collects 1.0 * 0.1 * 100 = 10 and each unit of p1 takes 4 of it; rp2 collects 0.2 * 50 = 10
    # and each unit of p2 takes 5.
    assert bounds["p1", "t1"] == pytest.approx(0.0, abs=1e-6)
    assert bounds["p1", "t2"] == pytest.approx(10.0 / 4.0, rel=1e-6)
    assert bounds["p2", "t2"] == pytest.approx(10.0 / 5.0, rel=1e-6)


def test_unknown_strengthening_is_rejected() -> None:
    from clsc.models.supply_chain import build_supply_chain_model

    with pytest.raises(ValueError, match="unknown formulation strengthening"):
        build_supply_chain_model(None, model_name="x", strengthening=["no_such_option"])


# Small generated instances (under 1 500 variables) on which the remanufacturing bound tightens the
# relaxation: (periods, factories, retailers, seed). On seed 0 with 3 periods and 1 factory it changes
# nothing, which would make the tests below trivial.
INSTANCES = [(3, 1, 2, 3), (3, 1, 2, 4), (3, 2, 2, 4), (4, 1, 2, 0), (4, 1, 3, 3)]


def _instance(periods: int, factories: int, retailers: int, seed: int):
    from clsc.generator.config import GeneratorConfig
    from clsc.generator.instance_builder import generate_instance
    from clsc.models.instance_data import InstanceData

    config = GeneratorConfig(
        suppliers=2, factories=factories, warehouses=2, retailers=retailers, airports=1, seaports=1, products=1,
        raw_materials=2, production_technologies=2, remanufacturing_technologies=2, periods=periods,
        seed=seed, instance_name=f"strength{periods}{factories}{retailers}{seed}",
    )
    return InstanceData.from_dict(generate_instance(config).to_dict())


def _solve(instance, strengthening, tax: float, *, relax: bool):
    import gurobipy as gp

    original = supply_chain.DEFAULT_FORMULATION_STRENGTHENING
    supply_chain.DEFAULT_FORMULATION_STRENGTHENING = tuple(strengthening)
    try:
        from clsc.models.follower import build_follower_model

        follower = build_follower_model(instance)
    finally:
        supply_chain.DEFAULT_FORMULATION_STRENGTHENING = original
    artifacts = follower.artifacts
    model = artifacts.model
    model.setObjective(artifacts.cost_expr + instance.tax_rate(tax) * artifacts.tax_base_expr, gp.GRB.MINIMIZE)
    model.update()
    model.Params.OutputFlag = 0
    model.Params.Threads = 1
    model.Params.MIPGap = 1e-9
    solved = model.relax() if relax else model
    solved.optimize()
    return solved.ObjVal


@requires_gurobi
@pytest.mark.parametrize("tax", [0.0, 25.0, 100.0])
@pytest.mark.parametrize("shape", INSTANCES)
def test_strengthening_keeps_the_integer_optimum(shape, tax: float) -> None:
    instance = _instance(*shape)
    plain = _solve(instance, (), tax, relax=False)
    strengthened = _solve(instance, FORMULATION_STRENGTHENING_OPTIONS, tax, relax=False)
    assert strengthened == pytest.approx(plain, rel=1e-9)


@requires_gurobi
@pytest.mark.parametrize("shape", INSTANCES)
def test_strengthening_raises_the_relaxation_bound_without_passing_the_optimum(shape) -> None:
    instance = _instance(*shape)
    plain = _solve(instance, (), 0.0, relax=True)
    strengthened = _solve(instance, FORMULATION_STRENGTHENING_OPTIONS, 0.0, relax=True)
    optimum = _solve(instance, (), 0.0, relax=False)
    assert strengthened > plain * 1.001  # it does something on these instances
    assert strengthened <= optimum * (1.0 + 1e-9)  # and the bound stays a bound
