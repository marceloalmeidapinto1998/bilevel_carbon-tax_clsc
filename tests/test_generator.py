"""The instance generator: base benchmark specs, parameter schema/ranges, and the two menu-
expansion scenario builders (technology, transport).

This layer produces every number the model will later be solved against, so its job is to
reproduce Tautenhain et al.'s sampling ranges and Mota et al.'s derived quantities exactly --
a wrong range here is invisible to the solver (Gurobi optimizes whatever it's handed) and would
propagate straight into the paper. Key regressions pinned here:
  * `d_i_j` arc distances are sampled independently per node pair, NOT from the Euclidean distance
    between sampled coordinates -- a metric distance would satisfy the triangle inequality and make
    every intermodal hub route structurally worse than the direct truck arc, leaving air/sea unused.
  * `bom_rem_r_p` (recovered-product BOM) is diagonal by construction (rp_i recovers only p_i); a
    dense sample let the factory-level balance equation pick up an unrelated product's
    remanufacturing throughput, producing ~50% infeasibility on multi-product (M8) instances
    (confirmed via Gurobi IIS, 2026-06-26).
  * expanding two or more structural menus of the same call together (`apply_structural_levels`)
    must not raise -- an earlier per-call rejection guard checked the full expanded profile instead
    of just the subset being added in that call, so S1/S8-style multi-menu scenarios wrongly raised
    "already contains scenario" (found 2026-07-09).
"""
from __future__ import annotations

import json

import pytest

from clsc.generator import tautenhain_data as taut
from clsc.generator import (
    DEFAULT_AIRPLANES,
    DEFAULT_BOATS,
    DEFAULT_TRUCKS,
    DEFAULT_TRANSPORT_MODES,
    apply_prefix_override,
    build_base_benchmark_specs,
    generate_benchmark,
    generate_instance,
    write_instance,
)
from clsc.models.instance import InstanceData
from clsc.campaign.structural import apply_structural_levels
from clsc.campaign.scenarios.technology import (
    DEFAULT_SCENARIO_NAME as DEFAULT_TECH_SCENARIO_NAME,
    create_technology_scenario,
    create_technology_scenario_instance,
)
from clsc.campaign.scenarios.transport import (
    DEFAULT_SCENARIO_NAME as DEFAULT_TRANSPORT_SCENARIO_NAME,
    create_transport_scenario,
    create_transport_scenario_instance,
)


def _generate(name: str, *, seed_base: int):
    spec = next(item for item in build_base_benchmark_specs(seed_base=seed_base) if item.name == name)
    return generate_instance(spec.to_config())


def _std_i17_m8_t3(seed_base: int = 13):
    return _generate("STD_I17_M8_T3", seed_base=seed_base)


# ---------------------------------------------------------------------------
# Base benchmark specs
# ---------------------------------------------------------------------------

def test_build_base_benchmark_specs_creates_12_unique_std_specs() -> None:
    specs = build_base_benchmark_specs(seed_base=11)

    assert len(specs) == 12
    assert len({spec.name for spec in specs}) == 12

    spec = next(item for item in specs if item.name == "STD_I25_M8_T12")
    assert spec.suppliers == 3
    assert spec.factories == 3
    assert spec.warehouses == 9
    assert spec.retailers == 4
    assert spec.airports == 4
    assert spec.seaports == 2
    assert spec.raw_materials == 4
    assert spec.products == 2
    assert spec.production_technologies == 3
    assert spec.remanufacturing_technologies == 3
    assert spec.periods == 12
    config = spec.to_config()
    assert config.trucks == DEFAULT_TRUCKS
    assert config.airplanes == DEFAULT_AIRPLANES
    assert config.boats == DEFAULT_BOATS


def test_std_prefix_override_preserves_base_parameters() -> None:
    base_instance = _generate("STD_I17_M4_T3", seed_base=3)
    assert apply_prefix_override(base_instance, "STD").parameters == base_instance.parameters


def test_generated_initial_product_inventory_is_zero_for_all_nodes() -> None:
    instance = _generate("STD_I17_M4_T3", seed_base=7)
    initial_inventory = instance.parameters["i_p_n_0"]
    assert all(
        value == 0.0
        for product_inventory in initial_inventory.values()
        for value in product_inventory.values()
    )


