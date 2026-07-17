"""Derived analysis for doe_campaign_01: read-only over results/runs/doe_campaign_01/, writes results/analysis/doe_campaign_01/.

  paths.py              canonical doe_campaign_01 filesystem locations
  aggregate.py           campaign_manifest.json -> results/analysis/doe_campaign_01/tables/master_runs_doe_campaign_01.csv
  doe_analysis.py        Family C/D: half-normal effect plots, main effects, interaction heatmaps
  frontier_analysis.py   Family B/E: MAC curves, tax-emissions frontier, regime overlays
  robustness_analysis.py Family F: seed/tolerance variance bands
  paper_export.py        the only module that writes paper/tables, paper/figures
"""
