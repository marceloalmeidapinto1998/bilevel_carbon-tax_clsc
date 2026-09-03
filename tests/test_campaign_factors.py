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
    """The core 7-factor set must all be present; the registry may legitimately contain more
    than these 7 (see test_continuous_factors_are_subset_of_registry) -- hence subset, not
    exact-equality.
    """
    expected = {
        "demand", "return_availability", "emission_intensity",
        "scope3_emissions", "capacity", "facility_area_cost", "tax_range",
    }
    assert expected.issubset(set(FACTOR_REGISTRY))


def test_continuous_factors_are_subset_of_registry() -> None:
    for name in CONTINUOUS_FACTORS:
        assert name in FACTOR_REGISTRY, f"CONTINUOUS_FACTORS entry {name!r} missing from registry"


def test_factor_registry_specs_have_valid_bounds() -> None:
    for name, spec in FACTOR_REGISTRY.items():
        assert spec.low < spec.high, f"Factor {name!r}: low >= high"
        assert spec.low > 0.0, f"Factor {name!r}: low must be positive"


def test_apply_levels_at_baseline_leaves_numeric_params_unchanged() -> None:
    params = _minimal_params()
    original_demand = params["d_r_p_t"]["r1"]["p1"]["t1"]
    original_e_prod = params["e_prod_g"]["g1"]
    apply_levels(params, CONTINUOUS_FACTORS, [1.0] * len(CONTINUOUS_FACTORS))
    assert params["d_r_p_t"]["r1"]["p1"]["t1"] == pytest.approx(original_demand)
    assert params["e_prod_g"]["g1"] == pytest.approx(original_e_prod)


# One case per factor whose `.apply()` scales a fixed set of leaves to an exact value. Each
# entry is (factor_name, level, [(path_into_params, expected_value), ...]). Factors with a
# qualitatively different assertion shape (return_availability's cap, tax_range's paired
# int+float update) get their own test below instead of forcing them into this table.
_LEAF_SCALING_CASES = [
    ("demand", 2.0, [(("d_r_p_t", "r1", "p1", "t1"), 200.0)]),
    ("emission_intensity", 0.5, [(("e_prod_g", "g1"), 0.05), (("e_rem_l", "l1"), 0.05)]),
    ("capacity", 1.5, [(("bar_p_g", "g1"), 750.0), (("bar_q_l", "l1"), 450.0)]),
    ("facility_area_cost", 0.5, [(("c_area_f", "f1"), 500.0), (("c_area_w", "w1"), 400.0)]),
    ("transport_emission_intensity", 0.5, [(("e_ship_m", "m1"), 0.15)]),
    ("return_economics", 1.5, [(("rpc_rp", "r1", "p1"), 75.0)]),
    ("raw_material_cost", 0.5, [(("rmc_s_u", "s1", "u1"), 10.0)]),
]


@pytest.mark.parametrize("factor, level, expected", _LEAF_SCALING_CASES, ids=[c[0] for c in _LEAF_SCALING_CASES])
def test_apply_levels_scales_the_expected_leaves(factor, level, expected) -> None:
    params = _minimal_params()
    apply_levels(params, (factor,), [level])
    for path, value in expected:
        node = params
        for key in path:
            node = node[key]
        assert node == pytest.approx(value), path


def test_apply_levels_return_availability_is_capped_at_one() -> None:
    params = _minimal_params()
    apply_levels(params, ("return_availability",), [3.0])
    assert params["rho_r_p_t"]["r1"]["p1"]["t1"] <= 1.0
    assert params["ret_max_frac_r_p_t"]["r1"]["p1"]["t1"] <= 1.0
    assert params["ret_min_frac_r_p_t"]["r1"]["p1"]["t1"] <= 1.0


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
