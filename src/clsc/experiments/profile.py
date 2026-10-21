"""What a follower response does, read from its variable values: the emissions by source, how much is
remanufactured, which facilities and technologies are installed and how the goods travel.

The emissions are recomputed here term by term, with the coefficients of supply_chain.emissions_expr
(undiscounted), so that they can be split by source; ``emissions_total`` is their sum and the caller
compares it with the emissions the solver reported, which catches any drift between the two.
"""
from __future__ import annotations

from collections import defaultdict
import re

from clsc.config.constants import KG_PER_TONNE
from clsc.models.instance_data import InstanceData
from clsc.models.supply_chain import (
    _emission_return_factor,
    _item_weights,
    _mode_family,
    embodied_emission_share_per_period,
)

EMISSION_SOURCES = ("raw_material", "production", "remanufacturing", "transport", "construction")
MODE_FAMILIES = ("truck", "air", "sea")
# A binary is taken as 1 above this value.
_ON = 0.5
_NAME = re.compile(r"^(\w+)\[(.*)\]$")


def parse_variables(values: dict[str, float]) -> dict[str, dict[tuple[str, ...], float]]:
    """Gurobi names such as ``q[p1,f1,g1,t1]`` grouped by variable: ``{"q": {("p1", "f1", "g1", "t1"): value}}``."""
    grouped: dict[str, dict[tuple[str, ...], float]] = defaultdict(dict)
    for name, value in values.items():
        match = _NAME.match(name)
        if match:
            grouped[match.group(1)][tuple(match.group(2).split(","))] = float(value)
    return grouped


def response_profile(instance: InstanceData, values: dict[str, float]) -> dict[str, float | str]:
    """One flat record per response, ready for a CSV row."""
    params = instance.parameters
    sets = instance.sets
    variables = parse_variables(values)
    periods = sets["T"]
    suppliers = set(sets["S"])
    retailers = set(sets["R"])
    recovered = sets.get("K", sets.get("RP", tuple(params.get("bom_rem_r_p", {}).keys())))
    weights = _item_weights(params, sets["U"], sets["P"], recovered)
    raw_materials = set(sets["U"])
    distances = params["d_i_j"]
    mode_family = params.get("mode_family_m", {})

    q = variables.get("q", {})
    rem = variables.get("rem", {})
    x = variables.get("x", {})
    area = variables.get("YC", {})

    emissions = dict.fromkeys(EMISSION_SOURCES, 0.0)
    emissions["production"] = sum(params["e_prod_g"][g] * params["omega_p"][p] * v for (p, _f, g, _t), v in q.items())
    emissions["remanufacturing"] = sum(params["e_rem_l"][l] * params["omega_p"][p] * v for (p, _f, l, _t), v in rem.items())
    emissions["construction"] = len(periods) * embodied_emission_share_per_period(params) * (
        sum(params["e_open_f"][node] * v for (node,), v in area.items() if node in params["e_open_f"])
        + sum(params["e_open_w"][node] * v for (node,), v in area.items() if node in params["e_open_w"])
    )

    tonne_km = dict.fromkeys(MODE_FAMILIES, 0.0)
    transport_emissions = dict.fromkeys(MODE_FAMILIES, 0.0)
    collected = 0.0
    for (item, origin, destination, mode, _t), value in x.items():
        if item in raw_materials and origin in suppliers:
            emissions["raw_material"] += params["e_raw_s_u"][origin][item] * params["omega_u"][item] * value
        if item in recovered and origin in retailers:
            collected += value
        kg_km = weights[item] * distances[origin][destination] * value
        family = _mode_family(mode, mode_family)
        tonne_km[family] = tonne_km.get(family, 0.0) + kg_km / KG_PER_TONNE
        transport_emissions[family] = transport_emissions.get(family, 0.0) + params["e_ship_m"][mode] * _emission_return_factor(params, mode) * kg_km
    emissions["transport"] = sum(transport_emissions.values())

    produced = sum(q.values())
    remanufactured = sum(rem.values())
    total_tonne_km = sum(tonne_km.values())

    def installed(name: str) -> str:
        return ";".join(":".join(key) for key, value in sorted(variables.get(name, {}).items()) if value > _ON)

    record: dict[str, float | str] = {f"emissions_{source}": emissions[source] for source in EMISSION_SOURCES}
    record["emissions_total"] = sum(emissions.values())
    record.update({f"emissions_transport_{family}": transport_emissions.get(family, 0.0) for family in MODE_FAMILIES})
    record.update({
        "produced": produced,
        "remanufactured": remanufactured,
        "remanufacturing_share": remanufactured / (produced + remanufactured) if produced + remanufactured > 0 else 0.0,
        "collected": collected,
        "tonne_km": total_tonne_km,
    })
    record.update({f"tonne_km_share_{family}": tonne_km.get(family, 0.0) / total_tonne_km if total_tonne_km > 0 else 0.0 for family in MODE_FAMILIES})
    record.update({
        "installed_area": sum(area.values()),
        "trucks": sum(variables.get("vehicle", {}).values()),
        "factories": installed("y_f"),
        "warehouses": installed("y_w"),
        "hubs": installed("y_h"),
        "production_technologies": installed("u_prod"),
        "remanufacturing_technologies": installed("u_rem"),
    })
    return record
