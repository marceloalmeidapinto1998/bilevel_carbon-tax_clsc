"""Canonical filesystem locations for the doe_campaign_01 campaign (separate from the v1 RUN_ID-based tree
in `tools.analysis.common.paths`, since doe_campaign_01 results are organized by family, not by date)."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RESULTS = REPO / "results"

RUNS = RESULTS / "runs" / "doe_campaign_01"
ANALYSIS_OUT = RESULTS / "analysis" / "doe_campaign_01"
TABLES = ANALYSIS_OUT / "tables"
FIGURES = ANALYSIS_OUT / "figures"
REPORTS = ANALYSIS_OUT / "reports"

INSTANCES = REPO / "data" / "instances" / "campaigns" / "doe_campaign_01"
MANIFESTS = REPO / "experiments" / "manifests"


def ensure_analysis_dirs() -> None:
    for directory in (TABLES, FIGURES, REPORTS):
        directory.mkdir(parents=True, exist_ok=True)
