"""Compute Morris elementary-effects indices from solved screening runs.

Joins ``morris_design_matrix.csv`` to solved incumbents, computes per-factor elementary
effects in normalized input units, and writes ``morris_<base>_indices.csv``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .. import io
from ..factors import FACTOR_REGISTRY

DESIGN_ROOT = io.DATA_INSTANCES / "experiments" / "sensitivity" / "morris"
OUTPUTS = {
    "emissions": "emissions",
    "cost": "cost",
    "hat_tau": "hat_tau",
}
_TOL = 1e-9


def elementary_effects(design: pd.DataFrame, factors: list[str], y: pd.Series) -> dict[str, np.ndarray]:
    """Per-factor elementary effects in normalized input units, using trajectory/step order."""
    span = {factor: FACTOR_REGISTRY[factor].high - FACTOR_REGISTRY[factor].low for factor in factors}
    effects: dict[str, list[float]] = {factor: [] for factor in factors}
    for _, traj in design.groupby("trajectory"):
        rows = traj.sort_values("step").to_dict("records")
        for before, after in zip(rows[:-1], rows[1:]):
            yb, ya = y.get(before["run_id"]), y.get(after["run_id"])
            if yb is None or ya is None or np.isnan(yb) or np.isnan(ya):
                continue
            changed = [factor for factor in factors if abs(after[factor] - before[factor]) > _TOL]
            if len(changed) != 1:
                continue
            factor = changed[0]
            delta_norm = (after[factor] - before[factor]) / span[factor]
            if abs(delta_norm) < _TOL:
                continue
            effects[factor].append((ya - yb) / delta_norm)
    return {factor: np.asarray(values, dtype=float) for factor, values in effects.items()}


def analyze(base_instance: str, results_root: Path = io.RUNS) -> Path:
    design_path = DESIGN_ROOT / base_instance / "morris_design_matrix.csv"
    if not design_path.exists():
        raise FileNotFoundError(f"No Morris design matrix at {design_path}")
    design = pd.read_csv(design_path)
    factors = [column for column in design.columns if column in FACTOR_REGISTRY]

    solved = io.load_summary_records(results_root, set(design["run_id"]))
    n_missing = len(design) - len(solved)

    records = []
    for out_name, col in OUTPUTS.items():
        y = pd.Series({rid: float(rec.get(col, np.nan)) for rid, rec in solved.items()})
        ee = elementary_effects(design, factors, y)
        for factor in factors:
            arr = ee[factor]
            records.append({
                "base_instance": base_instance,
                "output": out_name,
                "factor": factor,
                "n_effects": int(arr.size),
                "mu": float(np.mean(arr)) if arr.size else np.nan,
                "mu_star": float(np.mean(np.abs(arr))) if arr.size else np.nan,
                "sigma": float(np.std(arr, ddof=1)) if arr.size > 1 else np.nan,
            })

    indices = pd.DataFrame(records)
    io.TABLES.mkdir(parents=True, exist_ok=True)
    out_csv = io.TABLES / f"morris_{base_instance}_indices.csv"
    indices.to_csv(out_csv, index=False)

    print(f"morris_{base_instance}_indices.csv: {len(indices)} rows "
          f"({len(factors)} factors x {len(OUTPUTS)} outputs); "
          f"{len(solved)}/{len(design)} design points solved ({n_missing} missing)")
    for out_name in OUTPUTS:
        top = (
            indices[indices.output == out_name]
            .dropna(subset=["mu_star"])
            .sort_values("mu_star", ascending=False)
        )
        ranking = ", ".join(f"{r.factor}({r.mu_star:.3g})" for r in top.head(5).itertuples())
        print(f"  {out_name:9s} mu* ranking: {ranking}")
    return out_csv

