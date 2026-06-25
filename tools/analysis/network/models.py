"""Data classes and variable-family schema for the network pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TauSnapshot:
    hat_tau: int
    effective_tax: float
    cost: float
    emissions: float
    follower_objective: float
    objective_value: float
    solve_seconds: float | None
    mip_gap: float | None
    lex_primary_mip_gap: float | None
    lex_secondary_mip_gap: float | None
    rows_by_family: dict[str, list[dict[str, Any]]]
    metrics: dict[str, float]
    structural_signature: tuple[str, ...]
    is_lf_lex_incumbent: bool


@dataclass(frozen=True, slots=True)
class Phase:
    phase_id: int
    tau_start: int
    tau_end: int
    signature: tuple[str, ...]
    n_taus: int
    cost_min: float
    cost_max: float
    emissions_min: float
    emissions_max: float
    contains_lf_lex_incumbent: bool
    num_suppliers_open: int = 0
    num_factories_open: int = 0
    num_warehouses_open: int = 0
    num_hubs_open: int = 0
    num_prod_tech_installed: int = 0
    num_rem_tech_installed: int = 0
    active_modes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Transition:
    tau_from: int
    tau_to: int
    added: tuple[str, ...]
    removed: tuple[str, ...]
    delta_cost: float
    delta_emissions: float
    mac: float | None = None
    change_type: str = "other"


@dataclass(frozen=True, slots=True)
class AlignmentReport:
    instance: str
    lf_lex_present: bool
    lf_lex_hat_tau: int | None
    enum_selected_hat_tau: int
    hat_tau_match: bool
    emissions_match: bool
    cost_delta_at_same_tau: float | None
    emissions_delta_at_same_tau: float | None
    follower_objective_delta_at_same_tau: float | None
    tolerance: float


@dataclass(slots=True)
class TauStructureResult:
    instance: str
    snapshots: list[TauSnapshot]
    summary: "pd.DataFrame"
    phases: list[Phase]
    transitions: list[Transition]
    alignment: AlignmentReport
    unknown_rows: list[dict[str, Any]]
    rows_by_file: dict[str, list[dict[str, Any]]]


# ---------------------------------------------------------------------------
# Variable schema
# ---------------------------------------------------------------------------

VAR_KEY_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\[(?P<indices>.*)\]$")

VARIABLE_SCHEMA: dict[str, dict[str, Any]] = {
    "y_s":      {"dims": ["supplier"],                                        "kind": "binary",     "filename": "facility_open.csv",   "extra": {"layer": "supplier"}},
    "y_f":      {"dims": ["factory"],                                         "kind": "binary",     "filename": "facility_open.csv",   "extra": {"layer": "factory"}},
    "y_w":      {"dims": ["warehouse"],                                       "kind": "binary",     "filename": "facility_open.csv",   "extra": {"layer": "warehouse"}},
    "y_h":      {"dims": ["hub"],                                             "kind": "binary",     "filename": "facility_open.csv",   "extra": {"layer": "hub"}},
    "YC":       {"dims": ["facility"],                                        "kind": "continuous", "filename": "installed_area.csv",  "extra": {}},
    "u_prod":   {"dims": ["factory", "tech"],                                 "kind": "binary",     "filename": "tech_install.csv",    "extra": {"tech_kind": "prod"}},
    "u_rem":    {"dims": ["factory", "tech"],                                 "kind": "binary",     "filename": "tech_install.csv",    "extra": {"tech_kind": "rem"}},
    "use_rem":  {"dims": ["factory", "tech", "period"],                       "kind": "binary",     "filename": "tech_use.csv",        "extra": {}},
    "q":        {"dims": ["product", "factory", "tech", "period"],            "kind": "continuous", "filename": "production.csv",      "extra": {}},
    "rem":      {"dims": ["product", "factory", "tech", "period"],            "kind": "continuous", "filename": "remanufacturing.csv", "extra": {}},
    "inv_w":    {"dims": ["product", "warehouse", "period"],                  "kind": "continuous", "filename": "inventory.csv",       "extra": {"level": "warehouse"}},
    "order_su": {"dims": ["raw_material", "supplier", "period"],              "kind": "binary",     "filename": "supplier_orders.csv", "extra": {}},
    "zt":       {"dims": ["origin", "destination", "mode", "period"],         "kind": "binary",     "filename": "mode_active.csv",     "extra": {}},
    "x":        {"dims": ["item", "origin", "destination", "mode", "period"], "kind": "continuous", "filename": "flows.csv",           "extra": {}},
    "trip":     {"dims": ["origin", "destination", "mode", "period"],         "kind": "integer",    "filename": "trips.csv",           "extra": {}},
    "vehicle":  {"dims": ["origin", "mode"],                                  "kind": "integer",    "filename": "vehicles.csv",        "extra": {}},
    "contract": {"dims": ["mode", "period"],                                  "kind": "binary",     "filename": "contracts.csv",       "extra": {}},
}

FAMILY_TO_FILE: dict[str, str] = {f: s["filename"] for f, s in VARIABLE_SCHEMA.items()}
FAMILY_TO_KIND: dict[str, str] = {f: s["kind"] for f, s in VARIABLE_SCHEMA.items()}


def parse_var_name(key: str) -> tuple[str, tuple[str, ...]] | None:
    match = VAR_KEY_RE.match(key)
    if match is None:
        return None
    name = match.group("name")
    indices = tuple(idx.strip() for idx in match.group("indices").split(","))
    return name, indices


def family_of(key: str) -> str | None:
    parsed = parse_var_name(key)
    if parsed is None:
        return None
    family, _indices = parsed
    return family if family in VARIABLE_SCHEMA else None


def is_active(value: float, kind: str, eps: float) -> int:
    if kind in ("binary", "integer"):
        return 1 if value >= 0.5 else 0
    return 1 if abs(value) >= eps else 0

