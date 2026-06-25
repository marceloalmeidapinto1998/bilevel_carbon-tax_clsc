from __future__ import annotations

import pytest

from data.generator import tautenhain_data as taut
from data.generator import build_base_benchmark_specs, generate_instance, write_instance
from src.models.instance_loader import InstanceData
from tools.experiments.scenarios.transport import (
    DEFAULT_SCENARIO_NAME,
    create_transport_scenario,
    create_transport_scenario_instance,
)


def _base_payload() -> dict:
    spec = next(item for item in build_base_benchmark_specs(seed_base=31) if item.name == "STD_I17_M8_T3")
    return generate_instance(spec.to_config()).to_dict()


def test_create_transport_scenario_appends_meaningful_tradeoff_options() -> None:
    payload = _base_payload()
    base_sets = payload["sets"]
    base_params = payload["parameters"]
    base_road_modes = list(base_sets["M_RD"])
    base_air_modes = list(base_sets["M_A"])
    base_sea_modes = list(base_sets["M_S"])

    scenario = create_transport_scenario_instance(payload)
    scenario_payload = scenario.to_dict()
    scenario_sets = scenario_payload["sets"]
    scenario_params = scenario_payload["parameters"]

    InstanceData.from_dict(scenario_payload)

    assert scenario_payload["name"] == "STD_I17_M8_T3_TM12"
    assert scenario_sets["M_RD"] == [*base_road_modes, "mrd3", "mrd4"]
    assert scenario_sets["M_A"] == [*base_air_modes, "ma3", "ma4"]
    assert scenario_sets["M_S"] == [*base_sea_modes, "ms3", "ms4"]
    assert scenario_sets["M"] == [*scenario_sets["M_RD"], *scenario_sets["M_A"], *scenario_sets["M_S"]]
    assert scenario_payload["metadata"]["scenario"]["name"] == DEFAULT_SCENARIO_NAME
    assert scenario_payload["metadata"]["scenario"]["source_instance"] == "STD_I17_M8_T3"
    assert scenario_payload["metadata"]["config"]["instance_name"] == "STD_I17_M8_T3_TM12"
    assert scenario_payload["metadata"]["config"]["trucks"] == 4
    assert scenario_payload["metadata"]["config"]["airplanes"] == 4
    assert scenario_payload["metadata"]["config"]["boats"] == 4

    assert scenario_params["mode_family_m"] == {
        **{mode: "truck" for mode in scenario_sets["M_RD"]},
        **{mode: "air" for mode in scenario_sets["M_A"]},
        **{mode: "sea" for mode in scenario_sets["M_S"]},
    }
    assert scenario_payload["metadata"]["transport_mode_family"] == scenario_params["mode_family_m"]

    required_mode_maps = (
        "bar_X_m",
        "ctmin_m",
        "ccamax_m",
        "c_ship_m",
        "c_trip_m",
        "f_mode_m",
        "c_handle_m",
        "road_return_factor_m",
        "speed_km_h_m",
        "max_driving_hours_m",
        "trip_big_m_m",
        "e_ship_m",
    )
    for parameter_name in required_mode_maps:
        assert set(scenario_params[parameter_name]) == set(scenario_sets["M"])

    mean_road_variable_cost = sum(base_params["c_ship_m"][mode] for mode in base_road_modes) / len(base_road_modes)
    mean_road_fixed_cost = sum(base_params["f_mode_m"][mode] for mode in base_road_modes) / len(base_road_modes)
    min_road_emission = min(base_params["e_ship_m"][mode] for mode in base_road_modes)
    max_road_emission = max(base_params["e_ship_m"][mode] for mode in base_road_modes)
    max_road_capacity = max(base_params["bar_X_m"][mode] for mode in base_road_modes)

    assert scenario_params["bar_X_m"]["mrd3"] > max_road_capacity
    assert scenario_params["c_ship_m"]["mrd3"] > mean_road_variable_cost
    assert scenario_params["f_mode_m"]["mrd3"] > mean_road_fixed_cost
    assert scenario_params["e_ship_m"]["mrd3"] < min_road_emission
    assert scenario_params["c_ship_m"]["mrd4"] < mean_road_variable_cost
    assert scenario_params["f_mode_m"]["mrd4"] < mean_road_fixed_cost
    assert scenario_params["e_ship_m"]["mrd4"] > max_road_emission

    for family_modes, clean_mode, low_cost_mode in (
        (base_air_modes, "ma3", "ma4"),
        (base_sea_modes, "ms3", "ms4"),
    ):
        mean_variable_cost = sum(base_params["c_ship_m"][mode] for mode in family_modes) / len(family_modes)
        mean_handling_cost = sum(base_params["c_handle_m"][mode] for mode in family_modes) / len(family_modes)
        min_emission = min(base_params["e_ship_m"][mode] for mode in family_modes)
        max_emission = max(base_params["e_ship_m"][mode] for mode in family_modes)

        # Air/sea modes carry no separate fixed cost (f_mode_m is always 0 for
        # these families; the hub access fee f_h covers it), so f_mode_m is not
        # asserted here, unlike the road-mode checks above.
        assert scenario_params["c_ship_m"][clean_mode] > mean_variable_cost
        assert scenario_params["f_mode_m"][clean_mode] == 0.0
        assert scenario_params["c_handle_m"][clean_mode] > mean_handling_cost
        assert scenario_params["e_ship_m"][clean_mode] < min_emission
        assert scenario_params["c_ship_m"][low_cost_mode] < mean_variable_cost
        assert scenario_params["f_mode_m"][low_cost_mode] == 0.0
        assert scenario_params["c_handle_m"][low_cost_mode] < mean_handling_cost
        assert scenario_params["e_ship_m"][low_cost_mode] > max_emission

    for mode in scenario_sets["M"]:
        family = scenario_params["mode_family_m"][mode]
        assert scenario_params["ctmin_m"][mode] == taut.TRANSPORT_MIN_CAPACITY_KG
        if family == "truck":
            assert scenario_params["ccamax_m"][mode] == 0.0
            assert scenario_params["c_handle_m"][mode] == 0.0
            assert scenario_params["c_trip_m"][mode] == round(
                scenario_params["c_ship_m"][mode] * scenario_params["bar_X_m"][mode],
                6,
            )
            assert scenario_params["road_return_factor_m"][mode] == taut.TRUCK_RETURN_DISTANCE_FACTOR
            assert scenario_params["speed_km_h_m"][mode] == taut.TRUCK_SPEED_KM_H
            assert scenario_params["max_driving_hours_m"][mode] == taut.MAX_DRIVING_HOURS_PER_PERIOD
        else:
            assert scenario_params["ccamax_m"][mode] == taut.CONTRACTED_CAPACITY_KG
            assert scenario_params["c_trip_m"][mode] == 0.0
            assert scenario_params["road_return_factor_m"][mode] == 1.0
            assert scenario_params["speed_km_h_m"][mode] == 0.0
            assert scenario_params["max_driving_hours_m"][mode] == 0.0