@pytest.mark.gurobi
@pytest.mark.slow
def test_generate_benchmark_writes_expected_base_counts(tmp_path) -> None:
    summary = generate_benchmark(tmp_path, seed_base=5, file_format="json")

    assert summary.base_specs == 12
    assert summary.base_instances == 12

    base_files = sorted(tmp_path.glob("*.json"))

    assert len(base_files) == 12
    assert not (tmp_path / "scenarios").exists()

    sample_base = json.loads((tmp_path / "STD_I17_M4_T3.json").read_text(encoding="utf-8"))
    assert sample_base["name"] == "STD_I17_M4_T3"


# ---------------------------------------------------------------------------
# Parameter schema, sets, and metadata conventions
# ---------------------------------------------------------------------------

def test_generated_parameter_schema_has_required_and_no_legacy_keys() -> None:
    instance = _std_i17_m8_t3()
    params = instance.parameters

    required = {
        "a_in_u_p_g", "bar_s_s_u", "h_p", "bom_rem_r_p", "icmax_p_n", "icmin_p_n",
        "pcmin_g", "pcmin_l", "scmin_s_u", "rmc_s_u", "rpc_rp", "ret_yield_rp_p", "theta_p",
        "c_handle_m", "c_trip_m", "f_h", "ret_min_frac_r_p_t", "ret_max_frac_r_p_t",
        "road_return_factor_m", "speed_km_h_m", "max_driving_hours_m", "truck_investment_budget",
        "trip_big_m_m", "e_raw_s_u", "c_area_f", "c_area_w", "Amin_f", "Amin_w",
        "apu_u", "apu_p", "apur_p", "apu_rp", "apu_q",
    }
    legacy = {
        "a_in_u_p", "bar_i_f", "bar_i_r", "bar_i_w", "bar_s_s", "bom_rem_p", "bom_rem_r",
        "d_fw", "d_rf", "d_sf", "d_wr", "eta_p", "f_f", "f_s", "f_w", "h_f", "h_r", "h_w",
        "e_open_s", "h_rp", "icmax_rp_n", "icmin_rp_n", "i_rp_n_0", "psu_p", "rp_of_p", "rpc_p",
    }

    assert required <= params.keys(), f"Missing required keys: {required - params.keys()}"
    present_legacy = legacy & params.keys()
    assert not present_legacy, f"Legacy keys still present: {present_legacy}"


def test_generated_set_and_metadata_conventions() -> None:
    instance = _std_i17_m8_t3()

    for key in ("H_prod", "H_rem", "AIR", "PORT", "RP", "FLOW_RAW", "FLOW_FP", "FLOW_RP"):
        assert key in instance.sets, f"Missing set: {key}"

    assert instance.sets["N"] == [
        *instance.sets["S"], *instance.sets["F"], *instance.sets["W"],
        *instance.sets["R"], *instance.sets["AIR"], *instance.sets["PORT"],
    ]
    assert instance.sets["V"] == instance.sets["W"]
    assert instance.sets["K"] == instance.sets["RP"]

    assert instance.metadata["carbon_tax_units"] == {
        "underline_tau_overline_tau": "USD/kg CO2e",
        "tax_index_step": "0.01 USD/kg CO2e",
        "tau_formula_usd_per_kg_co2e": "0.01 * tax_index",
    }
    assert instance.metadata["source_model"] == "paper/bilevel_model.tex"
    assert instance.metadata["unit_convention"] == {
        "raw_material_flow": "item_units",
        "raw_material_cost": "USD/raw-material unit",
        "raw_material_emission_intensity": "kg CO2e/kg",
        "production_emission_intensity": "kg CO2e/kg",
        "remanufacturing_emission_intensity": "kg CO2e/kg",
    }
    assert set(instance.metadata["node_coordinates"]) == set(instance.sets["I"])
    span = instance.metadata["config"]["coordinate_span_km"]
    for coordinate in instance.metadata["node_coordinates"].values():
        assert set(coordinate) == {"x", "y"}
        assert 0.0 <= coordinate["x"] <= span
        assert 0.0 <= coordinate["y"] <= span

    # Arc distances follow Tautenhain's uniform range U[10, 750] and are sampled independently
    # per node pair -- see module docstring for why this must not be Euclidean.
    d_i_j = instance.parameters["d_i_j"]
    for targets in d_i_j.values():
        for distance in targets.values():
            assert taut.DISTANCE_RANGE[0] <= distance <= taut.DISTANCE_RANGE[1]
    nodes = list(d_i_j)

    def _d(a: str, b: str) -> float | None:
        return d_i_j.get(a, {}).get(b)

    # At least one triangle-inequality violation must exist (impossible under a
    # Euclidean/metric distance, guaranteed to occur under independent uniform draws).
    assert any(
        _d(i, j) is not None
        and _d(i, k) is not None
        and _d(k, j) is not None
        and _d(i, j) > _d(i, k) + _d(k, j) + 1e-6
        for i in nodes
        for j in nodes
        for k in nodes
        if i != j and i != k and j != k
    )


