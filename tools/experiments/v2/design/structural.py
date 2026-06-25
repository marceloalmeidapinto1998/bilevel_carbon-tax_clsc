"""Structural ("low"/"high") levels for the two menu-breadth factors.

Technology and transport menu breadth are not multiplier scalings of an existing parameter —
they add new technologies/modes (sets + their parameters), so they cannot go through
`FactorSpec.apply`. The "high" level reuses the existing, already-tested scenario-instance
builders (`tools.experiments.scenarios.technology/transport.generate`) rather than
re-implementing the g4-g6/l4-l6 and extra-mode append logic: those builders are generic
instance-mutation utilities, not v1-campaign-specific code, so they are not part of the
`legacy_v1` retirement.
"""
from __future__ import annotations

import copy
from typing import Any

from tools.experiments.scenarios.technology.generate import create_technology_scenario_instance
from tools.experiments.scenarios.transport.generate import create_transport_scenario_instance

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