def test_create_transport_scenario_writes_valid_files_and_protects_existing_outputs(tmp_path) -> None:
    source_dir = tmp_path / "base"
    output_dir = tmp_path / "scenarios" / DEFAULT_SCENARIO_NAME
    source_dir.mkdir()

    spec = next(item for item in build_base_benchmark_specs(seed_base=37) if item.name == "STD_I17_M4_T3")
    base_instance = generate_instance(spec.to_config())
    source_path = write_instance(base_instance, source_dir / f"{base_instance.name}.json")

    written_paths = create_transport_scenario(source_dir, output_dir)

    assert written_paths == [output_dir / "STD_I17_M4_T3_TM12.json"]
    scenario_instance = InstanceData.from_file(written_paths[0])
    assert source_path.name == "STD_I17_M4_T3.json"
    assert scenario_instance.name == "STD_I17_M4_T3_TM12"
    assert scenario_instance.metadata["config"]["instance_name"] == "STD_I17_M4_T3_TM12"
    assert scenario_instance.metadata["benchmark"]["kind"] == "scenario"
    assert scenario_instance.metadata["scenario"]["source_instance"] == base_instance.name
    assert scenario_instance.metadata["scenario"]["added_transport_modes"] == {
        "road": ["mrd3", "mrd4"],
        "air": ["ma3", "ma4"],
        "sea": ["ms3", "ms4"],
    }

    with pytest.raises(FileExistsError):
        create_transport_scenario(source_dir, output_dir)

    overwritten_paths = create_transport_scenario(source_dir, output_dir, overwrite=True)
    assert overwritten_paths == written_paths
