"""Derived analysis for the v2 campaign: read-only over results/runs/v2/, writes results/analysis/v2/.

  paths.py              canonical v2 filesystem locations
  aggregate.py           campaign_manifest.json -> results/analysis/v2/tables/master_runs_v2.csv
  doe_analysis.py        Family C/D: half-normal effect plots, main effects, interaction heatmaps
  frontier_analysis.py   Family B/E: MAC curves, tax-emissions frontier, regime overlays
  robustness_analysis.py Family F: seed/tolerance variance bands
  paper_export.py        the only module that writes paper/tables, paper/figures
"""
