"""Family C - Factor screening via resolution->=IV fractional factorial (RQ3, RQ6).

Replaces Morris elementary-effects screening (see plan §2). 8 factors at 2 levels (low/high):
the 6 core continuous factors (§4) plus the 2 structural menu-breadth factors, screened with a
32-run resolution->=IV design (`tools.experiments.v2.design.fractional_factorial`) on the fast
representative instance. The confirmatory instance (I25_M8_T3) replicates only the first 16 rows
(the design's un-folded resolution-III half) to confirm the flagged effects' signs and
magnitudes are not an artifact of instance size (RQ6) without doubling the run count.
"""
from __future__ import annotations

from experiments.designs._common import DesignPoint
from tools.experiments.v2.design.fractional_factorial import fractional_factorial_signs
from tools.experiments.v2.factors import CORE_CONTINUOUS_FACTORS, FACTOR_REGISTRY

FAMILY_ID = "C"
EXECUTION_MODE = "bilevel"

FAST_INSTANCE = "STD_I17_M4_T3"
CONFIRMATORY_INSTANCE = "STD_I25_M8_T3"

STRUCTURAL_FACTOR_NAMES: tuple[str, ...] = ("technology_menu", "transport_menu")
SCREENING_FACTORS: tuple[str, ...] = CORE_CONTINUOUS_FACTORS + STRUCTURAL_FACTOR_NAMES  # 8 factors

PER_SUBPROBLEM_TIME_LIMIT_SECONDS = 3600.0
PER_RUN_WALL_CLOCK_CAP_SECONDS = 14400.0


def _row_to_design_point(
    *, design_point_id: str, run_code: str, base_instance_id: str, signs: dict[str, int],
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
    )


def build_design_matrix() -> list[DesignPoint]:
    design = fractional_factorial_signs(SCREENING_FACTORS)  # 32 rows

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
        for i, signs in enumerate(design[:16])  # un-folded resolution-III half only
    ]
    return points
