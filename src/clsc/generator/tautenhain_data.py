from __future__ import annotations

import math
import random
from typing import Any

from clsc.config.constants import WEEKS_PER_YEAR

# Tautenhain-based: generator constants.
DEMAND_RANGE = (8336.8, 34481.28)
RETURN_RATE_UPPER_BOUND = 0.15
RETURN_RATE_RANGE = (0.0, RETURN_RATE_UPPER_BOUND)
# ret_min_frac_r_p_t (mandatory minimum collection) is a hard lower bound on the recovered-
# product flow network, independent of routing/connectivity, so sampling it arbitrarily close
# to ret_max_frac_r_p_t risks several retailers landing near-simultaneously near their ceiling
# in the same period purely by chance -- a compounding network-flow infeasibility unrelated to
# instance size (confirmed via Gurobi IIS on STD_I17_M8_T6/STD_I25_M8_T3, 2026-06-26). Capping
# the minimum at half the max keeps real optimizer slack regardless of how the independent draws
# land.
RETURN_MIN_RATE_DAMPING = 0.5
RETURN_LAG_RANGE = (1, 3)
BOM_PROD_RANGE = (0.015, 0.45)
BOM_REM_RANGE = (4.0, 5.0)
RAW_WEIGHT_RANGE = (0.1, 0.9)
RAW_AREA_RANGE = (0.001, 0.004)
INVENTORY_FRAC_MAX = 0.5
INVENTORY_FRAC_MIN = 0.01
# PRODUCT_ROTATION_PER_PERIOD is derived further down, beside WEEKS_PER_PERIOD:
# it is a per-period quantity and belongs with the temporal basis it depends on.
TECH_CAPACITY_MULTIPLIER_RANGE = (2.0, 4.0)
TECH_MIN_CAPACITY_FRAC = 0.0005
FACTORY_AREA_MAX_RANGE = (10000.0, 12500.0)
WAREHOUSE_AREA_MAX_RANGE = (4000.0, 4750.0)
FACTORY_AREA_MIN_RANGE = (2000.0, 2500.0)
WAREHOUSE_AREA_MIN_RANGE = (500.0, 750.0)
SUPPLIER_MIN_FRACTION_RANGE = (0.00001, 0.0001)
# Selecting a supplier is FREE, and deliberately so: neither source prices it.
# Mota's FCI_1 (eq. 45) covers only factories and warehouses; his fixed- and
# area-crew terms (eq. 43, terms 10-11) and Tautenhain's wi_i / wpsq_i are
# likewise scoped to I_f u I_w, and Mota's Table 7 lists worker counts for
# factories and warehouses only. A supplier carries just the per-unit rmc_su,
# plus a driver's wage when a truck is based there (eq. 43 term 13, the one
# labour term that does range over all of I). All the economic content of
# selecting supplier s sits in the minimum order above.
#
# A fixed selection cost of U[1000, 5000] was generated here until 2026-08-11.
# It had no counterpart in either source, and it taxed supplier switching --
# which is one of the follower's abatement channels, since e_raw_s_u is drawn
# per supplier and per material, so suppliers differ in carbon intensity.
TECH_INSTALL_FRAC_RANGE = (0.025, 0.037)
TECH_OPERATING_COST_RANGE = (0.150, 0.4)
STOCK_COST_BASE = 0.01
SELLING_PRICE_RANGE = (23.0, 37.0)
RECOVERY_COST_FRACTION_RANGE = (0.005, 0.5)
RAW_MATERIAL_COST_RANGE = (0.01, 0.27)
DISTANCE_RANGE = (10.0, 750.0)
# c_area_i (USD/m^2): the sole factory/warehouse installation cost, charged on
# the installed floor area YC_i, with no separate fixed opening cost. Both
# sources price facility installation exclusively as sqmc_i * YC_i. The range
# is Mota et al. (2018) Table 8, "Construction cost, sqmc_i", whose ten
# countries span Bulgaria 270 to Germany 661 USD/m^2.
#
# We follow Mota's per-square-metre rates and NOT Tautenhain et al.'s
# generator, which draws
#
#     sqmc_i ~ U[0.5 * lc_i * eamax_i,  50 + 1.25 * lc_i * eamax_i]
#
# and reports the result as a total in EUR rather than a rate per m^2. This is
# a documented divergence, not an unresolved choice between two usable
# conventions, for three reasons in order of weight:
#
#  1. As published it does not reproduce. Checked against their own
#     illustrative example (supplementary Tables 6 and 7), all three
#     facilities fall BELOW the formula's own lower bound -- factory 35,448
#     against a bound of 70,896; warehouses 6,505 against 25,203 and 13,009 --
#     and the two warehouses report an identical cost despite different lc_i
#     and eamax_i. Their code may do something else; only the published
#     specification can be worked from here.
#  2. It does not close dimensionally. Read as a total in EUR, sqmc_i * YC_i
#     carries units of EUR*m^2, yet Mota's equation is inherited unchanged.
#  3. The scales are irreconcilable under either reading: an 11,016 m^2
#     factory costs 2.97-7.28 MEUR at Mota's rates and 35,448 EUR in their
#     example, two orders of magnitude apart.
#
# The idea underneath -- that construction tracks the local wage -- is real
# but weak in Mota's own data, where sqmc_i / lc_i runs from 17.8 (Spain) to
# 73.0 (Bulgaria), a factor of four. Adopting the idea while repairing the
# scale would mean inventing a third convention with no source, which is the
# defect just removed from the supplier selection cost. Mota's tabulated rates
# close dimensionally, come from ten real countries, and reproduce his
# published capital-to-labour balance to within 7% -- asserted in
# tests/test_capital_charge.py, not merely claimed here.
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
# ANNUAL discount rate on every recurring monetary flow. Mota et al. (2018)
# eq. 41 maximises NPV = sum_t CF_t / (1+ir)^t - sum_g FCI_g and calibrates
# ir = 10% for a model whose periods are years; his depreciation schedule
# corroborates the basis (5%/12.5%/20% per period are 20-, 8- and 5-year asset
# lives). Tautenhain et al. list the same value among "the remaining
# parameters of the model studied by Mota et al. (2018)" without rescaling it
# to their 17.33-week periods, where it would compound to 33.1% a year.
#
# This module keeps the published value and treats it as annual;
# clsc.models.supply_chain.discount_factors compounds it to the period length.
# Capital is charged as a per-period rental over its asset life, not bought
# outright at t=0 (see ASSET_LIFE_YEARS below); emissions are
# NOT discounted -- Mota's environmental objective (eq. 46) is a plain sum
# over t -- but the carbon-tax payment is, because it is money.
#
# Tautenhain's data also fixes salvage value sv = 0.2 and corporate tax rate
# tx = 0.3, likewise annual and likewise not modelled here yet (no salvage
# recovery in the final period, no depreciation tax shield).
INTEREST_RATE = 0.10

