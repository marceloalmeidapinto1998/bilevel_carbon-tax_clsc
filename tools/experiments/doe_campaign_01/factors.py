"""Declarative factor registry for doe_campaign_01 (DOE screening, levers, response curves).

Covers the 7-factor set from the redesigned campaign plan: emission-intensity and capacity
factors scale their remanufacturing companion parameters too (e_rem_l, bar_q_l), and
`facility_area_cost` covers the post-Mota-alignment c_area_f/c_area_w parameters.
Morris screening is not part of the doe_campaign_01 methodology.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.models.instance import SCALE_FACTOR

_ROUND = 6


# ---------------------------------------------------------------------------
# In-place scaling helpers
# ---------------------------------------------------------------------------

def _scale_tree(obj: dict[str, Any], multiplier: float, *, cap: float | None = None) -> None:
    """Recursively scale every numeric leaf of a (possibly nested) dict in place."""
    for key, value in obj.items():
        if isinstance(value, dict):
            _scale_tree(value, multiplier, cap=cap)
        else:
            scaled = value * multiplier
            if cap is not None:
                scaled = min(scaled, cap)
            obj[key] = round(scaled, _ROUND)


def _scale_param(params: dict[str, Any], key: str, multiplier: float, *, cap: float | None = None) -> None:
    target = params.get(key)
    if isinstance(target, dict):
        _scale_tree(target, multiplier, cap=cap)


@dataclass(frozen=True, slots=True)
class FactorSpec:
    name: str
    label: str
    units: str
    low: float
    high: float
    rationale: str
    apply: Callable[[dict[str, Any], float], None]
    baseline: float = 1.0


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
    base = params.get("overline_tax_index")
    if base is None:
        return
    new_hat = max(1, int(round(float(base) * m)))
    params["overline_tax_index"] = new_hat
    params["overline_tau"] = round(new_hat * SCALE_FACTOR, 4)


def _apply_transport_emission_intensity(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "e_ship_m", m)


def _apply_return_economics(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "rpc_rp", m)


def _apply_raw_material_cost(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "rmc_s_u", m)


# ---------------------------------------------------------------------------
# Registry: the core doe_campaign_01 factor set (§4 of the redesigned-experiments plan)
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
        FactorSpec("tax_range", "Carbon tax upper bound (overline_tax_index)", "x baseline",
                   0.5, 2.0,
                   "Leader's policy space; kept for frontier/robustness purposes only — not "
                   "used to report a point-estimate optimal tax (carbon-price "
                   "non-identification limitation).", _apply_tax_range),
        # Added for doe_campaign_02's finalized 8-factor continuous set (EXPERIMENTAL_PLAN.md §5.1).
        FactorSpec("transport_emission_intensity", "Transport emission intensity (e_ship_m)",
                   "x baseline", 0.5, 1.5,
                   "Emissions per unit-distance transported; completes the "
                   "production/scope-3/transport emissions triad.", _apply_transport_emission_intensity),
        FactorSpec("return_economics", "Recovered-item acquisition cost (rpc_rp)",
                   "x baseline", 0.5, 1.5,
                   "Economic incentive to close the loop, complementing return_availability "
                   "(the physical-supply side).", _apply_return_economics),
        FactorSpec("raw_material_cost", "Virgin raw-material cost (rmc_s_u)",
                   "x baseline", 0.5, 1.5,
                   "Virgin-sourcing economics, symmetric to return_economics; together they "
                   "test whether the tax shifts sourcing between virgin and recovered inputs.",
                   _apply_raw_material_cost),
    )
}


# The 5 continuous factors used for DOE screening/levers (Families C, D, E). Structural factors
# (technology menu breadth, transport menu breadth) are handled separately — see
# `tools.experiments.doe_campaign_01.design.structural` — since they add sets/parameters rather than scale
# existing ones.
#
# `facility_area_cost` was dropped from the screened set on 2026-07-01 (still defined in
# FACTOR_REGISTRY below and independently testable/usable via `apply_levels`, just excluded from
# the DOE factor set) at the user's request.
CORE_CONTINUOUS_FACTORS: tuple[str, ...] = (
    "demand",
    "return_availability",
    "emission_intensity",
    "scope3_emissions",
    "capacity",
)

# doe_campaign_02's finalized 8-factor continuous set (EXPERIMENTAL_PLAN.md §5.1, Family C).
# Distinct from CORE_CONTINUOUS_FACTORS (doe_campaign_01's already-executed 5-factor set, left
# untouched above) — do not conflate the two across campaigns.
CAMPAIGN_02_CONTINUOUS_FACTORS: tuple[str, ...] = (
    "demand",
    "return_availability",
    "capacity",
    "emission_intensity",
    "scope3_emissions",
    "transport_emission_intensity",
    "return_economics",
    "raw_material_cost",
)

# Factors confirmed inert/non-binding in the v1 campaign; sampled but not varied in doe_campaign_01 designs.
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
