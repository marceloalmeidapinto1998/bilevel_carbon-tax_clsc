"""Structural menu-breadth expansions (Experiment 6 structural half-fraction).

Technology and transport menu breadth add new technologies/modes (sets + their parameters), so
they cannot go through a multiplier `FactorSpec`. Each of the five structural factors expands only
its own technology type or transport-mode family via the shared, validated scenario generators
under `clsc.campaign.scenarios`.
"""
from __future__ import annotations

import copy
from typing import Any

from clsc.campaign.scenarios.technology.generate import create_technology_scenario_instance
from clsc.campaign.scenarios.transport.generate import create_transport_scenario_instance

MENU_LEVELS = ("base", "expanded")


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


def apply_structural_levels(
    payload: dict[str, Any],
    *,
    production_technology_menu: str = "base",
    remanufacturing_technology_menu: str = "base",
    road_menu: str = "base",
    sea_menu: str = "base",
    air_menu: str = "base",
) -> dict[str, Any]:
    """Apply the 5-way structural split in a fixed order (production, remanufacturing, road, sea,
    air). Each factor touches disjoint sets/parameters, so the order does not change the result.
    """
    payload = apply_production_technology_menu(payload, production_technology_menu)
    payload = apply_remanufacturing_technology_menu(payload, remanufacturing_technology_menu)
    payload = apply_road_menu(payload, road_menu)
    payload = apply_sea_menu(payload, sea_menu)
    payload = apply_air_menu(payload, air_menu)
    return payload