# ---------------------------------------------------------------------------
# Parameter ranges (Tautenhain sampling; Mota derived quantities)
# ---------------------------------------------------------------------------

def test_generated_bom_follows_tautenhain_ranges() -> None:
    instance = _std_i17_m8_t3()
    params = instance.parameters
    production_pairs = {tuple(pair) for pair in instance.sets["H_prod"]}

    for material in instance.sets["U"]:
        for product in instance.sets["P"]:
            for technology in instance.sets["G"]:
                value = params["a_in_u_p_g"][material][product][technology]
                if (product, technology) in production_pairs:
                    assert taut.BOM_PROD_RANGE[0] <= value <= taut.BOM_PROD_RANGE[1]
                else:
                    assert value == 0.0


def test_generated_supplier_parameters_follow_ranges() -> None:
    instance = _std_i17_m8_t3()
    params = instance.parameters

    for supplier in instance.sets["S"]:
        for material in instance.sets["U"]:
            assert 0.0 <= params["scmin_s_u"][supplier][material] <= params["bar_s_s_u"][supplier][material]
            assert taut.RAW_MATERIAL_COST_RANGE[0] <= params["rmc_s_u"][supplier][material] <= taut.RAW_MATERIAL_COST_RANGE[1]
            assert taut.RAW_AREA_RANGE[0] <= params["apu_u"][material] <= taut.RAW_AREA_RANGE[1]
            assert params["apu_q"][material] == params["apu_u"][material]


def test_generated_facility_area_parameters_are_bounded() -> None:
    instance = _std_i17_m8_t3()
    params = instance.parameters

    for factory in instance.sets["F"]:
        assert taut.AREA_INSTALLATION_COST_RANGE[0] <= params["c_area_f"][factory] <= taut.AREA_INSTALLATION_COST_RANGE[1]
        assert taut.FACTORY_AREA_MIN_RANGE[0] <= params["Amin_f"][factory] <= taut.FACTORY_AREA_MIN_RANGE[1]
        assert params["Amin_f"][factory] <= params["A_f"][factory]

    for warehouse in instance.sets["W"]:
        assert taut.AREA_INSTALLATION_COST_RANGE[0] <= params["c_area_w"][warehouse] <= taut.AREA_INSTALLATION_COST_RANGE[1]
        assert taut.WAREHOUSE_AREA_MIN_RANGE[0] <= params["Amin_w"][warehouse] <= taut.WAREHOUSE_AREA_MIN_RANGE[1]
        assert params["Amin_w"][warehouse] <= params["A_w"][warehouse]


def test_generated_product_and_recovered_product_parameters() -> None:
    instance = _std_i17_m8_t3()
    params = instance.parameters

    for product in instance.sets["P"]:
        assert taut.RETURN_LAG_RANGE[0] <= params["theta_p"][product] <= min(taut.RETURN_LAG_RANGE[1], len(instance.sets["T"]))
        assert params["h_p"][product] == round(taut.STOCK_COST_BASE + params["omega_p"][product], 4)
        assert params["apu_p"][product] > 0.0
        assert params["apu_q"][product] == params["apu_p"][product]
        assert params["apur_p"][product] == pytest.approx(
            round(params["apu_p"][product] / taut.PRODUCT_ROTATION_PER_PERIOD, 6)
        )
        for retailer in instance.sets["R"]:
            for period in instance.sets["T"]:
                assert 0.0 <= params["ret_min_frac_r_p_t"][retailer][product][period] <= params["ret_max_frac_r_p_t"][retailer][product][period]
                assert params["rho_r_p_t"][retailer][product][period] == params["ret_max_frac_r_p_t"][retailer][product][period]
        for node in instance.sets["V"]:
            assert params["icmin_p_n"][product][node] == round(
                taut.INVENTORY_FRAC_MIN * params["icmax_p_n"][product][node], 2,
            )

    for recovered_product in instance.sets["RP"]:
        assert params["rpc_rp"][recovered_product] >= 0.0
        expected_recovered_area = sum(
            params["bom_rem_r_p"][recovered_product][product] * params["apu_p"][product]
            for product in instance.sets["P"]
        )
        assert params["apu_rp"][recovered_product] == pytest.approx(round(expected_recovered_area, 6))
        assert params["apu_q"][recovered_product] == params["apu_rp"][recovered_product]
        for product in instance.sets["P"]:
            value = params["bom_rem_r_p"][recovered_product][product]
            is_diagonal = recovered_product.removeprefix("rp") == product.removeprefix("p")
            # bom_rem_r_p is diagonal by construction -- see module docstring.
            if is_diagonal:
                assert taut.BOM_REM_RANGE[0] <= value <= taut.BOM_REM_RANGE[1]
            else:
                assert value == 0.0
            assert params["ret_yield_rp_p"][recovered_product][product] == (1.0 if is_diagonal else 0.0)


