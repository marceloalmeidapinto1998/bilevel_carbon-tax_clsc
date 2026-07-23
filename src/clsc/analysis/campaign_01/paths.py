"""Canonical filesystem locations for the campaign_01 experiments."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[4]  # src/clsc/analysis/campaign_01/paths.py -> repo root
RESULTS = REPO / "results"

RUNS = RESULTS / "runs" / "campaign_01"
ANALYSIS_OUT = RESULTS / "analysis" / "campaign_01"
TABLES = ANALYSIS_OUT / "tables"
FIGURES = ANALYSIS_OUT / "figures"
REPORTS = ANALYSIS_OUT / "reports"

INSTANCES = REPO / "data" / "instances" / "campaigns" / "campaign_01"
MANIFESTS = REPO / "experiments" / "campaign_01"


def ensure_analysis_dirs() -> None:
    for directory in (TABLES, FIGURES, REPORTS):
        directory.mkdir(parents=True, exist_ok=True)
