from __future__ import annotations

import math
import random
from typing import Any

# Tautenhain-based: generator constants.
DEMAND_RANGE = (8336.8, 34481.28)
RETURN_RATE_UPPER_BOUND = 0.15
RETURN_RATE_RANGE = (0.0, RETURN_RATE_UPPER_BOUND)
RETURN_LAG_RANGE = (1, 3)
BOM_PROD_RANGE = (0.015, 0.45)
BOM_REM_RANGE = (4.0, 5.0)
RAW_WEIGHT_RANGE = (0.1, 0.9)
RAW_AREA_RANGE = (0.001, 0.004)
INVENTORY_FRAC_MAX = 0.5
INVENTORY_FRAC_MIN = 0.01
# Mota et al. (2018) calibrate their flow-based floor-area rate as
# apur_m = apu_m / 4.5, where 4.5 is an assumed ANNUAL product-rotation
# (turnover) count -- valid in their case study because it uses yearly
# planning periods. This project's planning periods have no calendar/year
# semantics (configurable period counts, e.g. T3/T6/T12), so the same
# constant is reinterpreted here as a per-planning-period rotation count.
PRODUCT_ROTATION_PER_PERIOD = 4.5
TECH_CAPACITY_MULTIPLIER_RANGE = (2.0, 4.0)
TECH_MIN_CAPACITY_FRAC = 0.0005
FACTORY_AREA_MAX_RANGE = (10000.0, 12500.0)
WAREHOUSE_AREA_MAX_RANGE = (4000.0, 4750.0)
FACTORY_AREA_MIN_RANGE = (2000.0, 2500.0)
WAREHOUSE_AREA_MIN_RANGE = (500.0, 750.0)
SUPPLIER_MIN_FRACTION_RANGE = (0.00001, 0.0001)
SUPPLIER_SELECTION_FIXED_COST_RANGE = (1000.0, 5000.0)
TECH_INSTALL_FRAC_RANGE = (0.025, 0.037)
TECH_OPERATING_COST_RANGE = (0.150, 0.4)
STOCK_COST_BASE = 0.01
SELLING_PRICE_RANGE = (23.0, 37.0)
RECOVERY_COST_FRACTION_RANGE = (0.005, 0.5)
RAW_MATERIAL_COST_RANGE = (0.01, 0.27)
DISTANCE_RANGE = (10.0, 750.0)
# c_area_i (USD/m^2): the sole factory/warehouse installation cost, charged
# on the installed floor area YC_i, with no separate fixed opening cost --
# matches Mota et al. (2018)/Tautenhain et al. (2021), whose model prices
# facility installation exclusively as sqmc_i * YC_i. Range taken directly
# from their Table 8 "Construction cost, sqmc_i" column (Bulgaria 270 to
# Germany 661 USD/m^2).
AREA_INSTALLATION_COST_RANGE = (270.0, 661.0)

# Tautenhain-based: transport assumptions and case-study coefficients.
TRUCK_CAPACITY_KG_RANGE = (3500.0, 5500.0)
AIR_CAPACITY_KG = 40000.0
SEA_CAPACITY_KG = 50000.0
TRUCK_FIXED_COST_RANGE = (30000.0, 50000.0)
CONTRACTED_FIXED_COST_RANGE = (7200.0, 14400.0)
HUB_HANDLING_COST_RANGE = (0.075, 0.150)
FUEL_PRICE = 1.7
VEHICLE_MAINTENANCE_COST = 0.3
TRUCK_CONSUMPTION_RANGE = (14.0, 18.0)
TRUCK_RETURN_DISTANCE_FACTOR = 2.0
TRUCK_SPEED_KM_H = 60.0
MAX_DRIVING_HOURS_PER_WEEK = 45.0
WEEKS_PER_PERIOD = 17.33
WEEKLY_WORKING_HOURS = 40.0
MAX_DRIVING_HOURS_PER_PERIOD = round(MAX_DRIVING_HOURS_PER_WEEK * WEEKS_PER_PERIOD, 4)
# Direct kg.km transport cost coefficients from Tautenhain Table 8 / 19.
AIR_COST_PER_KGKM = 0.04
SEA_COST_PER_KGKM = 0.01