def test_generated_transport_mode_parameters_are_correct() -> None:
    instance = _std_i17_m8_t3()
    params = instance.parameters

    for hub in (*instance.sets["AIR"], *instance.sets["PORT"]):
        assert taut.CONTRACTED_FIXED_COST_RANGE[0] <= params["f_h"][hub] <= taut.CONTRACTED_FIXED_COST_RANGE[1]

    assert instance.sets["M_RD"] == ["mrd1", "mrd2"]
    assert instance.sets["M_A"] == ["ma1", "ma2"]
    assert instance.sets["M_S"] == ["ms1", "ms2"]
    assert instance.sets["M"] == list(DEFAULT_TRANSPORT_MODES)
    assert params["mode_family_m"] == {
        **{mode: "truck" for mode in instance.sets["M_RD"]},
        **{mode: "air" for mode in instance.sets["M_A"]},
        **{mode: "sea" for mode in instance.sets["M_S"]},
    }
    for mode in instance.sets["M"]:
        family = params["mode_family_m"][mode]
        if family == "truck":
            assert params["c_handle_m"][mode] == 0.0
            assert params["c_trip_m"][mode] == round(params["c_ship_m"][mode] * params["bar_X_m"][mode], 6)
            assert params["road_return_factor_m"][mode] == taut.TRUCK_RETURN_DISTANCE_FACTOR
            assert params["speed_km_h_m"][mode] == taut.TRUCK_SPEED_KM_H
            assert params["max_driving_hours_m"][mode] == taut.MAX_DRIVING_HOURS_PER_PERIOD
        else:
            assert taut.HUB_HANDLING_COST_RANGE[0] <= params["c_handle_m"][mode] <= taut.HUB_HANDLING_COST_RANGE[1]
            assert params["c_trip_m"][mode] == 0.0
            assert params["road_return_factor_m"][mode] == 1.0


def test_generated_technology_capacity_and_emission_ranges() -> None:
    instance = _std_i17_m8_t3()
    params = instance.parameters

    for technology in instance.sets["G"]:
        assert params["pcmin_g"][technology] == round(
            taut.TECH_MIN_CAPACITY_FRAC * params["bar_p_g"][technology], 2,
        )
        assert taut.PROCESS_EMISSION_RANGE_PER_KG_MASS[0] <= params["e_prod_g"][technology] <= taut.PROCESS_EMISSION_RANGE_PER_KG_MASS[1]

    for technology in instance.sets["L"]:
        assert params["pcmin_l"][technology] == round(
            taut.TECH_MIN_CAPACITY_FRAC * params["bar_q_l"][technology], 2,
        )
        assert taut.PROCESS_EMISSION_RANGE_PER_KG_MASS[0] <= params["e_rem_l"][technology] <= taut.PROCESS_EMISSION_RANGE_PER_KG_MASS[1]


def test_transport_mode_family_resolution_accepts_numbered_modes() -> None:
    assert taut.normalize_mode_family("mrd1") == "truck"
    assert taut.normalize_mode_family("mrd2") == "truck"
    assert taut.normalize_mode_family("ma1") == "air"
    assert taut.normalize_mode_family("ms1") == "sea"


