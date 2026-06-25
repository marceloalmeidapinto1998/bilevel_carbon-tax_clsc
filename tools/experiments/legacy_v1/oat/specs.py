"""OAT sensitivity catalogue: perturbation specs, parameter mutations, normalization metadata.

Each ``SensitivitySpec`` names a one-parameter perturbation of a base instance, with the
machine-readable ``factor``/``kind``/``multiplier``/``perturbed_value``/``baseline_path`` needed to
compute a comparable elasticity downstream. The actual parameter mutations live in
``MUTATION_FUNCTIONS`` (registered by code) and are applied verbatim — perturbation magnitudes are
preserved exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class SensitivitySpec:
    code: str
    label: str
    description: str
    priority: str
    dimension: str
    parameters_changed: tuple[str, ...]
    # --- normalization metadata (for elasticity reporting) ---
    factor: str = ""                          # canonical factor name
    kind: str = "scaling"                     # "scaling" | "absolute" | "structural"
    multiplier: float | None = None           # for kind == "scaling"
    perturbed_value: float | None = None      # for kind == "absolute"
    baseline_path: tuple[str, ...] | None = None  # dotted path to the scalar baseline

    def rel_input_change(self, base_params: dict[str, Any] | None = None) -> float | None:
        """Relative change of the perturbed input vs its baseline value.

        Returns ``(perturbed - baseline) / baseline`` so a downstream elasticity is
        ``pct_output_change / (100 * rel_input_change)``. ``None`` for structural
        perturbations (no single scalar input change) or a zero/absent baseline.
        """
        if self.kind == "scaling" and self.multiplier is not None:
            return self.multiplier - 1.0
        if (
            self.kind == "absolute"
            and self.perturbed_value is not None
            and self.baseline_path
            and base_params is not None
        ):
            node: Any = base_params
            for key in self.baseline_path:
                if not isinstance(node, dict) or key not in node:
                    return None
                node = node[key]
            if not isinstance(node, (int, float)) or node == 0:
                return None
            return (self.perturbed_value - node) / node
        return None


# ---------------------------------------------------------------------------
# Mutation registry
# ---------------------------------------------------------------------------

MUTATION_FUNCTIONS: dict[str, Callable[[dict[str, Any]], None]] = {}


LEGACY_CODE_ALIASES: dict[str, str] = {
    "RPC_2": "return_processing_cost_usd002",
    "RPC_5": "return_processing_cost_usd005",
    "BOM_1": "bom_ratio_v001",
    "BOM_2": "bom_ratio_v002",
    "CAP70": "production_capacity_x070",
    "DEM115": "demand_x115",
    "DEM130": "demand_x130",
    "RETFREE": "min_return_zero",
    "TAX40": "tax_range_max040",
    "TAX80": "tax_range_max080",
    "EMITEQ_MEAN": "supplier_emissions_mean",
    "AIR50": "air_sea_cost_x050",
    "TRUCK70": "truck_capacity_x070",
    "RET50": "return_availability_x050",
    "RET200": "return_availability_x200",
    "RPC0": "return_processing_cost_usd000",
    "SCOPE3_50": "scope3_emissions_x050",
    "PROD_CLEAN": "production_emissions_x050",
}


def canonical_code(code: str) -> str:
    return LEGACY_CODE_ALIASES.get(code, code)


def _register(code: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        MUTATION_FUNCTIONS[code] = fn
        return fn
    return decorator


# High priority — return processing cost

@_register("return_processing_cost_usd002")
def _(params: dict[str, Any]) -> None:
    """Set return processing cost to $2.00/unit (was $16.15)."""
    params["rpc_rp"]["rp1"] = 2.0


@_register("return_processing_cost_usd005")
def _(params: dict[str, Any]) -> None:
    """Set return processing cost to $5.00/unit (was $16.15)."""
    params["rpc_rp"]["rp1"] = 5.0


# High priority — BOM conversion ratio

@_register("bom_ratio_v001")
def _(params: dict[str, Any]) -> None:
    """Set remanufacturing BOM to 1:1 (was 4.4647 rp1 per p1)."""
    params["bom_rem_r_p"]["rp1"]["p1"] = 1.0


@_register("bom_ratio_v002")
def _(params: dict[str, Any]) -> None:
    """Set remanufacturing BOM to 2:1 (was 4.4647 rp1 per p1)."""
    params["bom_rem_r_p"]["rp1"]["p1"] = 2.0


# High priority — production technology capacity

@_register("production_capacity_x070")
def _(params: dict[str, Any]) -> None:
    """Reduce all production technology capacities by 30%."""
    for g in params["bar_p_g"]:
        params["bar_p_g"][g] = round(params["bar_p_g"][g] * 0.7, 2)


# High priority — demand level

@_register("demand_x115")
def _(params: dict[str, Any]) -> None:
    """Scale all retailer demand up by 15%."""
    for r in params["d_r_p_t"]:
        for p in params["d_r_p_t"][r]:
            for t in params["d_r_p_t"][r][p]:
                params["d_r_p_t"][r][p][t] = round(params["d_r_p_t"][r][p][t] * 1.15, 2)


@_register("demand_x130")
def _(params: dict[str, Any]) -> None:
    """Scale all retailer demand up by 30%."""
    for r in params["d_r_p_t"]:
        for p in params["d_r_p_t"][r]:
            for t in params["d_r_p_t"][r][p]:
                params["d_r_p_t"][r][p][t] = round(params["d_r_p_t"][r][p][t] * 1.30, 2)


# Medium priority — return rate bounds

@_register("min_return_zero")
def _(params: dict[str, Any]) -> None:
    """Set all minimum return fractions to zero (voluntary collection only)."""
    for r in params["ret_min_frac_r_p_t"]:
        for p in params["ret_min_frac_r_p_t"][r]:
            for t in params["ret_min_frac_r_p_t"][r][p]:
                params["ret_min_frac_r_p_t"][r][p][t] = 0.0


# Medium priority — carbon tax range

@_register("tax_range_max040")
def _(params: dict[str, Any]) -> None:
    """Double the carbon tax range: hat_tau 0–40 (0–0.4 USD/kg CO2e = 0–400 USD/t)."""
    params["overline_hat_tau"] = 40
    params["overline_tau"] = 0.4


@_register("tax_range_max080")
def _(params: dict[str, Any]) -> None:
    """Quadruple the carbon tax range: hat_tau 0–80 (0–0.8 USD/kg CO2e = 0–800 USD/t).

    Diagnoses tax-range censoring: instances whose bilevel optimum pins to the ceiling at 40
    are re-tested with a much taller range to recover the true interior optimum.
    """
    params["overline_hat_tau"] = 80
    params["overline_tau"] = 0.8


# Medium priority — supplier emission intensities

@_register("supplier_emissions_mean")
def _(params: dict[str, Any]) -> None:
    """Set supplier raw-material emission intensities to the material mean."""
    by_material: dict[str, list[float]] = {}
    for supplier_values in params["e_raw_s_u"].values():
        for raw_material, value in supplier_values.items():
            by_material.setdefault(raw_material, []).append(float(value))

    means = {
        raw_material: round(sum(values) / len(values), 4)
        for raw_material, values in by_material.items()
    }
    for supplier_values in params["e_raw_s_u"].values():
        for raw_material in supplier_values:
            supplier_values[raw_material] = means[raw_material]


# Low priority — transport fixed costs

@_register("air_sea_cost_x050")
def _(params: dict[str, Any]) -> None:
    """Halve hub operating costs (air/sea modes carry no separate fixed cost)."""
    for hub in params["f_h"]:
        if hub.startswith(("air", "port")):
            params["f_h"][hub] = round(params["f_h"][hub] / 2, 2)


# Low priority — truck capacity

@_register("truck_capacity_x070")
def _(params: dict[str, Any]) -> None:
    """Reduce mrd1 truck capacity by 30% (× 0.7)."""
    params["bar_X_m"]["mrd1"] = round(params["bar_X_m"]["mrd1"] * 0.7, 2)


# --- 6 new dimensions added for journal publication ---

# Return rate availability

@_register("return_availability_x050")
def _(params: dict[str, Any]) -> None:
    """Halve all return rate bounds (rho, ret_max_frac, ret_min_frac × 0.5)."""
    for outer in ("rho_r_p_t", "ret_max_frac_r_p_t", "ret_min_frac_r_p_t"):
        mapping = params.get(outer, {})
        for r in mapping:
            for p in mapping[r]:
                for t in mapping[r][p]:
                    mapping[r][p][t] = round(mapping[r][p][t] * 0.5, 6)


@_register("return_availability_x200")
def _(params: dict[str, Any]) -> None:
    """Double all return rate bounds, capped at 1.0 (rho, ret_max_frac, ret_min_frac × 2.0)."""
    for outer in ("rho_r_p_t", "ret_max_frac_r_p_t", "ret_min_frac_r_p_t"):
        mapping = params.get(outer, {})
        for r in mapping:
            for p in mapping[r]:
                for t in mapping[r][p]:
                    mapping[r][p][t] = round(min(mapping[r][p][t] * 2.0, 1.0), 6)


# Theoretical CLSC maximum

@_register("return_processing_cost_usd000")
def _(params: dict[str, Any]) -> None:
    """Set return processing cost to zero (rpc_rp = 0.0)."""
    for rp in params["rpc_rp"]:
        params["rpc_rp"][rp] = 0.0


# Background decarbonisation

@_register("scope3_emissions_x050")
def _(params: dict[str, Any]) -> None:
    """Halve all upstream (scope 3) raw material emission intensities (e_raw_s_u × 0.5)."""
    for s in params["e_raw_s_u"]:
        for u in params["e_raw_s_u"][s]:
            params["e_raw_s_u"][s][u] = round(params["e_raw_s_u"][s][u] * 0.5, 4)


@_register("production_emissions_x050")
def _(params: dict[str, Any]) -> None:
    """Halve all production technology emission intensities (e_prod_g × 0.5)."""
    for g in params["e_prod_g"]:
        params["e_prod_g"][g] = round(params["e_prod_g"][g] * 0.5, 4)


# ---------------------------------------------------------------------------
# Spec catalogue
# ---------------------------------------------------------------------------

_SENSITIVITY_SPECS_BASE: tuple[SensitivitySpec, ...] = (
    SensitivitySpec(
        code="return_processing_cost_usd002",
        label="return_processing_2",
        description="rpc_rp[rp1] = $2.00 (was $16.15). Tests whether the CLSC loop becomes economically attractive at a lower return processing cost.",
        priority="high",
        dimension="return_processing",
        parameters_changed=("rpc_rp",),
    ),
    SensitivitySpec(
        code="return_processing_cost_usd005",
        label="return_processing_5",
        description="rpc_rp[rp1] = $5.00 (was $16.15). Intermediate reduction in return processing cost.",
        priority="high",
        dimension="return_processing",
        parameters_changed=("rpc_rp",),
    ),
    SensitivitySpec(
        code="bom_ratio_v001",
        label="bom_one_to_one",
        description="bom_rem_r_p[rp1][p1] = 1.0 (was 4.4647). 1:1 BOM conversion — each unit of rp1 yields one unit of p1 from remanufacturing.",
        priority="high",
        dimension="bom_conversion",
        parameters_changed=("bom_rem_r_p",),
    ),
    SensitivitySpec(
        code="bom_ratio_v002",
        label="bom_two_to_one",
        description="bom_rem_r_p[rp1][p1] = 2.0 (was 4.4647). 2:1 BOM — more efficient than base but still requiring two recovered units per remanufactured unit.",
        priority="high",
        dimension="bom_conversion",
        parameters_changed=("bom_rem_r_p",),
    ),
    SensitivitySpec(
        code="production_capacity_x070",
        label="all_production_capacity_70pct",
        description="All bar_p_g scaled by 0.70. Tests whether a system-wide production capacity reduction forces network expansion or technology switching.",
        priority="high",
        dimension="production_capacity",
        parameters_changed=("bar_p_g",),
    ),
    SensitivitySpec(
        code="demand_x115",
        label="demand_plus_15pct",
        description="All d_r_p_t scaled by 1.15 (+15%). Tests whether moderate demand growth triggers network expansion.",
        priority="high",
        dimension="demand_level",
        parameters_changed=("d_r_p_t",),
    ),
    SensitivitySpec(
        code="demand_x130",
        label="demand_plus_30pct",
        description="All d_r_p_t scaled by 1.30 (+30%). Tests whether a larger demand increase forces a second factory or warehouse opening.",
        priority="high",
        dimension="demand_level",
        parameters_changed=("d_r_p_t",),
    ),
    SensitivitySpec(
        code="min_return_zero",
        label="min_returns_zero",
        description="All ret_min_frac_r_p_t = 0.0. Tests whether the model collects any returns voluntarily when collection is not mandated.",
        priority="medium",
        dimension="return_bounds",
        parameters_changed=("ret_min_frac_r_p_t",),
    ),
    SensitivitySpec(
        code="tax_range_max040",
        label="tax_range_doubled",
        description="overline_hat_tau=40, overline_tau=0.4. Doubles the carbon tax range to 0–400 USD/t CO2e. Tests whether further structural changes occur beyond the base optimal of 40 USD/t.",
        priority="medium",
        dimension="tax_range",
        parameters_changed=("overline_hat_tau", "overline_tau"),
    ),
    SensitivitySpec(
        code="tax_range_max080",
        label="tax_range_quadrupled",
        description="overline_hat_tau=80, overline_tau=0.8. Quadruples the carbon tax range to 0–800 USD/t CO2e. Diagnoses tax-range censoring (recovers the true optimum for instances pinned to the 40 ceiling).",
        priority="medium",
        dimension="tax_range",
        parameters_changed=("overline_hat_tau", "overline_tau"),
    ),
    SensitivitySpec(
        code="supplier_emissions_mean",
        label="supplier_emit_mean",
        description="For each raw material, all e_raw_s_u values are set to the supplier mean. Removes supplier-specific upstream emission advantages while preserving material-level average intensity.",
        priority="medium",
        dimension="supplier_emissions",
        parameters_changed=("e_raw_s_u",),
    ),
    SensitivitySpec(
        code="air_sea_cost_x050",
        label="air_sea_cost_half",
        description="Hub operating costs (f_h) halved. Tests whether modal shift to air or sea occurs when hub access is cheaper.",
        priority="low",
        dimension="transport_fixed_cost",
        parameters_changed=("f_h",),
    ),
    SensitivitySpec(
        code="truck_capacity_x070",
        label="truck_capacity_70pct",
        description="bar_X_m[mrd1] reduced by 30% (×0.7). Tests whether lower truck capacity forces more trips, larger fleets, or activation of mrd2.",
        priority="low",
        dimension="truck_capacity",
        parameters_changed=("bar_X_m",),
    ),
    # --- 6 new dimensions for journal publication ---
    SensitivitySpec(
        code="return_availability_x050",
        label="return_rate_halved",
        description="All rho_r_p_t, ret_max_frac_r_p_t, ret_min_frac_r_p_t halved (×0.5). Tests whether lower return availability suppresses CLSC activation.",
        priority="high",
        dimension="return_availability",
        parameters_changed=("rho_r_p_t", "ret_max_frac_r_p_t", "ret_min_frac_r_p_t"),
    ),
    SensitivitySpec(
        code="return_availability_x200",
        label="return_rate_doubled",
        description="All return rate bounds doubled (×2.0, capped at 1.0). Tests whether higher return availability unlocks the CLSC loop.",
        priority="high",
        dimension="return_availability",
        parameters_changed=("rho_r_p_t", "ret_max_frac_r_p_t", "ret_min_frac_r_p_t"),
    ),
    SensitivitySpec(
        code="return_processing_cost_usd000",
        label="return_processing_zero",
        description="rpc_rp = 0.0 (free return processing). Establishes theoretical maximum remanufacturing activity.",
        priority="high",
        dimension="return_processing",
        parameters_changed=("rpc_rp",),
    ),
    SensitivitySpec(
        code="scope3_emissions_x050",
        label="upstream_emissions_halved",
        description="All e_raw_s_u × 0.5. Tests whether upstream (scope 3) decarbonisation reduces the regulator's required tax.",
        priority="medium",
        dimension="background_emissions",
        parameters_changed=("e_raw_s_u",),
    ),
    SensitivitySpec(
        code="production_emissions_x050",
        label="production_emissions_halved",
        description="All e_prod_g × 0.5. Tests whether cleaner production technology (e.g. electrification) lowers the bilevel optimal tax.",
        priority="medium",
        dimension="background_emissions",
        parameters_changed=("e_prod_g",),
    ),
)


# Normalization metadata merged onto each base spec by code (drives elasticity computation).
_SPEC_ENRICHMENT: dict[str, dict[str, Any]] = {
    "return_processing_cost_usd002": dict(factor="return_processing_cost", kind="absolute", perturbed_value=2.0,
                                          baseline_path=("rpc_rp", "rp1")),
    "return_processing_cost_usd005": dict(factor="return_processing_cost", kind="absolute", perturbed_value=5.0,
                                          baseline_path=("rpc_rp", "rp1")),
    "return_processing_cost_usd000": dict(factor="return_processing_cost", kind="absolute", perturbed_value=0.0,
                                          baseline_path=("rpc_rp", "rp1")),
    "bom_ratio_v001": dict(factor="bom_ratio", kind="absolute", perturbed_value=1.0,
                           baseline_path=("bom_rem_r_p", "rp1", "p1")),
    "bom_ratio_v002": dict(factor="bom_ratio", kind="absolute", perturbed_value=2.0,
                           baseline_path=("bom_rem_r_p", "rp1", "p1")),
    "production_capacity_x070": dict(factor="production_capacity", kind="scaling", multiplier=0.7),
    "demand_x115": dict(factor="demand", kind="scaling", multiplier=1.15),
    "demand_x130": dict(factor="demand", kind="scaling", multiplier=1.30),
    "return_availability_x050": dict(factor="return_availability", kind="scaling", multiplier=0.5),
    "return_availability_x200": dict(factor="return_availability", kind="scaling", multiplier=2.0),
    "min_return_zero": dict(factor="min_return", kind="structural"),
    "tax_range_max040": dict(factor="tax_range", kind="scaling", multiplier=2.0),
    "tax_range_max080": dict(factor="tax_range", kind="scaling", multiplier=4.0),
    "supplier_emissions_mean": dict(factor="supplier_emissions", kind="structural"),
    "scope3_emissions_x050": dict(factor="scope3_emissions", kind="scaling", multiplier=0.5),
    "production_emissions_x050": dict(factor="production_emissions", kind="scaling", multiplier=0.5),
    "air_sea_cost_x050": dict(factor="air_sea_cost", kind="scaling", multiplier=0.5),
    "truck_capacity_x070": dict(factor="truck_capacity", kind="scaling", multiplier=0.7),
}

SENSITIVITY_SPECS: tuple[SensitivitySpec, ...] = tuple(
    replace(spec, **_SPEC_ENRICHMENT.get(spec.code, {})) for spec in _SENSITIVITY_SPECS_BASE
)

SPECS_BY_CODE: dict[str, SensitivitySpec] = {spec.code: spec for spec in SENSITIVITY_SPECS}
SPECS_BY_CODE.update({
    legacy_code: SPECS_BY_CODE[new_code]
    for legacy_code, new_code in LEGACY_CODE_ALIASES.items()
})
