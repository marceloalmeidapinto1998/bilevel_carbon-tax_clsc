"""censoring_flags.csv — runs whose incumbent tax sits at the top of the explored range.

Reads master_runs.csv (which carries the per-run ``censored`` + ``hat_tau_max_on_curve`` columns
computed by tools.analysis.aggregate) and writes the flagged subset. A censored run's optimum is a boundary
artifact; extend the tax range there (see tools/experiments/sensitivity/maintenance.py) and re-solve.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import io


def censoring_flags() -> Path | None:
    master = pd.read_csv(io.TABLES / "master_runs.csv")
    if "censored" not in master.columns:
        print("censoring_flags.csv: skipped (no network curves available)")
        return None

    net = master["net_available"].astype(str).str.lower().eq("true")
    cens = master[net].copy()
    cens["censored"] = cens["censored"].astype(str).str.lower().eq("true")
    cols = ["category", "scenario", "sa_dim", "base_instance", "instance_code",
            "hat_tau", "hat_tau_max_on_curve", "censored"]
    io.TABLES.mkdir(parents=True, exist_ok=True)
    out = io.TABLES / "censoring_flags.csv"
    cens[cols].to_csv(out, index=False)
    n_cens = int(cens["censored"].sum())
    print(f"censoring_flags.csv: {len(cens)} runs, {n_cens} censored "
          f"(incumbent tax at top of explored range -> extend tax range)")
    return out
