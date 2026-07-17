"""Family F - Solver gap-tolerance robustness (RQ6).

Isolated `mip_gap` sensitivity probe on the 4 T3 classes: does a looser per-MILP gap tolerance
change the optimal network structure? `dbp_relative_gap` (the outer bilevel loop's own convergence
criterion) is held fixed at the campaign-wide 1e-4 in both settings, so any observed structural
change is attributable specifically to per-MILP solve precision, not the outer loop's convergence
criterion (EXPERIMENTAL_PLAN.md §4-F). The tight-baseline point (`mip_gap=1e-6`, the campaign's
`CAMPAIGN_MIP_GAP`) is already covered by Family A and is not re-run here; both settings below are
DELIBERATELY LOOSER than that 1e-6 baseline, so "tight"/"loose" here are relative to each other,
not to Family A.

Time budgets are NOT symmetric between the two settings: the tight setting gets the full standard
tier (3,600 s / 28,800 s) because achieving a tighter gap generally needs *more* time than the
campaign default, not less -- a reduced budget would risk the tight-gap run merely timing out
(censored) rather than demonstrating genuinely higher precision, confounding the comparison this
family exists to make. The loose setting keeps a reduced budget (1,800 s / 7,200 s) since it is
expected to converge quickly.
"""
from __future__ import annotations

from experiments.designs._common import DesignPoint

FAMILY_ID = "F"
EXECUTION_MODE = "bilevel"

INSTANCES: tuple[str, ...] = (
    "STD_I17_M4_T3", "STD_I17_M8_T3", "STD_I25_M4_T3", "STD_I25_M8_T3",
)

CAMPAIGN_DBP_RELATIVE_GAP = 1e-4  # campaign-wide outer gap; fixed in both settings so mip_gap is the sole lever

TIGHT_MIP_GAP = 1e-3
TIGHT_SUBPROBLEM_SECONDS = 3600.0
TIGHT_WALL_CLOCK_SECONDS = 28800.0

LOOSE_MIP_GAP = 1e-1
LOOSE_SUBPROBLEM_SECONDS = 1800.0
LOOSE_WALL_CLOCK_SECONDS = 7200.0


def build_design_matrix() -> list[DesignPoint]:
    points: list[DesignPoint] = []
    index = 0
    for instance_id in INSTANCES:
        for label, mip_gap, subproblem_cap, wall_clock_cap in (
            ("tight", TIGHT_MIP_GAP, TIGHT_SUBPROBLEM_SECONDS, TIGHT_WALL_CLOCK_SECONDS),
            ("loose", LOOSE_MIP_GAP, LOOSE_SUBPROBLEM_SECONDS, LOOSE_WALL_CLOCK_SECONDS),
        ):
            index += 1
            points.append(
                DesignPoint(
                    family_id=FAMILY_ID,
                    design_point_id=f"F-{index:02d}",
                    run_code=f"gap_{label}",
                    base_instance_id=instance_id,
                    execution_mode=EXECUTION_MODE,
                    per_subproblem_time_limit_seconds=subproblem_cap,
                    per_run_wall_clock_cap_seconds=wall_clock_cap,
                    mip_gap=mip_gap,
                    dbp_relative_gap=CAMPAIGN_DBP_RELATIVE_GAP,
                )
            )
    return points
