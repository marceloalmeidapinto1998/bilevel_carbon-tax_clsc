"""Structural testbed cells and time tiers (docs/Experimental_Plan.md §2).

The 12 base cells span I in {17,25} x M in {4,8} x T in {3,6,12}. Five are hard-tier
(I25-M8-T6 plus the four T12 cells); the other seven are standard-tier. These are not design
factors -- they are structurally distinct optimization problems.
"""
from __future__ import annotations

ITEM_COUNTS = (17, 25)
TECH_COUNTS = (4, 8)
PERIOD_COUNTS = (3, 6, 12)


def cell_id(i: int, m: int, t: int) -> str:
    return f"STD_I{i}_M{m}_T{t}"


ALL_CELLS: tuple[str, ...] = tuple(
    cell_id(i, m, t) for i in ITEM_COUNTS for m in TECH_COUNTS for t in PERIOD_COUNTS
)

HARD_TIER_CELLS: frozenset[str] = frozenset(
    {cell_id(25, 8, 6)}
    | {cell_id(i, m, 12) for i in ITEM_COUNTS for m in TECH_COUNTS}
)
STANDARD_TIER_CELLS: tuple[str, ...] = tuple(c for c in ALL_CELLS if c not in HARD_TIER_CELLS)

# Per-subproblem / per-run wall-clock caps (seconds), by tier.
STANDARD_TIER_LIMITS = (3600.0, 28800.0)
HARD_TIER_LIMITS = (10800.0, 50400.0)

# Representative instances for the ablation and scalability experiments.
FAST_CELLS = (cell_id(17, 4, 3), cell_id(17, 4, 6))
MEDIUM_CELLS = (cell_id(17, 8, 6), cell_id(25, 4, 6))
HARD_CELLS = (cell_id(25, 8, 6), cell_id(25, 8, 12))
REPRESENTATIVE_CELLS = FAST_CELLS + MEDIUM_CELLS + HARD_CELLS


def time_limits(cell: str) -> tuple[float, float]:
    """(per_subproblem_time_limit_seconds, per_run_wall_clock_cap_seconds) for a cell's tier."""
    return HARD_TIER_LIMITS if cell in HARD_TIER_CELLS else STANDARD_TIER_LIMITS
