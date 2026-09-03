"""Per-experiment design-matrix builders for campaign_01 (exp1..exp4).

Each module exposes `build_design_matrix() -> list[DesignPoint]` (Experiment 3 accepts an optional
data-dependent `results_root` argument for its two-phase generation: local plateau refinement once
Experiment 2's M0 manifests exist, and the rho*-anchored suite once its own ratio sweep resolves
rho*). The orchestrator stamps the campaign-wide solver defaults onto every point that does not set
them explicitly.
"""