def test_technology_capacity_uses_product_period_loads(monkeypatch) -> None:
    captured_loads: list[tuple[list[float], int]] = []

    def fake_sample_technology_capacity(rng, demand_loads, *, facility_count):
        captured_loads.append((list(demand_loads), facility_count))
        return 100.0 + len(captured_loads)

    monkeypatch.setattr(taut, "sample_technology_capacity", fake_sample_technology_capacity)

    instance = _generate("STD_I17_M8_T3", seed_base=19)
    params = instance.parameters
    products = instance.sets["P"]
    retailers = instance.sets["R"]
    periods = instance.sets["T"]
    factories = instance.sets["F"]

    product_demand_loads = {
        product: [
            float(sum(params["d_r_p_t"][retailer][product][period] for retailer in retailers))
            for period in periods
        ]
        for product in products
    }
    products_by_production_technology = {technology: [] for technology in instance.sets["G"]}
    for product, technology in (tuple(pair) for pair in instance.sets["H_prod"]):
        products_by_production_technology[technology].append(product)
    products_by_remanufacturing_technology = {technology: [] for technology in instance.sets["L"]}
    for product, technology in (tuple(pair) for pair in instance.sets["H_rem"]):
        products_by_remanufacturing_technology[technology].append(product)

    expected_production_calls = [
        [
            product_demand_loads[product][period_index]
            for product in products_by_production_technology[technology]
            for period_index in range(len(periods))
        ]
        for technology in instance.sets["G"]
    ]
    expected_remanufacturing_calls = [
        [
            product_demand_loads[product][period_index]
            for product in products_by_remanufacturing_technology[technology]
            for period_index in range(len(periods))
        ]
        for technology in instance.sets["L"]
    ]
    previous_aggregate_production_loads = [
        float(sum(params["d_r_p_t"][retailer][product][period] for retailer in retailers))
        for product in products
        for period in periods
    ]

    production_call_count = len(instance.sets["G"])
    remanufacturing_call_count = len(instance.sets["L"])
    assert len(captured_loads) == production_call_count + remanufacturing_call_count
    assert [call[0] for call in captured_loads[:production_call_count]] == expected_production_calls
    assert [call[0] for call in captured_loads[production_call_count:]] == expected_remanufacturing_calls
    assert all(call[0] != previous_aggregate_production_loads for call in captured_loads if len(products) > 1)
    assert all(call[1] == len(factories) for call in captured_loads)


# ---------------------------------------------------------------------------
# Technology-menu scenario builder
# ---------------------------------------------------------------------------

def test_create_technology_scenario_appends_meaningful_tradeoff_options() -> None:
    payload = _generate("STD_I17_M8_T3", seed_base=23).to_dict()
    base_sets = payload["sets"]
    base_params = payload["parameters"]
    base_production = list(base_sets["G"])
    base_remanufacturing = list(base_sets["L"])

    scenario_payload = create_technology_scenario_instance(payload).to_dict()
    scenario_sets = scenario_payload["sets"]
    scenario_params = scenario_payload["parameters"]

    InstanceData.from_dict(scenario_payload)

    assert scenario_payload["name"] == "STD_I17_M8_T3_G6_L6"
    assert scenario_sets["G"] == [*base_production, "g4", "g5", "g6"]
    assert scenario_sets["L"] == [*base_remanufacturing, "l4", "l5", "l6"]
    assert scenario_payload["metadata"]["scenario"]["name"] == DEFAULT_TECH_SCENARIO_NAME
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
    output_dir = tmp_path / "scenarios" / DEFAULT_TECH_SCENARIO_NAME
    source_dir.mkdir()

    base_instance = _generate("STD_I17_M4_T3", seed_base=29)
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


# ---------------------------------------------------------------------------
# Transport-menu scenario builder
# ---------------------------------------------------------------------------