# Tautenhain-based: climate-change environmental coefficients.
ENTITY_INSTALL_EMISSION_PER_AREA = 3.7791e02
PROCESS_EMISSION_RANGE_PER_KG_MASS = (1.0286e02, 5.3629e02)
SUPPLIER_ACQUISITION_EMISSION_RANGE_PER_KG = PROCESS_EMISSION_RANGE_PER_KG_MASS
TRANSPORT_EMISSION_RANGE_PER_KGKM = (1.0890e-05, 1.8013e-03)
TRANSPORT_MIN_CAPACITY_KG = 0.0
CONTRACTED_CAPACITY_KG = 300000.0
MAX_ENTITY_FLOW_KG = 7000000.0
TRUCK_INVESTMENT_BUDGET = 2.0e6

MODE_FAMILIES = ("truck", "air", "sea")
MODE_FAMILY_ALIASES = {
    "truck": "truck",
    "road": "truck",
    "land": "truck",
    "lorry": "truck",
    "air": "air",
    "plane": "air",
    "airplane": "air",
    "airport": "air",
    "sea": "sea",
    "boat": "sea",
    "ship": "sea",
    "marine": "sea",
    "seaport": "sea",
}
MODE_FAMILY_PREFIXES = (
    ("mrd", "truck"),
    ("truck", "truck"),
    ("road", "truck"),
    ("land", "truck"),
    ("lorry", "truck"),
    ("plane", "air"),
    ("airplane", "air"),
    ("ma", "air"),
    ("air", "air"),
    ("boat", "sea"),
    ("ship", "sea"),
    ("ms", "sea"),
    ("sea", "sea"),
)


def ceil_nonnegative(value: float) -> int:
    return int(math.ceil(max(0.0, value)))


def normalize_mode_family(raw: Any) -> str | None:
    if raw is None:
        return None
    key = str(raw).strip().lower()
    family = MODE_FAMILY_ALIASES.get(key)
    if family is not None:
        return family
    for prefix, prefix_family in MODE_FAMILY_PREFIXES:
        if key.startswith(prefix):
            return prefix_family
    return None


def resolve_mode_family(label: str, option: dict[str, Any], *, fallback_index: int) -> str:
    for key in (
        "tautenhain_mode_family",
        "mode_family",
        "transport_family",
        "family",
        "type",
    ):
        normalized = normalize_mode_family(option.get(key))
        if normalized is not None:
            return normalized

    label_family = normalize_mode_family(label)
    if label_family is not None:
        return label_family

    return MODE_FAMILIES[fallback_index % len(MODE_FAMILIES)]


def sample_inventory_capacity_for_product(
    rng: random.Random,
    per_period_customer_demand: list[float],
) -> float:
    estimates = [
        ceil_nonnegative(
            INVENTORY_FRAC_MAX * demand_t + rng.uniform(0.0, demand_t)
        )
        for demand_t in per_period_customer_demand
    ]
    return float(max(estimates, default=0))


def sample_minimum_inventory(*, capacity: float) -> float:
    return round(INVENTORY_FRAC_MIN * capacity, 2)


def sample_return_lag_period(rng: random.Random, *, planning_periods: int) -> int:
    if planning_periods <= 0:
        raise ValueError("planning_periods must be positive")
    lower, upper = RETURN_LAG_RANGE
    return rng.randint(lower, min(upper, planning_periods))


def sample_technology_capacity(
    rng: random.Random,
    demand_loads: list[float],
    *,
    facility_count: int,
) -> float:
    if facility_count <= 0:
        raise ValueError("facility_count must be positive")
    if not demand_loads:
        return 0.0
    scaled_loads = [
        rng.uniform(*TECH_CAPACITY_MULTIPLIER_RANGE) * ceil_nonnegative(load / float(facility_count))
        for load in demand_loads
    ]
    return round(max(scaled_loads), 2)


