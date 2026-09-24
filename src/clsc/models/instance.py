from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from clsc.config.gap_tol import DEFAULT
from clsc.config.tax_scale import TAX_SCALE_FACTOR

# TAX_SCALE_FACTOR: USD/kg CO2e per integer tax_index step: tax_rate = TAX_SCALE_FACTOR * tax_index.
# The one carbon-tax resolution in the project (clsc.config.tax_scale.TAX_SCALE_FACTOR),
# re-exported under this name since it is part of this module's public API (imported elsewhere
# as clsc.models.instance.TAX_SCALE_FACTOR).
# Fallback for instances generated before 2026-08-11, which carry no
# product_rotation_per_period. Those were built reading Mota's 4.5 turns/year
# as a per-period count, and must keep it so archived runs stay reproducible.
# Fresh instances state their own value, which retires the hand-synced
# duplicate this constant used to be.
LEGACY_PRODUCT_ROTATION_PER_PERIOD = 4.5
SUPPORTED_MODE_FAMILIES = {"truck", "air", "sea"}
SUPPORTED_RAW_MATERIAL_FLOW_UNITS = {"item_units"}
SUPPORTED_PROCESS_EMISSION_UNITS = {"kg CO2e/kg"}
REQUIRED_SET_KEYS = (
    "S",
    "F",
    "W",
    "R",
    "AIR",
    "PORT",
    "I",
    "P",
    "U",
    "M",
    "G",
    "L",
    "T",
    "N",
    "V",
    "K",
    "A",
    "FLOW_RAW",
    "FLOW_FP",
    "FLOW_RP",
    "A_sf",
    "A_fw",
    "A_wr",
    "A_rf",
    "H_prod",
    "H_rem",
)
REQUIRED_PARAMETER_KEYS = (
    "i_prod_g",
    "i_rem_l",
    "c_prod_g",
    "c_rem_l",
    "h_p",
    "rpc_rp",
    "rmc_s_u",
    "c_ship_m",
    "f_mode_m",
    "c_handle_m",
    "f_h",
    "mode_family_m",
    "bar_s_s_u",
    "scmin_s_u",
    "bar_p_g",
    "bar_q_l",
    "pcmin_g",
    "pcmin_l",
    "icmax_p_n",
    "icmin_p_n",
    "i_p_n_0",
    "A_f",
    "A_w",
    "bar_X_m",
    "ctmin_m",
    "ccamax_m",
    "a_in_u_p_g",
    "bom_rem_r_p",
    "ret_yield_rp_p",
    "theta_p",
    "omega_u",
    "omega_p",
    "omega_rp",
    "d_r_p_t",
    "rho_r_p_t",
    "e_open_f",
    "e_open_w",
    "e_prod_g",
    "e_rem_l",
    "e_raw_s_u",
    "e_ship_m",
    "underline_tax_rate",
    "overline_tax_rate",
    "underline_tax_index",
    "overline_tax_index",
    "d_i_j",
)
# Legacy parameter keys accepted on load (mapped to their current name by
# _normalize_tax_index_parameter_keys before REQUIRED_PARAMETER_KEYS is
# checked), so instance files generated before the hat_tau -> tax_index
# rename keep loading unchanged. New instances are written with the current
# names only -- see data/generator/instance.py.
_LEGACY_PARAMETER_KEY_ALIASES = {
    "underline_tax_index": "underline_hat_tau",
    "overline_tax_index": "overline_hat_tau",
}


class InstanceValidationError(ValueError):
    """Raised when an instance file does not match the expected schema."""


