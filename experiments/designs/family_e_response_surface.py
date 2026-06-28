"""Family E - Dense univariate response curves (RQ5).

Unlike Families C/D, this family's factor choice is *data-driven*: it dense-samples whichever
2-3 continuous factors Family C's half-normal effect plot flags as dominant (top_factors),
not a fixed a-priori set. `build_design_matrix(top_factors=...)` must be called with that list
once Family C has been analyzed (Phase 5); the module-level default below is only a placeholder
so `campaign.py generate --dry-run` can report a run count before Family C exists, using the
two factors that were dominant in the v1 campaign (emission_intensity, demand) as a stand-in.

Design: the fast instance gets all `top_factors` dense-sampled at `N_LEVELS_FAST` levels each;
the confirmatory instance gets only the single top-ranked factor, at a coarse 3-point
(low/baseline/high) check — enough to confirm the curve's shape isn't instance-specific
without re-running the full grid.
"""
from __future__ import annotations

from experiments.designs._common import DesignPoint
from tools.experiments.v2.design.response_surface import dense_levels
from tools.experiments.v2.factors import FACTOR_REGISTRY

FAMILY_ID = "E"
EXECUTION_MODE = "bilevel"

FAST_INSTANCE = "STD_I17_M4_T3"
CONFIRMATORY_INSTANCE = "STD_I25_M8_T6"

# Placeholder only — replace with Family C's actual top-ranked factors before Phase 4 (RQ5).
DEFAULT_TOP_FACTORS: tuple[str, ...] = ("emission_intensity", "demand", "scope3_emissions")
N_LEVELS_FAST = 9
N_LEVELS_CONFIRM = 3

# Doubled from the plan's original 3600s/14400s (Phase 3.5 pre-flight check, 2026-06-26):
# the confirmatory instance (STD_I25_M8_T6) hit the original Family A cap at mip_gap~0.0001,
# essentially converged but needing more time.
PER_SUBPROBLEM_TIME_LIMIT_SECONDS = 7200.0
PER_RUN_WALL_CLOCK_CAP_SECONDS = 28800.0


def build_design_matrix(top_factors: tuple[str, ...] = DEFAULT_TOP_FACTORS) -> list[DesignPoint]:
    points: list[DesignPoint] = []
    index = 0

    for factor_name in top_factors:
        spec = FACTOR_REGISTRY[factor_name]
        for level in dense_levels(spec.low, spec.high, n_levels=N_LEVELS_FAST, baseline=spec.baseline):
            index += 1
            points.append(
                DesignPoint(
                    family_id=FAMILY_ID,
                    design_point_id=f"E-{index:02d}",
                    run_code=f"{factor_name}_{level:.4f}",
                    base_instance_id=FAST_INSTANCE,
                    execution_mode=EXECUTION_MODE,
                    per_subproblem_time_limit_seconds=PER_SUBPROBLEM_TIME_LIMIT_SECONDS,
                    per_run_wall_clock_cap_seconds=PER_RUN_WALL_CLOCK_CAP_SECONDS,
                    factor_levels={factor_name: level},
                )
            )

    top_ranked = top_factors[0]
    spec = FACTOR_REGISTRY[top_ranked]
    for level in dense_levels(spec.low, spec.high, n_levels=N_LEVELS_CONFIRM, baseline=spec.baseline):
        index += 1
        points.append(
            DesignPoint(
                family_id=FAMILY_ID,
                design_point_id=f"E-{index:02d}",
                run_code=f"{top_ranked}_{level:.4f}",
                base_instance_id=CONFIRMATORY_INSTANCE,
                execution_mode=EXECUTION_MODE,
                per_subproblem_time_limit_seconds=PER_SUBPROBLEM_TIME_LIMIT_SECONDS,
                per_run_wall_clock_cap_seconds=PER_RUN_WALL_CLOCK_CAP_SECONDS,
                factor_levels={top_ranked: level},
                notes="confirmatory instance, top-ranked factor only",
            )
        )
    return points
