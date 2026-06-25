"""Solver-robustness layer: DBP convergence/validation/timing, tax-range censoring, tolerances.

Modules by role:
  aggregate  — solver_robustness.csv (convergence/validation/timing across all runs)
  censoring  — censoring_flags.csv (incumbent tax pinned to the explored range ceiling)
  tolerance  — re-solve one instance under a tolerance grid (incumbent stability vs speed)
"""