@dataclass(frozen=True, slots=True)
class InstanceData:
    name: str
    metadata: dict[str, Any]
    sets: dict[str, Any]
    parameters: dict[str, Any]
    source_path: Path | None = None
    # Optional grid-resolution override (theta, USD/kg CO2e per integer tax_index step). When None
    # the tax resolution is read from the stored parameters (the project's one grid, TAX_SCALE_FACTOR,
    # index {0..200}); when set, the index bounds and scale_factor are DERIVED from it over the same
    # real tau range, without touching `parameters`. Set only via with_tax_grid_step(); a caller
    # deliberately probing a different resolution (e.g. the retired coarse grid, as a robustness
    # check) rather than something any current base instance needs at rest.
    tax_grid_step: float | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> "InstanceData":
        source_path = Path(path)
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        return cls.from_dict(payload, source_path=source_path)

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
        *,
        source_path: Path | None = None,
    ) -> "InstanceData":
        missing_top_level = {key for key in ("name", "metadata", "sets", "parameters") if key not in payload}
        if missing_top_level:
            raise InstanceValidationError(f"Missing top-level keys: {sorted(missing_top_level)}")

        sets = _normalize_sets(payload["sets"])
        parameters = dict(payload["parameters"])
        metadata = dict(payload["metadata"])
        _normalize_tax_index_parameter_keys(parameters)
        _apply_parameter_defaults(parameters, sets)
        _apply_metadata_defaults(metadata)

        instance = cls(
            name=str(payload["name"]),
            metadata=metadata,
            sets=sets,
            parameters=parameters,
            source_path=source_path,
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        missing_sets = [key for key in REQUIRED_SET_KEYS if key not in self.sets]
        if missing_sets:
            raise InstanceValidationError(f"Missing set keys: {missing_sets}")

        missing_parameters = [key for key in REQUIRED_PARAMETER_KEYS if key not in self.parameters]
        if missing_parameters:
            raise InstanceValidationError(f"Missing parameter keys: {missing_parameters}")

        lower_index = self.lower_tax_index
        upper_index = self.upper_tax_index
        if lower_index > upper_index:
            raise InstanceValidationError("underline_tax_index cannot exceed overline_tax_index")

        if _tax_rate_to_tax_index(self.parameters["underline_tax_rate"]) != lower_index:
            raise InstanceValidationError("underline_tax_rate and underline_tax_index are inconsistent")
        if _tax_rate_to_tax_index(self.parameters["overline_tax_rate"]) != upper_index:
            raise InstanceValidationError("overline_tax_rate and overline_tax_index are inconsistent")

        expected_all_nodes = tuple(self.sets["S"] + self.sets["F"] + self.sets["W"] + self.sets["R"] + self.sets["AIR"] + self.sets["PORT"])
        if tuple(self.sets["I"]) != expected_all_nodes:
            raise InstanceValidationError("Set I must equal S + F + W + R + AIR + PORT")
        if tuple(self.sets["N"]) != expected_all_nodes:
            raise InstanceValidationError("Set N must equal S + F + W + R + AIR + PORT")

        if tuple(self.sets["K"]) != tuple(self.sets["RP"]):
            raise InstanceValidationError("Set K must equal RP")

        missing_return_lags = [product for product in self.sets["P"] if product not in self.parameters["theta_p"]]
        if missing_return_lags:
            raise InstanceValidationError(f"Missing theta_p values for products: {missing_return_lags}")
        invalid_return_lags = []
        negative_return_lags = []
        for product, value in self.parameters["theta_p"].items():
            try:
                lag = int(value)
            except (TypeError, ValueError):
                invalid_return_lags.append(product)
                continue
            if lag != value:
                invalid_return_lags.append(product)
            elif lag < 0:
                negative_return_lags.append(product)
        if invalid_return_lags:
            raise InstanceValidationError(f"Return lags theta_p must be integer-valued: {invalid_return_lags}")
        if negative_return_lags:
            raise InstanceValidationError(f"Return lags theta_p must be nonnegative: {negative_return_lags}")

        _validate_arc_sets(self.sets)
        _validate_pair_sets(self.sets)
        _validate_flow_sets(self.sets)
        _validate_distance_coverage(self.sets, self.parameters)
        _validate_mode_parameters(self.sets, self.parameters)
        _validate_unit_conventions(self.metadata)
        _validate_technology_coverage(self.sets)
        _validate_capacity_feasibility(self.sets, self.parameters)

    @property
    def lower_tax_index(self) -> int:
        if self.tax_grid_step is not None:
            return round(float(self.parameters["underline_tax_rate"]) / self.tax_grid_step)
        return int(self.parameters["underline_tax_index"])

    @property
    def upper_tax_index(self) -> int:
        if self.tax_grid_step is not None:
            return round(float(self.parameters["overline_tax_rate"]) / self.tax_grid_step)
        return int(self.parameters["overline_tax_index"])

    def iter_tax_index(self) -> range:
        return range(self.lower_tax_index, self.upper_tax_index + 1)

    @property
    def scale_factor(self) -> float:
        """USD/kg CO2e per integer tax_index step. When a resolution override is in
        effect (see :meth:`with_tax_grid_step`) the override step is returned
        directly, exactly. Otherwise it is DERIVED from this instance's own stored
        grid (``overline_tax_rate``/``overline_tax_index``) rather than the module
        constant, so a base instance (overline_tax_rate=0.2, overline_tax_index=400)
        yields 0.2/400 = 5e-4 = the module TAX_SCALE_FACTOR and existing behaviour is
        unchanged. Falls back to the module constant for a degenerate single-point
        grid."""
        if self.tax_grid_step is not None:
            return self.tax_grid_step
        span_index = self.upper_tax_index - self.lower_tax_index
        if span_index <= 0:
            return TAX_SCALE_FACTOR
        span_rate = float(self.parameters["overline_tax_rate"]) - float(self.parameters["underline_tax_rate"])
        return span_rate / span_index

    def with_tax_grid_step(self, scale_factor: float) -> "InstanceData":
        """Return a NEW instance whose carbon-tax resolution is refined to resolution
        ``scale_factor`` (theta, USD/kg CO2e per integer tax_index step), while
        PRESERVING the real tax range ``[underline_tax_rate, overline_tax_rate]``.

        This is the immutable, first-class replacement for mutating the stored
        ``*_tax_index`` parameters in place. The refined index bounds are DERIVED
        (``round(tau / theta)``) from the step rather than stored, so overline_tax_rate
        = 0.2 with theta = 0.001 exposes ``upper_tax_index = 200`` (index
        {0..200}, 1 USD/t over the same 0-200 USD/t span). ``parameters`` and
        the on-disk file are untouched. Every base instance is generated directly
        at the project's one grid (``TAX_SCALE_FACTOR``), so calling this
        with that same step is a no-op; it exists for the rare deliberate probe
        at a different resolution (e.g. a coarser robustness check), not as a
        load-bearing rescale in the normal path.

        No re-validation is run: ``validate()``'s tau/index consistency check
        assumes the stored step and is only meaningful for the grid as loaded;
        the refined view is a derived projection of an already-validated
        instance, so re-validating it would spuriously reject a widened index.
        """
        if scale_factor <= 0.0:
            raise ValueError(f"tax resolution step must be positive, got {scale_factor}")
        underline_tax_rate = float(self.parameters["underline_tax_rate"])
        overline_tax_rate = float(self.parameters["overline_tax_rate"])
        lower_index = round(underline_tax_rate / scale_factor)
        upper_index = round(overline_tax_rate / scale_factor)
        if upper_index <= lower_index:
            raise ValueError(
                f"tax resolution step {scale_factor} collapses the grid of {self.name} "
                f"(tau range [{underline_tax_rate}, {overline_tax_rate}] -> index "
                f"[{lower_index}, {upper_index}])"
            )
        return replace(self, tax_grid_step=scale_factor)

    def arcs(self, arc_type: str) -> tuple[tuple[str, str], ...]:
        return self.sets[f"A_{arc_type}"]

    def scalar(self, parameter_name: str) -> float:
        return float(self.parameters[parameter_name])

    def parameter(self, parameter_name: str) -> Any:
        return self.parameters[parameter_name]

    def tax_rate(self, tax_index: int) -> float:
        """Real carbon tax rate (USD/kg CO2e) for leader tax index ``tax_index``.

        ``tax_index`` is the integer decision index the solver optimises over;
        this converts it to the actual tax rate via ``tax_rate = scale_factor *
        tax_index``, using this instance's own :attr:`scale_factor` (so a finer
        grid is honoured). (For the per-tonne rate used in reporting and the
        paper, multiply by 1000.)
        """
        return self.scale_factor * tax_index


def _normalize_tax_index_parameter_keys(parameters: dict[str, Any]) -> None:
    """Fill in the current tax-index parameter keys from their legacy names
    when only the legacy names are present, so instance files written before
    the hat_tau -> tax_index rename keep loading without modification. Leaves
    the legacy keys in place (harmless) rather than deleting them."""
    for current_key, legacy_key in _LEGACY_PARAMETER_KEY_ALIASES.items():
        if current_key not in parameters and legacy_key in parameters:
            parameters[current_key] = parameters[legacy_key]


def _normalize_sets(raw_sets: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in raw_sets.items():
        if key == "A" or key.startswith("A_") or key in {"H_prod", "H_rem"}:
            normalized[key] = tuple((str(origin), str(destination)) for origin, destination in value)
            continue
        if key.startswith("FLOW_"):
            normalized[key] = tuple(
                (str(item), str(origin), str(destination))
                for item, origin, destination in value
            )
            continue
        normalized[key] = tuple(str(item) for item in value)

    suppliers = normalized.get("S", tuple())
    factories = normalized.get("F", tuple())
    warehouses = normalized.get("W", tuple())
    retailers = normalized.get("R", tuple())
    airports = normalized.get("AIR", tuple())
    seaports = normalized.get("PORT", tuple())
    recovered_products = tuple(normalized.get("K", tuple()))
    legacy_recovered_products = tuple(normalized.get("RP", tuple()))
    all_nodes = tuple((*suppliers, *factories, *warehouses, *retailers, *airports, *seaports))
    inventory_nodes = tuple((*factories, *warehouses))
    legacy_inventory_nodes = tuple((*factories, *warehouses, *retailers))

    if "I" not in normalized or tuple(normalized.get("I", tuple())) in {tuple(), all_nodes}:
        normalized["I"] = all_nodes
    if "N" not in normalized or tuple(normalized.get("N", tuple())) in {tuple(), all_nodes, inventory_nodes, legacy_inventory_nodes}:
        normalized["N"] = all_nodes
    # V (Nv, the inventory-holding nodes) is warehouses only: factories carry
    # no inventory and recovered items are never held in stock anywhere,
    # matching the Mota et al. (2018) / Tautenhain et al. (2021) inventory
    # policy (paper/sections/04a_notation.tex).
    normalized["V"] = warehouses
    if recovered_products == ("raw", "fp", "rp") and legacy_recovered_products:
        recovered_products = legacy_recovered_products
    elif not recovered_products and legacy_recovered_products:
        recovered_products = legacy_recovered_products

    if recovered_products:
        normalized["K"] = recovered_products
        normalized["RP"] = recovered_products
    return normalized


def _tax_rate_to_tax_index(rate: Any) -> int:
    numeric_rate = float(rate)
    scaled = round(numeric_rate / TAX_SCALE_FACTOR)
    if abs(numeric_rate - scaled * TAX_SCALE_FACTOR) > DEFAULT.eps:
        raise InstanceValidationError(f"Tax bounds must be multiples of {TAX_SCALE_FACTOR} USD/kg CO2e")
    return int(scaled)




def _apply_metadata_defaults(metadata: dict[str, Any]) -> None:
    unit_convention = metadata.setdefault("unit_convention", {})
    unit_convention.setdefault("raw_material_flow", "item_units")
    unit_convention.setdefault("raw_material_cost", "USD/raw-material unit")
    unit_convention.setdefault("raw_material_emission_intensity", "kg CO2e/kg")


def _apply_parameter_defaults(parameters: dict[str, Any], sets: dict[str, Any]) -> None:
    parameters.setdefault("theta_p", {product: 1 for product in sets.get("P", ())})
    parameters.setdefault("f_s", {supplier: 0.0 for supplier in sets.get("S", ())})
    parameters.setdefault("c_area_f", {factory: 0.0 for factory in sets.get("F", ())})
    parameters.setdefault("c_area_w", {warehouse: 0.0 for warehouse in sets.get("W", ())})
    parameters.setdefault("Amin_f", {factory: 0.0 for factory in sets.get("F", ())})
    parameters.setdefault("Amin_w", {warehouse: 0.0 for warehouse in sets.get("W", ())})
    parameters.setdefault("apu_u", {material: 0.0 for material in sets.get("U", ())})
    parameters.setdefault("apu_p", {product: 0.0 for product in sets.get("P", ())})
    # apur_p is a DERIVED quantity -- apur_p[p] == apu_p[p] / product_rotation_per_period by
    # definition (it is the per-period rotation footprint the model reads as flow area, see
    # subproblems._item_flow_area_map). Recompute it authoritatively from apu_p on every load
    # rather than trusting whatever the file carries: the generator serialises apur_p rounded to
    # 6 DECIMAL places, which at its ~1e-4 magnitude keeps only ~3 significant figures and breaks
    # the defining ratio by ~1e-3 relative. Deriving on load keeps the in-memory model exactly
    # self-consistent regardless of the file's stored precision (and still fills it for older
    # files that omit apur_p entirely).
    parameters["apur_p"] = _derive_product_rotation_area(parameters, sets)
    parameters.setdefault("apu_rp", _derive_recovered_product_area(parameters, sets))
    for recovered_product in sets.get("K", ()):
        parameters["apu_rp"].setdefault(recovered_product, 0.0)
    parameters.setdefault("apu_q", _derive_item_area(parameters, sets))
    for item in (*sets.get("U", ()), *sets.get("P", ()), *sets.get("K", ())):
        parameters["apu_q"].setdefault(item, 0.0)
    if "rho_r_p_t" in parameters:
        parameters.setdefault("ret_max_frac_r_p_t", _copy_nested_dict(parameters["rho_r_p_t"]))
        parameters.setdefault("ret_min_frac_r_p_t", _zero_nested_dict(parameters["ret_max_frac_r_p_t"]))

    modes = sets.get("M", ())
    mode_family = parameters.get("mode_family_m", {})
    transport_capacity = parameters.get("bar_X_m", {})
    transport_cost = parameters.get("c_ship_m", {})
    parameters.setdefault(
        "c_trip_m",
        {
            mode: float(transport_cost.get(mode, 0.0)) * float(transport_capacity.get(mode, 0.0))
            if mode_family.get(mode, mode) == "truck"
            else 0.0
            for mode in modes
        },
    )
    parameters.setdefault(
        "road_return_factor_m",
        {mode: 2.0 if mode_family.get(mode, mode) == "truck" else 1.0 for mode in modes},
    )
    parameters.setdefault(
        "speed_km_h_m",
        {mode: 70.0 if mode_family.get(mode, mode) == "truck" else 0.0 for mode in modes},
    )
    parameters.setdefault(
        "max_driving_hours_m",
        {mode: 180.0 if mode_family.get(mode, mode) == "truck" else 0.0 for mode in modes},
    )
    parameters.setdefault("truck_investment_budget", 1.0e12)
    parameters.setdefault(
        "trip_big_m_m",
        {
            mode: max(
                1,
                int(
                    (
                        max(parameters.get("ecmax_i", {}).values(), default=0.0)
                        or float(transport_capacity.get(mode, 1.0))
                    )
                    // max(float(transport_capacity.get(mode, 1.0)), 1.0)
                    + 2
                ),
            )
            for mode in modes
        },
    )


def _copy_nested_dict(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy_nested_dict(nested) for key, nested in value.items()}
    return value


def _zero_nested_dict(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _zero_nested_dict(nested) for key, nested in value.items()}
    return 0.0


def _derive_product_rotation_area(parameters: dict[str, Any], sets: dict[str, Any]) -> dict[str, float]:
    rotation = float(
        parameters.get("product_rotation_per_period")
        or LEGACY_PRODUCT_ROTATION_PER_PERIOD
    )
    product_area = parameters.get("apu_p", {})
    return {
        product: float(product_area.get(product, 0.0)) / rotation
        for product in sets.get("P", ())
    }


def _derive_recovered_product_area(parameters: dict[str, Any], sets: dict[str, Any]) -> dict[str, float]:
    product_area = parameters.get("apu_p", {})
    remanufacturing_bom = parameters.get("bom_rem_r_p", {})
    products = sets.get("P", ())
    return {
        recovered_product: float(
            sum(
                float(remanufacturing_bom.get(recovered_product, {}).get(product, 0.0))
                * float(product_area.get(product, 0.0))
                for product in products
            )
        )
        for recovered_product in sets.get("K", ())
    }


def _derive_item_area(parameters: dict[str, Any], sets: dict[str, Any]) -> dict[str, float]:
    return {
        **{material: float(parameters.get("apu_u", {}).get(material, 0.0)) for material in sets.get("U", ())},
        **{product: float(parameters.get("apu_p", {}).get(product, 0.0)) for product in sets.get("P", ())},
        **{
            recovered_product: float(parameters.get("apu_rp", {}).get(recovered_product, 0.0))
            for recovered_product in sets.get("K", ())
        },
    }


def _validate_arc_sets(sets: dict[str, Any]) -> None:
    all_nodes = set(sets["I"])
    transport_arcs = set(sets["A"])
    for name, value in sets.items():
        if name == "A" or not name.startswith("A_"):
            continue
        arc_set = set(value)
        if not arc_set.issubset(transport_arcs):
            raise InstanceValidationError(f"{name} must be a subset of A")
        for origin, destination in value:
            if origin not in all_nodes or destination not in all_nodes:
                raise InstanceValidationError(f"{name} contains arc with nodes outside I: {(origin, destination)}")


def _validate_pair_sets(sets: dict[str, Any]) -> None:
    products = set(sets["P"])
    production_technologies = set(sets["G"])
    remanufacturing_technologies = set(sets["L"])
    for product, technology in sets["H_prod"]:
        if product not in products or technology not in production_technologies:
            raise InstanceValidationError(f"H_prod contains invalid pair: {(product, technology)}")
    for product, technology in sets["H_rem"]:
        if product not in products or technology not in remanufacturing_technologies:
            raise InstanceValidationError(f"H_rem contains invalid pair: {(product, technology)}")


def _validate_flow_sets(sets: dict[str, Any]) -> None:
    all_items = {
        "FLOW_RAW": set(sets["U"]),
        "FLOW_FP": set(sets["P"]),
        "FLOW_RP": set(sets["K"]),
    }
    all_nodes = set(sets["I"])
    transport_arcs = set(sets["A"])
    for flow_name, valid_items in all_items.items():
        for item, origin, destination in sets[flow_name]:
            if item not in valid_items:
                raise InstanceValidationError(f"{flow_name} contains item outside its domain: {(item, origin, destination)}")
            if origin not in all_nodes or destination not in all_nodes:
                raise InstanceValidationError(f"{flow_name} contains node outside I: {(item, origin, destination)}")
            if (origin, destination) not in transport_arcs:
                raise InstanceValidationError(f"{flow_name} contains arc outside A: {(item, origin, destination)}")


def _validate_distance_coverage(sets: dict[str, Any], parameters: dict[str, Any]) -> None:
    distances = parameters["d_i_j"]
    missing = [
        (origin, destination)
        for origin, destination in sets["A"]
        if origin not in distances or destination not in distances[origin]
    ]
    if missing:
        raise InstanceValidationError(f"d_i_j is missing distances for arcs: {missing[:5]}")


def _validate_mode_parameters(sets: dict[str, Any], parameters: dict[str, Any]) -> None:
    modes = sets["M"]
    mode_family = parameters["mode_family_m"]
    required_mode_maps = ("bar_X_m", "ctmin_m", "ccamax_m", "c_ship_m", "f_mode_m", "c_handle_m", "e_ship_m")
    missing_entries: dict[str, list[str]] = {}
    for parameter_name in required_mode_maps:
        missing = [mode for mode in modes if mode not in parameters[parameter_name]]
        if missing:
            missing_entries[parameter_name] = missing
    missing_family = [mode for mode in modes if mode not in mode_family]
    if missing_family:
        missing_entries["mode_family_m"] = missing_family
    if missing_entries:
        raise InstanceValidationError(f"Incomplete mode parameter coverage: {missing_entries}")

    invalid_family = [mode for mode in modes if mode_family[mode] not in SUPPORTED_MODE_FAMILIES]
    if invalid_family:
        raise InstanceValidationError(f"Unsupported mode families for modes: {invalid_family}")

    available_families = {mode_family[mode] for mode in modes}
    for origin, destination in sets["A"]:
        required_family = (
            "air"
            if origin in sets["AIR"] and destination in sets["AIR"]
            else "sea"
            if origin in sets["PORT"] and destination in sets["PORT"]
            else "truck"
        )
        if required_family not in available_families:
            raise InstanceValidationError(
                f"Arc {(origin, destination)} requires a {required_family} mode, but no such mode exists in M",
            )


def _validate_technology_coverage(sets: dict[str, Any]) -> None:
    """as:feas precondition: every product in P must be reachable via at least one compatible
    production technology (Omega^p, H_prod) or remanufacturing technology (Omega^r, H_rem).
    A product with no compatible technology of either kind can never be supplied, so the
    follower's feasible region would be empty for any positive demand of that product."""
    products = set(sets.get("P", ()))
    covered = {product for product, _ in sets.get("H_prod", ())}
    covered |= {product for product, _ in sets.get("H_rem", ())}
    uncovered = sorted(products - covered)
    if uncovered:
        raise InstanceValidationError(
            f"Products with no compatible production or remanufacturing technology: {uncovered}",
        )


def _validate_capacity_feasibility(sets: dict[str, Any], parameters: dict[str, Any]) -> None:
    """as:feas (paper/sections/04a_notation.tex): the follower's feasible region must be
    non-empty for every admissible tax_index, which the paper states "can be verified a priori by
    checking that the network has sufficient installed capacity to cover maximum aggregate
    demand." This is a necessary, not sufficient, a-priori check: it sums each product's
    production and remanufacturing capacity across every factory (since technology installation
    is an independent per-factory binary decision, this is the network's maximum *potential*
    capacity) and compares it against that product's largest single-period aggregate demand
    across all retailers. It cannot catch every source of infeasibility (per-facility area or
    raw-material bottlenecks, for instance), but a violation here proves the instance is
    infeasible regardless of tax_index or network configuration."""
    factories = sets.get("F", ())
    products = sets.get("P", ())
    production_technologies = sets.get("G", ())
    remanufacturing_technologies = sets.get("L", ())
    production_pairs = set(sets.get("H_prod", ()))
    remanufacturing_pairs = set(sets.get("H_rem", ()))
    bar_p_g = parameters.get("bar_p_g", {})
    bar_q_l = parameters.get("bar_q_l", {})
    demand = parameters.get("d_r_p_t", {})
    retailers = sets.get("R", ())
    periods = sets.get("T", ())

    if not factories or not periods:
        return

    insufficient: list[tuple[str, float, float]] = []
    for product in products:
        production_capacity = sum(
            float(bar_p_g.get(technology, 0.0))
            for technology in production_technologies
            if (product, technology) in production_pairs
        )
        remanufacturing_capacity = sum(
            float(bar_q_l.get(technology, 0.0))
            for technology in remanufacturing_technologies
            if (product, technology) in remanufacturing_pairs
        )
        total_capacity = len(factories) * (production_capacity + remanufacturing_capacity)
        max_period_demand = max(
            (
                sum(float(demand.get(retailer, {}).get(product, {}).get(period, 0.0)) for retailer in retailers)
                for period in periods
            ),
            default=0.0,
        )
        if total_capacity < max_period_demand:
            insufficient.append((product, total_capacity, max_period_demand))
    if insufficient:
        raise InstanceValidationError(
            "Network installed capacity cannot cover maximum aggregate demand for products "
            f"(as:feas violated; (product, max_capacity, max_period_demand)): {insufficient}",
        )


def _validate_unit_conventions(metadata: dict[str, Any]) -> None:
    raw_material_flow = metadata.get("unit_convention", {}).get("raw_material_flow")
    if raw_material_flow not in SUPPORTED_RAW_MATERIAL_FLOW_UNITS:
        raise InstanceValidationError(
            "Current implementation expects raw-material flows, supply bounds, and raw-material costs "
            "to use raw-material item units. kg-based raw-material flows are not supported without a "
            "coordinated data-model conversion.",
        )
    unit_convention = metadata.get("unit_convention", {})
    for key in ("production_emission_intensity", "remanufacturing_emission_intensity"):
        if unit_convention.get(key) not in SUPPORTED_PROCESS_EMISSION_UNITS:
            raise InstanceValidationError(
                "Current implementation expects production and remanufacturing emission intensities "
                "to use kg CO2e/kg. Regenerate legacy per-unit instances before solving.",
            )
