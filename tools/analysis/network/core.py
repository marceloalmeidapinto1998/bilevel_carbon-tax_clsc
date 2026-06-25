"""Analysis computations: variable parsing, metrics, structural phases, and alignment."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

import pandas as pd

from .models import (
    AlignmentReport,
    Phase,
    TauSnapshot,
    Transition,
    VARIABLE_SCHEMA,
    is_active,
    parse_var_name,
)

# ---------------------------------------------------------------------------
# Metrics field catalogue
# ---------------------------------------------------------------------------

COUNT_FIELDS: tuple[str, ...] = (
    "num_suppliers_open",
    "num_factories_open",
    "num_warehouses_open",
    "num_hubs_open",
    "num_prod_tech_installed",
    "num_rem_tech_installed",
    "num_active_arcs",
    "num_modes_contracted",
)

SUM_FIELDS: tuple[str, ...] = (
    "total_installed_area",
    "total_production_qty",
    "total_remanufacturing_qty",
    "total_flow_volume",
    "total_trips",
)

BASE_SUMMARY_COLUMNS: tuple[str, ...] = (
    "hat_tau",
    "effective_tax",
    "cost",
    "emissions",
    "follower_objective",
    "objective_value",
    "solve_seconds",
    "mip_gap",
    "lex_primary_mip_gap",
    "lex_secondary_mip_gap",
    *COUNT_FIELDS,
    *SUM_FIELDS,
    "is_lf_lex_incumbent",
)

DERIVED_SUMMARY_COLUMNS: tuple[str, ...] = (
    "delta_cost_vs_baseline",
    "delta_emissions_vs_baseline",
    "pct_cost_change",
    "pct_emissions_change",
    "mac",
    "cumulative_mac",
    "structural_change",
    "phase_id",
    "signature_size",
    "cost_per_unit_production",
    "emissions_per_unit_production",
    "remanufacturing_share",
    "flow_per_trip",
)


# ---------------------------------------------------------------------------
# Follower variable parsing
# ---------------------------------------------------------------------------

def parse_follower_into_rows(
    follower: dict[str, float],
    base_row: dict[str, Any],
    eps: float,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Group follower variable entries into long-form rows by family filename."""
    rows_by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unknown: list[dict[str, Any]] = []

    for raw_key, raw_value in follower.items():
        value = float(raw_value)
        parsed = parse_var_name(raw_key)
        if parsed is None:
            unknown.append({**base_row, "family": "?", "raw_key": raw_key, "value": value})
            continue
        family, indices = parsed
        schema = VARIABLE_SCHEMA.get(family)
        if schema is None or len(indices) != len(schema["dims"]):
            unknown.append({**base_row, "family": family, "raw_key": raw_key, "value": value})
            continue
        row = dict(base_row)
        row["family"] = family
        row.update(schema["extra"])
        for dim_name, idx_val in zip(schema["dims"], indices):
            row[dim_name] = idx_val
        row["value"] = value
        row["active"] = is_active(value, schema["kind"], eps)
        rows_by_file[schema["filename"]].append(row)

    return rows_by_file, unknown


# ---------------------------------------------------------------------------
# Snapshot metric aggregation
# ---------------------------------------------------------------------------

