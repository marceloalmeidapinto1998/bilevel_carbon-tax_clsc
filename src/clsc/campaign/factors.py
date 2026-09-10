"""Continuous factor registry for campaign_01 (Experiment 4 sensitivity/robustness screening).

Each factor is a multiplier applied to one or more instance parameters; multiplier == 1.0
reproduces the baseline. Emission-intensity and capacity factors scale their remanufacturing
companion parameters too (e_rem_l, bar_q_l). Parameter keys and caps reproduce the validated,
Mota-aligned model semantics (see the model-consistency notes) — the golden fixtures pin this.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from clsc.models.instance import SCALE_FACTOR

_ROUND = 6


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
    params["overline_tax_rate"] = round(new_hat * SCALE_FACTOR, 4)


def _apply_transport_emission_intensity(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "e_ship_m", m)


def _apply_return_economics(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "rpc_rp", m)


def _apply_raw_material_cost(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "rmc_s_u", m)


FACTOR_REGISTRY: dict[str, FactorSpec] = {
    spec.name: spec
    for spec in (
        FactorSpec("demand", "Retailer demand (d_r_p_t)", "x baseline", 0.7, 1.3,
                   "Structural driver of network sizing; highest cost elasticity.", _apply_demand),
        FactorSpec("return_availability", "Return/collection rate (ret_max_frac_r_p_t, rho_r_p_t)",
                   "x baseline", 0.5, 1.5,
                   "Governs CLSC loop closure (physical-supply side).", _apply_return_availability),
        FactorSpec("emission_intensity", "Production & remanufacturing emission intensity "
                   "(e_prod_g, e_rem_l)", "x baseline", 0.5, 1.5,
                   "Dominant emissions driver.", _apply_emission_intensity),
        FactorSpec("scope3_emissions", "Scope-3/supplier emission intensity (e_raw_s_u)",
                   "x baseline", 0.5, 1.5,
                   "Second-largest emissions driver.", _apply_scope3_emissions),
        FactorSpec("capacity", "Production & remanufacturing capacity (bar_p_g, bar_q_l)",
                   "x baseline", 0.7, 1.3,
                   "Governs binding-constraint regime changes.", _apply_capacity),
        FactorSpec("facility_area_cost", "Facility/area installation cost (c_area_f, c_area_w)",
                   "x baseline", 0.5, 1.5,
                   "Cost driver post-Mota-alignment.", _apply_facility_area_cost),
        FactorSpec("tax_range", "Carbon tax upper bound (overline_tax_index)", "x baseline",
                   0.5, 2.0,
                   "Leader's policy space; frontier/robustness use only.", _apply_tax_range),
        FactorSpec("transport_emission_intensity", "Transport emission intensity (e_ship_m)",
                   "x baseline", 0.5, 1.5,
                   "Completes the production/scope-3/transport emissions triad.",
                   _apply_transport_emission_intensity),
        FactorSpec("return_economics", "Recovered-item acquisition cost (rpc_rp)",
                   "x baseline", 0.5, 1.5,
                   "Economic incentive to close the loop.", _apply_return_economics),
        FactorSpec("raw_material_cost", "Virgin raw-material cost (rmc_s_u)",
                   "x baseline", 0.5, 1.5,
                   "Virgin-sourcing economics, symmetric to return_economics.",
                   _apply_raw_material_cost),
    )
}

# The 8 continuous factors screened in Experiment 4 (docs/Experimental_Plan.md §6). Structural
# menu-breadth factors are handled separately (see clsc.campaign.structural) since they add
# sets/parameters rather than scale existing ones.
CONTINUOUS_FACTORS: tuple[str, ...] = (
    "demand",
    "return_availability",
    "capacity",
    "emission_intensity",
    "scope3_emissions",
    "transport_emission_intensity",
    "return_economics",
    "raw_material_cost",
)


def apply_levels(params: dict[str, Any], factor_names: tuple[str, ...], levels) -> None:
    """Apply a vector of multiplier levels (one per factor) to an instance params dict."""
    for name, level in zip(factor_names, levels):
        FACTOR_REGISTRY[name].apply(params, float(level))


def build_salib_problem(factor_names: tuple[str, ...]) -> dict[str, Any]:
    """SALib-style problem definition over multiplier bounds for the given factors."""
    specs = [FACTOR_REGISTRY[name] for name in factor_names]
    return {
        "num_vars": len(specs),
        "names": [s.name for s in specs],
        "bounds": [[s.low, s.high] for s in specs],
    }
