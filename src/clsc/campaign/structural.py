"""Structural ("low"/"high") levels for the two menu-breadth factors.

Technology and transport menu breadth are not multiplier scalings of an existing parameter —
they add new technologies/modes (sets + their parameters), so they cannot go through
`FactorSpec.apply`. The "high" level reuses the existing, already-tested scenario-instance
builders (`clsc.campaign.scenarios.technology/transport.generate`) rather than
re-implementing the g4-g6/l4-l6 and extra-mode append logic: those builders are generic
instance-mutation utilities shared across campaigns.
"""
from __future__ import annotations

import copy
from typing import Any

from clsc.campaign.scenarios.technology.generate import create_technology_scenario_instance
from clsc.campaign.scenarios.transport.generate import create_transport_scenario_instance

TECHNOLOGY_MENU_LEVELS = ("base", "expanded")
TRANSPORT_MENU_LEVELS = ("base", "expanded")


def apply_technology_menu(payload: dict[str, Any], level: str) -> dict[str, Any]:
    if level == "base":
        return copy.deepcopy(payload)
    if level == "expanded":
        return create_technology_scenario_instance(payload).to_dict()
    raise ValueError(f"Unknown technology menu level: {level!r}")


def apply_transport_menu(payload: dict[str, Any], level: str) -> dict[str, Any]:
    if level == "base":
        return copy.deepcopy(payload)
    if level == "expanded":
        return create_transport_scenario_instance(payload).to_dict()
    raise ValueError(f"Unknown transport menu level: {level!r}")


def apply_structural_levels(
    payload: dict[str, Any],
    *,
    technology_menu: str = "base",
    transport_menu: str = "base",
) -> dict[str, Any]:
    """Apply technology- then transport-menu structural levels, in that order."""
    payload = apply_technology_menu(payload, technology_menu)
    payload = apply_transport_menu(payload, transport_menu)
    return payload


# ---------------------------------------------------------------------------
# doe_campaign_02's finalized 5-way structural split (EXPERIMENTAL_PLAN.md §5.1, Family C):
# production_technology_menu / remanufacturing_technology_menu / road_menu / sea_menu / air_menu.
# Each factor expands only its own technology type or transport-mode family, independently of the
# others, via the `include_production`/`include_remanufacturing`/`include_families` parameters
# added to the shared scenario generators for this purpose. Distinct from the 2-way
# technology_menu/transport_menu split above (doe_campaign_01's already-executed design, left
# untouched).
# ---------------------------------------------------------------------------

PRODUCTION_TECHNOLOGY_MENU_LEVELS = ("base", "expanded")
REMANUFACTURING_TECHNOLOGY_MENU_LEVELS = ("base", "expanded")
ROAD_MENU_LEVELS = ("base", "expanded")
SEA_MENU_LEVELS = ("base", "expanded")
AIR_MENU_LEVELS = ("base", "expanded")


def apply_production_technology_menu(payload: dict[str, Any], level: str) -> dict[str, Any]:
    if level == "base":
        return copy.deepcopy(payload)
    if level == "expanded":
        return create_technology_scenario_instance(
            payload, include_production=True, include_remanufacturing=False
        ).to_dict()
    raise ValueError(f"Unknown production technology menu level: {level!r}")


def apply_remanufacturing_technology_menu(payload: dict[str, Any], level: str) -> dict[str, Any]:
    if level == "base":
        return copy.deepcopy(payload)
    if level == "expanded":
        return create_technology_scenario_instance(
            payload, include_production=False, include_remanufacturing=True
        ).to_dict()
    raise ValueError(f"Unknown remanufacturing technology menu level: {level!r}")


def apply_road_menu(payload: dict[str, Any], level: str) -> dict[str, Any]:
    if level == "base":
        return copy.deepcopy(payload)
    if level == "expanded":
        return create_transport_scenario_instance(payload, include_families=frozenset({"truck"})).to_dict()
    raise ValueError(f"Unknown road menu level: {level!r}")


def apply_sea_menu(payload: dict[str, Any], level: str) -> dict[str, Any]:
    if level == "base":
        return copy.deepcopy(payload)
    if level == "expanded":
        return create_transport_scenario_instance(payload, include_families=frozenset({"sea"})).to_dict()
    raise ValueError(f"Unknown sea menu level: {level!r}")


def apply_air_menu(payload: dict[str, Any], level: str) -> dict[str, Any]:
    if level == "base":
        return copy.deepcopy(payload)
    if level == "expanded":
        return create_transport_scenario_instance(payload, include_families=frozenset({"air"})).to_dict()
    raise ValueError(f"Unknown air menu level: {level!r}")


def apply_structural_levels_v2(
    payload: dict[str, Any],
    *,
    production_technology_menu: str = "base",
    remanufacturing_technology_menu: str = "base",
    road_menu: str = "base",
    sea_menu: str = "base",
    air_menu: str = "base",
) -> dict[str, Any]:
    """Apply the 5-way structural split, in a fixed order (production, remanufacturing, road, sea, air).

    Each factor is independent (they touch disjoint sets/parameters), so the order only matters
    for which scenario-generator call sees the running payload; it does not change the result.
    """
    payload = apply_production_technology_menu(payload, production_technology_menu)
    payload = apply_remanufacturing_technology_menu(payload, remanufacturing_technology_menu)
    payload = apply_road_menu(payload, road_menu)
    payload = apply_sea_menu(payload, sea_menu)
    payload = apply_air_menu(payload, air_menu)
    return payload
