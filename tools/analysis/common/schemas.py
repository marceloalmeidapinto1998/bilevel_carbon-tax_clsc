"""Shared fixed-order schemas for result aggregation."""

from __future__ import annotations

import re

RUN_COLS = [
    "instance", "input_path", "success", "exact", "termination_reason",
    "iterations", "hat_tau", "effective_tax", "cost", "emissions",
    "follower_objective", "lower_bound", "upper_bound", "relative_gap",
    "validation_status", "failure_stage", "error_type", "error_message",
    "gurobi_status", "objective_bound", "iis_constraints", "solve_seconds",
]

NET_COLS = [
    "hat_tau", "effective_tax", "cost", "emissions", "follower_objective",
    "objective_value", "solve_seconds", "mip_gap", "lex_primary_mip_gap",
    "lex_secondary_mip_gap", "num_suppliers_open", "num_factories_open",
    "num_warehouses_open", "num_hubs_open", "num_prod_tech_installed",
    "num_rem_tech_installed", "num_active_arcs", "num_modes_contracted",
    "total_installed_area", "total_production_qty", "total_remanufacturing_qty",
    "total_flow_volume", "total_trips", "is_lf_lex_incumbent",
    "delta_cost_vs_baseline", "delta_emissions_vs_baseline", "pct_cost_change",
    "pct_emissions_change", "mac", "cumulative_mac", "structural_change",
    "phase_id", "signature_size", "cost_per_unit_production",
    "emissions_per_unit_production", "remanufacturing_share", "flow_per_trip",
]

NUM_RUN = [
    "iterations", "hat_tau", "effective_tax", "cost", "emissions",
    "follower_objective", "lower_bound", "upper_bound", "relative_gap",
    "iis_constraints", "solve_seconds",
]

INST_RE = re.compile(r"(STD_I(\d+)_M(\d+)_T(\d+))")


def base_instance(code: str) -> str | None:
    match = INST_RE.search(code)
    return match.group(1) if match else None


def imt(code: str) -> tuple[int, int, int] | tuple[None, None, None]:
    match = INST_RE.search(code)
    if not match:
        return (None, None, None)
    return int(match.group(2)), int(match.group(3)), int(match.group(4))