def test_create_transport_scenario_appends_meaningful_tradeoff_options() -> None:
    payload = _generate("STD_I17_M8_T3", seed_base=31).to_dict()
    base_sets = payload["sets"]
    base_params = payload["parameters"]
    base_road_modes = list(base_sets["M_RD"])
    base_air_modes = list(base_sets["M_A"])
    base_sea_modes = list(base_sets["M_S"])

    scenario_payload = create_transport_scenario_instance(payload).to_dict()
    scenario_sets = scenario_payload["sets"]
    scenario_params = scenario_payload["parameters"]

    InstanceData.from_dict(scenario_payload)

    assert scenario_payload["name"] == "STD_I17_M8_T3_TM12"
    assert scenario_sets["M_RD"] == [*base_road_modes, "mrd3", "mrd4"]
    assert scenario_sets["M_A"] == [*base_air_modes, "ma3", "ma4"]
    assert scenario_sets["M_S"] == [*base_sea_modes, "ms3", "ms4"]
    assert scenario_sets["M"] == [*scenario_sets["M_RD"], *scenario_sets["M_A"], *scenario_sets["M_S"]]
    assert scenario_payload["metadata"]["scenario"]["name"] == DEFAULT_TRANSPORT_SCENARIO_NAME
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
        "bar_X_m", "ctmin_m", "ccamax_m", "c_ship_m", "c_trip_m", "f_mode_m", "c_handle_m",
        "road_return_factor_m", "speed_km_h_m", "max_driving_hours_m", "trip_big_m_m", "e_ship_m",
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

        # Air/sea modes carry no separate fixed cost (f_mode_m is always 0 for these families;
        # the hub access fee f_h covers it), so f_mode_m is not asserted here.
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
                scenario_params["c_ship_m"][mode] * scenario_params["bar_X_m"][mode], 6,
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
    output_dir = tmp_path / "scenarios" / DEFAULT_TRANSPORT_SCENARIO_NAME
    source_dir.mkdir()

    base_instance = _generate("STD_I17_M4_T3", seed_base=37)
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


# ---------------------------------------------------------------------------
# Multi-menu structural expansion (apply_structural_levels)
# ---------------------------------------------------------------------------

def test_all_five_menus_expanded_together() -> None:
    """S8-style: production+remanufacturing+road+sea+air all expanded must not raise."""
    payload = _generate("STD_I17_M4_T3", seed_base=0).to_dict()
    g0, l0 = len(payload["sets"]["G"]), len(payload["sets"]["L"])
    rd0, a0, s0 = (len(payload["sets"][k]) for k in ("M_RD", "M_A", "M_S"))

    out = apply_structural_levels(
        payload,
        production_technology_menu="expanded",
        remanufacturing_technology_menu="expanded",
        road_menu="expanded",
        sea_menu="expanded",
        air_menu="expanded",
    )
    InstanceData.from_dict(out)  # must validate

    assert len(out["sets"]["G"]) == g0 + 3
    assert len(out["sets"]["L"]) == l0 + 3
    assert len(out["sets"]["M_RD"]) == rd0 + 2
    assert len(out["sets"]["M_A"]) == a0 + 2
    assert len(out["sets"]["M_S"]) == s0 + 2
    assert out["sets"]["M"] == [*out["sets"]["M_RD"], *out["sets"]["M_A"], *out["sets"]["M_S"]]


def test_s1_style_partial_multi_menu() -> None:
    """S1-style: production + road + sea expanded (remanufacturing/air left at base)."""
    payload = _generate("STD_I17_M4_T3", seed_base=0).to_dict()
    g0, l0 = len(payload["sets"]["G"]), len(payload["sets"]["L"])
    rd0, a0, s0 = (len(payload["sets"][k]) for k in ("M_RD", "M_A", "M_S"))

    out = apply_structural_levels(
        payload,
        production_technology_menu="expanded",
        road_menu="expanded",
        sea_menu="expanded",
    )
    InstanceData.from_dict(out)

    assert len(out["sets"]["G"]) == g0 + 3       # production expanded
    assert len(out["sets"]["L"]) == l0           # remanufacturing untouched
    assert len(out["sets"]["M_RD"]) == rd0 + 2   # road expanded
    assert len(out["sets"]["M_S"]) == s0 + 2     # sea expanded
    assert len(out["sets"]["M_A"]) == a0         # air untouched


def test_all_base_is_noop() -> None:
    payload = _generate("STD_I17_M4_T3", seed_base=0).to_dict()
    before = (len(payload["sets"]["G"]), len(payload["sets"]["L"]),
              len(payload["sets"]["M_RD"]), len(payload["sets"]["M_A"]), len(payload["sets"]["M_S"]))
    out = apply_structural_levels(payload)  # all default "base"
    after = (len(out["sets"]["G"]), len(out["sets"]["L"]),
             len(out["sets"]["M_RD"]), len(out["sets"]["M_A"]), len(out["sets"]["M_S"]))
    assert before == after
