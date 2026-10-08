"""Structural testbed cells and time tiers (docs/Experimental_Plan.md §2).

The 12 base cells span I in {17,25} x M in {4,8} x T in {3,6,12}. Six are hard-tier
(I25-M8-T6, I17-M8-T6, plus the four T12 cells); the other six are standard-tier. These are not
design factors -- they are structurally distinct optimization problems.

I17-M8-T6 was promoted to the hard tier after its standard-tier (3600 s) Exp1 solve stagnated at a
6.2% follower MIP gap on the tax=0 subproblem; the two M8-T6 cells now share the same 10800 s tier.
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
    {cell_id(25, 8, 6), cell_id(17, 8, 6)}
    | {cell_id(i, m, 12) for i in ITEM_COUNTS for m in TECH_COUNTS}
)
STANDARD_TIER_CELLS: tuple[str, ...] = tuple(c for c in ALL_CELLS if c not in HARD_TIER_CELLS)

# (per-subproblem time limit, per-run wall-clock cap) in seconds, by tier. Since 2026-10-08 both
# tiers follow Soares et al. (2021): a 10-minute computational budget per MILP subproblem (their
# larger model) and no cap on the run as a whole. The tiers are kept because the designs still
# use them to decide which cells may carry sweeps.
STANDARD_TIER_LIMITS: tuple[float, float | None] = (600.0, None)
HARD_TIER_LIMITS: tuple[float, float | None] = (600.0, None)

# Representative instances for the ablation and scalability experiments.
FAST_CELLS = (cell_id(17, 4, 3), cell_id(17, 4, 6))
MEDIUM_CELLS = (cell_id(17, 8, 6), cell_id(25, 4, 6))
HARD_CELLS = (cell_id(25, 8, 6), cell_id(25, 8, 12))
REPRESENTATIVE_CELLS = FAST_CELLS + MEDIUM_CELLS + HARD_CELLS


def time_limits(cell: str) -> tuple[float, float | None]:
    """(per_subproblem_time_limit_seconds, per_run_wall_clock_cap_seconds) for a cell's tier."""
    return HARD_TIER_LIMITS if cell in HARD_TIER_CELLS else STANDARD_TIER_LIMITS
