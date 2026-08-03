from __future__ import annotations

import pytest

from clsc.generator import build_base_benchmark_specs, generate_instance, write_instance
from clsc.models.instance import InstanceData
from clsc.campaign.scenarios.technology import (
    DEFAULT_SCENARIO_NAME,
    create_technology_scenario,
    create_technology_scenario_instance,
)


def _base_payload() -> dict:
    spec = next(item for item in build_base_benchmark_specs(seed_base=23) if item.name == "STD_I17_M8_T3")
    return generate_instance(spec.to_config()).to_dict()


def test_create_technology_scenario_appends_meaningful_tradeoff_options() -> None:
    payload = _base_payload()
    base_sets = payload["sets"]
    base_params = payload["parameters"]
    base_production = list(base_sets["G"])
    base_remanufacturing = list(base_sets["L"])

    scenario = create_technology_scenario_instance(payload)
    scenario_payload = scenario.to_dict()
    scenario_sets = scenario_payload["sets"]
    scenario_params = scenario_payload["parameters"]

    InstanceData.from_dict(scenario_payload)

    assert scenario_payload["name"] == "STD_I17_M8_T3_G6_L6"
    assert scenario_sets["G"] == [*base_production, "g4", "g5", "g6"]
    assert scenario_sets["L"] == [*base_remanufacturing, "l4", "l5", "l6"]
    assert scenario_payload["metadata"]["scenario"]["name"] == DEFAULT_SCENARIO_NAME
    assert scenario_payload["metadata"]["scenario"]["source_instance"] == "STD_I17_M8_T3"
    assert scenario_payload["metadata"]["config"]["instance_name"] == "STD_I17_M8_T3_G6_L6"
    assert scenario_payload["metadata"]["config"]["production_technologies"] == 6
    assert scenario_payload["metadata"]["config"]["remanufacturing_technologies"] == 6

    production_pairs = {tuple(pair) for pair in scenario_sets["H_prod"]}
    remanufacturing_pairs = {tuple(pair) for pair in scenario_sets["H_rem"]}
    for product in scenario_sets["P"]:
        for technology in ("g4", "g5", "g6"):
            assert (product, technology) in production_pairs
        for technology in ("l4", "l5", "l6"):
            assert (product, technology) in remanufacturing_pairs

    mean_production_cost = sum(base_params["c_prod_g"][technology] for technology in base_production) / len(base_production)
    min_production_emission = min(base_params["e_prod_g"][technology] for technology in base_production)
    max_production_emission = max(base_params["e_prod_g"][technology] for technology in base_production)
    max_production_capacity = max(base_params["bar_p_g"][technology] for technology in base_production)

    assert scenario_params["c_prod_g"]["g4"] > mean_production_cost
    assert scenario_params["e_prod_g"]["g4"] < min_production_emission
    assert scenario_params["c_prod_g"]["g5"] < mean_production_cost
    assert scenario_params["e_prod_g"]["g5"] > max_production_emission
    assert scenario_params["bar_p_g"]["g6"] > max_production_capacity

    material = scenario_sets["U"][0]
    product = scenario_sets["P"][0]
    source_inputs = [
        base_params["a_in_u_p_g"][material][product][technology]
        for technology in base_production
        if base_params["a_in_u_p_g"][material][product][technology] > 0.0
    ]
    mean_input = sum(source_inputs) / len(source_inputs)
    assert scenario_params["a_in_u_p_g"][material][product]["g4"] < mean_input
    assert scenario_params["a_in_u_p_g"][material][product]["g5"] > mean_input

    mean_remanufacturing_cost = sum(base_params["c_rem_l"][technology] for technology in base_remanufacturing) / len(
        base_remanufacturing,
    )
    min_remanufacturing_emission = min(base_params["e_rem_l"][technology] for technology in base_remanufacturing)
    max_remanufacturing_emission = max(base_params["e_rem_l"][technology] for technology in base_remanufacturing)
    max_remanufacturing_capacity = max(base_params["bar_q_l"][technology] for technology in base_remanufacturing)

    assert scenario_params["c_rem_l"]["l4"] > mean_remanufacturing_cost
    assert scenario_params["e_rem_l"]["l4"] < min_remanufacturing_emission
    assert scenario_params["c_rem_l"]["l5"] < mean_remanufacturing_cost
    assert scenario_params["e_rem_l"]["l5"] > max_remanufacturing_emission
    assert scenario_params["bar_q_l"]["l6"] > max_remanufacturing_capacity


def test_create_technology_scenario_writes_valid_files_and_protects_existing_outputs(tmp_path) -> None:
    source_dir = tmp_path / "base"
    output_dir = tmp_path / "scenarios" / DEFAULT_SCENARIO_NAME
    source_dir.mkdir()

    spec = next(item for item in build_base_benchmark_specs(seed_base=29) if item.name == "STD_I17_M4_T3")
    base_instance = generate_instance(spec.to_config())
    source_path = write_instance(base_instance, source_dir / f"{base_instance.name}.json")

    written_paths = create_technology_scenario(source_dir, output_dir)

    assert written_paths == [output_dir / "STD_I17_M4_T3_G6_L6.json"]
    scenario_instance = InstanceData.from_file(written_paths[0])
    assert source_path.name == "STD_I17_M4_T3.json"
    assert scenario_instance.name == "STD_I17_M4_T3_G6_L6"
    assert scenario_instance.metadata["config"]["instance_name"] == "STD_I17_M4_T3_G6_L6"
    assert scenario_instance.metadata["benchmark"]["kind"] == "scenario"
    assert scenario_instance.metadata["scenario"]["source_instance"] == base_instance.name
    assert scenario_instance.metadata["scenario"]["added_technologies"] == {
        "production": ["g4", "g5", "g6"],
        "remanufacturing": ["l4", "l5", "l6"],
    }

    with pytest.raises(FileExistsError):
        create_technology_scenario(source_dir, output_dir)

    overwritten_paths = create_technology_scenario(source_dir, output_dir, overwrite=True)
    assert overwritten_paths == written_paths
