from __future__ import annotations

import pytest

from clsc.campaign.factors import (
    CONTINUOUS_FACTORS,
    FACTOR_REGISTRY,
    apply_levels,
    build_salib_problem,
)


def _minimal_params() -> dict:
    """Synthetic params dict with a key for every leaf that any v2 factor touches."""
    return {
        "d_r_p_t": {"r1": {"p1": {"t1": 100.0}}},
        "rho_r_p_t": {"r1": {"p1": {"t1": 0.5}}},
        "ret_max_frac_r_p_t": {"r1": {"p1": {"t1": 0.5}}},
        "ret_min_frac_r_p_t": {"r1": {"p1": {"t1": 0.2}}},
        "e_prod_g": {"g1": 0.1},
        "e_rem_l": {"l1": 0.1},
        "e_raw_s_u": {"s1": {"u1": 0.2}},
        "bar_p_g": {"g1": 500.0},
        "bar_q_l": {"l1": 300.0},
        "c_area_f": {"f1": 1000.0},
        "c_area_w": {"w1": 800.0},
        "overline_tax_index": 20,
        "overline_tau": 0.2,
        "e_ship_m": {"m1": 0.3},
        "rpc_rp": {"r1": {"p1": 50.0}},
        "rmc_s_u": {"s1": {"u1": 20.0}},
    }


def test_factor_registry_contains_expected_factors() -> None:
    """The core 7-factor set must all be present; the registry is shared with the campaign
    (see test_campaign_02_continuous_factors_are_subset_of_registry below), so it may
    legitimately contain more than these 7 -- hence subset, not exact-equality.
    """
    expected = {
        "demand", "return_availability", "emission_intensity",
        "scope3_emissions", "capacity", "facility_area_cost", "tax_range",
    }
    assert expected.issubset(set(FACTOR_REGISTRY))


def test_campaign_02_continuous_factors_are_subset_of_registry() -> None:
    for name in CONTINUOUS_FACTORS:
        assert name in FACTOR_REGISTRY, f"campaign_02 factor {name!r} missing from registry"


def test_factor_registry_specs_have_valid_bounds() -> None:
    for name, spec in FACTOR_REGISTRY.items():
        assert spec.low < spec.high, f"Factor {name!r}: low >= high"
        assert spec.low > 0.0, f"Factor {name!r}: low must be positive"


def test_core_continuous_factors_are_subset_of_registry() -> None:
    for name in CONTINUOUS_FACTORS:
        assert name in FACTOR_REGISTRY, f"CORE factor {name!r} missing from registry"


def test_apply_levels_at_baseline_leaves_numeric_params_unchanged() -> None:
    params = _minimal_params()
    original_demand = params["d_r_p_t"]["r1"]["p1"]["t1"]
    original_e_prod = params["e_prod_g"]["g1"]
    apply_levels(params, CONTINUOUS_FACTORS, [1.0] * len(CONTINUOUS_FACTORS))
    assert params["d_r_p_t"]["r1"]["p1"]["t1"] == pytest.approx(original_demand)
    assert params["e_prod_g"]["g1"] == pytest.approx(original_e_prod)


def test_apply_levels_demand_scales_leaf_values() -> None:
    params = _minimal_params()
    apply_levels(params, ("demand",), [2.0])
    assert params["d_r_p_t"]["r1"]["p1"]["t1"] == pytest.approx(200.0)


def test_apply_levels_emission_intensity_scales_both_prod_and_rem() -> None:
    params = _minimal_params()
    apply_levels(params, ("emission_intensity",), [0.5])
    assert params["e_prod_g"]["g1"] == pytest.approx(0.05)
    assert params["e_rem_l"]["l1"] == pytest.approx(0.05)


def test_apply_levels_capacity_scales_both_prod_and_rem() -> None:
    params = _minimal_params()
    apply_levels(params, ("capacity",), [1.5])
    assert params["bar_p_g"]["g1"] == pytest.approx(750.0)
    assert params["bar_q_l"]["l1"] == pytest.approx(450.0)


def test_apply_levels_facility_area_cost_scales_both_f_and_w() -> None:
    params = _minimal_params()
    apply_levels(params, ("facility_area_cost",), [0.5])
    assert params["c_area_f"]["f1"] == pytest.approx(500.0)
    assert params["c_area_w"]["w1"] == pytest.approx(400.0)


def test_apply_levels_return_availability_is_capped_at_one() -> None:
    params = _minimal_params()
    apply_levels(params, ("return_availability",), [3.0])
    assert params["rho_r_p_t"]["r1"]["p1"]["t1"] <= 1.0
    assert params["ret_max_frac_r_p_t"]["r1"]["p1"]["t1"] <= 1.0
    assert params["ret_min_frac_r_p_t"]["r1"]["p1"]["t1"] <= 1.0


def test_apply_levels_transport_emission_intensity_scales_e_ship_m() -> None:
    params = _minimal_params()
    apply_levels(params, ("transport_emission_intensity",), [0.5])
    assert params["e_ship_m"]["m1"] == pytest.approx(0.15)


def test_apply_levels_return_economics_scales_rpc_rp() -> None:
    params = _minimal_params()
    apply_levels(params, ("return_economics",), [1.5])
    assert params["rpc_rp"]["r1"]["p1"] == pytest.approx(75.0)


def test_apply_levels_raw_material_cost_scales_rmc_s_u() -> None:
    params = _minimal_params()
    apply_levels(params, ("raw_material_cost",), [0.5])
    assert params["rmc_s_u"]["s1"]["u1"] == pytest.approx(10.0)


def test_apply_levels_tax_range_updates_tax_index_and_tau_together() -> None:
    params = _minimal_params()
    apply_levels(params, ("tax_range",), [2.0])
    assert params["overline_tax_index"] == 40
    assert params["overline_tau"] == pytest.approx(0.4)


def test_build_salib_problem_has_correct_shape() -> None:
    problem = build_salib_problem(CONTINUOUS_FACTORS)
    n = len(CONTINUOUS_FACTORS)
    assert problem["num_vars"] == n
    assert len(problem["names"]) == n
    assert len(problem["bounds"]) == n


def test_build_salib_problem_bounds_match_registry() -> None:
    problem = build_salib_problem(CONTINUOUS_FACTORS)
    for name, (low, high) in zip(problem["names"], problem["bounds"]):
        spec = FACTOR_REGISTRY[name]
        assert low == spec.low
        assert high == spec.high
