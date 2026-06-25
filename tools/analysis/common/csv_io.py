"""Robust CSV readers shared by analysis pipelines."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from .schemas import NET_COLS, NUM_RUN, RUN_COLS

Logger = Callable[[str], None]


def read_run(csv_path: Path, log: Logger | None = None) -> dict | None:
    """Positionally read one run-level ``summary.csv`` record."""
    try:
        df = pd.read_csv(
            csv_path,
            skiprows=1,
            names=RUN_COLS,
            header=None,
            dtype=str,
            keep_default_na=False,
        )
    except Exception as exc:  # noqa: BLE001
        if log is not None:
            log(f"  [SKIP] unreadable run summary: {csv_path} ({exc})")
        return None
    if df.empty:
        if log is not None:
            log(f"  [SKIP] empty run summary: {csv_path}")
        return None
    rec = df.iloc[0].to_dict()
    for column in NUM_RUN:
        try:
            rec[column] = float(rec[column]) if rec[column] != "" else np.nan
        except ValueError:
            rec[column] = np.nan
    return rec


def read_network(net_path: Path, log: Logger | None = None) -> pd.DataFrame | None:
    """Positionally read a network ``summary.csv`` table."""
    if not net_path.exists():
        return None
    try:
        return pd.read_csv(net_path, skiprows=1, names=NET_COLS, header=None)
    except Exception as exc:  # noqa: BLE001
        if log is not None:
            log(f"  [SKIP] unreadable network csv: {net_path} ({exc})")
        return None

