"""The case study of Mota et al. (2018) as an instance of this model.

Sources, cited at each table below:
- Mota, Gomes, Carvalho and Barbosa-Povoa (2018), "Sustainable supply chains: an integrated modeling
  approach under uncertainty", Omega 77, 32-57 ("Mota").
- Tautenhain, Barbosa-Povoa, Mota and Nascimento (2020), "Data for: An efficient Lagrangian-based
  heuristic ...", Mendeley Data, doi 10.17632/f82by28vnm.2, section 3 ("Tautenhain data"), which
  publishes the case's demand, distances and environmental factors that Mota leaves to supplementary
  material.

Where the two disagree, Mota is followed (see CONFLICTS). What neither states is assumed (see
ASSUMPTIONS). Both lists are written into the instance's metadata.

Quantities of items are in thousands of units (QUANTITY_UNIT): the tables are transcribed as published,
in units, and converted at the end (in_thousands). In units the follower's matrix spans 1e0 to 6e6 and
the solver's tolerances are no longer met; in thousands, per-unit costs, weights and areas grow by the
same factor and the quantities shrink by it, which leaves every cost and emission unchanged.

    python -m clsc.generator.mota2018 [--output data/case_study/MOTA2018.json]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from clsc.models.instance_data import InstanceData

CONFLICTS = [
    "Production bill of materials: Mota Table 2 (it agrees with Mota Fig. 3); the Tautenhain data Table 15 "
    "swaps the columns of gp1alt and gp2.",
    "Operating cost of gp2: 0.324 EUR/unit (Mota Table 4); the Tautenhain data Table 14 gives 0.314.",
    "Minimum order at the Hannover and Leeds suppliers: 1000/1000/200/1000 units (Mota Table 5); the "
    "Tautenhain data Table 17 gives 0.",
    "Minimum warehouse stock: 12000 (fp1) and 10000 (fp2) units (Mota Table 9 and the Tautenhain data text); "
    "the Tautenhain data Table 18 shows 391.",
    "Remanufacturing climate-change factors: 134 (gr1) and 103 (gr2) kg CO2e/kg (Tautenhain data Table 24), "
    "25% and 20% of gp1 and gp2; Mota's text says 25% and 20% lower. Table 24's values reproduce Mota's own "
    "results (Table B.2.1, case A, climate change of fp1 production and remanufacturing).",
    "Construction cost in Verona (F1, W1): none, the facilities already exist (Mota Table 8, note a); the "
    "Tautenhain paper's Table 7 gives 595 EUR/m2.",
]

ASSUMPTIONS = [
    "Weeks per period: 52 (Mota's periods are years; the 17.33 of the Tautenhain data's section 1 is the "
    "generator's period). It sets the labour cost per period and the trucks' driving hours (45 h x 52).",
    "Labour cost (Mota Table 8) in EUR per hour; the table states no unit.",
    "Returns: at least 15% (Mota's RetF) and at most 100% (Mota eq. 9) of the previous year's deliveries, one "
    "recovered product per final product returned (Mota's BOM^recov, whose value is not published).",
    "Node flow capacity (Mota eq. 12-13; 7,000,000 in the Tautenhain data's section 1) is not imposed, as in "
    "the generated instances.",
    "Fuel price 1.7 EUR/l, maintenance 0.3 EUR/km and the truck investment ceiling of 2,000,000 EUR are the "
    "fixed values in the Tautenhain data's section 1 (Mota gives them in supplementary material).",
    "Raw-material acquisition emissions: none (Mota's environmental objective has no supplier term).",
    "Mota's objective is the NPV after a 30% profit tax, with salvage values; this model minimises cost "
    "(capital at its rental equivalent over the asset lives of Mota Table 20) plus the carbon tax, and taxes "
    "the climate-change category only, with construction emissions amortised over 20 years.",
    "Warehouse transhipment (Mota: allowed) is given arcs for final and recovered products alike.",
]

# ---------------------------------------------------------------------------------------- entities
# Mota Table 1 and Table 8 (country of each entity).
SUPPLIERS = {"s1": "Verona", "s2": "Hannover", "s3": "Leeds"}
FACTORIES = {"f1": "Verona", "f2": "Hannover", "f3": "Leeds"}
WAREHOUSES = {
    "w1": "Verona", "w2": "Hannover", "w3": "Leeds", "w4": "Zaragoza", "w5": "Lisbon",
    "w6": "Sao Paulo", "w7": "Recife", "w8": "Budapest", "w9": "Sofia",
}
MARKETS = {"r1": "Italy", "r2": "Germany", "r3": "United Kingdom", "r4": "Spain", "r5": "Portugal",
           "r6": "Sao Paulo", "r7": "Recife"}
AIRPORTS = {"air1": "Zaragoza", "air2": "Paris-Charles de Gaulle", "air3": "Kortrijk-Wevelgem", "air4": "Sao Paulo"}
SEAPORTS = {"port1": "Hamburg", "port2": "Santos"}

COUNTRY = {
    "s1": "Italy", "f1": "Italy", "w1": "Italy", "r1": "Italy",
    "s2": "Germany", "f2": "Germany", "w2": "Germany", "r2": "Germany", "port1": "Germany",
    "s3": "United Kingdom", "f3": "United Kingdom", "w3": "United Kingdom", "r3": "United Kingdom",
    "w4": "Spain", "r4": "Spain", "air1": "Spain",
    "w5": "Portugal", "r5": "Portugal",
    "w6": "Brazil", "w7": "Brazil", "r6": "Brazil", "r7": "Brazil", "air4": "Brazil", "port2": "Brazil",
    "w8": "Hungary", "w9": "Bulgaria", "air2": "France", "air3": "Belgium",
}
# Mota Table 8: average labour cost (EUR/h, assumed) and construction cost (EUR/m2) per country.
LABOUR_COST = {"Brazil": 8.98, "Bulgaria": 3.7, "Hungary": 7.5, "Portugal": 12.2, "Spain": 21.0, "Italy": 28.1,
               "United Kingdom": 15.3, "France": 32.4, "Belgium": 37.2, "Germany": 30.4}
CONSTRUCTION_COST = {"Brazil": 538.0, "Bulgaria": 270.0, "Hungary": 282.0, "Portugal": 318.0, "Spain": 373.0,
                     "United Kingdom": 601.0, "Germany": 661.0, "Italy": 0.0}  # Italy: F1, W1 already exist

# ------------------------------------------------------------------------------------------ items
# Mota Table 3 (and Tautenhain data Table 13): weight (kg), area per unit (m2), costs (EUR).
RAW_MATERIALS = {"u1": "rm1", "u2": "rm2", "u3": "rm3", "u4": "rm4"}
PRODUCTS = {"p1": "fp1", "p2": "fp2"}
RECOVERED = {"rp1": "rp1", "rp2": "rp2"}
RETURNED_AS = {"rp1": "p1", "rp2": "p2"}  # the recovered product each final product becomes
WEIGHT = {"u1": 0.118, "u2": 0.184, "u3": 0.365, "u4": 0.913, "p1": 0.4, "p2": 0.5, "rp1": 0.4, "rp2": 0.5}
AREA = {"u1": 0.002, "u2": 0.001, "u3": 0.004, "u4": 0.003, "p1": 0.007, "p2": 0.009, "rp1": 0.007, "rp2": 0.009}
INVENTORY_COST = {"p1": 0.01, "p2": 0.01}
RECOVERY_COST = {"rp1": 0.15, "rp2": 0.15}
ROTATIONS_PER_YEAR = 4.5  # Mota section 5.1: apur from a product rotation of 4.5 times per year

# ----------------------------------------------------------------------------------- technologies
# Mota Table 4: max capacity, min level (units per period), installation cost, operating cost (EUR/unit),
# workers. Products: Mota Fig. 3.
PRODUCTION = {
    "gp1": dict(product="p1", cap=5_800_000, min=30_000, install=150_000, operate=0.212, workers=2),
    "gp1alt": dict(product="p1", cap=6_000_000, min=30_000, install=175_000, operate=0.196, workers=1),
    "gp2": dict(product="p2", cap=4_600_000, min=30_000, install=167_000, operate=0.324, workers=4),
    "gp2alt": dict(product="p2", cap=5_200_000, min=30_000, install=186_000, operate=0.267, workers=3),
}
REMANUFACTURING = {
    "gr1": dict(product="p1", recovered="rp1", units=4.0, cap=2_900_000, min=0, install=50_000, operate=0.116, workers=1),
    "gr2": dict(product="p2", recovered="rp2", units=5.0, cap=2_300_000, min=0, install=45_000, operate=0.134, workers=1),
}
# Mota Table 2: raw materials per unit of product, by technology.
BILL = {
    "u1": {"gp1": 0.25, "gp1alt": 0.45, "gp2": 0.25, "gp2alt": 0.42},
    "u2": {"gp1": 0.3, "gp1alt": 0.4, "gp2": 0.3, "gp2alt": 0.2},
    "u3": {"gp1": 0.15, "gp1alt": 0.025, "gp2": 0.05, "gp2alt": 0.015},
    "u4": {"gp1": 0.3, "gp1alt": 0.42, "gp2": 0.2, "gp2alt": 0.3},
}
# Tautenhain data Table 24, climate change (kg CO2e per kg produced or remanufactured).
TECHNOLOGY_CC = {"gp1": 536.0, "gp1alt": 375.0, "gp2": 514.0, "gp2alt": 411.0, "gr1": 134.0, "gr2": 103.0}

# ------------------------------------------------------------------------------------- suppliers
# Mota Table 5: maximum supply, minimum order (units per period) and cost (EUR/unit).
SUPPLY = {
    "s1": {"u1": (3_600_000, 1000, 0.01), "u2": (3_600_000, 1000, 0.025), "u3": (1_000_000, 200, 0.03), "u4": (4_000_000, 1000, 0.09)},
    "s2": {"u1": (3_800_000, 1000, 0.035), "u2": (3_800_000, 1000, 0.0875), "u3": (1_200_000, 200, 0.105), "u4": (5_000_000, 1000, 0.315)},
    "s3": {"u1": (3_800_000, 1000, 0.03), "u2": (3_800_000, 1000, 0.075), "u3": (1_200_000, 200, 0.09), "u4": (5_000_000, 1000, 0.27)},
}

# ------------------------------------------------------------------------------------ facilities
# Mota Table 6 (areas, m2), Table 7 (workers), Table 9 (inventory) and section 5.2.2 (F1, W1 exist).
FACTORY_AREA = {"f1": (20_000, 20_000), "f2": (2_000, 25_000), "f3": (2_000, 25_000)}
WAREHOUSE_AREA = {"w1": (5_000, 5_000), **{w: (500, 8_000) for w in WAREHOUSES if w != "w1"}}
EXISTING = {"f1": 20_000, "w1": 5_000}
FIXED_WORKERS = {"factory": 11, "warehouse": 9}
WORKERS_PER_M2 = 0.01
STOCK_MAX = {"p1": 1_200_000, "p2": 1_000_000}
STOCK_MIN = {"p1": 12_000, "p2": 10_000}
INITIAL_STOCK = {"w1": {"p1": 196_000, "p2": 84_000}}
INSTALLATION_CC = 378.0  # Tautenhain data Table 23, kg CO2e per m2

# ------------------------------------------------------------------------------------- transport
# Tautenhain data Table 19 (capacities in units, as Mota eq. 24-28) and section 1 (fuel, maintenance).
FUEL_PRICE, MAINTENANCE = 1.7, 0.3
MODES = {
    "truck1": dict(family="truck", capacity=35_000, minimum=200, fixed=30_000, litres_per_100km=14, cc=1.80e-3),
    "truck2": dict(family="truck", capacity=55_000, minimum=200, fixed=50_000, litres_per_100km=18, cc=4.34e-4),
    "plane": dict(family="air", capacity=400_000, minimum=1000, contracted=3_000_000, per_kg_km=0.04, cc=1.03e-3),
    "ship": dict(family="sea", capacity=500_000, minimum=1000, contracted=3_000_000, per_kg_km=0.01, cc=1.09e-5),
}
# Table 19: contracted payment per period (EUR) and handling per unit (EUR) at each hub.
HUB_FIXED = {"air1": 216_000, "air2": 252_000, "air3": 252_000, "air4": 144_000, "port1": 288_000, "port2": 144_000}
HUB_HANDLING = {"air1": 0.100, "air2": 0.125, "air3": 0.125, "air4": 0.075, "port1": 0.150, "port2": 0.075}
SPEED_KM_H, DRIVING_HOURS_PER_WEEK, WEEKS_PER_PERIOD, WEEKLY_WORKING_HOURS = 60.0, 45.0, 52.0, 40.0
TRUCK_INVESTMENT_CEILING = 2_000_000.0

# --------------------------------------------------------------------------------------- demand
# Tautenhain data Table 21: units per year, markets in the order of Mota Table 1 (C1..C7).
DEMAND = {
    "p1": {
        "r1": [2873448, 2077056, 2527512, 2761104, 2873448, 2077056, 2527512, 2761104, 2873448, 2077056],
        "r2": [1789152, 2125200, 1963824, 1731192, 1789152, 2125200, 1963824, 1731192, 1789152, 2125200],
        "r3": [1138848, 1940424, 1693848, 1730232, 1138848, 1940424, 1693848, 1730232, 1138848, 1940424],
        "r4": [1221432, 1706760, 1416312, 1413504, 1221432, 1706760, 1416312, 1413504, 1221432, 1706760],
        "r5": [1128840, 1147512, 1180632, 1291368, 1128840, 1147512, 1180632, 1291368, 1128840, 1147512],
        "r6": [919464, 1414368, 1014696, 1146216, 919464, 1414368, 1014696, 1146216, 919464, 1414368],
        "r7": [1443216, 1513152, 1676112, 1217544, 1443216, 1513152, 1676112, 1217544, 1443216, 1513152],
    },
    "p2": {
        "r1": [1518120, 2017416, 1502280, 2114616, 1518120, 2017416, 1502280, 2114616, 1518120, 2017416],
        "r2": [1570152, 1836480, 1396152, 1962480, 1570152, 1836480, 1396152, 1962480, 1570152, 1836480],
        "r3": [1033632, 1229904, 1259544, 1554048, 1033632, 1229904, 1259544, 1554048, 1033632, 1229904],
        "r4": [825308, 706380, 785482, 769706, 825308, 706380, 785482, 769706, 825308, 706380],
        "r5": [1065288, 1055544, 936192, 1100112, 1065288, 1055544, 936192, 1100112, 1065288, 1055544],
        "r6": [1390704, 1251432, 991992, 1570176, 1390704, 1251432, 991992, 1570176, 1390704, 1251432],
        "r7": [833688, 1362000, 1547280, 1426056, 833688, 1362000, 1547280, 1426056, 833688, 1362000],
    },
}
PERIODS = [f"t{k}" for k in range(1, 11)]
RETURN_MIN, RETURN_MAX = 0.15, 1.0

# ------------------------------------------------------------------------------------ distances
# Tautenhain data Table 22 (km); None where the table shows "-" (no connection). Columns in this order:
COLUMNS = ["f1", "f2", "f3", "w1", "w2", "w3", "w4", "w5", "w6", "w7", "w8", "w9",
           "r1", "r2", "r3", "r4", "r5", "r6", "r7", "air1", "air2", "air3", "air4", "port1", "port2"]
_ = None
DISTANCE_ROWS = {
    "s1": [5, 1031, 1637] + [_] * 22,
    "s2": [1031, 7, 1120] + [_] * 22,
    "s3": [1637, 1120, 4] + [_] * 22,
    "f1": [0, 1031, 1637, 5, 1031, 1637, 1417, 2276, _, _, 807, 1261, 10, 1031, 1637, 1417, 2276, _, _, 1419, 1021, 1151, _, 1186, _],
    "f2": [1031, 0, 1120, 1031, 5, 1120, 1841, 2500, _, _, 1031, 1793, 1031, 10, 1120, 1841, 2500, _, _, 1859, 758, 543, _, 152, _],
    "f3": [1637, 1120, 0, 1637, 1120, 5, 1831, 2494, _, _, 2029, 2743, 1637, 1120, 10, 1831, 2494, _, _, 1833, 738, 594, _, 1236, _],
    "w1": [5, 1031, 1637, 0, 1031, 1637, 1417, 2276, _, _, 807, 1261, 10, 1031, 1637, 1417, 2276, _, _, 1419, 1021, 1151, _, 1186, _],
    "w2": [1031, 5, 1120, 1031, 0, 1120, 1841, 2500, _, _, 1031, 1793, 1031, 10, 1120, 1841, 2500, _, _, 1859, 758, 543, _, 152, _],
    "w3": [1637, 1120, 5, 1637, 1120, 0, 1831, 2494, _, _, 2029, 2743, 1637, 1120, 10, 1831, 2494, _, _, 1833, 738, 594, _, 1236, _],
    "w4": [1417, 1841, 1831, 1417, 1841, 1831, 0, 937, _, _, 2212, 2666, 1417, 1841, 1831, 10, 937, _, _, 13, 1098, 1319, _, 1922, _],
    "w5": [2276, 2500, 2494, 2276, 2500, 2494, 937, 0, _, _, 3075, 3529, 2276, 2500, 2494, 937, 10, _, _, 931, 1756, 1976, _, 2740, _],
    "w6": [_, _, _, _, _, _, _, _, 0, 2130, _, _, _, _, _, _, _, 10, 2130, _, _, _, 5, _, 83],
    "w7": [_, _, _, _, _, _, _, _, 2130, 0, _, _, _, _, _, _, _, 2130, 10, _, _, _, 2130, _, 2130],
    "w8": [807, 1031, 2029, 807, 1031, 2029, 2212, 3075, _, _, 0, 771, 807, 1031, 2029, 2212, 3075, _, _, 2221, 1474, 1453, _, 1145, _],
    "w9": [1261, 1793, 2743, 1261, 1793, 2743, 2666, 3529, _, _, 771, 0, 1261, 1793, 2743, 2666, 3529, _, _, 2675, 2235, 2214, _, 1907, _],
    "r1": [10, 1031, 1637, 10, 1031, 1637, 1417, 2276, _, _, 807, 1261, 0, 1031, 1637, 1417, 2276, _, _, 1419, 1021, 1151, _, 1186, _],
    "r2": [1031, 10, 1120, 1031, 10, 1120, 1841, 2500, _, _, 1031, 1793, 1031, 0, 1120, 1841, 2500, _, _, 1859, 758, 543, _, 152, _],
    "r3": [1637, 1120, 10, 1637, 1120, 10, 1831, 2494, _, _, 2029, 2743, 1637, 1120, 0, 1831, 2494, _, _, 1833, 738, 594, _, 1236, _],
    "r4": [1417, 1841, 1831, 1417, 1841, 1831, 10, 937, _, _, 2212, 2666, 1417, 1841, 1831, 0, 937, _, _, 13, 1098, 1319, _, 1922, _],
    "r5": [2276, 2500, 2494, 2276, 2500, 2494, 937, 10, _, _, 3075, 3529, 2276, 2500, 2494, 937, 0, _, _, 931, 1756, 1976, _, 2740, _],
    "r6": [_, _, _, _, _, _, _, _, 10, 2130, _, _, _, _, _, _, _, 0, 2130, _, _, _, 50, _, 128],
    "r7": [_, _, _, _, _, _, _, _, 2130, 10, _, _, _, _, _, _, _, 2130, 0, _, _, _, 2130, _, 2130],
    "air1": [1419, 1859, 1833, 1419, 1859, 1833, 13, 931, _, _, 2221, 2675, 1419, 1859, 1833, 13, 931, _, _, 0, 1005, 1225, 8644, 1922, _],
    "air2": [1021, 758, 738, 1021, 758, 738, 1098, 1756, _, _, 1474, 2235, 1021, 758, 738, 1098, 1756, _, _, 1005, 0, 228, 9401, 891, _],
    "air3": [1151, 543, 594, 1151, 543, 594, 1319, 1976, _, _, 1453, 2214, 1151, 543, 594, 1319, 1976, _, _, 1225, 228, 0, 9567, 663, _],
    "air4": [_, _, _, _, _, _, _, _, 5, 2130, _, _, _, _, _, _, _, 50, 2130, 8644, 9401, 9567, 0, _, 78],
    "port1": [1186, 152, 1236, 1186, 152, 1236, 1922, 2740, _, _, 1145, 1907, 1186, 152, 1236, 1922, 2740, _, _, 1922, 891, 663, _, 0, 10149],
    "port2": [_, _, _, _, _, _, _, _, 83, 2130, _, _, _, _, _, _, _, 128, 2130, _, _, _, 78, 10149, 0],
}


def distances() -> dict[str, dict[str, float]]:
    table: dict[str, dict[str, float]] = {}
    for origin, row in DISTANCE_ROWS.items():
        assert len(row) == len(COLUMNS), origin
        table[origin] = {destination: float(km) for destination, km in zip(COLUMNS, row) if km is not None}
    return table


def check_transcription() -> None:
    """Consistency checks of the transcribed tables (a typo in a large table should fail here)."""
    table = distances()
    for origin, row in table.items():
        for destination, km in row.items():
            back = table.get(destination, {}).get(origin)
            if origin.startswith("s"):
                continue  # supplier rows have no supplier column
            assert back == km, f"distance {origin}->{destination} = {km} but {destination}->{origin} = {back}"
    for product, by_market in DEMAND.items():
        for market, series in by_market.items():
            assert len(series) == len(PERIODS), (product, market)
            assert series[:4] * 2 + series[:2] == series, f"demand of {product} at {market} is not the 4-year cycle"
    assert all(set(BILL[u]) == set(PRODUCTION) for u in BILL), "every raw material needs a quantity per technology"
    assert set(DEMAND["p1"]) == set(MARKETS) == set(DEMAND["p2"])


def _kind(node: str) -> str:
    for prefix, kind in (("air", "AIR"), ("port", "PORT"), ("s", "S"), ("f", "F"), ("w", "W"), ("r", "R")):
        if node.startswith(prefix):
            return kind
    raise ValueError(node)


# Which items may travel between which kinds of node (Mota section 3 and Fig. 1, eq. 1-6 and 22-23).
FLOW_RULES = {
    "FLOW_RAW": {("S", "F")},
    "FLOW_FP": {("F", "W"), ("F", "R"), ("F", "AIR"), ("F", "PORT"), ("W", "W"), ("W", "R"), ("W", "AIR"),
                ("W", "PORT"), ("AIR", "AIR"), ("PORT", "PORT"), ("AIR", "W"), ("AIR", "R"), ("PORT", "W"),
                ("PORT", "R")},
    "FLOW_RP": {("R", "W"), ("R", "F"), ("R", "AIR"), ("R", "PORT"), ("W", "F"), ("W", "W"), ("W", "AIR"),
                ("W", "PORT"), ("AIR", "AIR"), ("PORT", "PORT"), ("AIR", "W"), ("AIR", "F"), ("PORT", "W"),
                ("PORT", "F")},
}
ARC_SUBSETS = {
    "A_sf": ("S", "F"), "A_fw": ("F", "W"), "A_fr": ("F", "R"), "A_wr": ("W", "R"), "A_rw": ("R", "W"),
    "A_rf": ("R", "F"), "A_wf": ("W", "F"), "A_ww": ("W", "W"), "A_air_air": ("AIR", "AIR"),
    "A_port_port": ("PORT", "PORT"),
}


QUANTITY_UNIT = 1000.0
# Parameters counted in item units (divided by QUANTITY_UNIT) and parameters per item unit (multiplied).
PER_QUANTITY = ("d_r_p_t", "bar_s_s_u", "scmin_s_u", "bar_p_g", "bar_q_l", "pcmin_g", "pcmin_l", "icmax_p_n",
                "icmin_p_n", "i_p_n_0", "bar_X_m", "ctmin_m", "ccamax_m")
PER_UNIT = ("omega_u", "omega_p", "omega_rp", "apu_u", "apu_p", "apu_rp", "c_prod_g", "c_rem_l", "h_p", "rpc_rp",
            "rmc_s_u", "c_handle_h")


def _scale(value, factor: float):
    if isinstance(value, dict):
        return {key: _scale(nested, factor) for key, nested in value.items()}
    return float(value) * factor


def in_thousands(parameters: dict) -> dict:
    """Express item quantities in thousands of units. Ratios between items (bills of materials, return
    fractions), costs per trip, per kg km or per technology, areas, distances and emission factors per kg,
    m2 or kg km do not change."""
    converted = dict(parameters)
    for name in PER_QUANTITY:
        converted[name] = _scale(parameters[name], 1.0 / QUANTITY_UNIT)
    for name in PER_UNIT:
        converted[name] = _scale(parameters[name], QUANTITY_UNIT)
    return converted


def build_instance() -> dict:
    check_transcription()
    table = distances()
    suppliers, factories, warehouses = list(SUPPLIERS), list(FACTORIES), list(WAREHOUSES)
    markets, airports, seaports = list(MARKETS), list(AIRPORTS), list(SEAPORTS)
    hubs = airports + seaports
    nodes = suppliers + factories + warehouses + markets + airports + seaports
    products, raw, recovered = list(PRODUCTS), list(RAW_MATERIALS), list(RECOVERED)
    items = {"FLOW_RAW": raw, "FLOW_FP": products, "FLOW_RP": recovered}

    flows: dict[str, list] = {name: [] for name in FLOW_RULES}
    arcs: list[tuple[str, str]] = []
    for origin in nodes:
        for destination, km in table.get(origin, {}).items():
            if origin == destination:
                continue
            pair = (_kind(origin), _kind(destination))
            used = False
            for name, rule in FLOW_RULES.items():
                if pair in rule:
                    flows[name] += [[item, origin, destination] for item in items[name]]
                    used = True
            if used:
                arcs.append((origin, destination))
    hub_arcs = {
        "A_f_hub": [a for a in arcs if _kind(a[0]) == "F" and a[1] in hubs],
        "A_hub_f": [a for a in arcs if a[0] in hubs and _kind(a[1]) == "F"],
        "A_w_hub": [a for a in arcs if _kind(a[0]) == "W" and a[1] in hubs],
        "A_hub_w": [a for a in arcs if a[0] in hubs and _kind(a[1]) == "W"],
        "A_r_hub": [a for a in arcs if _kind(a[0]) == "R" and a[1] in hubs],
        "A_hub_r": [a for a in arcs if a[0] in hubs and _kind(a[1]) == "R"],
        "A_s_hub": [],
    }
    arc_sets = {name: [list(a) for a in arcs if (_kind(a[0]), _kind(a[1])) == pair] for name, pair in ARC_SUBSETS.items()}
    arc_sets.update({name: [list(a) for a in value] for name, value in hub_arcs.items()})

    modes = list(MODES)
    family = {m: spec["family"] for m, spec in MODES.items()}
    trucks = [m for m in modes if family[m] == "truck"]
    production = list(PRODUCTION)
    remanufacturing = list(REMANUFACTURING)

    # Trips per arc and period cannot exceed the most units any arc can carry: a supplier's whole supply, or
    # everything all factories can make plus the initial stock.
    most_units = max(
        max(sum(capacity for capacity, _, _ in by_material.values()) for by_material in SUPPLY.values()),
        len(factories) * (sum(spec["cap"] for spec in PRODUCTION.values()) + sum(spec["cap"] for spec in REMANUFACTURING.values()))
        + sum(sum(stock.values()) for stock in INITIAL_STOCK.values()),
    )

    def per_market(value: float) -> dict:
        return {r: {p: {t: value for t in PERIODS} for p in products} for r in markets}

    parameters = {
        # costs
        "f_s": {s: 0.0 for s in suppliers},
        "c_area_f": {f: CONSTRUCTION_COST[COUNTRY[f]] for f in factories},
        "c_area_w": {w: CONSTRUCTION_COST[COUNTRY[w]] for w in warehouses},
        "i_prod_g": {g: float(PRODUCTION[g]["install"]) for g in production},
        "i_rem_l": {l: float(REMANUFACTURING[l]["install"]) for l in remanufacturing},
        "c_prod_g": {g: PRODUCTION[g]["operate"] for g in production},
        "c_rem_l": {l: REMANUFACTURING[l]["operate"] for l in remanufacturing},
        "h_p": dict(INVENTORY_COST),
        "rpc_rp": dict(RECOVERY_COST),
        "rmc_s_u": {s: {u: SUPPLY[s][u][2] for u in raw} for s in suppliers},
        # transport
        "mode_family_m": family,
        "c_ship_m": {m: MODES[m].get("per_kg_km", 0.0) for m in modes},
        "c_trip_m": {m: (MODES[m]["litres_per_100km"] / 100 * FUEL_PRICE + MAINTENANCE) if m in trucks else 0.0 for m in modes},
        "f_mode_m": {m: float(MODES[m].get("fixed", 0.0)) if m in trucks else 0.0 for m in modes},
        "c_handle_m": {m: 0.0 for m in modes},
        "c_handle_h": dict(HUB_HANDLING),
        "f_h": {h: float(HUB_FIXED[h]) for h in hubs},
        "road_return_factor_m": {m: 2.0 if m in trucks else 1.0 for m in modes},
        "emission_return_factor_m": {m: 1.0 for m in modes},
        "capacity_unit_m": {m: "unit" for m in modes},
        "bar_X_m": {m: float(MODES[m]["capacity"]) for m in modes},
        "ctmin_m": {m: float(MODES[m]["minimum"]) for m in modes},
        "ccamax_m": {m: float(MODES[m].get("contracted", 0.0)) for m in modes},
        "trip_big_m_m": {m: int(math.ceil(most_units / MODES[m]["capacity"])) + 1 for m in modes},
        "speed_km_h_m": {m: SPEED_KM_H if m in trucks else 0.0 for m in modes},
        "max_driving_hours_m": {m: DRIVING_HOURS_PER_WEEK * WEEKS_PER_PERIOD if m in trucks else 0.0 for m in modes},
        "truck_investment_budget": TRUCK_INVESTMENT_CEILING,
        # money over time and labour
        "interest_rate": 0.1,
        "asset_life_years": {"facility": 20.0, "technology": 8.0, "vehicle": 5.0},
        "labour_cost_i": {i: LABOUR_COST[COUNTRY[i]] for i in nodes},
        "workers_fixed_i": {**{f: FIXED_WORKERS["factory"] for f in factories}, **{w: FIXED_WORKERS["warehouse"] for w in warehouses}},
        "workers_per_sqm_i": {i: WORKERS_PER_M2 for i in factories + warehouses},
        "workers_prod_g": {g: PRODUCTION[g]["workers"] for g in production},
        "workers_rem_l": {l: REMANUFACTURING[l]["workers"] for l in remanufacturing},
        "workers_mode_m": {m: 1.0 if m in trucks else 0.0 for m in modes},
        "weekly_working_hours": WEEKLY_WORKING_HOURS,
        "weeks_per_period": WEEKS_PER_PERIOD,
        # capacities
        "bar_s_s_u": {s: {u: float(SUPPLY[s][u][0]) for u in raw} for s in suppliers},
        "scmin_s_u": {s: {u: float(SUPPLY[s][u][1]) for u in raw} for s in suppliers},
        "bar_p_g": {g: float(PRODUCTION[g]["cap"]) for g in production},
        "bar_q_l": {l: float(REMANUFACTURING[l]["cap"]) for l in remanufacturing},
        "pcmin_g": {g: float(PRODUCTION[g]["min"]) for g in production},
        "pcmin_l": {l: float(REMANUFACTURING[l]["min"]) for l in remanufacturing},
        "icmax_p_n": {p: {w: float(STOCK_MAX[p]) for w in warehouses} for p in products},
        "icmin_p_n": {p: {w: float(STOCK_MIN[p]) for w in warehouses} for p in products},
        "i_p_n_0": {p: {w: float(INITIAL_STOCK.get(w, {}).get(p, 0.0)) for w in warehouses} for p in products},
        "A_f": {f: float(FACTORY_AREA[f][1]) for f in factories},
        "A_w": {w: float(WAREHOUSE_AREA[w][1]) for w in warehouses},
        "Amin_f": {f: float(FACTORY_AREA[f][0]) for f in factories},
        "Amin_w": {w: float(WAREHOUSE_AREA[w][0]) for w in warehouses},
        "existing_i": {i: float(area) for i, area in EXISTING.items()},
        "apu_u": {u: AREA[u] for u in raw},
        "apu_p": {p: AREA[p] for p in products},
        "apu_rp": {rp: AREA[rp] for rp in recovered},
        "product_rotation_per_period": ROTATIONS_PER_YEAR,
        # bills, returns, demand
        "a_in_u_p_g": {u: {p: {g: BILL[u][g] for g in production if PRODUCTION[g]["product"] == p} for p in products} for u in raw},
        "bom_rem_r_p": {rp: {p: next((spec["units"] for spec in REMANUFACTURING.values() if spec["recovered"] == rp and spec["product"] == p), 0.0) for p in products} for rp in recovered},
        "ret_yield_rp_p": {rp: {p: 1.0 if RETURNED_AS[rp] == p else 0.0 for p in products} for rp in recovered},
        "theta_p": {p: 1 for p in products},
        "omega_u": {u: WEIGHT[u] for u in raw},
        "omega_p": {p: WEIGHT[p] for p in products},
        "omega_rp": {rp: WEIGHT[rp] for rp in recovered},
        "d_r_p_t": {r: {p: {t: float(DEMAND[p][r][k]) for k, t in enumerate(PERIODS)} for p in products} for r in markets},
        "rho_r_p_t": per_market(RETURN_MAX),
        "ret_max_frac_r_p_t": per_market(RETURN_MAX),
        "ret_min_frac_r_p_t": per_market(RETURN_MIN),
        # emissions (climate change, kg CO2e)
        "e_open_f": {f: INSTALLATION_CC for f in factories},
        "e_open_w": {w: INSTALLATION_CC for w in warehouses},
        "e_prod_g": {g: TECHNOLOGY_CC[g] for g in production},
        "e_rem_l": {l: TECHNOLOGY_CC[l] for l in remanufacturing},
        "e_raw_s_u": {s: {u: 0.0 for u in raw} for s in suppliers},
        "e_ship_m": {m: MODES[m]["cc"] for m in modes},
        # the leader's tax range, EUR per kg CO2e (0-200 EUR/t)
        "underline_tax_rate": 0.0,
        "overline_tax_rate": 0.2,
        "d_i_j": table,
    }
    parameters = in_thousands(parameters)
    sets = {
        "S": suppliers, "F": factories, "W": warehouses, "R": markets, "AIR": airports, "PORT": seaports,
        "I": nodes, "N": nodes, "V": warehouses, "P": products, "U": raw, "K": recovered, "RP": recovered,
        "M": modes, "M_RD": trucks, "M_A": [m for m in modes if family[m] == "air"], "M_S": [m for m in modes if family[m] == "sea"],
        "G": production, "L": remanufacturing, "T": PERIODS,
        "H_prod": [[spec["product"], g] for g, spec in PRODUCTION.items()],
        "H_rem": [[spec["product"], l] for l, spec in REMANUFACTURING.items()],
        "A": [list(a) for a in arcs],
        **arc_sets,
        **flows,
    }
    metadata = {
        "source": "Mota et al. (2018), Omega 77:32-57, case study; data as published in Tautenhain et al. (2020), "
                  "Mendeley Data doi 10.17632/f82by28vnm.2, section 3",
        "builder": "clsc.generator.mota2018",
        "names": {**SUPPLIERS, **FACTORIES, **WAREHOUSES, **MARKETS, **AIRPORTS, **SEAPORTS,
                  **RAW_MATERIALS, **PRODUCTS, **RECOVERED},
        "conflicts_resolved": CONFLICTS,
        "assumptions": ASSUMPTIONS,
        "transport_mode_family": family,
        "unit_convention": {
            "currency": "EUR",
            "raw_material_flow": "item_units",
            "raw_material_cost": "EUR/raw-material unit",
            "raw_material_emission_intensity": "kg CO2e/kg",
            "production_emission_intensity": "kg CO2e/kg",
            "remanufacturing_emission_intensity": "kg CO2e/kg",
            "installation_emission_intensity": "kg CO2e/m2",
            "transport_emission_intensity": "kg CO2e/(kg km), per mode",
            "transport_capacity": "items (capacity_unit_m)",
            "item_quantity": "thousands of units (demand, supplies, capacities, stock); costs, weights and areas per thousand units",
        },
        "carbon_tax_units": {"underline_tax_rate_overline_tax_rate": "EUR/kg CO2e"},
        "benchmark": {"kind": "case_study"},
    }
    instance = {"name": "MOTA2018", "metadata": metadata, "sets": sets, "parameters": parameters}
    InstanceData.from_dict(json.loads(json.dumps(instance)))  # the model's own validation
    return instance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m clsc.generator.mota2018", description=__doc__.splitlines()[0])
    parser.add_argument("--output", default="data/case_study/MOTA2018.json")
    args = parser.parse_args(argv)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_instance(), indent=1), encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
