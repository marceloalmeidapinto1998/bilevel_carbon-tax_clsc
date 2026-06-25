"""Read-only aggregation of all committed bilevel-CLSC results.

Walks results/{base,scenarios/*,sensitivity}/**/lf_lex_exact and consolidates
every run into master tables under results/analysis/.

Corruption-robust by design: the run-level summary.csv and the network/summary.csv
have fixed column orders. We therefore parse every CSV positionally, which also
recovers older scenario outputs with corrupted header text.

This module only reads results/** and only writes results/analysis/**.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from tools.analysis.common.csv_io import read_network, read_run
from tools.analysis.common.paths import REPORTS, RUNS, TABLES, ensure_analysis_dirs
from tools.analysis.common.schemas import base_instance, imt
from tools.experiments.legacy_v1.oat.specs import canonical_code

_LOG: list[str] = []


def log(msg: str) -> None:
    _LOG.append(msg)
    print(msg)


def corruption_tag(run_dir: Path) -> str:
    parts = run_dir.parts
    if "tech" in parts and "tech_trans" not in parts and "scenarios" in parts:
        return "tech(t->e)"
    if "trans" in parts and "tech_trans" not in parts and "scenarios" in parts:
        return "trans(t->r)"
    return "clean"


def main() -> None:
    _LOG.clear()
    ensure_analysis_dirs()
    run_rows: list[dict] = []
    curve_frames: list[pd.DataFrame] = []

    for csv_path in sorted(RUNS.glob("**/lf_lex_exact/summary.csv")):
        run_dir = csv_path.parent
        rel = run_dir.relative_to(RUNS).parts
        if len(rel) >= 5 and rel[:3] == ("experiments", "sensitivity", "oat"):
            raw_code = rel[4][3:] if rel[4].startswith("SA_") else rel[4]
            canon = canonical_code(raw_code)
            if canon != rel[4] and (run_dir.parent.parent / canon / run_dir.name / "summary.csv").exists():
                continue
        rec = read_run(csv_path, log)
        if rec is None:
            continue

        # results/runs/{base/<inst>, experiments/scenarios/<type>/<inst>,
        #               experiments/sensitivity/oat/<base>/<SA>, experiments/sensitivity/morris/...}
        rec_instance = str(rec["instance"])
        if rel[0] == "base":
            category, scenario, sa_dim, code = "base", "base", "", rel[1]
        elif len(rel) >= 4 and rel[:2] == ("experiments", "scenarios"):
            category, scenario, sa_dim, code = "scenario", rel[2], "", rel[3]
        elif len(rel) >= 5 and rel[:3] == ("experiments", "sensitivity", "oat"):
            category, scenario, sa_dim, code = "sensitivity", "base", rel[4], rel[3]
        else:
            continue  # morris runs (analyzed separately) and anything unrecognized

        binst = base_instance(code) or base_instance(rec_instance) or code
        I, M, T = imt(binst)
        fo_check = rec["cost"] + rec["effective_tax"] * rec["emissions"]
        resid = abs(fo_check - rec["follower_objective"])

        row = {
            "category": category,
            "scenario": scenario,
            "sa_dim": sa_dim,
            "instance_code": rec_instance,
            "base_instance": binst,
            "I": I,
            "M": M,
            "T": T,
            "corruption": corruption_tag(run_dir),
            "success": rec["success"],
            "exact": rec["exact"],
            "termination_reason": rec["termination_reason"],
            "iterations": rec["iterations"],
            "hat_tau": rec["hat_tau"],
            "effective_tax": rec["effective_tax"],
            "cost": rec["cost"],
            "emissions": rec["emissions"],
            "follower_objective": rec["follower_objective"],
            "fo_residual": resid,
            "relative_gap": rec["relative_gap"],
            "validation": rec["validation_status"].replace("validaeed", "validated")
                                                .replace("validared", "validated"),
            "solve_seconds": rec["solve_seconds"],
        }

        net = read_network(run_dir / "network" / "summary.csv", log)
        if net is not None and not net.empty:
            inc = net[net["is_lf_lex_incumbent"] == 1]
            inc = inc.iloc[0] if not inc.empty else net.iloc[(net["hat_tau"] - rec["hat_tau"]).abs().idxmin()]
            E0 = (
                float(net.loc[net["hat_tau"] == 0, "emissions"].iloc[0])
                if (net["hat_tau"] == 0).any()
                else float(net["emissions"].iloc[0])
            )
            Emin = float(net["emissions"].min())
            row.update({
                "net_available": True,
                "sup_open": int(inc["num_suppliers_open"]),
                "fac_open": int(inc["num_factories_open"]),
                "wh_open": int(inc["num_warehouses_open"]),
                "hub_open": int(inc["num_hubs_open"]),
                "prod_tech": int(inc["num_prod_tech_installed"]),
                "rem_tech": int(inc["num_rem_tech_installed"]),
                "modes_contracted": int(inc["num_modes_contracted"]),
                "active_arcs": int(inc["num_active_arcs"]),
                "prod_qty": float(inc["total_production_qty"]),
                "reman_qty": float(inc["total_remanufacturing_qty"]),
                "reman_share": float(inc["remanufacturing_share"]),
                "trips": float(inc["total_trips"]),
                "wh_open_max": int(net["num_warehouses_open"].max()),
                "emis_tau0": E0,
                "emis_floor": Emin,
                "max_abatement_pct": (E0 - Emin) / E0 * 100 if E0 else pd.NA,
                "n_phases": int(net["phase_id"].nunique()),
                "n_structural_changes": int(net["structural_change"].sum()),
                "hat_tau_max_on_curve": int(net["hat_tau"].max()),
                "censored": bool(rec["hat_tau"] >= net["hat_tau"].max() - 1e-9),
            })
            cf = net.copy()
            cf.insert(0, "base_instance", binst)
            cf.insert(0, "sa_dim", sa_dim)
            cf.insert(0, "scenario", scenario)
            cf.insert(0, "category", category)
            curve_frames.append(cf)
        else:
            row["net_available"] = False

        run_rows.append(row)

    master = pd.DataFrame(run_rows).sort_values(
        ["category", "scenario", "base_instance", "sa_dim"],
    ).reset_index(drop=True)
    master.to_csv(TABLES / "master_runs.csv", index=False)
    log(f"master_runs.csv: {len(master)} runs")
    for cat, n in master.groupby("category").size().items():
        log(f"  {cat}: {n}")
    log("  scenarios: " + ", ".join(
        f"{s}={n}" for s, n in master[master.category == "scenario"].groupby("scenario").size().items()
    ))

    if curve_frames:
        long = pd.concat(curve_frames, ignore_index=True)
        long.to_csv(TABLES / "tax_response_long.csv", index=False)
        log(f"tax_response_long.csv: {len(long)} (run,tau) rows from "
            f"{master['net_available'].sum()} runs with network data")

    scn = master[master.category.isin(["base", "scenario"])].copy()
    piv = scn.pivot_table(
        index="base_instance",
        columns="scenario",
        values=["effective_tax", "emissions", "cost"],
        aggfunc="first",
    )
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    for metric in ["effective_tax", "emissions", "cost"]:
        for s in ["tech", "trans", "tech_trans"]:
            bcol, scol = f"{metric}_base", f"{metric}_{s}"
            if bcol in piv and scol in piv:
                piv[f"d_{metric}_{s}_pct"] = (piv[scol] - piv[bcol]) / piv[bcol] * 100
    piv.to_csv(TABLES / "scenario_2x2.csv")
    log(f"scenario_2x2.csv: {piv.shape[0]} base instances")

    bad = master[master.fo_residual > 1.0]
    log(f"follower-objective identity: max residual="
        f"{master['fo_residual'].max():.3g}; rows>1.0: {len(bad)}")
    log(f"warehouses ever open (incumbent): "
        f"{int((master.get('wh_open', pd.Series(dtype=float)) > 0).sum())}; "
        f"warehouses open anywhere on any curve: "
        f"{int((master.get('wh_open_max', pd.Series(dtype=float)) > 0).sum())}")

    (REPORTS / "build_log.txt").write_text("\n".join(_LOG), encoding="utf-8")
    log(f"\nWrote tables to {TABLES}")


if __name__ == "__main__":
    main()