def aggregate_snapshot_metrics(rows_by_file: dict[str, list[dict[str, Any]]]) -> dict[str, float]:
    """Aggregate count/sum metrics from long-form rows for a single hat_tau."""
    metrics: dict[str, float] = {name: 0 for name in COUNT_FIELDS}
    metrics.update({name: 0.0 for name in SUM_FIELDS})

    for row in rows_by_file.get("facility_open.csv", ()):
        if row["active"] != 1:
            continue
        layer = row.get("layer")
        if layer == "supplier":
            metrics["num_suppliers_open"] += 1
        elif layer == "factory":
            metrics["num_factories_open"] += 1
        elif layer == "warehouse":
            metrics["num_warehouses_open"] += 1
        elif layer == "hub":
            metrics["num_hubs_open"] += 1

    metrics["total_installed_area"] = sum(
        row["value"] for row in rows_by_file.get("installed_area.csv", ())
    )

    for row in rows_by_file.get("tech_install.csv", ()):
        if row["active"] != 1:
            continue
        if row.get("tech_kind") == "prod":
            metrics["num_prod_tech_installed"] += 1
        elif row.get("tech_kind") == "rem":
            metrics["num_rem_tech_installed"] += 1

    metrics["total_production_qty"] = sum(
        row["value"] for row in rows_by_file.get("production.csv", ())
    )
    metrics["total_remanufacturing_qty"] = sum(
        row["value"] for row in rows_by_file.get("remanufacturing.csv", ())
    )
    metrics["total_flow_volume"] = sum(row["value"] for row in rows_by_file.get("flows.csv", ()))
    metrics["num_active_arcs"] = sum(
        1 for row in rows_by_file.get("mode_active.csv", ()) if row["active"] == 1
    )
    metrics["total_trips"] = sum(row["value"] for row in rows_by_file.get("trips.csv", ()))
    metrics["num_modes_contracted"] = sum(
        1 for row in rows_by_file.get("contracts.csv", ()) if row["active"] == 1
    )
    return metrics


def build_transport_mode_dataframe(rows_by_file: dict[str, list[dict[str, Any]]]) -> pd.DataFrame:
    """Summarize active transport decisions by tau and mode."""
    mode_rows: dict[tuple[int, float, int, str], dict[str, Any]] = {}

    def _row(source: dict[str, Any]) -> dict[str, Any]:
        key = (
            int(source["hat_tau"]),
            float(source["effective_tax"]),
            int(source["is_lf_lex_incumbent"]),
            str(source["mode"]),
        )
        if key not in mode_rows:
            hat_tau, effective_tax, is_incumbent, mode = key
            mode_rows[key] = {
                "hat_tau": hat_tau,
                "effective_tax": effective_tax,
                "is_lf_lex_incumbent": is_incumbent,
                "mode": mode,
                "active_arc_periods": 0,
                "total_flow_qty": 0.0,
                "total_trips": 0.0,
                "total_vehicles": 0.0,
                "active_contract_periods": 0,
            }
        return mode_rows[key]

    for source in rows_by_file.get("mode_active.csv", ()):
        if source["active"] == 1:
            _row(source)["active_arc_periods"] += 1
    for source in rows_by_file.get("flows.csv", ()):
        _row(source)["total_flow_qty"] += float(source["value"])
    for source in rows_by_file.get("trips.csv", ()):
        _row(source)["total_trips"] += float(source["value"])
    for source in rows_by_file.get("vehicles.csv", ()):
        _row(source)["total_vehicles"] += float(source["value"])
    for source in rows_by_file.get("contracts.csv", ()):
        if source["active"] == 1:
            _row(source)["active_contract_periods"] += 1

    columns = [
        "hat_tau", "effective_tax", "is_lf_lex_incumbent", "mode",
        "active_arc_periods", "total_flow_qty", "total_trips",
        "total_vehicles", "active_contract_periods",
    ]
    if not mode_rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(mode_rows.values(), columns=columns).sort_values(
        ["hat_tau", "mode"], ignore_index=True,
    )


