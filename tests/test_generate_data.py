from __future__ import annotations

import json

import pytest

from data.generator import tautenhain_data as taut
from data.generator import (
    DEFAULT_AIRPLANES,
    DEFAULT_BOATS,
    DEFAULT_TRUCKS,
    DEFAULT_TRANSPORT_MODES,
    apply_prefix_override,
    build_base_benchmark_specs,
    generate_benchmark,
    generate_instance,
)


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
    spec = next(item for item in build_base_benchmark_specs(seed_base=3) if item.name == "STD_I17_M4_T3")
    base_instance = generate_instance(spec.to_config())

    assert apply_prefix_override(base_instance, "STD").parameters == base_instance.parameters


def test_generated_initial_product_inventory_is_zero_for_all_nodes() -> None:
    spec = next(item for item in build_base_benchmark_specs(seed_base=7) if item.name == "STD_I17_M4_T3")
    instance = generate_instance(spec.to_config())

    initial_inventory = instance.parameters["i_p_n_0"]
    assert all(
        value == 0.0
        for product_inventory in initial_inventory.values()
        for value in product_inventory.values()
    )


def test_generated_parameters_follow_tautenhain_bom_capacity_and_stock_structures() -> None:
    spec = next(item for item in build_base_benchmark_specs(seed_base=13) if item.name == "STD_I17_M8_T3")
    instance = generate_instance(spec.to_config())
    params = instance.parameters

    assert "a_in_u_p_g" in params
    assert "a_in_u_p" not in params
    assert "bar_s_s_u" in params
    assert "f_s" in params
    assert "h_p" in params
    assert "bom_rem_r_p" in params
    assert "icmax_p_n" in params
    assert "icmin_p_n" in params
    assert "pcmin_g" in params
    assert "pcmin_l" in params
    assert "scmin_s_u" in params
    assert "rmc_s_u" in params
    assert "rpc_rp" in params
    assert "ret_yield_rp_p" in params
    assert "theta_p" in params
    assert "c_handle_m" in params
    assert "c_trip_m" in params
    assert "f_h" in params
    assert "ret_min_frac_r_p_t" in params
    assert "ret_max_frac_r_p_t" in params
    assert "road_return_factor_m" in params
    assert "speed_km_h_m" in params
    assert "max_driving_hours_m" in params
    assert "truck_investment_budget" in params
    assert "trip_big_m_m" in params
    assert "e_raw_s_u" in params
    assert "c_area_f" in params
    assert "c_area_w" in params
    assert "Amin_f" in params
    assert "Amin_w" in params
    assert "apu_u" in params
    assert "apu_p" in params
    assert "apur_p" in params
    assert "apu_rp" in params
    assert "apu_q" in params
    assert not {
        "bar_i_f",
        "bar_i_r",
        "bar_i_w",
        "bar_s_s",
        "bom_rem_p",
        "bom_rem_r",
        "d_fw",
        "d_rf",
        "d_sf",
        "d_wr",
        "eta_p",
        "h_f",
        "h_r",
        "h_w",
        "psu_p",
        "rp_of_p",
        "rpc_p",
    }.intersection(params)
    assert "H_prod" in instance.sets
    assert "H_rem" in instance.sets
    assert "AIR" in instance.sets
    assert "PORT" in instance.sets
    assert "RP" in instance.sets
    assert "FLOW_RAW" in instance.sets
    assert "FLOW_FP" in instance.sets
    assert "FLOW_RP" in instance.sets
    assert instance.sets["N"] == [
        *instance.sets["S"],
        *instance.sets["F"],
        *instance.sets["W"],
        *instance.sets["R"],
        *instance.sets["AIR"],
        *instance.sets["PORT"],
    ]
    assert instance.sets["V"] == instance.sets["W"]
    assert instance.sets["K"] == instance.sets["RP"]
    assert instance.metadata["carbon_tax_units"] == {
        "underline_tau_overline_tau": "USD/kg CO2e",
        "hat_tau_step": "0.01 USD/kg CO2e",
        "tau_formula_usd_per_kg_co2e": "0.01 * hat_tau",
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
    for node, coordinate in instance.metadata["node_coordinates"].items():
        assert set(coordinate) == {"x", "y"}
        assert 0.0 <= coordinate["x"] <= instance.metadata["config"]["coordinate_span_km"]
        assert 0.0 <= coordinate["y"] <= instance.metadata["config"]["coordinate_span_km"]

    production_pairs = {tuple(pair) for pair in instance.sets["H_prod"]}

    for material in instance.sets["U"]:
        for product in instance.sets["P"]:
            for technology in instance.sets["G"]:
                value = params["a_in_u_p_g"][material][product][technology]
                if (product, technology) in production_pairs:
                    assert taut.BOM_PROD_RANGE[0] <= value <= taut.BOM_PROD_RANGE[1]
                else:
                    assert value == 0.0

    for supplier in instance.sets["S"]:
        assert taut.SUPPLIER_SELECTION_FIXED_COST_RANGE[0] <= params["f_s"][supplier] <= taut.SUPPLIER_SELECTION_FIXED_COST_RANGE[1]
        for material in instance.sets["U"]:
            assert 0.0 <= params["scmin_s_u"][supplier][material] <= params["bar_s_s_u"][supplier][material]
            assert taut.RAW_MATERIAL_COST_RANGE[0] <= params["rmc_s_u"][supplier][material] <= taut.RAW_MATERIAL_COST_RANGE[1]
            assert taut.RAW_AREA_RANGE[0] <= params["apu_u"][material] <= taut.RAW_AREA_RANGE[1]
            assert params["apu_q"][material] == params["apu_u"][material]

    assert "f_f" not in params
    assert "f_w" not in params
    assert "e_open_s" not in params
    assert "h_rp" not in params
    assert "icmax_rp_n" not in params
    assert "icmin_rp_n" not in params
    assert "i_rp_n_0" not in params

    for factory in instance.sets["F"]:
        assert taut.AREA_INSTALLATION_COST_RANGE[0] <= params["c_area_f"][factory] <= taut.AREA_INSTALLATION_COST_RANGE[1]
        assert taut.FACTORY_AREA_MIN_RANGE[0] <= params["Amin_f"][factory] <= taut.FACTORY_AREA_MIN_RANGE[1]
        assert params["Amin_f"][factory] <= params["A_f"][factory]

    for warehouse in instance.sets["W"]:
        assert taut.AREA_INSTALLATION_COST_RANGE[0] <= params["c_area_w"][warehouse] <= taut.AREA_INSTALLATION_COST_RANGE[1]
        assert taut.WAREHOUSE_AREA_MIN_RANGE[0] <= params["Amin_w"][warehouse] <= taut.WAREHOUSE_AREA_MIN_RANGE[1]
        assert params["Amin_w"][warehouse] <= params["A_w"][warehouse]

    for product in instance.sets["P"]:
        assert taut.RETURN_LAG_RANGE[0] <= params["theta_p"][product] <= min(taut.RETURN_LAG_RANGE[1], len(instance.sets["T"]))
        assert params["h_p"][product] == round(taut.STOCK_COST_BASE + params["omega_p"][product], 4)
        for retailer in instance.sets["R"]:
            for period in instance.sets["T"]:
                assert 0.0 <= params["ret_min_frac_r_p_t"][retailer][product][period] <= params["ret_max_frac_r_p_t"][retailer][product][period]
                assert params["rho_r_p_t"][retailer][product][period] == params["ret_max_frac_r_p_t"][retailer][product][period]
        for node in instance.sets["V"]:
            assert params["icmin_p_n"][product][node] == round(
                taut.INVENTORY_FRAC_MIN * params["icmax_p_n"][product][node],
                2,
            )
        assert params["apu_p"][product] > 0.0
        assert params["apu_q"][product] == params["apu_p"][product]
        assert params["apur_p"][product] == pytest.approx(
            round(params["apu_p"][product] / taut.PRODUCT_ROTATION_PER_PERIOD, 6)
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
            # bom_rem_r_p is diagonal by construction (rp_i is the recovered form of p_i, same
            # positional correspondence as ret_yield_rp_p below): a dense sample here let the
            # factory-level recovered-product balance equation pick up an unrelated product's
            # remanufacturing throughput, producing a ~50% network-flow infeasibility rate for
            # multi-product (M8) instances. Confirmed via Gurobi IIS, 2026-06-26.
            if is_diagonal:
                assert taut.BOM_REM_RANGE[0] <= value <= taut.BOM_REM_RANGE[1]
            else:
                assert value == 0.0
            expected_yield = 1.0 if is_diagonal else 0.0
            assert params["ret_yield_rp_p"][recovered_product][product] == expected_yield

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

    for technology in instance.sets["G"]:
        assert params["pcmin_g"][technology] == round(
            taut.TECH_MIN_CAPACITY_FRAC * params["bar_p_g"][technology],
            2,
        )
        assert (
            taut.PROCESS_EMISSION_RANGE_PER_KG_MASS[0]
            <= params["e_prod_g"][technology]
            <= taut.PROCESS_EMISSION_RANGE_PER_KG_MASS[1]
        )
    for technology in instance.sets["L"]:
        assert params["pcmin_l"][technology] == round(
            taut.TECH_MIN_CAPACITY_FRAC * params["bar_q_l"][technology],
            2,
        )
        assert (
            taut.PROCESS_EMISSION_RANGE_PER_KG_MASS[0]
            <= params["e_rem_l"][technology]
            <= taut.PROCESS_EMISSION_RANGE_PER_KG_MASS[1]
        )


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

    spec = next(item for item in build_base_benchmark_specs(seed_base=19) if item.name == "STD_I17_M8_T3")
    instance = generate_instance(
        spec.to_config()
    )
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


def test_generate_benchmark_writes_expected_base_counts(tmp_path) -> None:
    summary = generate_benchmark(tmp_path, seed_base=5, file_format="json")

    assert summary.base_specs == 12
    assert summary.base_instances == 12

    base_files = sorted(tmp_path.glob("*.json"))

    assert len(base_files) == 12
    assert not (tmp_path / "scenarios").exists()

    sample_base = json.loads((tmp_path / "STD_I17_M4_T3.json").read_text(encoding="utf-8"))

    assert sample_base["name"] == "STD_I17_M4_T3"