# One planning period is 17.33 weeks (~4 months, 52/3), the value published in
# Tautenhain et al.'s generator data ("number of weeks per time period
# wpt = 17.33"). Their generator DEPARTS from Mota et al. (2018) here, whose
# case study runs a ten-year horizon with yearly increments (wpt = 52). This
# module follows the generator, so T in {3, 6, 12} spans 1, 2 and 4 years and
# every per-period quantity below is a per-four-month quantity.
#
# mhw = 45 h/week is the EU driving-time limit Mota cites (his eq. 29
# denominator is avs * mhw * wpt), giving 779.85 h per vehicle per period.
MAX_DRIVING_HOURS_PER_WEEK = 45.0
WEEKS_PER_PERIOD = 17.33
# wwh = 40 weekly working hours (Tautenhain). Combined with wpt this gives
# 693.2 paid hours per worker per period -- exactly a full-time year over the
# three periods that make up 12 months.
WEEKLY_WORKING_HOURS = 40.0
YEARS_PER_PERIOD = WEEKS_PER_PERIOD / WEEKS_PER_YEAR

# Mota et al. (2018) size the flow component of floor area as
# apur_m = apu_m / 4.5 and state the basis outright: "apur_m is obtained
# assuming a product rotation of 4.5 times PER YEAR" (p. 42). His periods are
# years, so the two agree. Tautenhain's generator carries no apur at all, only
# apu, and so settles nothing either way.
#
# Our periods are a third of a year, which gives 1.5 turns per period. This is
# the same annual-to-period conversion applied to the interest rate in
# clsc.models.supply_chain.discount_factors, and consistency demands the same
# answer here. Until 2026-08-11 the 4.5 was read as a per-period count, which
# assumed three times the real turnover and so understated, by that same
# factor, the floor area each unit of throughput demands.
PRODUCT_ROTATION_PER_YEAR = 4.5
PRODUCT_ROTATION_PER_PERIOD = round(PRODUCT_ROTATION_PER_YEAR * YEARS_PER_PERIOD, 6)

