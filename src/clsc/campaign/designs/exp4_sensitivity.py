"""Experiment 4 - Sensitivity / Robustness Screening (docs/Experimental_Plan.md §4).

A single-stage screen of the 8 continuous factors on the fast cell (I17-M4-T3), one seed: a
resolution-IV two-level fractional factorial via fold-over
(`clsc.campaign.doe.fractional_factorial.fractional_factorial_signs`, 2^(k0+1) = 32 runs for
k=8). This is a deliberate cut from the prior campaign's resolution-V design (64 runs x 2 seeds),
its separate 5-factor structural half-fraction, and its face-centred CCD curvature-augmentation
stage: a screening-only main-effects result (a tornado chart) is standard and sufficient for a
robustness check in this paper; resolving two-factor interactions and curvature are not needed for
a claim of "these are the inputs that matter."
"""
from __future__ import annotations

from clsc.campaign.designs._cells import cell_id, time_limits
from clsc.campaign.designs._common import DesignPoint
from clsc.campaign.doe.fractional_factorial import fractional_factorial_signs
from clsc.campaign.factors import CONTINUOUS_FACTORS, FACTOR_REGISTRY

EXPERIMENT_ID = "exp4"
SCREENING_CELL = cell_id(17, 4, 3)


def _coded_to_multiplier(factor: str, sign: int) -> float:
    spec = FACTOR_REGISTRY[factor]
    return spec.high if sign > 0 else spec.low


def build_design_matrix() -> list[DesignPoint]:
    sub, wall = time_limits(SCREENING_CELL)
    points: list[DesignPoint] = []
    for run_index, signs in enumerate(fractional_factorial_signs(CONTINUOUS_FACTORS)):
        levels = {f: _coded_to_multiplier(f, signs[f]) for f in CONTINUOUS_FACTORS}
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID,
            design_point_id=f"exp4-cont-r{run_index:02d}",
            run_code=f"cont_r{run_index:02d}", base_instance_id=SCREENING_CELL,
            execution_mode="bilevel", factor_levels=levels,
            per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
            notes="Resolution-IV continuous screening (H4.1).",
        ))
    return points
