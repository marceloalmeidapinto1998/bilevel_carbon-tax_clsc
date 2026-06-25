"""Canonical filesystem locations for the v2 campaign (separate from the v1 RUN_ID-based tree
in `tools.analysis.common.paths`, since v2 results are organized by family, not by date)."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RESULTS = REPO / "results"

RUNS = RESULTS / "runs" / "v2"
ANALYSIS_OUT = RESULTS / "analysis" / "v2"
TABLES = ANALYSIS_OUT / "tables"
FIGURES = ANALYSIS_OUT / "figures"
REPORTS = ANALYSIS_OUT / "reports"

INSTANCES = REPO / "data" / "instances" / "campaigns" / "v2"
MANIFESTS = REPO / "experiments" / "manifests"


def ensure_analysis_dirs() -> None:
    for directory in (TABLES, FIGURES, REPORTS):
        directory.mkdir(parents=True, exist_ok=True)
