"""Family D - Design-lever factorial (RQ4).

Full 2^4 factorial over the genuinely actionable design levers (technology menu, transport
menu, return/collection rate, demand) on a small and a large representative instance, to read
off interaction effects directly (e.g. does technology breadth only help abatement when returns
are high?) rather than relying on the screening design's aliasing structure.

Seed replication (2026-07-01): mirrors the Family C rationale -- absolute emissions/cost levels
are seed-sensitive (Family F: CV~40%, intrinsic to the Tautenhain-style generator ranges, not a
bug), but factor effects and interactions computed as within-seed contrasts should cancel that
noise. The small-instance 16-run factorial is replicated at 3 extra seeds to confirm the D main
effects (demand dominant, technology_menu substantial, return_availability/transport_menu
negligible) and the technology x demand interaction hold across instance draws. The large
instance is NOT replicated (STD_I25_M8_T6 is already the most expensive cell in the campaign;
Family A's censored baseline means there is no confirmed reference to replicate against yet).
"""
from __future__ import annotations

from experiments.designs._common import DesignPoint
from tools.experiments.doe_campaign_01.design.full_factorial import full_factorial_signs
from tools.experiments.doe_campaign_01.design.robustness import seed_grid
from tools.experiments.doe_campaign_01.factors import FACTOR_REGISTRY

FAMILY_ID = "D"
EXECUTION_MODE = "bilevel"

SMALL_INSTANCE = "STD_I17_M4_T3"
LARGE_INSTANCE = "STD_I25_M8_T6"
INSTANCES: tuple[str, ...] = (SMALL_INSTANCE, LARGE_INSTANCE)

LEVER_FACTORS: tuple[str, ...] = ("technology_menu", "transport_menu", "return_availability", "demand")

# Two-tier time-limit scheme (2026-07-01), see family_a_baseline.py: SMALL_INSTANCE (and its
# seed replicates) get the standard tier; LARGE_INSTANCE (STD_I25_M8_T6) gets the hard tier.
STANDARD_SUBPROBLEM_SECONDS = 3600.0
STANDARD_WALL_CLOCK_SECONDS = 28800.0
HARD_SUBPROBLEM_SECONDS = 10800.0
HARD_WALL_CLOCK_SECONDS = 50400.0

# Extra seeds replicating the small-instance 16-run factorial, to confirm main effects and
# interactions are stable across instance draws. 3 extra seeds matches Family F/C's convention
# (4 total draws per cell: base + 3).
N_EXTRA_SEEDS = 3


def _signs_to_levels(signs: dict[str, int]) -> tuple[dict[str, float], str, str]:
    factor_levels: dict[str, float] = {}
    technology_menu = "expanded" if signs["technology_menu"] > 0 else "base"
    transport_menu = "expanded" if signs["transport_menu"] > 0 else "base"
    for factor_name in ("return_availability", "demand"):
        spec = FACTOR_REGISTRY[factor_name]
        factor_levels[factor_name] = spec.high if signs[factor_name] > 0 else spec.low
    return factor_levels, technology_menu, transport_menu


def build_design_matrix() -> list[DesignPoint]:
    design = full_factorial_signs(LEVER_FACTORS)  # 16 rows

    points: list[DesignPoint] = []
    index = 0
    for instance_id in INSTANCES:
        is_hard = instance_id == LARGE_INSTANCE
        subproblem_cap = HARD_SUBPROBLEM_SECONDS if is_hard else STANDARD_SUBPROBLEM_SECONDS
        wall_clock_cap = HARD_WALL_CLOCK_SECONDS if is_hard else STANDARD_WALL_CLOCK_SECONDS
        for signs in design:
            index += 1
            factor_levels, technology_menu, transport_menu = _signs_to_levels(signs)
            points.append(
                DesignPoint(
                    family_id=FAMILY_ID,
                    design_point_id=f"D-{index:02d}",
                    run_code=f"run{index:02d}",
                    base_instance_id=instance_id,
                    execution_mode=EXECUTION_MODE,
                    per_subproblem_time_limit_seconds=subproblem_cap,
                    per_run_wall_clock_cap_seconds=wall_clock_cap,
                    factor_levels=factor_levels,
                    technology_menu=technology_menu,
                    transport_menu=transport_menu,
                )
            )

    for seed_offset in seed_grid(N_EXTRA_SEEDS):
        for i, signs in enumerate(design):
            factor_levels, technology_menu, transport_menu = _signs_to_levels(signs)
            points.append(
                DesignPoint(
                    family_id=FAMILY_ID,
                    design_point_id=f"D-{i + 1:02d}-seed{seed_offset}",
                    run_code=f"run{i + 1:02d}_seed{seed_offset}",
                    base_instance_id=SMALL_INSTANCE,
                    execution_mode=EXECUTION_MODE,
                    per_subproblem_time_limit_seconds=STANDARD_SUBPROBLEM_SECONDS,
                    per_run_wall_clock_cap_seconds=STANDARD_WALL_CLOCK_SECONDS,
                    factor_levels=factor_levels,
                    technology_menu=technology_menu,
                    transport_menu=transport_menu,
                    seed_offset=seed_offset,
                )
            )
    return points