# Straight-line asset lives in years, recovered from Mota's own depreciation
# schedule (Tautenhain et al. supplementary material, Table 20) read together
# with his salvage values. Over that ten-year, yearly-period case study:
#
#   class          rate/period   x10 periods   salvage   total
#   entities       0.05          0.50          0.50      1.00
#   technologies   0.125         1.00          0.00      1.00
#   transport      0.20          1.00          0.00      1.00
#
# Depreciation plus salvage exhausts the asset in every class, so sv is not a
# free parameter: it is the book value still unconsumed at the horizon. The
# invariant underneath is the life 1/rate -- 20, 8 and 5 years -- and that is
# what transfers to a horizon of a different length. See
# clsc.models.supply_chain.capital_multipliers for how it is charged.
ASSET_LIFE_YEARS = {"facility": 20.0, "technology": 8.0, "vehicle": 5.0}

# ---------------------------------------------------------------------------
# Labour (Mota et al. 2018, eq. 43, terms 10-13; Tautenhain generator Table 5)
#
# Four recurring labour costs attach to network-DESIGN variables: a fixed crew
# per opened facility, a crew proportional to installed floor area, a crew per
# installed technology, and a crew per owned vehicle. Each is charged every
# period as workers * lc_i * wwh * wpt.
#
# These dominate: at lc = 17 EUR/h a 10,000 m^2 factory carries 100 workers,
# i.e. ~1.18 MEUR per period in area-proportional labour alone. That is by
# design -- labour is a first-order cost in Mota's formulation, not a
# correction -- but it restructures the capital/operating balance the carbon
# tax acts on.
# ---------------------------------------------------------------------------
LABOUR_COST_RANGE = (3.5, 30.4)          # lc_i, EUR per hour
FIXED_WORKERS_FACTORY_RANGE = (1, 2)     # wi_i, factories
FIXED_WORKERS_WAREHOUSE_RANGE = (1, 2)   # wi_i, warehouses
WORKERS_PER_SQM = 0.01                   # wpsq_i, workers per m^2
# wg_g = fracwg * ceil(opc_g); opc_g lies in [0.15, 0.4], so the ceiling is 1
# and every technology carries exactly fracwg workers.
TECH_WORKERS_FACTOR = 10
# wa_a: one driver per truck; outsourced carriers employ their own crews, so
# air and sea modes contribute no labour cost to the operator.
TRUCK_WORKERS_PER_VEHICLE = 1.0
OUTSOURCED_WORKERS_PER_VEHICLE = 0.0
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


def sample_selling_price(rng: random.Random) -> float:
    return round(rng.uniform(*SELLING_PRICE_RANGE), 2)


def sample_area_installation_cost(rng: random.Random) -> float:
    return round(rng.uniform(*AREA_INSTALLATION_COST_RANGE), 2)


def sample_labour_cost(rng: random.Random) -> float:
    """lc_i: hourly labour cost at an entity's location (Tautenhain Table 5)."""
    return round(rng.uniform(*LABOUR_COST_RANGE), 4)


def sample_fixed_workers(rng: random.Random, *, factory: bool) -> int:
    """wi_i: crew required to keep a facility running, independent of size."""
    lower, upper = FIXED_WORKERS_FACTORY_RANGE if factory else FIXED_WORKERS_WAREHOUSE_RANGE
    return rng.randint(lower, upper)


def technology_workers(operating_cost: float) -> int:
    """wg_g = fracwg * ceil(opc_g) (Tautenhain generator, Table 2)."""
    return TECH_WORKERS_FACTOR * ceil_nonnegative(operating_cost)


def mode_workers(family: str) -> float:
    """wa_a: crew per owned vehicle; zero for outsourced carriers."""
    return TRUCK_WORKERS_PER_VEHICLE if family == "truck" else OUTSOURCED_WORKERS_PER_VEHICLE


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
