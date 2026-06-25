"""Declarative factor registry for global sensitivity designs (Morris).

This is the single source of truth for *how* a named model factor is perturbed and over
*what* range. Each ``FactorSpec`` exposes ``apply(params, multiplier)`` which scales the
relevant baseline parameter(s) of an instance ``parameters`` dict in place, where
``multiplier == 1.0`` reproduces the baseline. Multipliers give a natural elasticity
interpretation: ``rel_input_change = multiplier - 1``.

Design rationale
----------------
The legacy one-at-a-time (OAT) mutations in ``sensitivity_analyses.py`` use heterogeneous,
non-normalized perturbations (mixed ``x0.5``/``x1.15``/absolute replacements and per-mutation
rounding). They are deliberately left untouched here so existing instances regenerate with
identical *parameters*. The setters below encode the same scaling logic in a *normalized*,
parameterized form (uniform 6-dp rounding) so that Morris screening draws on one consistent
definition of each factor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# Tax index step (USD/kg CO2e per integer hat_tau); mirrors instance_loader.CARBON_TAX_SCALE
# and generate_data.CARBON_TAX_RATE_STEP.
CARBON_TAX_RATE_STEP = 0.01
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


# ---------------------------------------------------------------------------
# Factor setters (multiplier == 1.0 reproduces the baseline)
# ---------------------------------------------------------------------------

def _apply_demand(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "d_r_p_t", m)


def _apply_return_processing_cost(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "rpc_rp", m)


def _apply_bom_ratio(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "bom_rem_r_p", m)


def _apply_production_capacity(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "bar_p_g", m)


def _apply_return_availability(params: dict[str, Any], m: float) -> None:
    # Return fractions are bounded by 1.0; rho/min/max are scaled together and capped.
    for key in ("rho_r_p_t", "ret_max_frac_r_p_t", "ret_min_frac_r_p_t"):
        _scale_param(params, key, m, cap=1.0)


def _apply_production_emissions(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "e_prod_g", m)


def _apply_scope3_emissions(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "e_raw_s_u", m)


def _apply_transport_cost(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "c_ship_m", m)


def _apply_production_cost(params: dict[str, Any], m: float) -> None:
    _scale_param(params, "c_prod_g", m)


def _apply_tax_range(params: dict[str, Any], m: float) -> None:
    # Scale the upper carbon-tax bound, keeping hat_tau integral and tau consistent.
    base = params.get("overline_hat_tau")
    if base is None:
        return
    new_hat = max(1, int(round(float(base) * m)))
    params["overline_hat_tau"] = new_hat
    params["overline_tau"] = round(new_hat * CARBON_TAX_RATE_STEP, 4)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FactorSpec:
    name: str                                   # canonical factor key
    label: str                                  # human-readable label
    units: str
    low: float                                  # low multiplier bound
    high: float                                 # high multiplier bound
    rationale: str
    apply: Callable[[dict[str, Any], float], None]
    baseline: float = 1.0                       # nominal multiplier reproducing baseline


FACTOR_REGISTRY: dict[str, FactorSpec] = {
    spec.name: spec
    for spec in (
        FactorSpec("demand", "Retailer demand", "x baseline", 0.7, 1.3,
                   "Demand uncertainty; scales all throughput and emissions.", _apply_demand),
        FactorSpec("return_processing_cost", "Return processing cost (rpc_rp)", "x baseline",
                   0.1, 1.5, "Reverse-logistics cost; primary CLSC loop-closure lever.",
                   _apply_return_processing_cost),
        FactorSpec("bom_ratio", "Remanufacturing BOM ratio", "x baseline", 0.2, 1.2,
                   "Recovered-units per remanufactured unit; loop efficiency.", _apply_bom_ratio),
        FactorSpec("production_capacity", "Production capacity (bar_p_g)", "x baseline",
                   0.7, 1.3, "Capacity tightness; can force network/technology switching.",
                   _apply_production_capacity),
        FactorSpec("return_availability", "Return availability (rho/ret_*_frac)", "x baseline",
                   0.5, 1.5, "Collectable volume (EPR / consumer participation).",
                   _apply_return_availability),
        FactorSpec("production_emissions", "Production emission intensity (e_prod_g)", "x baseline",
                   0.5, 1.5, "Process decarbonisation; shifts the cost-emissions trade-off.",
                   _apply_production_emissions),
        FactorSpec("scope3_emissions", "Upstream/scope-3 intensity (e_raw_s_u)", "x baseline",
                   0.5, 1.5, "Upstream decarbonisation; weakly identified empirically.",
                   _apply_scope3_emissions),
        FactorSpec("transport_cost", "Transport cost (c_ship_m)", "x baseline", 0.5, 1.5,
                   "Logistics cost; drives facility-location economics.", _apply_transport_cost),
        FactorSpec("production_cost", "Production cost (c_prod_g)", "x baseline", 0.5, 1.5,
                   "Forward production cost.",
                   _apply_production_cost),
        FactorSpec("tax_range", "Carbon tax upper bound (overline_hat_tau)", "x baseline",
                   0.5, 2.0, "Leader's policy space; tests tax-range censoring.", _apply_tax_range),
    )
}


# Default factor set for Morris screening (order is stable for SALib problem definitions).
DEFAULT_MORRIS_FACTORS: tuple[str, ...] = (
    "demand",
    "return_processing_cost",
    "bom_ratio",
    "production_capacity",
    "return_availability",
    "production_emissions",
    "scope3_emissions",
    "transport_cost",
    "tax_range",
)


def build_salib_problem(factor_names: tuple[str, ...] = DEFAULT_MORRIS_FACTORS) -> dict[str, Any]:
    """SALib-style problem definition over multiplier bounds for the given factors."""
    specs = [FACTOR_REGISTRY[name] for name in factor_names]
    return {
        "num_vars": len(specs),
        "names": [s.name for s in specs],
        "bounds": [[s.low, s.high] for s in specs],
    }


def apply_levels(params: dict[str, Any], factor_names: tuple[str, ...], levels) -> None:
    """Apply a vector of multiplier levels (one per factor) to an instance params dict."""
    for name, level in zip(factor_names, levels):
        FACTOR_REGISTRY[name].apply(params, float(level))
