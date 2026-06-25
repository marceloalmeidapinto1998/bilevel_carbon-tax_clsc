"""Canonical filesystem locations used by analysis tools."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RESULTS = REPO / "results"

# Raw solver outputs live under results/runs/; derived analysis under results/analysis/.
# Set RUN_ID to target a specific dated run folder (e.g. "20260619").
# Set to "" to scan the entire runs/ tree across all generations.
RUN_ID = "20260619"
RUNS = RESULTS / "runs" / RUN_ID if RUN_ID else RESULTS / "runs"
ANALYSIS_OUT = RESULTS / "analysis"
TABLES = ANALYSIS_OUT / "tables"      # aggregated CSV tables
FIGURES = ANALYSIS_OUT / "figures"    # plots
REPORTS = ANALYSIS_OUT / "reports"    # markdown reports + logs


def ensure_analysis_dirs() -> None:
    for directory in (TABLES, FIGURES, REPORTS):
        directory.mkdir(parents=True, exist_ok=True)
