"""Declarative factor registry for the v2 campaign (DOE screening, levers, response curves).

Extends `tools.experiments.sensitivity.factors` (kept untouched for the v1/legacy_v1 pipeline)
with the core factor set from the v2 plan: emission-intensity and capacity factors now scale
their *remanufacturing* companion parameter too (e_rem_l, bar_q_l), and a new
`facility_area_cost` factor covers the post-Mota-alignment c_area_f/c_area_w parameters that
did not exist when the v1 registry was written. `DEFAULT_MORRIS_FACTORS` is dropped entirely —
Morris screening is not part of the v2 methodology.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from tools.experiments.sensitivity.factors import (
    CARBON_TAX_RATE_STEP,
    FactorSpec,
    _scale_param,
)

_ROUND = 6


# ---------------------------------------------------------------------------
# Factor setters (multiplier == 1.0 reproduces the baseline)
# ---------------------------------------------------------------------------

def _apply_demand(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "d_r_p_t", m)


def _apply_return_availability(params: dict[str, Any], m: float) -> None:
    for key in ("rho_r_p_t", "ret_max_frac_r_p_t", "ret_min_frac_r_p_t"):
        _scale_param(params, key, m, cap=1.0)


def _apply_emission_intensity(params: dict[str, Any], m: float) -> None:
    """Production *and* remanufacturing emission intensity (e_prod_g, e_rem_l) together."""
    _scale_param(params, "e_prod_g", m)
    _scale_param(params, "e_rem_l", m)


def _apply_scope3_emissions(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "e_raw_s_u", m)


def _apply_capacity(params: dict[str, Any], m: float) -> None:
    """Production *and* remanufacturing capacity (bar_p_g, bar_q_l) together."""
    _scale_param(params, "bar_p_g", m)
    _scale_param(params, "bar_q_l", m)


def _apply_facility_area_cost(params: dict[str, Any], m: float) -> None:
    """Facility/area installation cost (c_area_f, c_area_w) — post-Mota-alignment factor."""
    _scale_param(params, "c_area_f", m)
    _scale_param(params, "c_area_w", m)


def _apply_tax_range(params: dict[str, Any], m: float) -> None:
    base = params.get("overline_hat_tau")
    if base is None:
        return
    new_hat = max(1, int(round(float(base) * m)))
    params["overline_hat_tau"] = new_hat
    params["overline_tau"] = round(new_hat * CARBON_TAX_RATE_STEP, 4)


# ---------------------------------------------------------------------------
# Registry: the core v2 factor set (§4 of the redesigned-experiments plan)
# ---------------------------------------------------------------------------

FACTOR_REGISTRY: dict[str, FactorSpec] = {
    spec.name: spec
    for spec in (
        FactorSpec("demand", "Retailer demand (d_r_p_t)", "x baseline", 0.7, 1.3,
                   "Highest cost elasticity (~0.64) in the v1 campaign; structural driver of "
                   "network sizing.", _apply_demand),
        FactorSpec("return_availability", "Return/collection rate (ret_max_frac_r_p_t, rho_r_p_t)",
                   "x baseline", 0.5, 1.5,
                   "Governs CLSC loop closure; v1 showed a counterintuitive negative "
                   "tax-elasticity worth re-confirming post-model-change.", _apply_return_availability),
        FactorSpec("emission_intensity", "Production & remanufacturing emission intensity "
                   "(e_prod_g, e_rem_l)", "x baseline", 0.5, 1.5,
                   "Dominant emissions driver in v1 (elasticity ~0.45-0.54).", _apply_emission_intensity),
        FactorSpec("scope3_emissions", "Scope-3/supplier emission intensity (e_raw_s_u)",
                   "x baseline", 0.5, 1.5,
                   "Second-largest emissions driver in v1.", _apply_scope3_emissions),
        FactorSpec("capacity", "Production & remanufacturing capacity (bar_p_g, bar_q_l)",
                   "x baseline", 0.7, 1.3,
                   "Governs binding-constraint regime changes (facility/tech activation "
                   "thresholds).", _apply_capacity),
        FactorSpec("facility_area_cost", "Facility/area installation cost (c_area_f, c_area_w)",
                   "x baseline", 0.5, 1.5,
                   "New cost driver post-Mota-alignment (2026-06-24/25); never tested under "
                   "the new cost structure.", _apply_facility_area_cost),
        FactorSpec("tax_range", "Carbon tax upper bound (overline_hat_tau)", "x baseline",
                   0.5, 2.0,
                   "Leader's policy space; kept for frontier/robustness purposes only — not "
                   "used to report a point-estimate optimal tax (carbon-price "
                   "non-identification limitation).", _apply_tax_range),
    )
}


# The 6 continuous factors used for DOE screening/levers (Families C, D, E). Structural factors
# (technology menu breadth, transport menu breadth) are handled separately — see
# `tools.experiments.v2.design.structural` — since they add sets/parameters rather than scale
# existing ones.
CORE_CONTINUOUS_FACTORS: tuple[str, ...] = (
    "demand",
    "return_availability",
    "emission_intensity",
    "scope3_emissions",
    "capacity",
    "facility_area_cost",
)

# Factors confirmed inert/non-binding in the v1 campaign; sampled but not varied in v2 designs.
# Re-check after Phase 4 that they remain inert under the new model (RQ3/RQ6).
EXCLUDED_INERT_PARAMETERS: tuple[str, ...] = (
    "ctmin_m",
    "scmin_s_u",
    "ecmax_i",
    "i_p_n_0",
    "apu_u",
    "apu_rp",
)


def apply_levels(params: dict[str, Any], factor_names: tuple[str, ...], levels) -> None:
    """Apply a vector of multiplier levels (one per factor) to an instance params dict."""
    for name, level in zip(factor_names, levels):
        FACTOR_REGISTRY[name].apply(params, float(level))


def build_salib_problem(factor_names: tuple[str, ...]) -> dict[str, Any]:
    """SALib-style problem definition over multiplier bounds for the given factors.

    No default factor set (unlike the v1 registry's Morris default) — callers must name the
    factors explicitly. Kept for a possible future Sobol extension (see plan §5 optional tier).
    """
    specs = [FACTOR_REGISTRY[name] for name in factor_names]
    return {
        "num_vars": len(specs),
        "names": [s.name for s in specs],
        "bounds": [[s.low, s.high] for s in specs],
    }
