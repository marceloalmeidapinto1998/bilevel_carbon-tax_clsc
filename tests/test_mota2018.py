"""Tests of the Mota et al. (2018) case-study instance builder (no Gurobi licence needed)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clsc.generator import mota2018
from clsc.models.instance_data import InstanceData

COMMITTED = Path(__file__).resolve().parents[1] / "data" / "case_study" / "MOTA2018.json"


@pytest.fixture(scope="module")
def instance() -> dict:
    return mota2018.build_instance()


def test_the_instance_is_valid_and_matches_the_committed_file(instance) -> None:
    InstanceData.from_dict(json.loads(json.dumps(instance)))
    assert json.loads(COMMITTED.read_text(encoding="utf-8")) == json.loads(json.dumps(instance))


def test_total_demand_matches_mota(instance) -> None:
    # Mota Table A.1, case A: 197.30 million units produced and 6.23 million remanufactured over the
    # horizon, which with 0.28 million units of initial stock meet the demand.
    demand = instance["parameters"]["d_r_p_t"]
    total = sum(value for by_product in demand.values() for by_period in by_product.values() for value in by_period.values())
    assert total * mota2018.QUANTITY_UNIT == pytest.approx(197.30e6 + 6.23e6 + 0.28e6, rel=2e-3)


def test_network_follows_the_published_distances(instance) -> None:
    sets, distance = instance["sets"], instance["parameters"]["d_i_j"]
    assert all(destination in distance[origin] for origin, destination in sets["A"])
    # Brazil is reached from Europe only by plane or ship, through Sao Paulo's airport and Santos.
    brazil = {"w6", "w7", "r6", "r7", "air4", "port2"}
    crossing = {(o, d) for o, d in sets["A"] if (o in brazil) != (d in brazil)}
    assert crossing == {("air1", "air4"), ("air2", "air4"), ("air3", "air4"), ("air4", "air1"), ("air4", "air2"),
                        ("air4", "air3"), ("port1", "port2"), ("port2", "port1")}
    # Suppliers ship raw materials only, to factories.
    assert {(o, d) for _, o, d in sets["FLOW_RAW"]} == {(s, f) for s in sets["S"] for f in sets["F"]}


def test_quantities_are_in_thousands_and_leave_costs_unchanged(instance) -> None:
    parameters = instance["parameters"]
    # A thousand units of fp1 weigh 400 kg; a truck2 trip carries 55 thousand units.
    assert parameters["omega_p"]["p1"] == pytest.approx(400.0)
    assert parameters["bar_X_m"]["truck2"] == pytest.approx(55.0)
    # Cost of producing the whole demand of fp1 at gp1 is the same in either unit.
    demand = sum(parameters["d_r_p_t"][r]["p1"][t] for r in instance["sets"]["R"] for t in instance["sets"]["T"])
    assert demand * parameters["c_prod_g"]["gp1"] == pytest.approx(112.8e6 * 0.212, rel=1e-3)


def test_existing_facilities_and_the_resolved_conflicts(instance) -> None:
    parameters = instance["parameters"]
    assert parameters["existing_i"] == {"f1": 20000.0, "w1": 5000.0}
    assert parameters["c_area_f"]["f1"] == 0.0 and parameters["c_area_w"]["w1"] == 0.0
    assert parameters["c_prod_g"]["gp2"] == pytest.approx(0.324 * 1000)  # Mota Table 4, EUR per thousand units
    assert parameters["a_in_u_p_g"]["u1"]["p1"] == {"gp1": 0.25, "gp1alt": 0.45}  # Mota Table 2
    assert parameters["scmin_s_u"]["s2"]["u1"] == pytest.approx(1.0)  # Mota Table 5, 1000 units
    assert parameters["icmin_p_n"]["p1"]["w4"] == pytest.approx(12.0)  # Mota Table 9, 12000 units
    assert parameters["e_rem_l"] == {"gr1": 134.0, "gr2": 103.0}  # Tautenhain data Table 24
    assert len(instance["metadata"]["conflicts_resolved"]) == len(mota2018.CONFLICTS)
    assert len(instance["metadata"]["assumptions"]) == len(mota2018.ASSUMPTIONS)
