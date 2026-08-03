"""Recompute an exp8 enumeration run's incumbent from its saved `enumeration_trace.csv`, using the
corrected plateau tie tolerance (`clsc.solvers.enumeration.PLATEAU_RELATIVE_GAP`).

Why this exists: `enumerate_tax_grid`'s incumbent-selection originally reused DBP main-loop's
near-machine-precision tie tolerance, which silently drifts on a long ascending scan once
solve-to-solve Gurobi noise (~1e-8 relative) exceeds it -- confirmed on STD_I17_M4_T6, where the
reported tau* drifted from the true left edge (index 1264, matching DBP exactly) out to index 1903.
Fixed in `enumeration.py` (PLATEAU_RELATIVE_GAP, matching dbp_lex._REFINE_TIE_REL). All underlying
Gurobi solves were already correct -- only the post-hoc incumbent bookkeeping was wrong -- so
already-completed runs are corrected by replaying their trace, not by re-solving (which would cost
hours per cell for zero new information).

Usage: python scripts/recompute_enumeration_incumbent.py <cell> [--apply]
Without --apply, prints the correction and exits without touching any file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from clsc.solvers.dbp_lex import IncumbentSolution  # noqa: E402
from clsc.solvers.enumeration import PLATEAU_RELATIVE_GAP, _is_better_on_plateau  # noqa: E402

RUN_DIR = REPO_ROOT / "results" / "runs" / "campaign_01" / "exp8_benchmark"


def recompute(cell: str) -> IncumbentSolution:
    trace_path = RUN_DIR / cell / "enumeration" / "enumeration_trace.csv"
    trace = pd.read_csv(trace_path)
    incumbent: IncumbentSolution | None = None
    for row in trace.itertuples():
        candidate = IncumbentSolution(
            tax_index=int(row.tax_index), cost=float(row.cost), emissions=float(row.emissions),
            follower_objective=0.0,  # not stored per-point in the trace; not needed for tau*/E*
        )
        if _is_better_on_plateau(candidate, incumbent, relative_gap=PLATEAU_RELATIVE_GAP):
            incumbent = candidate
    assert incumbent is not None
    return incumbent


def apply_correction(cell: str, incumbent: IncumbentSolution) -> None:
    run_dir = RUN_DIR / cell / "enumeration"
    for fname, tax_key, tax_scale_key in [
        ("result.json", "tax_index", "effective_tax"),
        ("campaign_manifest.json", "leader_tax", "effective_tax_usd_per_kg"),
    ]:
        path = run_dir / fname
        payload = json.loads(path.read_text(encoding="utf-8"))
        target = payload["objective_values"] if "objective_values" in payload else payload
        before = {"tax_index": payload.get(tax_key), "emissions": target.get("emissions")}
        target["emissions"] = incumbent.emissions
        if "cost" in target:
            target["cost"] = incumbent.cost
        payload[tax_key] = incumbent.tax_index
        # exp8 always solves on the campaign's fine grid (Experimental_Plan.md §3): 1e-4 USD/kg step.
        payload[tax_scale_key] = incumbent.tax_index * 1e-4
        payload["_correction"] = {
            "reason": "incumbent recomputed from enumeration_trace.csv with the corrected "
                      "plateau tie tolerance (PLATEAU_RELATIVE_GAP=1e-4); the original "
                      "near-machine-precision comparator drifted on this cell's long ascending "
                      "scan. See scripts/recompute_enumeration_incumbent.py.",
            "before": before,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"patched {path.relative_to(REPO_ROOT)}: tax_index {before['tax_index']} -> "
              f"{incumbent.tax_index}, emissions {before['emissions']:.6e} -> {incumbent.emissions:.6e}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cell")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    incumbent = recompute(args.cell)
    print(f"{args.cell}: corrected tau_index={incumbent.tax_index} "
          f"({incumbent.tax_index * 1e-4 * 1000:.1f} USD/t), emissions={incumbent.emissions:.6e}, "
          f"cost={incumbent.cost:.6e}")
    if args.apply:
        apply_correction(args.cell, incumbent)
    else:
        print("(dry run -- pass --apply to patch result.json / campaign_manifest.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
