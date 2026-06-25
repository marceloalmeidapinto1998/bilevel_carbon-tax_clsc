"""Sensitivity & robustness analysis for the bilevel CLSC model (v1 campaign).

A layered, reproducible methodology behind one orchestrator (`python -m tools.experiments.sensitivity`).
Shared core + one subpackage per method:

  factors      — canonical factor registry (names, multiplier ranges, rationale)
  io           — instance materialization, design-matrix writing, results-join, paths, constants
  robustness/  — DBP convergence/validation/timing, tax-range censoring, tolerance sweep
  report       — assemble SENSITIVITY_REPORT.md

`oat/` and `morris/` (local one-at-a-time perturbations and global Morris elementary-effects
screening) have moved to `tools.experiments.legacy_v1` as of the 2026-06-25 v2 campaign redesign,
which replaces both with a fractional factorial screening design and dense univariate response
curves (see `tools/experiments/v2/`). They are still imported here (from legacy_v1) so the v1
`analyze-all`/`report` pipeline keeps working against the archived `results/runs/20260619` data.

Tax-range extension is an OAT spec (tax_range_max040 / tax_range_max080), not a separate command.
"""
