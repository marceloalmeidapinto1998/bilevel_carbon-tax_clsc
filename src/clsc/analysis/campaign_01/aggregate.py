"""Read-only aggregation of campaign_01 runs into
results/analysis/campaign_01/tables/master_runs_campaign_01.csv.

Every field is already explicit in each run's campaign_manifest.json, so this is a straight
walk-and-flatten over the experiment-keyed run tree.
"""
from __future__ import annotations

import json

import pandas as pd

from clsc.analysis.common.schemas import imt
from clsc.analysis.campaign_01.paths import REPO, RUNS, TABLES, ensure_analysis_dirs

KG_PER_TONNE = 1000.0

_STRUCTURAL_MENU_FIELDS = (
    "production_technology_menu",
    "remanufacturing_technology_menu",
    "road_menu",
    "sea_menu",
    "air_menu",
)


def _effective_tax_usd_per_kg(manifest: dict) -> float | None:
    """The run's carbon tax as a RATE, which is the only form comparable across runs.

    A `tax_index` is meaningless without its grid step, and the campaign uses two grids 100x
    apart (fine 1e-4 for the bilevel runs, coarse 1e-2 natively) -- so the rate is taken from
    what the solver actually applied, never recomputed from a global constant. Runs solved
    before the grid step was recorded in the manifest are recovered from their solve output.
    """
    rate = manifest.get("effective_tax_usd_per_kg")
    if rate is not None:
        return float(rate)

    tax_index = manifest.get("leader_tax")
    step = manifest.get("tax_grid_step_usd_per_kg")
    if step is not None and tax_index is not None:
        return float(step) * float(tax_index)

    output_path = manifest.get("output_path")
    if output_path:
        try:
            payload = json.loads((REPO / output_path).read_text(encoding="utf-8"))
            summary = payload[0] if isinstance(payload, list) else payload
            if summary.get("effective_tax") is not None:
                return float(summary["effective_tax"])
        except (OSError, json.JSONDecodeError, IndexError, TypeError, ValueError):
            pass
    return None  # better absent than silently on the wrong grid


def _flatten(manifest: dict) -> dict:
    base_instance = manifest.get("base_instance_id", "")
    I, M, T = imt(base_instance)
    objective_values = manifest.get("objective_values") or {}
    factor_levels = manifest.get("factor_levels") or {}
    tax_index = manifest.get("leader_tax")
    effective_tax = _effective_tax_usd_per_kg(manifest)

    row = {
        "campaign_id": manifest.get("campaign_id"),
        "experiment_id": manifest.get("experiment_id"),
        "design_point_id": manifest.get("design_point_id"),
        "base_instance_id": base_instance,
        "I": I,
        "M": M,
        "T": T,
        "algorithm_variant": manifest.get("algorithm_variant"),
        "seed_offset": manifest.get("seed_offset"),
        "gurobi_seed": manifest.get("gurobi_seed"),
        "valuation_ratio": manifest.get("valuation_ratio"),
        "code_version": manifest.get("code_version"),
        # Provenance, carried through from the manifest rather than recomputed: a row whose
        # code_dirty is true (or null) was produced by code that matches no commit, and must not
        # be quoted in the paper without saying so. Runs written before these fields existed
        # report None, which is distinct from a verified False.
        "code_dirty": manifest.get("code_dirty"),
        "instance_sha256": manifest.get("instance_sha256"),
        "instance_content_sha256": manifest.get("instance_content_sha256"),
        "solver_method": manifest.get("solver_method"),
        "solve_status": manifest.get("solve_status"),
        "termination_reason": manifest.get("termination_reason"),
        "censored": manifest.get("censored"),
        "cost": objective_values.get("cost"),
        "emissions": objective_values.get("emissions"),
        "follower_objective": objective_values.get("follower_objective"),
        "leader_tax_index": tax_index,
        "tax_grid_step_usd_per_kg": manifest.get("tax_grid_step_usd_per_kg"),
        "leader_tax_usd_per_tonne": (
            effective_tax * KG_PER_TONNE if effective_tax is not None else None
        ),
        "runtime_seconds": manifest.get("runtime_seconds"),
        "wall_clock_seconds": manifest.get("wall_clock_seconds"),
        "mip_gap": manifest.get("mip_gap"),
        "time_limit_seconds": manifest.get("time_limit_seconds"),
        "wall_clock_cap_seconds": manifest.get("wall_clock_cap_seconds"),
        "validation_status": manifest.get("validation_status"),
        "error_type": manifest.get("error_type"),
        "output_path": manifest.get("output_path"),
        "notes": manifest.get("notes"),
    }
    for field in _STRUCTURAL_MENU_FIELDS:
        row[field] = manifest.get(field)
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
    out_path = TABLES / "master_runs_campaign_01.csv"
    df.to_csv(out_path, index=False)
    return df


if __name__ == "__main__":
    frame = aggregate()
    print(f"Aggregated {len(frame)} campaign_01 runs -> {TABLES / 'master_runs_campaign_01.csv'}")
