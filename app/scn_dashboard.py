"""Supply Chain Network Dashboard

Interactive Streamlit app showing how the supply chain network changes
with the carbon tax level τ̂ as determined by the bilevel leader.

Run from the project root:
    streamlit run app/scn_dashboard.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT        = Path(__file__).parent.parent
NETWORK_REL = Path("lf_lex_exact/network")

CATEGORIES: dict[str, str] = {
    "Base":                   "base",
    "Technology":             "scenarios/tech",
    "Transport":              "scenarios/trans",
    "Technology + transport": "scenarios/tech_trans",
    "Sensitivity":            "sensitivity",
}


def _discover_instances(cat_key: str) -> list[str]:
    """Return sorted list of instances that have both JSON + results for a category.

    For the sensitivity category the layout is two levels deep:
        data/instances/sensitivity/{base_instance}/{SA_CODE}.json
        results/sensitivity/{base_instance}/{SA_CODE}/lf_lex_exact/network/summary.csv
    Returned identifiers use a forward-slash separator so that Path joining in
    load_data() constructs the correct nested paths automatically.
    """
    inst_dir = ROOT / "data/instances" / cat_key
    res_dir  = ROOT / "results" / cat_key
    if cat_key == "sensitivity":
        available = sorted(
            f"{p.parent.name}/{p.stem}"
            for p in inst_dir.glob("*/*.json")
            if (res_dir / p.parent.name / p.stem / NETWORK_REL / "summary.csv").exists()
        )
    else:
        available = sorted(
            p.stem for p in inst_dir.glob("*.json")
            if (res_dir / p.stem / NETWORK_REL / "summary.csv").exists()
        )
    return available or []


# ---------------------------------------------------------------------------
# Visual config
# ---------------------------------------------------------------------------

NODE_STYLE: dict[str, dict] = {
    "S":    {"color": "#E69F00", "symbol": "square",             "label": "Supplier"},
    "F":    {"color": "#009E73", "symbol": "diamond",            "label": "Factory"},
    "W":    {"color": "#56B4E9", "symbol": "hexagon",            "label": "Warehouse"},
    "R":    {"color": "#0072B2", "symbol": "circle",             "label": "Retailer"},
    "AIR":  {"color": "#CC79A7", "symbol": "star-triangle-up",   "label": "Airport"},
    "PORT": {"color": "#D55E00", "symbol": "star-triangle-down", "label": "Seaport"},
}

ARC_COLOR: dict[str, str] = {
    "A_sf": "#E69F00",
    "A_fr": "#009E73",
    "A_rf": "#CC79A7",
    "A_fw": "#56B4E9",
    "A_wr": "#0072B2",
    "A_wf": "#D55E00",
    "A_rw": "#9B59B6",
    "hub":  "#888888",
}

ARC_LABEL: dict[str, str] = {
    "A_sf": "Supplier → Factory",
    "A_fr": "Factory → Retailer",
    "A_rf": "Retailer → Factory (return)",
    "A_fw": "Factory → Warehouse",
    "A_wr": "Warehouse → Retailer",
    "A_wf": "Warehouse → Factory (return)",
    "A_rw": "Retailer → Warehouse (return)",
    "hub":  "Hub routes",
}

INACTIVE_COLOR = "rgba(180,180,180,0.20)"
BILEVEL_COLOR  = "#000000"   # black — bilevel optimal tax reference

# Node types that are demand points (never selected by the model — always shown at full opacity)
ALWAYS_ACTIVE_TYPES = {"R"}
HUB_NODE_TYPES      = {"AIR", "PORT"}  # shown only when contracted; no open/closed label


# ---------------------------------------------------------------------------
# Unit formatting helpers
# ---------------------------------------------------------------------------

def _fmt_emissions(val_kg: float) -> str:
    val_t = val_kg / 1e3
    if val_t >= 1e6:
        return f"{val_t/1e6:.2f} Mt CO₂e"
    if val_t >= 1e3:
        return f"{val_t/1e3:.1f} kt CO₂e"
    if val_t >= 1.0:
        return f"{val_t:.1f} t CO₂e"
    return f"{val_kg:.0f} kg CO₂e"


def _fmt_cost(val_usd: float) -> str:
    if val_usd >= 1e6:
        return f"${val_usd/1e6:.2f} M"
    if val_usd >= 1e3:
        return f"${val_usd/1e3:.1f} k"
    return f"${val_usd:.0f}"


def _delta_count(current: int, baseline: int) -> str:
    diff = current - baseline
    if diff == 0:
        return "= baseline"
    return f"{diff:+d} vs baseline"


def _fmt_optional(val, fmt: str) -> str:
    import math
    try:
        return fmt.format(float(val)) if not math.isnan(float(val)) else "—"
    except (TypeError, ValueError):
        return "—"


# ---------------------------------------------------------------------------
# Data loading (cached per instance)
# ---------------------------------------------------------------------------

@st.cache_data
def load_data(instance: str, cat_key: str) -> dict:
    json_path = ROOT / "data/instances" / cat_key / f"{instance}.json"
    base_dir  = ROOT / "results" / cat_key / instance / NETWORK_REL

    with open(json_path) as f:
        inst = json.load(f)

    sets   = inst["sets"]
    coords: dict[str, dict] = inst["metadata"]["node_coordinates"]

    # Node → type mapping
    node_type: dict[str, str] = {}
    for n in sets.get("S", []):    node_type[n] = "S"
    for n in sets.get("F", []):    node_type[n] = "F"
    for n in sets.get("W", []):    node_type[n] = "W"
    for n in sets.get("R", []):    node_type[n] = "R"
    for n in sets.get("AIR", []):  node_type[n] = "AIR"
    for n in sets.get("PORT", []): node_type[n] = "PORT"

    # Arc → category mapping
    road_categories = ["A_sf", "A_fw", "A_wr", "A_fr", "A_rf", "A_wf", "A_rw"]
    arc_cat: dict[tuple[str, str], str] = {}
    for cat in road_categories:
        for pair in sets.get(cat, []):
            arc_cat[tuple(pair)] = cat
    for pair in sets.get("A", []):
        k = tuple(pair)
        if k not in arc_cat:
            arc_cat[k] = "hub"

    # CSV data
    summary         = pd.read_csv(base_dir / "summary.csv")
    facility        = pd.read_csv(base_dir / "facility_open.csv")
    mode_active     = pd.read_csv(base_dir / "mode_active.csv")
    flows           = pd.read_csv(base_dir / "flows.csv")
    tech_install    = pd.read_csv(base_dir / "tech_install.csv")
    def _read_optional(name: str, fallback_cols: list[str]) -> pd.DataFrame:
        p = base_dir / name
        return pd.read_csv(p) if p.exists() else pd.DataFrame(columns=fallback_cols)

    production      = _read_optional("production.csv",      ["hat_tau", "factory",  "value", "active"])
    remanufacturing = _read_optional("remanufacturing.csv", ["hat_tau", "factory",  "value", "active"])
    transport_modes = _read_optional("transport_modes.csv", ["hat_tau", "mode", "total_flow_qty"])
    installed_area  = _read_optional("installed_area.csv",  ["hat_tau", "facility", "value", "active"])
    tech_use        = _read_optional("tech_use.csv",        ["hat_tau", "factory", "tech", "period", "value", "active"])
    supplier_orders = _read_optional("supplier_orders.csv", ["hat_tau", "raw_material", "supplier", "period", "value", "active"])
    inventory       = _read_optional("inventory.csv",       ["hat_tau", "level", "product", "factory", "period", "value", "active"])
    trips_df        = _read_optional("trips.csv",           ["hat_tau", "origin", "destination", "mode", "period", "value", "active"])
    vehicles_df     = _read_optional("vehicles.csv",        ["hat_tau", "origin", "mode", "value", "active"])

    # Pre-compute max flow across ALL tau for stable arc-width normalisation.
    # Group by (hat_tau, origin, destination) to get per-arc per-tau totals,
    # then take the global max so the scale is stable as the slider moves.
    flow_agg_all = (
        flows[flows["active"] == 1]
        .groupby(["hat_tau", "origin", "destination"])["value"].sum()
    )
    max_flow = float(flow_agg_all.max()) if not flow_agg_all.empty else 1.0

    # Pre-aggregate node volumes across ALL tau for stable node-size normalisation
    prod_agg = (
        production[production["active"] == 1]
        .groupby(["hat_tau", "factory"])["value"].sum()
        .reset_index().rename(columns={"value": "prod_qty"})
    )
    max_prod_vol = float(prod_agg["prod_qty"].max()) if not prod_agg.empty else 1.0

    rem_agg = (
        remanufacturing[remanufacturing["active"] == 1]
        .groupby(["hat_tau", "factory"])["value"].sum()
        .reset_index().rename(columns={"value": "rem_qty"})
    )
    max_rem_vol = float(rem_agg["rem_qty"].max()) if not rem_agg.empty else 1.0

    # Order qty per supplier = actual raw-material flow from supplier to factory
    suppliers_set = set(sets.get("S", []))
    factories_set = set(sets.get("F", []))
    order_agg = (
        flows[
            (flows["active"] == 1) &
            (flows["origin"].isin(suppliers_set)) &
            (flows["destination"].isin(factories_set))
        ]
        .groupby(["hat_tau", "origin"])["value"].sum()
        .reset_index()
        .rename(columns={"origin": "supplier", "value": "order_qty"})
    )
    max_order_vol = float(order_agg["order_qty"].max()) if not order_agg.empty else 1.0

    retailers = set(sets.get("R", []))
    demand_agg = (
        flows[(flows["active"] == 1) & (flows["destination"].isin(retailers))]
        .groupby(["hat_tau", "destination"])["value"].sum()
        .reset_index().rename(columns={"destination": "retailer", "value": "demand_qty"})
    )
    max_retailer_demand = float(demand_agg["demand_qty"].max()) if not demand_agg.empty else 1.0

    max_installed_area = float(installed_area["value"].max()) if not installed_area.empty else 1.0

    return {
        "instance":    instance,
        "sets":        sets,
        "coords":      coords,
        "node_type":   node_type,
        "arc_cat":     arc_cat,
        "summary":     summary,
        "facility":    facility,
        "mode_active": mode_active,
        "flows":        flows,
        "max_flow":     max_flow,
        "tech_install": tech_install,
        "prod_by_tau_factory":   prod_agg,
        "rem_by_tau_factory":    rem_agg,
        "order_by_tau_supplier": order_agg,
        "transport_modes":       transport_modes,
        "retailer_demand_agg":   demand_agg,
        "max_retailer_demand":   max_retailer_demand,
        "max_prod_vol":          max_prod_vol,
        "max_rem_vol":           max_rem_vol,
        "max_order_vol":         max_order_vol,
        "installed_area":        installed_area,
        "max_installed_area":    max_installed_area,
        "tech_use":              tech_use,
        "supplier_orders":       supplier_orders,
        "inventory":             inventory,
        "trips_df":              trips_df,
        "vehicles_df":           vehicles_df,
        "tau_min":     int(summary["hat_tau"].min()),
        "tau_max":     int(summary["hat_tau"].max()),
        "incumbent_tau": int(
            summary.loc[summary["is_lf_lex_incumbent"] == 1, "hat_tau"].iloc[0]
        ),
    }


# ---------------------------------------------------------------------------
# Per-τ helpers
# ---------------------------------------------------------------------------

def _open_nodes(data: dict, tau: int) -> set[str]:
    fac = data["facility"]
    entity_cols = [c for c in ["factory", "supplier", "warehouse", "hub"]
                   if c in fac.columns]
    sub = fac.loc[(fac["hat_tau"] == tau) & (fac["active"] == 1), entity_cols]
    return set(
        sub.stack().dropna().astype(str).str.strip().loc[lambda s: s != ""]
    )


def _active_arcs(data: dict, tau: int) -> set[tuple[str, str]]:
    ma = data["mode_active"]
    sub = ma[(ma["hat_tau"] == tau) & (ma["active"] == 1) & (ma["family"] == "zt")]
    return set(zip(sub["origin"], sub["destination"]))


def _arc_flow_map(data: dict, tau: int) -> dict[tuple[str, str], float]:
    fl = data["flows"]
    sub = fl[(fl["hat_tau"] == tau) & (fl["active"] == 1)]
    agg = sub.groupby(["origin", "destination"])["value"].sum()
    return {(o, d): v for (o, d), v in agg.items()}


def _arc_mode_map(data: dict, tau: int) -> dict[tuple[str, str], str]:
    ma = data["mode_active"]
    sub = ma[(ma["hat_tau"] == tau) & (ma["active"] == 1) & (ma["family"] == "zt")]
    grouped = sub.groupby(["origin", "destination"])["mode"].apply(
        lambda s: " / ".join(sorted(s.unique()))
    )
    return {(o, d): m for (o, d), m in grouped.items()}



def _arc_width(flow: float, max_flow: float, show_flow: bool) -> float:
    if not show_flow or max_flow == 0:
        return 2.5
    return 1.5 + 7.0 * (flow / max_flow)


def _installed_tech(data: dict, tau: int) -> dict[str, dict[str, str]]:
    """Returns {factory: {"prod": tech, "rem": tech}} active at given tau."""
    ti = data["tech_install"]
    sub = ti[(ti["hat_tau"] == tau) & (ti["active"] == 1)]
    result: dict[str, dict[str, str]] = {}
    for _, row in sub.iterrows():
        f = str(row["factory"])
        result.setdefault(f, {})[str(row["tech_kind"])] = str(row["tech"])
    return result


def _node_volume_map(data: dict, tau: int) -> dict[str, dict[str, float]]:
    """Returns {node: {"prod": qty, "rem": qty, "order": qty}} at given tau."""
    result: dict[str, dict[str, float]] = {}

    prod_sub = data["prod_by_tau_factory"]
    for _, r in prod_sub[prod_sub["hat_tau"] == tau].iterrows():
        result.setdefault(str(r["factory"]), {})["prod"] = float(r["prod_qty"])

    rem_sub = data["rem_by_tau_factory"]
    for _, r in rem_sub[rem_sub["hat_tau"] == tau].iterrows():
        result.setdefault(str(r["factory"]), {})["rem"] = float(r["rem_qty"])

    ord_sub = data["order_by_tau_supplier"]
    for _, r in ord_sub[ord_sub["hat_tau"] == tau].iterrows():
        result.setdefault(str(r["supplier"]), {})["order"] = float(r["order_qty"])

    dem_sub = data["retailer_demand_agg"]
    for _, r in dem_sub[dem_sub["hat_tau"] == tau].iterrows():
        result.setdefault(str(r["retailer"]), {})["demand"] = float(r["demand_qty"])

    return result


def _node_size(vol: float, max_vol: float, enabled: bool) -> int:
    """Map volume to marker size in [10, 24] px; returns 16 when disabled."""
    if not enabled or max_vol == 0:
        return 16
    return int(10 + 14 * (vol / max_vol))


def _installed_area_map(data: dict, tau: int) -> dict[str, float]:
    """Return {facility: YC_value} for active installed-area rows at tau."""
    ia = data["installed_area"]
    if ia.empty:
        return {}
    sub = ia[(ia["hat_tau"] == tau) & (ia["active"] == 1)]
    return {str(r["facility"]): float(r["value"]) for _, r in sub.iterrows()}


def _vehicle_map(data: dict, tau: int) -> dict[str, dict[str, int]]:
    """Return {origin: {mode: vehicle_count}} at tau."""
    vdf = data["vehicles_df"]
    if vdf.empty:
        return {}
    sub = vdf[(vdf["hat_tau"] == tau) & (vdf["active"] == 1)]
    result: dict[str, dict[str, int]] = {}
    for _, r in sub.iterrows():
        result.setdefault(str(r["origin"]), {})[str(r["mode"])] = int(r["value"])
    return result


def _trip_map_by_arc(data: dict, tau: int, period: str | None) -> dict[tuple[str, str, str], int]:
    """Return {(origin, dest, mode): trip_count} at tau, optionally filtered to period."""
    tdf = data["trips_df"]
    if tdf.empty:
        return {}
    sub = tdf[(tdf["hat_tau"] == tau) & (tdf["active"] == 1)]
    if period is not None:
        sub = sub[sub["period"] == period]
    result: dict[tuple[str, str, str], int] = {}
    for _, r in sub.iterrows():
        key = (str(r["origin"]), str(r["destination"]), str(r["mode"]))
        result[key] = result.get(key, 0) + int(r["value"])
    return result


def _inventory_by_node(data: dict, tau: int, period: str | None) -> dict[str, dict[str, float]]:
    """Return {node: {label: inv_qty}} for factory and warehouse inventory at tau.
    inventory.csv uses 'factory' column for factory-level rows and 'warehouse' column
    for warehouse/warehouse_recovered rows."""
    inv = data["inventory"]
    if inv.empty:
        return {}
    sub = inv[(inv["hat_tau"] == tau) & (inv["active"] == 1)]
    if period is not None:
        sub = sub[sub["period"] == period]
    result: dict[str, dict[str, float]] = {}
    for _, r in sub.iterrows():
        level = str(r.get("level", ""))
        if level == "factory":
            node = str(r["factory"]) if "factory" in r.index else None
        else:
            node = str(r["warehouse"]) if "warehouse" in r.index else None
        if not node or node == "nan":
            continue
        prod  = str(r["product"])
        label = prod if level == "factory" else f"{prod} [{level}]"
        qty   = float(r["value"])
        result.setdefault(node, {})[label] = result.get(node, {}).get(label, 0.0) + qty
    return result


def _supplier_orders_active(data: dict, tau: int, period: str | None) -> dict[str, set[str]]:
    """Return {supplier: {raw_material, ...}} where order_su == 1 at tau."""
    so = data["supplier_orders"]
    if so.empty:
        return {}
    sub = so[(so["hat_tau"] == tau) & (so["active"] == 1)]
    if period is not None:
        sub = sub[sub["period"] == period]
    result: dict[str, set[str]] = {}
    for _, r in sub.iterrows():
        result.setdefault(str(r["supplier"]), set()).add(str(r["raw_material"]))
    return result


# ---------------------------------------------------------------------------
# Network figure
# ---------------------------------------------------------------------------

def build_network_fig(
    data: dict,
    tau: int,
    show_inactive: bool,
    show_flow: bool,
    show_node_vol: bool = False,
    show_yc_border: bool = False,
    period: str | None = None,
    height: int = 580,
) -> go.Figure:
    instance  = data["instance"]
    coords    = data["coords"]
    node_type = data["node_type"]
    arc_cat   = data["arc_cat"]
    max_flow  = data["max_flow"]

    open_nodes  = _open_nodes(data, tau)

    # Period-filtered arc/flow data when a period is selected
    if period is not None:
        ma_p = data["mode_active"]
        ma_p = ma_p[(ma_p["hat_tau"] == tau) & (ma_p["active"] == 1) &
                    (ma_p["family"] == "zt") & (ma_p["period"] == period)]
        active_arcs = set(zip(ma_p["origin"], ma_p["destination"]))
        fl_p = data["flows"]
        fl_p = fl_p[(fl_p["hat_tau"] == tau) & (fl_p["active"] == 1) &
                    (fl_p["period"] == period)]
        flow_map = {(o, d): v for (o, d), v in
                    fl_p.groupby(["origin", "destination"])["value"].sum().items()}
        mode_map = {(o, d): " / ".join(sorted(s.unique()))
                    for (o, d), s in ma_p.groupby(["origin", "destination"])["mode"]}
    else:
        active_arcs = _active_arcs(data, tau)
        flow_map    = _arc_flow_map(data, tau)
        mode_map    = _arc_mode_map(data, tau)

    hub_nodes_used = {n for (o, d) in active_arcs
                      for n in (o, d) if node_type.get(n) in HUB_NODE_TYPES}
    tech_info   = _installed_tech(data, tau)
    vol_map     = _node_volume_map(data, tau)

    # New variable maps
    area_map     = _installed_area_map(data, tau)
    vehicle_map  = _vehicle_map(data, tau)
    trip_map     = _trip_map_by_arc(data, tau, period)
    inv_map      = _inventory_by_node(data, tau, period)
    orders_map   = _supplier_orders_active(data, tau, period)
    max_yc       = data.get("max_installed_area", 1.0) or 1.0

    # Build a set of modes with active contracts at this tau (for κ_mt arc dash)
    tm_tau       = data["transport_modes"]
    tm_tau       = tm_tau[tm_tau["hat_tau"] == tau] if not tm_tau.empty else tm_tau
    contracted_modes: set[str] = set()
    if not tm_tau.empty and "active_contract_periods" in tm_tau.columns:
        contracted_modes = set(
            tm_tau[tm_tau["active_contract_periods"] > 0]["mode"].astype(str)
        )

    _max_vol: dict[str, float] = {
        "F": data.get("max_prod_vol",       1.0),
        "S": data.get("max_order_vol",      1.0),
        "R": data.get("max_retailer_demand", 1.0),
    }

    fig = go.Figure()

    # ── Inactive arcs ────────────────────────────────────────────────────────
    if show_inactive:
        ix, iy = [], []
        for (o, d) in arc_cat:
            if (o, d) not in active_arcs and o in coords and d in coords:
                ix += [coords[o]["x"], coords[d]["x"], None]
                iy += [coords[o]["y"], coords[d]["y"], None]
        if ix:
            fig.add_trace(go.Scatter(
                x=ix, y=iy, mode="lines",
                line=dict(color=INACTIVE_COLOR, width=0.8),
                hoverinfo="skip", showlegend=False,
            ))

    # ── Active arcs ──────────────────────────────────────────────────────────
    cat_arcs: dict[str, list[tuple[str, str]]] = {c: [] for c in ARC_COLOR}
    for (o, d) in active_arcs:
        cat_arcs[arc_cat.get((o, d), "hub")].append((o, d))

    for cat, arcs in cat_arcs.items():
        if not arcs:
            continue
        color = ARC_COLOR[cat]
        for o, d in arcs:
            if o not in coords or d not in coords:
                continue
            vol  = flow_map.get((o, d), 0.0)
            mode = mode_map.get((o, d), "—")
            w    = _arc_width(vol, max_flow, show_flow)
            mx   = (coords[o]["x"] + coords[d]["x"]) / 2
            my   = (coords[o]["y"] + coords[d]["y"]) / 2

            # Trip count for road arcs (Q_ijmt)
            road_modes  = [m for m in mode.split(" / ") if m.startswith("mrd")]
            trip_total  = sum(trip_map.get((o, d, m), 0) for m in road_modes)
            trip_suffix = f"<br>Trips: {trip_total:,}" if trip_total > 0 else ""

            # κ_mt: dashed if none of the arc's modes are contracted
            arc_modes    = [m.strip() for m in mode.split(" / ") if m.strip()]
            is_hub_arc   = cat == "hub"
            has_contract = any(m in contracted_modes for m in arc_modes) if arc_modes else True
            dash_style   = "solid" if (not is_hub_arc or has_contract) else "dot"

            fig.add_trace(go.Scatter(
                x=[coords[o]["x"], mx, coords[d]["x"]],
                y=[coords[o]["y"], my, coords[d]["y"]],
                mode="lines",
                line=dict(color=color, width=w, dash=dash_style),
                hovertemplate=(
                    f"{o} → {d}<br>Mode: {mode}<br>Flow: {vol:,.0f} units"
                    f"{trip_suffix}<extra></extra>"
                ),
                showlegend=False,
            ))
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="lines",
            line=dict(color=color, width=3),
            name=ARC_LABEL.get(cat, cat),
        ))

    # ── Nodes ────────────────────────────────────────────────────────────────
    for ntype, style in NODE_STYLE.items():
        nodes_of_type = [n for n, t in node_type.items() if t == ntype]
        if not nodes_of_type:
            continue

        nx_o, ny_o, txt_o, hov_o = [], [], [], []
        nx_c, ny_c, txt_c, hov_c = [], [], [], []

        always_active = ntype in ALWAYS_ACTIVE_TYPES

        for n in nodes_of_type:
            if n not in coords:
                continue
            x_, y_ = coords[n]["x"], coords[n]["y"]
            if ntype in HUB_NODE_TYPES:
                tip = f"<b>{n}</b> ({style['label']})"
                if n in hub_nodes_used:
                    nx_o.append(x_); ny_o.append(y_)
                    txt_o.append(n); hov_o.append(tip)
                else:
                    nx_c.append(x_); ny_c.append(y_)
                    txt_c.append(n); hov_c.append(tip)
            elif always_active:
                tip = f"<b>{n}</b> ({style['label']})"
                if ntype == "R":
                    demand_qty = vol_map.get(n, {}).get("demand", 0.0)
                    tip += f"<br>Demand fulfilled: {demand_qty:,.0f} units"
                nx_o.append(x_); ny_o.append(y_)
                txt_o.append(n); hov_o.append(tip)
            else:
                status = "Open" if n in open_nodes else "Closed"
                tip = f"<b>{n}</b> ({style['label']})<br>Status: {status}"

                # YC_i — installed floor area (all facility nodes)
                yc_val = area_map.get(n)
                if yc_val is not None:
                    tip += f"<br>Installed area: {yc_val:.1f} m²"

                if ntype == "F":
                    prod_t   = tech_info.get(n, {}).get("prod", "—")
                    rem_t    = tech_info.get(n, {}).get("rem",  "—")
                    prod_qty = vol_map.get(n, {}).get("prod", 0.0)
                    rem_qty  = vol_map.get(n, {}).get("rem",  0.0)
                    tip += (
                        f"<br>Production tech: {prod_t}<br>Remanufacturing tech: {rem_t}"
                        f"<br>Production: {prod_qty:,.0f} units"
                        f"<br>Remanufacturing: {rem_qty:,.0f} units"
                    )
                    veh = vehicle_map.get(n)
                    if veh:
                        veh_str = ", ".join(f"{m}: {k}" for m, k in sorted(veh.items()))
                        tip += f"<br>Fleet: {veh_str}"
                    inv_n = inv_map.get(n)
                    if inv_n:
                        inv_str = ", ".join(f"{p}: {v:,.0f}" for p, v in sorted(inv_n.items()))
                        tip += f"<br>Inventory: {inv_str}"
                elif ntype == "W":
                    veh = vehicle_map.get(n)
                    if veh:
                        veh_str = ", ".join(f"{m}: {k}" for m, k in sorted(veh.items()))
                        tip += f"<br>Fleet: {veh_str}"
                    inv_n = inv_map.get(n)
                    if inv_n:
                        inv_str = ", ".join(f"{p}: {v:,.0f}" for p, v in sorted(inv_n.items()))
                        tip += f"<br>Inventory: {inv_str}"
                elif ntype == "S":
                    order_qty = vol_map.get(n, {}).get("order", 0.0)
                    tip += f"<br>Orders: {order_qty:,.0f} units"
                    active_mats = orders_map.get(n)
                    if active_mats:
                        tip += f"<br>Active orders: {', '.join(sorted(active_mats))}"
                    veh = vehicle_map.get(n)
                    if veh:
                        veh_str = ", ".join(f"{m}: {k}" for m, k in sorted(veh.items()))
                        tip += f"<br>Fleet: {veh_str}"

                if n in open_nodes:
                    nx_o.append(x_); ny_o.append(y_)
                    txt_o.append(n); hov_o.append(tip)
                else:
                    nx_c.append(x_); ny_c.append(y_)
                    txt_c.append(n); hov_c.append(tip)

        legend_open  = style["label"] if (always_active or ntype in HUB_NODE_TYPES) else f"{style['label']} (open)"
        legend_closed = style["label"] if ntype in HUB_NODE_TYPES else f"{style['label']} (closed)"

        if nx_o:
            max_v   = _max_vol.get(ntype, 1.0)
            vol_key = {"F": "prod", "S": "order", "R": "demand"}.get(ntype)
            sizes_o = [
                _node_size(vol_map.get(n, {}).get(vol_key, 0.0), max_v,
                           show_node_vol and vol_key is not None)
                for n in txt_o
            ]
            # YC border-width encoding (show_yc_border): border ∝ installed area
            if show_yc_border and ntype in ("F", "W", "S"):
                border_widths = [
                    1.5 + 6.0 * (area_map.get(n, 0.0) / max_yc)
                    for n in txt_o
                ]
                border_color = style["color"]
            else:
                border_widths = 1.5
                border_color  = "white"
            fig.add_trace(go.Scatter(
                x=nx_o, y=ny_o, mode="markers+text",
                text=txt_o, textposition="top center",
                textfont=dict(size=10, color=style["color"]),
                marker=dict(symbol=style["symbol"], size=sizes_o,
                            color=style["color"], opacity=1.0,
                            line=dict(color=border_color, width=border_widths)),
                hovertext=hov_o, hoverinfo="text",
                name=legend_open,
            ))
        if nx_c:
            fig.add_trace(go.Scatter(
                x=nx_c, y=ny_c, mode="markers+text",
                text=txt_c, textposition="top center",
                textfont=dict(size=9, color="#aaaaaa"),
                marker=dict(symbol=style["symbol"], size=11,
                            color=style["color"], opacity=0.22,
                            line=dict(color="#cccccc", width=1.0)),
                hovertext=hov_c, hoverinfo="text",
                name=legend_closed,
            ))

    period_label = f" &nbsp;|&nbsp; Period = <b>{period}</b>" if period else ""
    fig.update_layout(
        title=dict(
            text=(
                f"Supply Chain Network — <b>{instance}</b> &nbsp;|&nbsp; "
                f"Carbon tax = <b>{tau * 10:.0f} USD/t CO₂e</b>{period_label}"
            ),
            font=dict(size=14),
        ),
        showlegend=True,
        legend=dict(
            x=1.01, y=1, xanchor="left", yanchor="top",
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#cccccc", borderwidth=1,
            font=dict(size=11),
        ),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
                   scaleanchor="y", scaleratio=1),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        plot_bgcolor="white",
        margin=dict(l=10, r=160, t=60, b=10),
        height=height,
    )
    return fig


# ---------------------------------------------------------------------------
# Sparkline  (dual y-axes: emissions left, follower objective right)
# ---------------------------------------------------------------------------

def build_sparkline(summary: pd.DataFrame, tau: int, incumbent_tau: int) -> go.Figure:
    fig = go.Figure()

    eff_tax = summary["hat_tau"] * 10  # USD/t CO₂e

    # Left axis — Supply chain emissions (kt CO₂e)
    fig.add_trace(go.Scatter(
        x=eff_tax,
        y=summary["emissions"] / 1e6,
        mode="lines+markers", marker=dict(size=4),
        line=dict(color="#0072B2", width=1.8),
        name="Supply chain emissions (kt CO₂e)",
        yaxis="y1",
    ))

    # Right axis — Total supply chain cost (M USD)
    fig.add_trace(go.Scatter(
        x=eff_tax,
        y=summary["follower_objective"] / 1e6,
        mode="lines+markers", marker=dict(size=4),
        line=dict(color="#E69F00", width=1.8, dash="dash"),
        name="Total supply chain cost (M USD)",
        yaxis="y2",
    ))

    # Bilevel optimal tax marker on emissions curve
    inc = summary[summary["is_lf_lex_incumbent"] == 1]
    if not inc.empty:
        fig.add_trace(go.Scatter(
            x=inc["hat_tau"] * 10,
            y=inc["emissions"] / 1e6,
            mode="markers",
            marker=dict(symbol="diamond", size=12, color=BILEVEL_COLOR,
                        line=dict(color="white", width=1.5)),
            name=f"Bilevel optimal tax ({incumbent_tau * 10:.0f} USD/t CO₂e)",
            yaxis="y1",
        ))

    # Vertical line at current carbon tax
    fig.add_vline(x=tau * 10, line=dict(color="#333333", width=1.5, dash="dot"))

    fig.update_layout(
        height=160,
        margin=dict(l=55, r=65, t=6, b=35),
        xaxis=dict(
            title="Carbon tax (USD/t CO₂e)", tickmode="linear", dtick=20,
            tickformat=".0f",
            showgrid=True, gridcolor="#eeeeee",
        ),
        yaxis=dict(
            title=dict(text="Emissions (kt CO₂e)", font=dict(color="#0072B2", size=10)),
            tickfont=dict(color="#0072B2", size=9),
            showgrid=True, gridcolor="#eeeeee",
        ),
        yaxis2=dict(
            title=dict(text="Total cost (M USD)", font=dict(color="#E69F00", size=10)),
            tickfont=dict(color="#E69F00", size=9),
            overlaying="y", side="right",
            showgrid=False,
        ),
        plot_bgcolor="white",
        legend=dict(orientation="h", y=-0.45, font=dict(size=9)),
    )
    return fig


# ---------------------------------------------------------------------------
# Technology Installation Gantt
# ---------------------------------------------------------------------------

def build_tech_gantt(data: dict, tau: int, incumbent_tau: int) -> go.Figure:
    ti = data["tech_install"]

    # Universe: (factory, tech_kind, tech) pairs active at least once
    active_pairs = (
        ti[ti["active"] == 1][["factory", "tech_kind", "tech"]]
        .drop_duplicates()
        .sort_values(["factory", "tech_kind"])  # prod before rem alphabetically
        .reset_index(drop=True)
    )

    n_rows = len(active_pairs)
    fig = go.Figure()

    legend_added: set[str] = set()

    for row_idx, pair in active_pairs.iterrows():
        factory   = str(pair["factory"])
        tech_kind = str(pair["tech_kind"])
        tech_name = str(pair["tech"])

        active_taus = ti[
            (ti["factory"]   == factory) &
            (ti["tech_kind"] == tech_kind) &
            (ti["tech"]      == tech_name) &
            (ti["active"]    == 1)
        ]["hat_tau"].tolist()

        color     = "#0284C7" if tech_kind == "prod" else "#059669"
        leg_label = "Production technology" if tech_kind == "prod" else "Remanufacturing technology"
        show_leg  = leg_label not in legend_added

        x_segs, y_segs = [], []
        for t in active_taus:
            x_segs += [(t - 0.45) * 10, (t + 0.45) * 10, None]
            y_segs += [row_idx, row_idx, None]

        fig.add_trace(go.Scatter(
            x=x_segs, y=y_segs,
            mode="lines",
            line=dict(color=color, width=14),
            name=leg_label,
            legendgroup=tech_kind,
            showlegend=show_leg,
            hovertemplate=(
                f"<b>{factory}</b> — {'Production' if tech_kind == 'prod' else 'Remanufacturing'}: {tech_name}"
                "<extra></extra>"
            ),
        ))
        if show_leg:
            legend_added.add(leg_label)

    # Vertical line at current carbon tax
    fig.add_vline(
        x=tau * 10,
        line=dict(color="#333333", width=1.5, dash="dot"),
    )

    # Bilevel optimal tax — vertical reference line spanning all rows
    fig.add_vline(
        x=incumbent_tau * 10,
        line=dict(color=BILEVEL_COLOR, width=2.0),
    )
    # Phantom trace so the bilevel optimal appears in the legend
    fig.add_trace(go.Scatter(
        x=[None], y=[None],
        mode="lines",
        line=dict(color=BILEVEL_COLOR, width=2.0),
        name=f"Bilevel optimal tax ({incumbent_tau * 10:.0f} USD/t CO₂e)",
        showlegend=True,
    ))

    row_labels = [
        f"{r['factory']} — {'Production' if r['tech_kind']=='prod' else 'Remanufacturing'} ({r['tech']})"
        for _, r in active_pairs.iterrows()
    ]

    fig.update_layout(
        height=max(120, n_rows * 38 + 70),
        margin=dict(l=170, r=20, t=36, b=45),
        title=dict(text="Technology Installation", font=dict(size=12)),
        xaxis=dict(
            title="Carbon tax (USD/t CO₂e)",
            tickmode="linear", dtick=20, tickformat=".0f",
            showgrid=True, gridcolor="#eeeeee",
            range=[-5, data["tau_max"] * 10 + 5],
        ),
        yaxis=dict(
            tickmode="array",
            tickvals=list(range(n_rows)),
            ticktext=row_labels,
            tickfont=dict(size=10),
            showgrid=False,
            range=[-0.6, n_rows - 0.4],
        ),
        plot_bgcolor="white",
        legend=dict(
            x=1.01, y=1, xanchor="left", yanchor="top",
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#cccccc", borderwidth=1,
            font=dict(size=10),
        ),
    )
    return fig


# ---------------------------------------------------------------------------
# Transport Route Activity Gantt
# ---------------------------------------------------------------------------

def build_transport_gantt(data: dict, tau: int, incumbent_tau: int) -> go.Figure:
    ma = data["mode_active"]

    active_ma = ma[ma["active"] == 1]
    if active_ma.empty:
        fig = go.Figure()
        fig.add_annotation(text="No transport route data available",
                           xref="paper", yref="paper", x=0.5, y=0.5,
                           showarrow=False, font=dict(size=12, color="#888888"))
        fig.update_layout(height=120, plot_bgcolor="white",
                          margin=dict(l=20, r=20, t=36, b=20),
                          title=dict(text="Transport Activity", font=dict(size=12)))
        return fig

    # Arc-type ordering: S→F, F→W, hub, F→R, W→R, R→F, R→W, W→F
    _ARC_ORDER = {"A_sf": 0, "A_fw": 1, "hub": 2, "A_fr": 3, "A_wr": 4,
                  "A_rf": 5, "A_rw": 6, "A_wf": 7}

    active_pairs = (
        active_ma[["origin", "destination", "mode"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    active_pairs["_arc_order"] = active_pairs.apply(
        lambda r: _ARC_ORDER.get(
            data["arc_cat"].get((r["origin"], r["destination"]), "hub"), 99
        ),
        axis=1,
    )
    active_pairs = (
        active_pairs
        .sort_values(["_arc_order", "origin", "destination", "mode"])
        .reset_index(drop=True)
    )
    n_rows = len(active_pairs)
    fig = go.Figure()

    # Distinct color per unique truck mode; air and sea get fixed colors
    _ROAD_PALETTE = ["#E69F00", "#D55E00", "#CC79A7", "#F0E442", "#009E73"]
    _road_modes   = sorted(active_pairs[active_pairs["mode"].str.startswith("mrd")]["mode"].unique())
    _road_color   = {m: _ROAD_PALETTE[i % len(_ROAD_PALETTE)] for i, m in enumerate(_road_modes)}

    def _mode_color(mode: str) -> str:
        if mode.startswith("mrd"):
            return _road_color.get(mode, "#E69F00")
        if mode.startswith("ma"):
            return "#56B4E9"
        if mode.startswith("ms"):
            return "#009E73"
        return "#999999"

    def _mode_label(mode: str) -> str:
        if mode.startswith("mrd"):
            return f"Truck ({mode})"
        if mode.startswith("ma"):
            return "Air"
        if mode.startswith("ms"):
            return "Sea"
        return mode

    legend_added: set[str] = set()

    for row_idx, pair in active_pairs.iterrows():
        orig = str(pair["origin"])
        dest = str(pair["destination"])
        mode = str(pair["mode"])

        active_taus = (
            active_ma[
                (active_ma["origin"]      == orig) &
                (active_ma["destination"] == dest) &
                (active_ma["mode"]        == mode)
            ]["hat_tau"]
            .unique()
            .tolist()
        )

        color     = _mode_color(mode)
        leg_label = _mode_label(mode)
        show_leg  = leg_label not in legend_added

        x_segs, y_segs = [], []
        for t in active_taus:
            x_segs += [(t - 0.45) * 10, (t + 0.45) * 10, None]
            y_segs += [row_idx, row_idx, None]

        fig.add_trace(go.Scatter(
            x=x_segs, y=y_segs,
            mode="lines",
            line=dict(color=color, width=14),
            name=leg_label,
            legendgroup=leg_label,
            showlegend=show_leg,
            hovertemplate=(
                f"<b>{orig} → {dest}</b> ({mode})"
                "<extra></extra>"
            ),
        ))
        if show_leg:
            legend_added.add(leg_label)

    fig.add_vline(x=tau * 10, line=dict(color="#333333", width=1.5, dash="dot"))
    fig.add_vline(x=incumbent_tau * 10, line=dict(color=BILEVEL_COLOR, width=2.0))
    fig.add_trace(go.Scatter(
        x=[None], y=[None],
        mode="lines",
        line=dict(color=BILEVEL_COLOR, width=2.0),
        name=f"Bilevel optimal tax ({incumbent_tau * 10:.0f} USD/t CO₂e)",
        showlegend=True,
    ))

    row_labels = [
        f"{r['origin']} → {r['destination']} ({r['mode']})"
        for _, r in active_pairs.iterrows()
    ]

    fig.update_layout(
        height=max(120, n_rows * 38 + 70),
        margin=dict(l=170, r=20, t=36, b=45),
        title=dict(text="Transport Activity", font=dict(size=12)),
        xaxis=dict(
            title="Carbon tax (USD/t CO₂e)",
            tickmode="linear", dtick=20, tickformat=".0f",
            showgrid=True, gridcolor="#eeeeee",
            range=[-5, data["tau_max"] * 10 + 5],
        ),
        yaxis=dict(
            tickmode="array",
            tickvals=list(range(n_rows)),
            ticktext=row_labels,
            tickfont=dict(size=10),
            showgrid=False,
            range=[-0.6, n_rows - 0.4],
        ),
        plot_bgcolor="white",
        legend=dict(
            x=1.01, y=1, xanchor="left", yanchor="top",
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#cccccc", borderwidth=1,
            font=dict(size=10),
        ),
    )
    return fig





# ---------------------------------------------------------------------------
# Streamlit app
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="SC Network Viewer",
        page_icon="\U0001f310",
        layout="wide",
    )

    st.markdown("""
    <style>
    section[data-testid="stSidebar"] [data-testid="stMetricValue"] {
        font-size: 1.4rem;
    }
    section[data-testid="stSidebar"] [data-testid="stMetricLabel"] {
        font-size: 0.85rem;
    }
    section[data-testid="stSidebar"] [data-testid="stMetricDelta"] {
        font-size: 0.78rem;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## Controls")

        cat_label = st.selectbox(
            "Instance category",
            options=list(CATEGORIES.keys()),
            index=0,
            help="Choose the scenario group: Base uses the standard instance set; "
                 "Tech/Transport expansion scenarios include additional technology or transport options.",
        )
        cat_key   = CATEGORIES[cat_label]
        instances = _discover_instances(cat_key)

        if not instances:
            st.warning("No solved instances found for this category.")
            st.stop()

        default_inst = "STD_I17_M4_T3" if cat_key == "base" else instances[0]
        instance = st.selectbox(
            "Instance",
            options=instances,
            index=instances.index(default_inst) if default_inst in instances else 0,
            help="Select the specific problem instance to visualise.",
        )

        st.caption(f"Loaded: **{instance}**")

        data = load_data(instance, cat_key)
        summary       = data["summary"]
        tau_min       = data["tau_min"]
        tau_max       = data["tau_max"]
        incumbent_tau = data["incumbent_tau"]

        st.divider()

        eff_tax_val = st.slider(
            "Carbon tax (USD/t CO₂e)",
            min_value=float(tau_min * 10),
            max_value=float(tau_max * 10),
            value=float(incumbent_tau * 10),
            step=10.0,
            format="%.0f",
            help="Step size is 10 USD/t CO₂e. The bilevel leader chooses the optimal tax "
                 "that minimises total emissions subject to the follower's cost response.",
        )
        tau = round(eff_tax_val / 10)

        # Carbon tax position in the modelled range
        n_steps = tau_max - tau_min
        rank    = tau - tau_min
        pct     = int(100 * rank / n_steps) if n_steps > 0 else 100
        st.caption(f"Tax level: {pct}th percentile of modelled range")

        if tau == incumbent_tau:
            st.success(f"Bilevel optimal tax ({eff_tax_val:.0f} USD/t CO₂e)")

        st.divider()
        row          = summary[summary["hat_tau"] == tau].iloc[0]
        baseline_row = summary[summary["hat_tau"] == tau_min].iloc[0]

        st.metric(
            "Supply chain emissions",
            _fmt_emissions(row["emissions"]),
            delta=f"{row['pct_emissions_change']:+.1f}% vs baseline",
            delta_color="inverse",
        )
        st.metric(
            "Total supply chain cost",
            _fmt_cost(row["follower_objective"]),
            delta=f"{row['pct_cost_change']:+.1f}% vs baseline",
            delta_color="inverse",
        )

        st.divider()

        # pre-compute transport stats (reused across Facilities and Transport)
        ma_sub = data["mode_active"]
        ma_sub = ma_sub[
            (ma_sub["hat_tau"] == tau) & (ma_sub["active"] == 1) & (ma_sub["family"] == "zt")
        ]
        used_hubs  = set(ma_sub["origin"]) | set(ma_sub["destination"])
        n_airports = len(used_hubs & set(data["sets"].get("AIR",  [])))
        n_seaports = len(used_hubs & set(data["sets"].get("PORT", [])))
        route_by_mode = (
            ma_sub.groupby("mode")
            .apply(lambda x: x[["origin", "destination"]].drop_duplicates().shape[0])
            .to_dict()
        )
        road = {m: v for m, v in route_by_mode.items() if m.startswith("mrd")}
        air  = {m: v for m, v in route_by_mode.items() if m.startswith("ma")}
        sea  = {m: v for m, v in route_by_mode.items() if m.startswith("ms")}

        def _route_count(d: dict) -> int:
            return sum(d.values()) if d else 0

        # baseline transport stats for delta comparison
        ma_base = data["mode_active"]
        ma_base = ma_base[
            (ma_base["hat_tau"] == tau_min) & (ma_base["active"] == 1) & (ma_base["family"] == "zt")
        ]
        base_route_by_mode = (
            ma_base.groupby("mode")
            .apply(lambda x: x[["origin", "destination"]].drop_duplicates().shape[0])
            .to_dict()
        )
        base_road = {m: v for m, v in base_route_by_mode.items() if m.startswith("mrd")}
        base_air  = {m: v for m, v in base_route_by_mode.items() if m.startswith("ma")}
        base_sea  = {m: v for m, v in base_route_by_mode.items() if m.startswith("ms")}

        base_used_hubs  = set(ma_base["origin"]) | set(ma_base["destination"])
        base_n_airports = len(base_used_hubs & set(data["sets"].get("AIR",  [])))
        base_n_seaports = len(base_used_hubs & set(data["sets"].get("PORT", [])))

        # transport_modes aggregates
        tm      = data["transport_modes"]
        tm_tau  = tm[tm["hat_tau"] == tau]
        tm_base = tm[tm["hat_tau"] == tau_min]

        def _tm_sum(df: pd.DataFrame, prefix: str, col: str) -> int:
            sub = df[df["mode"].str.startswith(prefix)]
            return int(sub[col].sum()) if col in sub.columns and not sub.empty else 0

        road_flow      = _tm_sum(tm_tau,  "mrd", "total_flow_qty")
        road_trips     = _tm_sum(tm_tau,  "mrd", "total_trips")
        road_vehicles  = _tm_sum(tm_tau,  "mrd", "total_vehicles")
        air_flow       = _tm_sum(tm_tau,  "ma",  "total_flow_qty")
        air_vehicles   = _tm_sum(tm_tau,  "ma",  "total_vehicles")
        sea_flow       = _tm_sum(tm_tau,  "ms",  "total_flow_qty")
        sea_vehicles   = _tm_sum(tm_tau,  "ms",  "total_vehicles")

        base_road_flow     = _tm_sum(tm_base, "mrd", "total_flow_qty")
        base_road_trips    = _tm_sum(tm_base, "mrd", "total_trips")
        base_road_vehicles = _tm_sum(tm_base, "mrd", "total_vehicles")
        base_air_flow      = _tm_sum(tm_base, "ma",  "total_flow_qty")
        base_air_vehicles  = _tm_sum(tm_base, "ma",  "total_vehicles")
        base_sea_flow      = _tm_sum(tm_base, "ms",  "total_flow_qty")
        base_sea_vehicles  = _tm_sum(tm_base, "ms",  "total_vehicles")

        _ARC_ORDER = {"A_sf": 0, "A_fw": 1, "hub": 2, "A_fr": 3, "A_wr": 4,
                      "A_rf": 5, "A_rw": 6, "A_wf": 7}
        road_routes = sorted(
            {(r["origin"], r["destination"])
             for _, r in ma_sub[ma_sub["mode"].str.startswith("mrd")].iterrows()},
            key=lambda t: (_ARC_ORDER.get(data["arc_cat"].get(t, "hub"), 99), t[0], t[1]),
        )

        open_nodes       = _open_nodes(data, tau)
        open_factories   = sorted(n for n in open_nodes if data["node_type"].get(n) == "F")
        open_warehouses  = sorted(n for n in open_nodes if data["node_type"].get(n) == "W")
        open_suppliers   = sorted(n for n in open_nodes if data["node_type"].get(n) == "S")
        active_airports  = sorted(used_hubs & set(data["sets"].get("AIR",  [])))
        active_seaports  = sorted(used_hubs & set(data["sets"].get("PORT", [])))

        # ── Facilities ───────────────────────────────────────────────────────
        with st.expander("Facilities", expanded=True):
            st.caption("Open")
            c1, c2 = st.columns(2)
            c1.metric(
                "Factories",
                int(row["num_factories_open"]),
                delta=_delta_count(int(row["num_factories_open"]), int(baseline_row["num_factories_open"])),
                delta_color="normal",
            )
            c2.metric(
                "Warehouses",
                int(row["num_warehouses_open"]),
                delta=_delta_count(int(row["num_warehouses_open"]), int(baseline_row["num_warehouses_open"])),
                delta_color="normal",
            )
            if open_factories:
                c1.caption(", ".join(open_factories))
            if open_warehouses:
                c2.caption(", ".join(open_warehouses))
            ia_tau = data["installed_area"]
            if not ia_tau.empty:
                ia_sub = ia_tau[(ia_tau["hat_tau"] == tau) & (ia_tau["active"] == 1)]
                if not ia_sub.empty:
                    st.caption("Installed area")
                    st.dataframe(
                        ia_sub[["facility", "value"]]
                        .rename(columns={"facility": "Facility", "value": "Area (m²)"})
                        .sort_values("Facility")
                        .reset_index(drop=True),
                        use_container_width=True,
                        hide_index=True,
                    )
            st.caption("Contracted")
            st.metric(
                "Suppliers",
                int(row["num_suppliers_open"]),
                delta=_delta_count(int(row["num_suppliers_open"]), int(baseline_row["num_suppliers_open"])),
                delta_color="normal",
            )
            if open_suppliers:
                st.caption(", ".join(open_suppliers))
            c1, c2 = st.columns(2)
            c1.metric(
                "Airports",
                n_airports,
                delta=_delta_count(n_airports, base_n_airports),
                delta_color="normal",
            )
            c2.metric(
                "Seaports",
                n_seaports,
                delta=_delta_count(n_seaports, base_n_seaports),
                delta_color="normal",
            )
            if active_airports:
                st.caption("Airports: " + ", ".join(active_airports))
            if active_seaports:
                st.caption("Seaports: " + ", ".join(active_seaports))

        # ── Transport ────────────────────────────────────────────────────────
        with st.expander("Transport", expanded=True):
            st.caption("Road (owned)")
            c1, c2 = st.columns(2)
            c1.metric(
                "Trucks",
                road_vehicles,
                delta=_delta_count(road_vehicles, base_road_vehicles),
                delta_color="normal",
            )
            c2.metric(
                "Routes",
                _route_count(road),
                delta=_delta_count(_route_count(road), _route_count(base_road)),
                delta_color="normal",
            )
            c1, c2 = st.columns(2)
            c1.metric(
                "Trips",
                road_trips,
                delta=_delta_count(road_trips, base_road_trips),
                delta_color="normal",
            )
            if road_flow > 0:
                c2.metric(
                    "Flow qty (units)",
                    f"{road_flow:,}",
                    delta=_delta_count(road_flow, base_road_flow),
                    delta_color="normal",
                )
            if road_routes:
                st.caption("Active routes: " + ", ".join(f"{o}→{d}" for o, d in road_routes))

            st.caption("Air (contracted)")
            c1, c2 = st.columns(2)
            c1.metric(
                "Routes",
                _route_count(air),
                delta=_delta_count(_route_count(air), _route_count(base_air)),
                delta_color="normal",
            )
            c2.metric(
                "Planes",
                air_vehicles,
                delta=_delta_count(air_vehicles, base_air_vehicles),
                delta_color="normal",
            )
            if air_flow > 0:
                st.metric(
                    "Flow qty (units)",
                    f"{air_flow:,}",
                    delta=_delta_count(air_flow, base_air_flow),
                    delta_color="normal",
                )

            st.caption("Sea (contracted)")
            c1, c2 = st.columns(2)
            c1.metric(
                "Routes",
                _route_count(sea),
                delta=_delta_count(_route_count(sea), _route_count(base_sea)),
                delta_color="normal",
            )
            c2.metric(
                "Ships",
                sea_vehicles,
                delta=_delta_count(sea_vehicles, base_sea_vehicles),
                delta_color="normal",
            )
            if sea_flow > 0:
                st.metric(
                    "Flow qty (units)",
                    f"{sea_flow:,}",
                    delta=_delta_count(sea_flow, base_sea_flow),
                    delta_color="normal",
                )


            # κ_mt — outsourced capacity contracts
            tm_c = data["transport_modes"]
            if not tm_c.empty and "active_contract_periods" in tm_c.columns:
                tm_c_tau = tm_c[tm_c["hat_tau"] == tau]
                air_sea_c = tm_c_tau[tm_c_tau["mode"].str.startswith(("ma", "ms"))]
                if not air_sea_c.empty:
                    st.caption("Outsourced contracts (κ_mt)")
                    st.dataframe(
                        air_sea_c[["mode", "active_contract_periods"]]
                        .rename(columns={"mode": "Mode",
                                         "active_contract_periods": "Contracted periods"})
                        .sort_values("Mode")
                        .reset_index(drop=True),
                        use_container_width=True,
                        hide_index=True,
                    )

        # technology install lists and output volumes
        ti     = data["tech_install"]
        ti_tau = ti[(ti["hat_tau"] == tau) & (ti["active"] == 1)]
        prod_tech_list = sorted(
            f"{r['tech']} at {r['factory']}"
            for _, r in ti_tau[ti_tau["tech_kind"] == "prod"].iterrows()
        )
        rem_tech_list = sorted(
            f"{r['tech']} at {r['factory']}"
            for _, r in ti_tau[ti_tau["tech_kind"] == "rem"].iterrows()
        )
        pbt = data["prod_by_tau_factory"]
        rbt = data["rem_by_tau_factory"]
        prod_vol      = pbt[pbt["hat_tau"] == tau]["prod_qty"].sum()
        prod_vol_base = pbt[pbt["hat_tau"] == tau_min]["prod_qty"].sum()
        rem_vol       = rbt[rbt["hat_tau"] == tau]["rem_qty"].sum()
        rem_vol_base  = rbt[rbt["hat_tau"] == tau_min]["rem_qty"].sum()

        # ── Technologies ─────────────────────────────────────────────────────
        with st.expander("Technologies", expanded=True):
            c1, c2 = st.columns(2)
            c1.metric(
                "Production",
                int(row["num_prod_tech_installed"]),
                delta=_delta_count(int(row["num_prod_tech_installed"]), int(baseline_row["num_prod_tech_installed"])),
                delta_color="normal",
            )
            c2.metric(
                "Remanufacturing",
                int(row["num_rem_tech_installed"]),
                delta=_delta_count(int(row["num_rem_tech_installed"]), int(baseline_row["num_rem_tech_installed"])),
                delta_color="normal",
            )
            if prod_tech_list or rem_tech_list:
                c1, c2 = st.columns(2)
                if prod_tech_list:
                    c1.caption(", ".join(prod_tech_list))
                if rem_tech_list:
                    c2.caption(", ".join(rem_tech_list))
            c1, c2 = st.columns(2)
            c1.metric(
                "Qty produced (units)",
                f"{prod_vol:,.0f}",
                delta=_delta_count(int(prod_vol), int(prod_vol_base)),
                delta_color="normal",
            )
            c2.metric(
                "Qty remanufactured (units)",
                f"{rem_vol:,.0f}",
                delta=_delta_count(int(rem_vol), int(rem_vol_base)),
                delta_color="normal",
            )

        # ── Inventory ─────────────────────────────────────────────────────────
        with st.expander("Inventory (units)", expanded=False):
            inv_df = data["inventory"]
            if inv_df.empty:
                st.caption("No inventory data available.")
            else:
                inv_tau = inv_df[(inv_df["hat_tau"] == tau) & (inv_df["active"] == 1)]
                if inv_tau.empty:
                    st.caption("No active inventory at this tax level.")
                else:
                    inv_f_sub = inv_tau[inv_tau["level"] == "factory"]
                    inv_w_sub = inv_tau[inv_tau["level"] == "warehouse"]
                    inv_r_sub = inv_tau[inv_tau["level"] == "warehouse_recovered"]

                    fac_total = inv_f_sub["value"].sum()
                    wh_total  = inv_w_sub["value"].sum() + inv_r_sub["value"].sum()

                    c1, c2 = st.columns(2)
                    c1.metric("Factories (units)", f"{fac_total:,.0f}")
                    c2.metric("Warehouses (units)", f"{wh_total:,.0f}")

                    if not inv_f_sub.empty:
                        _fac_col = "factory" if "factory" in inv_f_sub.columns else inv_f_sub.columns[0]
                        fac_by_node = (
                            inv_f_sub.groupby(_fac_col)["value"].sum()
                            .sort_index()
                        )
                        st.caption("Factories: " + ", ".join(
                            f"{n}: {v:,.0f}" for n, v in fac_by_node.items()
                        ))

                    _wh_col = "warehouse" if "warehouse" in inv_tau.columns else "factory"
                    wh_all = inv_tau[inv_tau["level"].isin(["warehouse", "warehouse_recovered"])]
                    if not wh_all.empty:
                        wh_by_node = (
                            wh_all.groupby(_wh_col)["value"].sum()
                            .sort_index()
                        )
                        st.caption("Warehouses: " + ", ".join(
                            f"{n}: {v:,.0f}" for n, v in wh_by_node.items()
                        ))

        # ── Display options ───────────────────────────────────────────────────
        with st.expander("Display options", expanded=False):
            st.caption("Arcs")
            show_inactive = st.checkbox(
                "Show inactive arcs (grey)",
                value=False,
                help="Render arcs that carry no flow at this tax level as faint grey lines.",
            )
            show_flow     = st.checkbox(
                "Arc width proportional to flow volume",
                value=False,
                help="Thicker arcs indicate higher flow quantities along that route.",
            )
            st.caption("Nodes")
            show_node_vol = st.checkbox(
                "Node size proportional to production volume",
                value=False,
                help="Larger node markers indicate higher production or order quantities.",
            )
            show_yc_border = st.checkbox(
                "Node border width ∝ installed area",
                value=False,
                help="Thicker node borders indicate larger installed facility area.",
            )
            period = None
            st.caption("Network map")
            map_height = st.slider("Height (px)", min_value=300, max_value=1000, value=580, step=50)

        # ── Structural info ───────────────────────────────────────────────────
        with st.expander("Structural info", expanded=False):
            if row["structural_change"] == 1:
                st.warning("Structural change at this carbon tax")
            c1, c2 = st.columns(2)
            c1.metric(
                "Phase",
                int(row["phase_id"]),
                help="A phase groups consecutive carbon tax levels that share the same "
                     "network topology — the same set of open facilities and active arcs. "
                     "A new phase begins whenever a structural change occurs.",
            )
            c2.metric("Active arcs", int(row["num_active_arcs"]))

            st.caption("Carbon economics")
            c1, c2 = st.columns(2)
            st.metric("MAC (USD/kg CO₂e)", _fmt_optional(row["mac"], "{:.3f}"))

            st.caption("Efficiency")
            c1, c2 = st.columns(2)
            c1.metric(
                "Emissions intensity (kg/unit)",
                f"{row['emissions_per_unit_production']:,.1f}",
                delta=_delta_count(
                    int(row["emissions_per_unit_production"]),
                    int(baseline_row["emissions_per_unit_production"]),
                ),
                delta_color="inverse",
            )
            c2.metric(
                "Cost per unit (USD)",
                f"{row['cost_per_unit_production']:.2f}",
                delta=_delta_count(
                    int(row["cost_per_unit_production"] * 100),
                    int(baseline_row["cost_per_unit_production"] * 100),
                ),
                delta_color="normal",
            )
            st.metric(
                "Flow per trip (units)",
                f"{row['flow_per_trip']:,.0f}",
                delta=_delta_count(
                    int(row["flow_per_trip"]),
                    int(baseline_row["flow_per_trip"]),
                ),
                delta_color="normal",
            )

            st.caption("Solver")
            c1, c2 = st.columns(2)
            c1.metric("Solve time", f"{row['solve_seconds']:.1f} s")
            c2.metric("MIP gap", f"{float(row['mip_gap']):.4%}")

        st.divider()
        csv_row = summary[summary["hat_tau"] == tau].to_csv(index=False)
        st.download_button(
            "Export current row",
            data=csv_row,
            file_name=f"{instance}_tau{eff_tax_val:.0f}.csv",
            mime="text/csv",
            help="Download the summary metrics for the currently selected carbon tax level as a CSV file.",
        )

    # ── Main area ─────────────────────────────────────────────────────────────
    fig_net       = build_network_fig(
        data, tau, show_inactive, show_flow, show_node_vol,
        show_yc_border=show_yc_border, period=period, height=map_height,
    )
    fig_spark     = build_sparkline(summary, tau, incumbent_tau)
    fig_tech      = build_tech_gantt(data, tau, incumbent_tau)
    fig_transport = build_transport_gantt(data, tau, incumbent_tau)
    st.plotly_chart(fig_net,       use_container_width=True)
    st.plotly_chart(fig_spark,     use_container_width=True)
    st.plotly_chart(fig_tech,      use_container_width=True)
    st.plotly_chart(fig_transport, use_container_width=True)


if __name__ == "__main__":
    main()
