"""Tests of the experiment framework: scenarios, response profiles, job expansion and the tables.
None needs Gurobi.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from clsc.experiments.plan import EXPERIMENTS
from clsc.experiments.profile import response_profile
from clsc.experiments.report import write_tables
from clsc.experiments.runner import JOB_FILE, expand
from clsc.experiments.scenarios import SCENARIOS, SENSITIVITY_SCENARIOS, apply_scenario, write_variant
from clsc.models.instance_data import InstanceData

INSTANCE = Path("data/STD_I17_M4_T3.json")


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(INSTANCE.read_text(encoding="utf-8"))


def test_six_parameters_two_levels_each() -> None:
    assert len(SENSITIVITY_SCENARIOS) == 12
    parameters = [SCENARIOS[name].parameter for name in SENSITIVITY_SCENARIOS]
    assert sorted(set(parameters)) == ["clean_cost", "e_prod", "e_rem", "interest", "q", "returns"]
    assert all(parameters.count(parameter) == 2 for parameter in set(parameters))


def test_production_intensity_scales_production_alone(payload) -> None:
    variant = apply_scenario(payload, SCENARIOS["e_prod_x2"])
    before, after = payload["parameters"], variant["parameters"]
    assert after["e_prod_g"]["g1"] == pytest.approx(2 * before["e_prod_g"]["g1"])
    assert after["e_rem_l"] == before["e_rem_l"] and after["e_raw_s_u"] == before["e_raw_s_u"]
    assert variant["name"] == "STD_I17_M4_T3__e_prod_x2"
    assert payload["parameters"]["e_prod_g"] == before["e_prod_g"]  # the input is not changed


def test_return_fractions_are_capped_at_one(payload) -> None:
    variant = apply_scenario(payload, SCENARIOS["returns_x2"])["parameters"]
    for name in ("rho_r_p_t", "ret_min_frac_r_p_t", "ret_max_frac_r_p_t"):
        values = [v for by_product in variant[name].values() for by_period in by_product.values() for v in by_period.values()]
        assert max(values) <= 1.0


def test_interest_rate_levels(payload) -> None:
    assert apply_scenario(payload, SCENARIOS["interest_x0.5"])["parameters"]["interest_rate"] == pytest.approx(0.05)
    assert apply_scenario(payload, SCENARIOS["interest_x2"])["parameters"]["interest_rate"] == pytest.approx(0.2)


def test_clean_cost_scales_the_cleanest_technology(payload) -> None:
    variant = apply_scenario(payload, SCENARIOS["clean_cost_x2"])
    emissions = payload["parameters"]["e_prod_g"]
    cleanest = min(emissions, key=emissions.get)
    assert variant["metadata"]["scenario"]["operations"][0]["technologies"] == [cleanest]
    assert variant["parameters"]["c_prod_g"][cleanest] == pytest.approx(2 * payload["parameters"]["c_prod_g"][cleanest])


def test_the_weight_is_a_solver_option_on_unchanged_data(payload) -> None:
    scenario = SCENARIOS["q_1e-3"]
    assert scenario.solver_options == {"leader_tax_weight_relative": 1e-3}
    variant = apply_scenario(payload, scenario)
    assert variant["parameters"] == payload["parameters"] and variant["name"] == "STD_I17_M4_T3__q_1e-3"


@pytest.mark.parametrize("instance", ["data/STD_I17_M4_T3.json", "data/case_study/MOTA2018.json"])
def test_every_scenario_gives_a_valid_instance(tmp_path, instance) -> None:
    for scenario in SCENARIOS.values():
        path = write_variant(Path(instance), scenario, tmp_path)
        if scenario.is_base:
            assert path == Path(instance)
        else:
            assert InstanceData.from_file(path).name == path.stem


def test_profile_splits_the_emissions_by_source() -> None:
    instance = InstanceData.from_file(INSTANCE)
    p = instance.parameters
    supplier, factory = next((s, d) for u, s, d in instance.sets["FLOW_RAW"] if s in instance.sets["S"])
    raw = next(u for u, s, d in instance.sets["FLOW_RAW"] if s == supplier and d == factory)
    values = {
        "q[p1,f1,g1,t1]": 10.0, "rem[p1,f1,l1,t2]": 2.0, f"x[{raw},{supplier},{factory},mrd1,t1]": 5.0,
        "y_f[f1]": 1.0, "y_f[f2]": 0.0, "u_prod[f1,g1]": 1.0,
    }
    profile = response_profile(instance, values)
    assert profile["emissions_production"] == pytest.approx(p["e_prod_g"]["g1"] * p["omega_p"]["p1"] * 10.0)
    assert profile["emissions_remanufacturing"] == pytest.approx(p["e_rem_l"]["l1"] * p["omega_p"]["p1"] * 2.0)
    assert profile["emissions_raw_material"] == pytest.approx(p["e_raw_s_u"][supplier][raw] * p["omega_u"][raw] * 5.0)
    assert profile["remanufacturing_share"] == pytest.approx(2.0 / 12.0)
    assert profile["factories"] == "f1" and profile["production_technologies"] == "f1:g1"


def test_expansion_names_a_directory_per_job(tmp_path) -> None:
    jobs = expand(EXPERIMENTS["P2a"], instances=["I17_M4_T3"])
    assert len(jobs) == 12
    assert jobs[0].directory(tmp_path) == tmp_path / "P2a" / "seed0" / "STD_I17_M4_T3__q_1e-5"
    assert len(expand(EXPERIMENTS["P1"])) == 16 and len(expand(EXPERIMENTS["P2b"])) == 12
    job = jobs[0]
    assert not job.is_done(tmp_path)
    job.directory(tmp_path).mkdir(parents=True)
    (job.directory(tmp_path) / JOB_FILE).write_text(json.dumps({"status": "failed"}), encoding="utf-8")
    assert not job.is_done(tmp_path)
    (job.directory(tmp_path) / JOB_FILE).write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    assert job.is_done(tmp_path)


def test_every_planned_instance_exists() -> None:
    for experiment in EXPERIMENTS.values():
        assert all(Path(path).exists() for path in experiment.instances), experiment.key
        assert all(scenario in SCENARIOS for scenario in experiment.scenarios), experiment.key


def _fake_run(directory: Path, *, tax: float, emissions: float, cost: float, follower_objective: float, weight: float) -> None:
    directory.mkdir(parents=True)
    summary = {
        "success": True, "result_class": "optimal", "termination_reason": "optimal", "relative_gap": 0.0, "iterations": 2,
        "solve_seconds": 10.0, "leader_tax_weight": weight, "tax": tax, "emissions": emissions, "cost": cost,
        "follower_objective": follower_objective, "leader_objective_lb": emissions, "leader_objective_ub": emissions,
        "upper_bound_certified": True, "validation_status": "validated",
    }
    (directory / "summary.json").write_text(json.dumps([summary]), encoding="utf-8")
    with (directory / "dbp_trace.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["iteration", "relaxation_tax", "follower_objective", "leader_objective_ub"])
        writer.writeheader()
        writer.writerow({"iteration": 1, "relaxation_tax": 0.0, "follower_objective": 1000.0, "leader_objective_ub": 200.0})


def test_tables_are_written_from_dbp_runs(tmp_path) -> None:
    name = "STD_I17_M4_T3"
    _fake_run(tmp_path / "P1" / "seed0" / name, tax=30.0, emissions=150.0, cost=1100.0, follower_objective=1104.5, weight=0.01)
    _fake_run(tmp_path / "P2a" / "seed0" / f"{name}__q_1e-5", tax=50.0, emissions=140.0, cost=1150.0, follower_objective=1157.0, weight=0.001)
    counts = write_tables(tmp_path, ["sensitivity", "tornado", "policy"])
    assert counts["sensitivity"] == 2
    with (tmp_path / "tables" / "sensitivity.csv").open(encoding="utf-8") as handle:
        rows = {row["scenario"]: row for row in csv.DictReader(handle)}
    assert float(rows["base"]["emission_reduction"]) == pytest.approx(0.25)
    assert float(rows["base"]["cost_increase"]) == pytest.approx(0.1)
    assert float(rows["base"]["tax_paid"]) == pytest.approx(4.5)
    with (tmp_path / "tables" / "tornado.csv").open(encoding="utf-8") as handle:
        q = next(row for row in csv.DictReader(handle) if row["instance"] == name and row["parameter"] == "q")
    assert float(q["tax_change_low"]) == pytest.approx(20.0) and q["tax_high"] == ""
    with (tmp_path / "tables" / "policy.csv").open(encoding="utf-8") as handle:
        points = {row["point"]: row for row in csv.DictReader(handle) if row["instance"] == name}
    assert float(points["least_emissions"]["emissions"]) == pytest.approx(0.01 / 1e-4)
