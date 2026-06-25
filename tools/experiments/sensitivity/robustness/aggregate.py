"""solver_robustness.csv — convergence, validation, and timing across all committed runs.

Reads the generic master_runs.csv (from tools.analysis.aggregate) and aggregates the DBP
performance fields by category and by instance. This is the methodological robustness evidence:
the algorithm converges, validates, and stays within gap across the whole design space.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .. import io


def _solver_stats(df: pd.DataFrame) -> dict:
    n = len(df)
    succ = df["success"].astype(str).str.lower().eq("true")
    valid = df["validation"].astype(str).eq("validated")
    gap = pd.to_numeric(df["relative_gap"], errors="coerce")
    secs = pd.to_numeric(df["solve_seconds"], errors="coerce")
    iters = pd.to_numeric(df["iterations"], errors="coerce")
    return {
        "n_runs": n,
        "frac_success": round(float(succ.mean()), 4) if n else np.nan,
        "frac_validated": round(float(valid.mean()), 4) if n else np.nan,
        "max_relative_gap": float(gap.max()),
        "n_gap_above_target": int((gap > 1.5 * io.DBP_GAP_TARGET).sum()),
        "mean_iterations": round(float(iters.mean()), 2),
        "max_iterations": float(iters.max()),
        "median_solve_s": round(float(secs.median()), 2),
        "max_solve_s": round(float(secs.max()), 2),
    }


def aggregate() -> Path:
    master = pd.read_csv(io.TABLES / "master_runs.csv")
    rows = [{"grouping": "all", "key": "all", **_solver_stats(master)}]
    for cat, g in master.groupby("category"):
        rows.append({"grouping": "category", "key": cat, **_solver_stats(g)})
    for binst, g in master.groupby("base_instance"):
        rows.append({"grouping": "instance", "key": binst, **_solver_stats(g)})
    io.TABLES.mkdir(parents=True, exist_ok=True)
    out = io.TABLES / "solver_robustness.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    a = rows[0]
    print(f"solver_robustness.csv: {len(rows)} groups; overall validated={a['frac_validated']}, "
          f"max_gap={a['max_relative_gap']:.2g}, runs over target gap={a['n_gap_above_target']}")
    return out