def sample_technology_install_cost(rng: random.Random, *, capacity: float) -> float:
    return round(rng.uniform(*TECH_INSTALL_FRAC_RANGE) * capacity, 2)


def sample_minimum_technology_use(*, capacity: float) -> float:
    return round(TECH_MIN_CAPACITY_FRAC * capacity, 2)


def sample_supplier_minimum_order(rng: random.Random, *, capacity: float) -> float:
    lower = SUPPLIER_MIN_FRACTION_RANGE[0] * capacity
    upper = SUPPLIER_MIN_FRACTION_RANGE[1] * capacity
    return round(rng.uniform(lower, upper), 4)


def sample_raw_material_cost(rng: random.Random) -> float:
    return round(rng.uniform(*RAW_MATERIAL_COST_RANGE), 4)


def sample_supplier_selection_cost(rng: random.Random) -> float:
    return round(rng.uniform(*SUPPLIER_SELECTION_FIXED_COST_RANGE), 2)


def sample_selling_price(rng: random.Random) -> float:
    return round(rng.uniform(*SELLING_PRICE_RANGE), 2)


def sample_recovery_cost(
    rng: random.Random,
    *,
    remanufacturing_bom: float,
    selling_price: float,
) -> float:
    return round(
        remanufacturing_bom
        * selling_price
        * rng.uniform(*RECOVERY_COST_FRACTION_RANGE),
        4,
    )


def sample_area_installation_cost(rng: random.Random) -> float:
    return round(rng.uniform(*AREA_INSTALLATION_COST_RANGE), 2)


def sample_distance_km(rng: random.Random, *, lower: float, upper: float) -> float:
    if lower < 0.0 or upper < lower:
        raise ValueError("distance bounds must be nonnegative and ordered")
    return round(rng.uniform(lower, upper), 3)


def sample_transport_capacity_kg(rng: random.Random, family: str) -> float:
    if family == "truck":
        return rng.uniform(*TRUCK_CAPACITY_KG_RANGE)
    if family == "air":
        return AIR_CAPACITY_KG
    if family == "sea":
        return SEA_CAPACITY_KG
    raise ValueError(f"Unsupported transport family: {family}")


def sample_transport_fixed_cost(rng: random.Random, family: str) -> float:
    if family == "truck":
        return round(rng.uniform(*TRUCK_FIXED_COST_RANGE), 2)
    if family in {"air", "sea"}:
        # No separate per-mode fixed cost for outsourced air/sea modes: Tautenhain's
        # generator only randomizes a single contracted fee, attached to the hub
        # entity (sample_hub_operating_cost / f_h), matching Mota et al.'s cfp_i,
        # which covers "the allocated transportation capacity and/or hub terminal
        # use" as one payment. A nonzero value here would double-charge that fee.
        return 0.0
    raise ValueError(f"Unsupported transport family: {family}")


def sample_hub_operating_cost(rng: random.Random) -> float:
    return round(rng.uniform(*CONTRACTED_FIXED_COST_RANGE), 2)


def sample_hub_handling_cost(rng: random.Random, family: str) -> float:
    if family == "truck":
        return 0.0
    if family in {"air", "sea"}:
        return round(rng.uniform(*HUB_HANDLING_COST_RANGE), 4)
    raise ValueError(f"Unsupported transport family: {family}")


def sample_transport_cost_per_kg_km(
    rng: random.Random,
    family: str,
    *,
    capacity_kg: float,
) -> float:
    if capacity_kg <= 0.0:
        raise ValueError("capacity_kg must be positive")

    if family == "truck":
        consumption = rng.uniform(*TRUCK_CONSUMPTION_RANGE)
        vehicle_cost_per_km = (consumption / 100.0) * FUEL_PRICE + VEHICLE_MAINTENANCE_COST
        return round(vehicle_cost_per_km / capacity_kg, 6)
    if family == "air":
        return round(AIR_COST_PER_KGKM, 6)
    if family == "sea":
        return round(SEA_COST_PER_KGKM, 6)
    raise ValueError(f"Unsupported transport family: {family}")
