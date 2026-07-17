"""Family C - Factor screening via resolution->=IV fractional factorial (RQ3, RQ6).

Replaces Morris elementary-effects screening (see plan §2). 7 factors at 2 levels (low/high):
the 5 core continuous factors (§4) plus the 2 structural menu-breadth factors, screened with a
resolution->=IV design (`clsc.campaign.doe.fractional_factorial`) on the fast
representative instance. `facility_area_cost` was dropped from the screened set on 2026-07-01 at
the user's request (still defined in the factor registry, just excluded from this design).

The confirmatory instance (I25_M8_T3) replicates only the first half of the fast-instance design
(its un-folded resolution-III half, by construction of the fold-over design -- see
`fractional_factorial_signs`) to confirm the flagged effects' signs and magnitudes are not an
artifact of instance size (RQ6) without doubling the run count. This ratio is computed from the
actual design length rather than hardcoded, so it stays correct if the factor count changes again.

Seed replication (2026-07-01): the base-seed draw of each instance class has genuinely wide
emissions variance (Family F: CV~40%, an intrinsic property of Tautenhain-style generator ranges,
not a bug -- see project memory). Absolute levels are seed-sensitive, but factor effects computed
as within-seed contrasts (same draw on both arms of a comparison) should cancel that noise. The
fast-instance factorial is replicated at 3 extra seeds to confirm the C main-effects ranking
(demand > emission_intensity > scope3 > technology_menu, others in the noise floor) holds across
seeds and is not an artifact of one instance draw. The confirmatory instance is NOT replicated
(I25_M8_T3 is already probed for seed sensitivity by Family F).
"""
from __future__ import annotations

from clsc.campaign.designs._common import DesignPoint
from clsc.campaign.doe.fractional_factorial import fractional_factorial_signs
from clsc.campaign.doe.robustness import seed_grid
from clsc.campaign.factors import CORE_CONTINUOUS_FACTORS, FACTOR_REGISTRY

FAMILY_ID = "C"
EXECUTION_MODE = "bilevel"

FAST_INSTANCE = "STD_I17_M4_T3"
CONFIRMATORY_INSTANCE = "STD_I25_M8_T3"

STRUCTURAL_FACTOR_NAMES: tuple[str, ...] = ("technology_menu", "transport_menu")
SCREENING_FACTORS: tuple[str, ...] = CORE_CONTINUOUS_FACTORS + STRUCTURAL_FACTOR_NAMES  # 7 factors

# Standard tier of the two-tier time-limit scheme (2026-07-01), see family_a_baseline.py.
# Neither instance here reaches STD_I25_M8_T6, so the hard tier is never needed in this family.
PER_SUBPROBLEM_TIME_LIMIT_SECONDS = 3600.0
PER_RUN_WALL_CLOCK_CAP_SECONDS = 28800.0

# Extra seeds replicating the full fast-instance factorial, to confirm main effects are stable
# across instance draws (not just the single base seed). 3 extra seeds matches Family F's
# convention (4 total draws per class: base + 3).
N_EXTRA_SEEDS = 3


def _row_to_design_point(
    *,
    design_point_id: str,
    run_code: str,
    base_instance_id: str,
    signs: dict[str, int],
    seed_offset: int = 0,
) -> DesignPoint:
    factor_levels: dict[str, float] = {}
    technology_menu = "base"
    transport_menu = "base"
    for factor_name, sign in signs.items():
        if factor_name == "technology_menu":
            technology_menu = "expanded" if sign > 0 else "base"
        elif factor_name == "transport_menu":
            transport_menu = "expanded" if sign > 0 else "base"
        else:
            spec = FACTOR_REGISTRY[factor_name]
            factor_levels[factor_name] = spec.high if sign > 0 else spec.low
    return DesignPoint(
        family_id=FAMILY_ID,
        design_point_id=design_point_id,
        run_code=run_code,
        base_instance_id=base_instance_id,
        execution_mode=EXECUTION_MODE,
        per_subproblem_time_limit_seconds=PER_SUBPROBLEM_TIME_LIMIT_SECONDS,
        per_run_wall_clock_cap_seconds=PER_RUN_WALL_CLOCK_CAP_SECONDS,
        factor_levels=factor_levels,
        technology_menu=technology_menu,
        transport_menu=transport_menu,
        seed_offset=seed_offset,
    )


def build_design_matrix() -> list[DesignPoint]:
    design = fractional_factorial_signs(SCREENING_FACTORS)
    confirm_half = design[: len(design) // 2]  # un-folded resolution-III half only

    points: list[DesignPoint] = [
        _row_to_design_point(
            design_point_id=f"C-fast-{i + 1:02d}",
            run_code=f"run{i + 1:02d}",
            base_instance_id=FAST_INSTANCE,
            signs=signs,
        )
        for i, signs in enumerate(design)
    ]
    points += [
        _row_to_design_point(
            design_point_id=f"C-confirm-{i + 1:02d}",
            run_code=f"run{i + 1:02d}",
            base_instance_id=CONFIRMATORY_INSTANCE,
            signs=signs,
        )
        for i, signs in enumerate(confirm_half)
    ]
    points += [
        _row_to_design_point(
            design_point_id=f"C-fast-{i + 1:02d}-seed{seed_offset}",
            run_code=f"run{i + 1:02d}_seed{seed_offset}",
            base_instance_id=FAST_INSTANCE,
            signs=signs,
            seed_offset=seed_offset,
        )
        for seed_offset in seed_grid(N_EXTRA_SEEDS)
        for i, signs in enumerate(design)
    ]
    return points
