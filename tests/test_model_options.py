"""Tests of the optional instance parameters that let an instance follow Mota et al. (2018)'s case study:
existing facilities, capacities counted in units, handling per hub and unit, and the emissions'
return factor. Absent, they leave the model as it was (the benchmark instances carry none of them).

They build or solve the tiny generated instance (seconds) and are skipped without a Gurobi licence.
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict

import pytest

from clsc.models.instance_data import InstanceData, InstanceValidationError


def _gurobi_available() -> bool:
    try:
        import gurobipy as gp

        with gp.Env(params={"OutputFlag": 0}):
            return True
    except Exception:
        return False


requires_gurobi = pytest.mark.skipif(not _gurobi_available(), reason="no usable Gurobi licence")


@pytest.fixture(scope="module")
def tiny_dict() -> dict:
    from clsc.generator.config import GeneratorConfig
    from clsc.generator.instance_builder import generate_instance

    config = GeneratorConfig(
        suppliers=2, factories=1, warehouses=2, retailers=2, airports=1, seaports=1, products=1,
        raw_materials=2, production_technologies=2, remanufacturing_technologies=2, periods=3,
        seed=0, instance_name="tiny0",
    )
    return generate_instance(config).to_dict()


def _with(tiny_dict: dict, **parameters) -> InstanceData:
    data = copy.deepcopy(tiny_dict)
    data["parameters"].update(parameters)
    return InstanceData.from_dict(data)


def _coefficients(expression) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for k in range(expression.size()):
        totals[expression.getVar(k).VarName] += expression.getCoeff(k)
    return totals


def _artifacts(instance: InstanceData):
    from clsc.models.follower import build_follower_model

    artifacts = build_follower_model(instance).artifacts
    artifacts.model.update()
    return artifacts


def _solve(instance: InstanceData, tax: float = 0.0):
    import gurobipy as gp
    from clsc.models.follower import build_follower_model

    follower = build_follower_model(instance)
    model = follower.artifacts.model
    model.setObjective(follower.artifacts.cost_expr + instance.tax_rate(tax) * follower.artifacts.tax_base_expr, gp.GRB.MINIMIZE)
    model.Params.OutputFlag = 0
    model.Params.Threads = 1
    model.optimize()
    assert model.SolCount > 0
    return follower, {v.VarName: v.X for v in model.getVars()}


def _truck_modes(instance: InstanceData) -> list[str]:
    return [m for m, family in instance.parameters["mode_family_m"].items() if family == "truck"]


@requires_gurobi
def test_an_existing_facility_is_open_with_its_area(tiny_dict) -> None:
    params = tiny_dict["parameters"]
    warehouse = tiny_dict["sets"]["W"][-1]
    area = 0.5 * (params["Amin_w"][warehouse] + params["A_w"][warehouse])
    _, values = _solve(_with(tiny_dict, existing_i={warehouse: area}))
    assert values[f"y_w[{warehouse}]"] == pytest.approx(1.0)
    assert values[f"YC[{warehouse}]"] == pytest.approx(area)


@pytest.mark.parametrize(
    "parameters, message",
    [
        ({"existing_i": {"r1": 10.0}}, "not a factory or warehouse"),
        ({"existing_i": {"w1": 1e9}}, "outside"),
        ({"capacity_unit_m": {"mrd1": "tonne"}}, "capacity_unit_m"),
        ({"c_handle_h": {"w1": 0.1}}, "not hubs"),
        ({"emission_return_factor_m": {"no_such_mode": 1.0}}, "unknown mode"),
    ],
)
def test_invalid_options_are_rejected(tiny_dict, parameters, message) -> None:
    with pytest.raises(InstanceValidationError, match=message):
        _with(tiny_dict, **parameters)


@requires_gurobi
def test_truck_capacity_can_count_units(tiny_dict) -> None:
    from clsc.models.supply_chain import total_emissions_upper_bound

    trucks = _truck_modes(InstanceData.from_dict(tiny_dict))
    capacity = 1000.0
    instance = _with(
        tiny_dict,
        capacity_unit_m={m: "unit" for m in trucks},
        bar_X_m={**tiny_dict["parameters"]["bar_X_m"], **{m: capacity for m in trucks}},
    )
    follower, values = _solve(instance)
    units = defaultdict(float)
    for name, value in values.items():
        if name.startswith("x[") and value > 1e-9:
            item, origin, destination, mode, period = name[2:-1].split(",")
            if mode in trucks:
                units[origin, destination, mode, period] += value
    assert units  # trucks carry something
    for (origin, destination, mode, period), carried in units.items():
        trips = values[f"trip[{origin},{destination},{mode},{period}]"]
        # Units, not kg, fill the trucks; trips are paid for, so they are just enough.
        assert trips == pytest.approx(math.ceil(carried / capacity - 1e-9))
    assert total_emissions_upper_bound(instance) >= follower.artifacts.emissions_expr.getValue()


@requires_gurobi
def test_handling_per_hub_charges_units_entering_a_hub(tiny_dict) -> None:
    from clsc.models.supply_chain import discount_factors

    base = _with(tiny_dict, c_handle_m={m: 0.0 for m in tiny_dict["parameters"]["c_handle_m"]})
    hubs = [*tiny_dict["sets"]["AIR"], *tiny_dict["sets"]["PORT"]]
    rate = 0.5
    per_hub = _with(tiny_dict, c_handle_h={h: rate for h in hubs})
    base_artifacts, per_hub_artifacts = _artifacts(base), _artifacts(per_hub)  # keep the models alive
    plain = _coefficients(base_artifacts.cost_expr)
    charged = _coefficients(per_hub_artifacts.cost_expr)
    discount = discount_factors(per_hub.parameters, per_hub.sets["T"])
    entering = 0
    for name in set(plain) | set(charged):
        difference = charged.get(name, 0.0) - plain.get(name, 0.0)
        if name.startswith("x["):
            item, origin, destination, mode, period = name[2:-1].split(",")
            if destination in hubs and origin not in hubs:
                entering += 1
                assert difference == pytest.approx(discount[period] * rate)
                continue
        assert difference == pytest.approx(0.0, abs=1e-12)
    assert entering > 0


@requires_gurobi
def test_emission_return_factor_scales_truck_emissions_only(tiny_dict) -> None:
    trucks = _truck_modes(InstanceData.from_dict(tiny_dict))
    default = _artifacts(InstanceData.from_dict(tiny_dict))
    outbound = _artifacts(_with(tiny_dict, emission_return_factor_m={m: 1.0 for m in trucks}))
    plain, outbound_only = _coefficients(default.emissions_expr), _coefficients(outbound.emissions_expr)
    params = tiny_dict["parameters"]
    weight = {**params["omega_u"], **params["omega_p"], **params["omega_rp"]}
    checked = 0
    for name, value in plain.items():
        dropped = 0.0
        if name.startswith("x["):
            item, origin, destination, mode, period = name[2:-1].split(",")
            if mode in trucks:
                # The return leg (factor 2 -> 1): one more distance's worth of the mode's emissions.
                dropped = params["e_ship_m"][mode] * weight[item] * params["d_i_j"][origin][destination]
                checked += 1
        assert outbound_only.get(name, 0.0) == pytest.approx(value - dropped, rel=1e-12, abs=1e-12)
    assert checked > 0
    assert _coefficients(outbound.cost_expr) == pytest.approx(_coefficients(default.cost_expr))
