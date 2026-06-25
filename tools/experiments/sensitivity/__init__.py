"""Sensitivity & robustness analysis for the bilevel CLSC model.

A layered, reproducible methodology behind one orchestrator (`python -m tools.experiments.sensitivity`).
Shared core + one subpackage per method:

  factors      — canonical factor registry (names, multiplier ranges, rationale)
  io           — instance materialization, design-matrix writing, results-join, paths, constants
  oat/         — local one-at-a-time perturbations + normalized elasticities (design, analyze)
  morris/      — global Morris elementary-effects screening (design, analyze)
  robustness/  — DBP convergence/validation/timing, tax-range censoring, tolerance sweep
  report       — assemble SENSITIVITY_REPORT.md

Tax-range extension is an OAT spec (tax_range_max040 / tax_range_max080), not a separate command.
"""
