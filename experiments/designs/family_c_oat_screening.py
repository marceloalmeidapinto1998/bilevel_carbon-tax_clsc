"""Family C - One-at-a-time (OAT) sensitivity analysis (RQ3).

8 continuous factors x 5 levels (low, mid-low, baseline, mid-high, high) + 5 structural factors
x 1 on/off contrast, single instance, holding every other factor at baseline. This is the
dominant sensitivity-analysis convention in closed-loop supply chain network design (Fleischmann
et al., 2001; Pishvaee, Rabbani & Torabi, 2011). See EXPERIMENTAL_PLAN.md §4-C for the full
factor table and rationale.

Factors are expressed as multipliers relative to the baseline instance (multiplier=1.0, or
"base" for structural factors, reproduces the baseline), so a level is applied by only setting
that one factor -- every other factor is implicitly at baseline because it is simply not touched.
"""
from __future__ import annotations

from experiments.designs._common import DesignPoint
from tools.experiments.doe_campaign_01.factors import CAMPAIGN_02_CONTINUOUS_FACTORS, FACTOR_REGISTRY

FAMILY_ID = "C"
EXECUTION_MODE = "bilevel"

INSTANCE = "STD_I17_M4_T3"

STRUCTURAL_FACTORS: tuple[str, ...] = (
    "production_technology_menu",
    "remanufacturing_technology_menu",
    "road_menu",
    "sea_menu",
    "air_menu",
)

# Standard tier throughout (EXPERIMENTAL_PLAN.md §4-C) -- INSTANCE is the fast class.
STANDARD_SUBPROBLEM_SECONDS = 3600.0
STANDARD_WALL_CLOCK_SECONDS = 28800.0


def _oat_levels(low: float, high: float, baseline: float) -> list[float]:
    """5 points: low, mid-low, baseline, mid-high, high."""
    return [low, (low + baseline) / 2.0, baseline, (baseline + high) / 2.0, high]


def build_design_matrix() -> list[DesignPoint]:
    points: list[DesignPoint] = []
    index = 0

    for factor_name in CAMPAIGN_02_CONTINUOUS_FACTORS:
        spec = FACTOR_REGISTRY[factor_name]
        for level in _oat_levels(spec.low, spec.high, spec.baseline):
            index += 1
            points.append(
                DesignPoint(
                    family_id=FAMILY_ID,
                    design_point_id=f"C-{index:02d}",
                    run_code=f"{factor_name}_{level:.4f}",
                    base_instance_id=INSTANCE,
                    execution_mode=EXECUTION_MODE,
                    per_subproblem_time_limit_seconds=STANDARD_SUBPROBLEM_SECONDS,
                    per_run_wall_clock_cap_seconds=STANDARD_WALL_CLOCK_SECONDS,
                    factor_levels={factor_name: level},
                )
            )

    for factor_name in STRUCTURAL_FACTORS:
        index += 1
        points.append(
            DesignPoint(
                family_id=FAMILY_ID,
                design_point_id=f"C-{index:02d}",
                run_code=f"{factor_name}_expanded",
                base_instance_id=INSTANCE,
                execution_mode=EXECUTION_MODE,
                per_subproblem_time_limit_seconds=STANDARD_SUBPROBLEM_SECONDS,
                per_run_wall_clock_cap_seconds=STANDARD_WALL_CLOCK_SECONDS,
                notes="on/off structural contrast (base vs. expanded)",
                **{factor_name: "expanded"},
            )
        )

    return points