def build_summary_dataframe(snapshots: list[TauSnapshot]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for s in snapshots:
        row = {
            "hat_tau": s.hat_tau,
            "effective_tax": s.effective_tax,
            "cost": s.cost,
            "emissions": s.emissions,
            "follower_objective": s.follower_objective,
            "objective_value": s.objective_value,
            "solve_seconds": s.solve_seconds,
            "mip_gap": s.mip_gap,
            "lex_primary_mip_gap": s.lex_primary_mip_gap,
            "lex_secondary_mip_gap": s.lex_secondary_mip_gap,
            "is_lf_lex_incumbent": int(s.is_lf_lex_incumbent),
        }
        for name in COUNT_FIELDS:
            row[name] = s.metrics.get(name, 0)
        for name in SUM_FIELDS:
            row[name] = s.metrics.get(name, 0.0)
        rows.append(row)
    df = pd.DataFrame(rows, columns=list(BASE_SUMMARY_COLUMNS))
    return df.sort_values("hat_tau", ignore_index=True)


def _safe_div(num: float, den: float, eps: float) -> float:
    if not math.isfinite(num) or not math.isfinite(den):
        return float("nan")
    if abs(den) < eps:
        return float("nan")
    return num / den


def enrich_summary(
    df: pd.DataFrame,
    snapshots: list[TauSnapshot],
    baseline_tau: int,
    eps: float,
) -> pd.DataFrame:
    """Append derived columns: deltas, MAC, phase id, normalized metrics."""
    if df.empty:
        for col in DERIVED_SUMMARY_COLUMNS:
            df[col] = []
        return df

    df = df.copy()

    baseline_mask = df["hat_tau"] == baseline_tau
    if baseline_mask.any():
        base_cost = float(df.loc[baseline_mask, "cost"].iloc[0])
        base_emissions = float(df.loc[baseline_mask, "emissions"].iloc[0])
    else:
        base_cost = float(df["cost"].iloc[0])
        base_emissions = float(df["emissions"].iloc[0])

    df["delta_cost_vs_baseline"] = df["cost"] - base_cost
    df["delta_emissions_vs_baseline"] = df["emissions"] - base_emissions
    df["pct_cost_change"] = df["delta_cost_vs_baseline"].apply(
        lambda v: _safe_div(v, base_cost, eps) * 100.0
    )
    df["pct_emissions_change"] = df["delta_emissions_vs_baseline"].apply(
        lambda v: _safe_div(v, base_emissions, eps) * 100.0
    )

    mac_values: list[float] = []
    cum_mac_values: list[float] = []
    prev_cost: float | None = None
    prev_emissions: float | None = None
    for _, r in df.iterrows():
        c = float(r["cost"])
        e = float(r["emissions"])
        if prev_cost is None:
            mac_values.append(float("nan"))
        else:
            mac_values.append(_safe_div(c - prev_cost, prev_emissions - e, eps))
        cum_mac_values.append(_safe_div(c - base_cost, base_emissions - e, eps))
        prev_cost = c
        prev_emissions = e
    df["mac"] = mac_values
    df["cumulative_mac"] = cum_mac_values

    signatures = {s.hat_tau: s.structural_signature for s in snapshots}
    sig_series = df["hat_tau"].map(signatures)
    df["signature_size"] = sig_series.apply(lambda sig: len(sig) if isinstance(sig, tuple) else 0)

    structural_change = [0]
    phase_id = [0]
    current_phase = 0
    prev_sig: tuple[str, ...] | None = None
    for sig in sig_series:
        if prev_sig is None:
            prev_sig = sig
            continue
        if sig != prev_sig:
            structural_change.append(1)
            current_phase += 1
            prev_sig = sig
        else:
            structural_change.append(0)
        phase_id.append(current_phase)
    df["structural_change"] = structural_change
    df["phase_id"] = phase_id

    df["cost_per_unit_production"] = df.apply(
        lambda r: _safe_div(float(r["cost"]), float(r["total_production_qty"]), eps), axis=1,
    )
    df["emissions_per_unit_production"] = df.apply(
        lambda r: _safe_div(float(r["emissions"]), float(r["total_production_qty"]), eps), axis=1,
    )
    df["remanufacturing_share"] = df.apply(
        lambda r: _safe_div(
            float(r["total_remanufacturing_qty"]),
            float(r["total_production_qty"]) + float(r["total_remanufacturing_qty"]),
            eps,
        ),
        axis=1,
    )
    df["flow_per_trip"] = df.apply(
        lambda r: _safe_div(float(r["total_flow_volume"]), float(r["total_trips"]), eps), axis=1,
    )

    return df[list(BASE_SUMMARY_COLUMNS) + list(DERIVED_SUMMARY_COLUMNS)]


# ---------------------------------------------------------------------------
# Structural signatures, phases, and transitions
# ---------------------------------------------------------------------------

_FACILITY_FAMILIES: frozenset[str] = frozenset({"y_s", "y_f", "y_w", "y_h", "YC"})
_TECH_FAMILIES: frozenset[str] = frozenset({"u_prod", "u_rem"})
_LOGISTICS_FAMILIES: frozenset[str] = frozenset({"contract", "zt"})


def _signature_key_for_family(family: str, row: dict[str, Any]) -> str:
    dims = VARIABLE_SCHEMA[family]["dims"]
    parts = [str(row.get(dim, "?")) for dim in dims]
    return f"{family}[{','.join(parts)}]"


def compute_structural_signature(
    rows_by_file: dict[str, list[dict[str, Any]]],
    families: Iterable[str],
) -> tuple[str, ...]:
    """Sorted tuple of active structural keys (family + indices) for one snapshot."""
    family_set = set(families)
    keys: set[str] = set()
    for rows in rows_by_file.values():
        for row in rows:
            family = row.get("family")
            if family in family_set and row.get("active") == 1:
                keys.add(_signature_key_for_family(family, row))
    return tuple(sorted(keys))


def signature_diff(
    a: tuple[str, ...],
    b: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (added_in_b, removed_in_b) relative to a."""
    sa, sb = set(a), set(b)
    return tuple(sorted(sb - sa)), tuple(sorted(sa - sb))


def _classify_change_type(added: tuple[str, ...], removed: tuple[str, ...]) -> str:
    groups: set[str] = set()
    for key in added + removed:
        family = key.split("[")[0]
        if family in _FACILITY_FAMILIES:
            groups.add("facility")
        elif family in _TECH_FAMILIES:
            groups.add("technology")
        elif family in _LOGISTICS_FAMILIES:
            groups.add("logistics")
        else:
            groups.add("other")
    if len(groups) > 1:
        return "mixed"
    return next(iter(groups), "other")


def detect_phases(snapshots: list[TauSnapshot]) -> list[Phase]:
    if not snapshots:
        return []
    ordered = sorted(snapshots, key=lambda s: s.hat_tau)
    phases: list[Phase] = []
    current_sig = ordered[0].structural_signature
    start_idx = 0
    phase_id = 0
    for i in range(1, len(ordered) + 1):
        boundary = i == len(ordered) or ordered[i].structural_signature != current_sig
        if not boundary:
            continue
        bucket = ordered[start_idx:i]
        rep = bucket[0]
        costs = [s.cost for s in bucket]
        ems = [s.emissions for s in bucket]
        active_modes = tuple(sorted({
            row["mode"]
            for row in rep.rows_by_family.get("mode_active.csv", [])
            if row.get("active") == 1
        }))
        phases.append(Phase(
            phase_id=phase_id,
            tau_start=bucket[0].hat_tau,
            tau_end=bucket[-1].hat_tau,
            signature=current_sig,
            n_taus=len(bucket),
            cost_min=min(costs),
            cost_max=max(costs),
            emissions_min=min(ems),
            emissions_max=max(ems),
            contains_lf_lex_incumbent=any(s.is_lf_lex_incumbent for s in bucket),
            num_suppliers_open=int(rep.metrics.get("num_suppliers_open", 0)),
            num_factories_open=int(rep.metrics.get("num_factories_open", 0)),
            num_warehouses_open=int(rep.metrics.get("num_warehouses_open", 0)),
            num_hubs_open=int(rep.metrics.get("num_hubs_open", 0)),
            num_prod_tech_installed=int(rep.metrics.get("num_prod_tech_installed", 0)),
            num_rem_tech_installed=int(rep.metrics.get("num_rem_tech_installed", 0)),
            active_modes=active_modes,
        ))
        if i < len(ordered):
            current_sig = ordered[i].structural_signature
            start_idx = i
            phase_id += 1
    return phases


def detect_transitions(snapshots: list[TauSnapshot]) -> list[Transition]:
    if len(snapshots) < 2:
        return []
    ordered = sorted(snapshots, key=lambda s: s.hat_tau)
    out: list[Transition] = []
    for prev, curr in zip(ordered, ordered[1:]):
        added, removed = signature_diff(prev.structural_signature, curr.structural_signature)
        if not added and not removed:
            continue
        delta_cost = curr.cost - prev.cost
        delta_emissions = curr.emissions - prev.emissions
        mac = (delta_cost / -delta_emissions) if delta_emissions < 0 else None
        out.append(Transition(
            tau_from=prev.hat_tau,
            tau_to=curr.hat_tau,
            added=added,
            removed=removed,
            delta_cost=delta_cost,
            delta_emissions=delta_emissions,
            mac=mac,
            change_type=_classify_change_type(added, removed),
        ))
    return out


def phases_to_rows(phases: list[Phase]) -> list[dict[str, Any]]:
    return [
        {
            "phase_id": p.phase_id,
            "tau_start": p.tau_start,
            "tau_end": p.tau_end,
            "n_taus": p.n_taus,
            "signature_size": len(p.signature),
            "cost_min": p.cost_min,
            "cost_max": p.cost_max,
            "emissions_min": p.emissions_min,
            "emissions_max": p.emissions_max,
            "contains_lf_lex_incumbent": int(p.contains_lf_lex_incumbent),
            "num_suppliers_open": p.num_suppliers_open,
            "num_factories_open": p.num_factories_open,
            "num_warehouses_open": p.num_warehouses_open,
            "num_hubs_open": p.num_hubs_open,
            "num_prod_tech_installed": p.num_prod_tech_installed,
            "num_rem_tech_installed": p.num_rem_tech_installed,
            "active_modes": ";".join(p.active_modes),
        }
        for p in phases
    ]


def transitions_to_rows(transitions: list[Transition]) -> list[dict[str, Any]]:
    return [
        {
            "tau_from": t.tau_from,
            "tau_to": t.tau_to,
            "n_added": len(t.added),
            "n_removed": len(t.removed),
            "added": ";".join(t.added),
            "removed": ";".join(t.removed),
            "delta_cost": t.delta_cost,
            "delta_emissions": t.delta_emissions,
            "mac": t.mac,
            "change_type": t.change_type,
        }
        for t in transitions
    ]


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------

def build_alignment(
    enum_payload: dict[str, Any],
    lf_lex_payload: dict[str, Any] | None,
    eps: float,
) -> AlignmentReport:
    instance = str(enum_payload.get("instance", "unknown"))
    enum_selected = int(enum_payload["selected_hat_tau"])

    if lf_lex_payload is None:
        return AlignmentReport(
            instance=instance,
            lf_lex_present=False,
            lf_lex_hat_tau=None,
            enum_selected_hat_tau=enum_selected,
            hat_tau_match=False,
            emissions_match=False,
            cost_delta_at_same_tau=None,
            emissions_delta_at_same_tau=None,
            follower_objective_delta_at_same_tau=None,
            tolerance=eps,
        )

    lf_tau = int(lf_lex_payload["leader"]["hat_tau"])
    lf_obj = lf_lex_payload["objectives"]
    lf_cost = float(lf_obj["cost"])
    lf_em = float(lf_obj["emissions"])
    lf_fo = float(lf_obj["follower_objective"])

    same_tau_snap = next(
        (ts for ts in enum_payload["tax_solutions"] if int(ts["leader"]["hat_tau"]) == lf_tau),
        None,
    )
    if same_tau_snap is not None:
        same_obj = same_tau_snap["objectives"]
        cost_delta = float(same_obj["cost"]) - lf_cost
        emissions_delta = float(same_obj["emissions"]) - lf_em
        fo_delta = float(same_obj["follower_objective"]) - lf_fo
    else:
        cost_delta = emissions_delta = fo_delta = None

    incumbent_snap = next(
        (ts for ts in enum_payload["tax_solutions"] if int(ts["leader"]["hat_tau"]) == enum_selected),
        None,
    )
    if incumbent_snap is not None:
        em_incumbent = float(incumbent_snap["objectives"]["emissions"])
        emissions_match = abs(em_incumbent - lf_em) <= max(eps, eps * abs(lf_em))
    else:
        emissions_match = False

    return AlignmentReport(
        instance=instance,
        lf_lex_present=True,
        lf_lex_hat_tau=lf_tau,
        enum_selected_hat_tau=enum_selected,
        hat_tau_match=(enum_selected == lf_tau),
        emissions_match=emissions_match,
        cost_delta_at_same_tau=cost_delta,
        emissions_delta_at_same_tau=emissions_delta,
        follower_objective_delta_at_same_tau=fo_delta,
        tolerance=eps,
    )
