"""Canonical filesystem locations for the doe_campaign_02 campaign (solver-config replication of
doe_campaign_01 -- see clsc.campaign.orchestrator for what changed and why).

Unlike doe_campaign_01's paths.py, MANIFESTS is namespaced under the campaign id so this
campaign's design_matrix.csv files never collide with doe_campaign_01's."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RESULTS = REPO / "results"

RUNS = RESULTS / "runs" / "doe_campaign_02"
ANALYSIS_OUT = RESULTS / "analysis" / "doe_campaign_02"
TABLES = ANALYSIS_OUT / "tables"
FIGURES = ANALYSIS_OUT / "figures"
REPORTS = ANALYSIS_OUT / "reports"

INSTANCES = REPO / "data" / "instances" / "campaigns" / "doe_campaign_02"
MANIFESTS = REPO / "manifests" / "doe_campaign_02"


def ensure_analysis_dirs() -> None:
    for directory in (TABLES, FIGURES, REPORTS):
        directory.mkdir(parents=True, exist_ok=True)
