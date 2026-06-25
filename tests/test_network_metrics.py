"""Tests for tools.analysis.network metrics helpers."""

from __future__ import annotations

from dataclasses import replace

from tools.analysis.network.io import DEFAULT
from tools.analysis.network.core import (
    BASE_SUMMARY_COLUMNS,
    DERIVED_SUMMARY_COLUMNS,
    aggregate_snapshot_metrics,
    build_summary_dataframe,
    build_transport_mode_dataframe,
    enrich_summary,
    parse_follower_into_rows,
)
from tools.analysis.network.pipeline import _snapshots_from_payload


def test_parse_follower_groups_into_files():
    follower = {
        "y_s[s1]": 1.0,
        "y_f[f1]": 1.0,
        "q[p1,f1,t1,1]": 5.0,
        "ghost[?]": 0.5,
    }
    base = {"hat_tau": 0, "effective_tax": 0.0, "is_lf_lex_incumbent": 0}
    rows_by_file, unknown = parse_follower_into_rows(follower, base, 1e-6)
    assert {r["layer"] for r in rows_by_file["facility_open.csv"]} == {"supplier", "factory"}
    assert any(r["value"] == 5.0 for r in rows_by_file["production.csv"])
    assert any(u["raw_key"] == "ghost[?]" for u in unknown)


def test_aggregate_snapshot_metrics_counts_open_facilities():
    follower = {
        "y_s[s1]": 1.0, "y_s[s2]": 1.0,
        "y_f[f1]": 1.0,
        "u_prod[f1,p_tech]": 1.0,
        "u_rem[f1,r_tech]": 1.0,
        "q[p1,f1,p_tech,t1]": 3.0,
        "rem[p1,f1,r_tech,t1]": 1.0,
        "x[p1,f1,w1,mrd1,t1]": 4.0,
        "trip[f1,w1,mrd1,t1]": 1.0,
        "zt[f1,w1,mrd1,t1]": 1.0,
        "contract[mrd1,t1]": 1.0,
    }
    rows_by_file, _ = parse_follower_into_rows(
        follower, {"hat_tau": 0, "effective_tax": 0.0, "is_lf_lex_incumbent": 0}, 1e-6,
    )
    m = aggregate_snapshot_metrics(rows_by_file)
    assert m["num_suppliers_open"] == 2
    assert m["num_factories_open"] == 1
    assert m["num_prod_tech_installed"] == 1
    assert m["num_rem_tech_installed"] == 1
    assert m["total_production_qty"] == 3.0
    assert m["total_flow_volume"] == 4.0
    assert m["num_modes_contracted"] == 1


def test_build_transport_mode_dataframe_summarizes_modes():
    follower = {
        "x[p1,f1,w1,mrd1,t1]": 4.0,
        "trip[f1,w1,mrd1,t1]": 2.0,
        "zt[f1,w1,mrd1,t1]": 1.0,
        "vehicle[f1,mrd1]": 1.0,
        "x[p1,air1,air2,ma1,t1]": 7.0,
        "zt[air1,air2,ma1,t1]": 1.0,
        "contract[ma1,t1]": 1.0,
    }
    rows_by_file, _ = parse_follower_into_rows(
        follower, {"hat_tau": 0, "effective_tax": 0.0, "is_lf_lex_incumbent": 0}, 1e-6,
    )
    df = build_transport_mode_dataframe(rows_by_file)

    by_mode = {row["mode"]: row for row in df.to_dict("records")}
    assert by_mode["mrd1"]["active_arc_periods"] == 1
    assert by_mode["mrd1"]["total_flow_qty"] == 4.0
    assert by_mode["mrd1"]["total_trips"] == 2.0
    assert by_mode["mrd1"]["total_vehicles"] == 1.0
    assert by_mode["ma1"]["active_contract_periods"] == 1
    assert by_mode["ma1"]["total_flow_qty"] == 7.0


def test_enrich_summary_adds_all_derived_columns(synthetic_results_base, synthetic_instance):
    cfg = replace(DEFAULT, results_base=synthetic_results_base)
    from tools.analysis.network.io import load_enumeration_payload
    enum_payload = load_enumeration_payload(synthetic_instance, cfg)
    snapshots, _, _ = _snapshots_from_payload(enum_payload, lf_lex_hat_tau=2, cfg=cfg)
    df = build_summary_dataframe(snapshots)
    df = enrich_summary(df, snapshots, baseline_tau=0, eps=1e-6)
    for col in BASE_SUMMARY_COLUMNS + DERIVED_SUMMARY_COLUMNS:
        assert col in df.columns
    assert df.iloc[0]["delta_cost_vs_baseline"] == 0.0
    assert df.iloc[0]["delta_emissions_vs_baseline"] == 0.0
    assert df.iloc[1]["pct_emissions_change"] < 0  # emissions go down with tax


def test_mac_handles_zero_emissions_delta(synthetic_results_base, synthetic_instance):
    cfg = replace(DEFAULT, results_base=synthetic_results_base)
    from tools.analysis.network.io import load_enumeration_payload
    enum_payload = load_enumeration_payload(synthetic_instance, cfg)
    # Force two adjacent identical emissions
    enum_payload["tax_solutions"][2]["objectives"]["emissions"] = (
        enum_payload["tax_solutions"][1]["objectives"]["emissions"]
    )
    snapshots, _, _ = _snapshots_from_payload(enum_payload, lf_lex_hat_tau=2, cfg=cfg)
    df = build_summary_dataframe(snapshots)
    df = enrich_summary(df, snapshots, baseline_tau=0, eps=1e-6)
    import math
    assert math.isnan(df.iloc[2]["mac"])


