"""Read-only aggregation of doe_campaign_01 runs into results/analysis/doe_campaign_01/tables/master_runs_doe_campaign_01.csv.

Unlike the v1 aggregator (`tools.analysis.aggregate.core`), this does not need to parse
directory-name conventions to recover instance class/scenario/factor information: every field
is already explicit in each run's `campaign_manifest.json` (written by
`tools.experiments.doe_campaign_01.campaign`), so this module is a straight walk-and-flatten.
"""
from __future__ import annotations

import json

import pandas as pd

from clsc.models.instance import SCALE_FACTOR
from tools.analysis.common.schemas import imt
from tools.analysis.doe_campaign_01.paths import RUNS, TABLES, ensure_analysis_dirs

# USD/t per integer tax_index step: SCALE_FACTOR is USD/kg per step (single source of
# truth in clsc.models.instance); x1000 converts kg -> t.
USD_PER_TONNE_PER_TAX_INDEX = SCALE_FACTOR * 1000.0


def _flatten(manifest: dict) -> dict:
    base_instance = manifest.get("base_instance_id", "")
    I, M, T = imt(base_instance)
    objective_values = manifest.get("objective_values") or {}
    factor_levels = manifest.get("factor_levels") or {}
    tax_index = manifest.get("leader_tax")

    row = {
        "campaign_id": manifest.get("campaign_id"),
        "family_id": manifest.get("family_id"),
        "design_point_id": manifest.get("design_point_id"),
        "base_instance_id": base_instance,
        "I": I,
        "M": M,
        "T": T,
        "technology_menu": manifest.get("technology_menu"),
        "transport_menu": manifest.get("transport_menu"),
        "seed_offset": manifest.get("seed_offset"),
        "code_version": manifest.get("code_version"),
        "solver_method": manifest.get("solver_method"),
        "solve_status": manifest.get("solve_status"),
        "termination_reason": manifest.get("termination_reason"),
        "censored": manifest.get("censored"),
        "cost": objective_values.get("cost"),
        "emissions": objective_values.get("emissions"),
        "follower_objective": objective_values.get("follower_objective"),
        # Analysis/reporting should use the economically meaningful rate, not the raw
        # index -- see paper/appendix/app_data.tex Sec. "Carbon-Tax Range Justification".
        # leader_tax_index is kept only for traceability/joining against design points.
        "leader_tax_index": tax_index,
        "leader_tax_usd_per_tonne": (
            tax_index * USD_PER_TONNE_PER_TAX_INDEX if tax_index is not None else None
        ),
        "runtime_seconds": manifest.get("runtime_seconds"),
        "mip_gap": manifest.get("mip_gap"),
        "time_limit_seconds": manifest.get("time_limit_seconds"),
        "wall_clock_cap_seconds": manifest.get("wall_clock_cap_seconds"),
        "validation_status": manifest.get("validation_status"),
        "error_type": manifest.get("error_type"),
        "output_path": manifest.get("output_path"),
        "notes": manifest.get("notes"),
    }
    for factor_name, level in factor_levels.items():
        row[f"factor__{factor_name}"] = level
    return row


def aggregate() -> pd.DataFrame:
    ensure_analysis_dirs()
    rows = []
    for manifest_path in sorted(RUNS.glob("**/campaign_manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append(_flatten(manifest))

    df = pd.DataFrame(rows)
    out_path = TABLES / "master_runs_doe_campaign_01.csv"
    df.to_csv(out_path, index=False)
    return df


def main() -> None:
    df = aggregate()
    print(f"Wrote {len(df)} run rows to {TABLES / 'master_runs_doe_campaign_01.csv'}")
    if not df.empty:
        print(df["solve_status"].value_counts().to_string())


if __name__ == "__main__":
    main()
