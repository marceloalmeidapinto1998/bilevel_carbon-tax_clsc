"""Per-experiment design-matrix builders for campaign_01 (exp1..exp7).

Each module exposes `build_design_matrix() -> list[DesignPoint]` (Experiments 6 and 7 accept an
optional data-dependent argument for their two-phase generation). The orchestrator stamps the
campaign-wide solver defaults onto every point that does not set them explicitly.
"""
