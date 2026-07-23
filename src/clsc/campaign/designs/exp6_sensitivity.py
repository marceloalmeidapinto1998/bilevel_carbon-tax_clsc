"""Experiment 6 - Global Sensitivity Analysis (docs/Experimental_Plan.md §8).

Two design families on the fast cell (I17-M4-T3):
- 8 continuous factors in a resolution-V 2^(8-2) fractional factorial (64 runs) x 2 seeds = 128.
- 5 structural menu factors in a resolution-V 2^(5-1) half-fraction (16 runs) x seed 0.
Plus a data-dependent second stage (after the screening analysis): a face-centred central composite
design on the top-3 factors (15 runs) and a single-factor confirmatory check on a hard cell (3 runs).

Two-phase (like Exp7): `build_design_matrix(results_root=...)` returns only the screening families
until a screening summary (`<results_root>/exp6_sensitivity/_screening_top3.json`, a JSON list of
3 factor names) exists, after which it appends the curvature-augmentation stage.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

from clsc.campaign.designs._cells import cell_id, time_limits
from clsc.campaign.designs._common import DesignPoint
from clsc.campaign.doe.fractional_factorial import resolution_v_signs
from clsc.campaign.factors import CONTINUOUS_FACTORS, FACTOR_REGISTRY

EXPERIMENT_ID = "exp6"
SCREENING_CELL = cell_id(17, 4, 3)
CONFIRMATORY_CELL = cell_id(25, 8, 6)
CONTINUOUS_SEEDS = (0, 1)

STRUCTURAL_FACTORS = (
    "production_technology_menu",
    "remanufacturing_technology_menu",
    "road_menu",
    "sea_menu",
    "air_menu",
)
_STRUCTURAL_LEVEL = {-1: "base", 1: "expanded"}


def _coded_to_multiplier(factor: str, sign: int) -> float:
    spec = FACTOR_REGISTRY[factor]
    return spec.high if sign > 0 else spec.low


def _screening_top3_path(results_root: Path) -> Path:
    return Path(results_root) / "exp6_sensitivity" / "_screening_top3.json"


def _continuous_points() -> list[DesignPoint]:
    sub, wall = time_limits(SCREENING_CELL)
    points: list[DesignPoint] = []
    for run_index, signs in enumerate(resolution_v_signs(CONTINUOUS_FACTORS)):
        levels = {f: _coded_to_multiplier(f, signs[f]) for f in CONTINUOUS_FACTORS}
        for seed in CONTINUOUS_SEEDS:
            points.append(DesignPoint(
                experiment_id=EXPERIMENT_ID,
                design_point_id=f"exp6-cont-r{run_index:02d}-s{seed}",
                run_code=f"cont_r{run_index:02d}_s{seed}", base_instance_id=SCREENING_CELL,
                execution_mode="bilevel", factor_levels=levels, seed_offset=seed,
                per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
                notes="Resolution-V continuous screening (H6.1).",
            ))
    return points


def _structural_points() -> list[DesignPoint]:
    sub, wall = time_limits(SCREENING_CELL)
    points: list[DesignPoint] = []
    for run_index, signs in enumerate(resolution_v_signs(STRUCTURAL_FACTORS)):
        menus = {f: _STRUCTURAL_LEVEL[signs[f]] for f in STRUCTURAL_FACTORS}
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID,
            design_point_id=f"exp6-struct-r{run_index:02d}",
            run_code=f"struct_r{run_index:02d}", base_instance_id=SCREENING_CELL,
            execution_mode="bilevel",
            production_technology_menu=menus["production_technology_menu"],
            remanufacturing_technology_menu=menus["remanufacturing_technology_menu"],
            road_menu=menus["road_menu"], sea_menu=menus["sea_menu"], air_menu=menus["air_menu"],
            per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
            notes="Resolution-V structural half-fraction (H6.1).",
        ))
    return points


def _face_centred_ccd_signs(k: int = 3) -> list[dict[int, float]]:
    """Face-centred CCD for k factors: 2^k corners (+-1), 2k axial faces (0/+-1), 1 centre = 2^k+2k+1."""
    idx = tuple(range(k))
    runs: list[dict[int, float]] = []
    for corner in itertools.product((-1.0, 1.0), repeat=k):  # factorial corners
        runs.append(dict(zip(idx, corner)))
    for i in idx:  # axial (face) points at alpha = 1
        for level in (-1.0, 1.0):
            axial = {j: 0.0 for j in idx}
            axial[i] = level
            runs.append(axial)
    runs.append({j: 0.0 for j in idx})  # centre
    return runs


def _curvature_points(top3: list[str]) -> list[DesignPoint]:
    sub, wall = time_limits(SCREENING_CELL)
    csub, cwall = time_limits(CONFIRMATORY_CELL)
    points: list[DesignPoint] = []
    for run_index, signs in enumerate(_face_centred_ccd_signs(len(top3))):
        levels = {}
        for pos, factor in enumerate(top3):
            spec = FACTOR_REGISTRY[factor]
            coded = signs[pos]  # -1 / 0 / +1
            levels[factor] = spec.baseline + coded * (spec.high - spec.baseline) if coded >= 0 \
                else spec.baseline + coded * (spec.baseline - spec.low)
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID, design_point_id=f"exp6-ccd-r{run_index:02d}",
            run_code=f"ccd_r{run_index:02d}", base_instance_id=SCREENING_CELL,
            execution_mode="bilevel", factor_levels=levels,
            per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
            notes="Face-centred CCD curvature augmentation (top-3 factors).",
        ))
    # Confirmatory: the single top factor at low/baseline/high on a hard cell.
    top1 = top3[0]
    spec = FACTOR_REGISTRY[top1]
    for label, level in (("low", spec.low), ("base", spec.baseline), ("high", spec.high)):
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID, design_point_id=f"exp6-confirm-{top1}-{label}",
            run_code=f"confirm_{label}", base_instance_id=CONFIRMATORY_CELL,
            execution_mode="bilevel", factor_levels={top1: level},
            per_subproblem_time_limit_seconds=csub, per_run_wall_clock_cap_seconds=cwall,
            notes="Confirmatory check of the dominant factor on a hard cell.",
        ))
    return points


def build_design_matrix(*, results_root: Path | None = None) -> list[DesignPoint]:
    points = _continuous_points() + _structural_points()
    if results_root is not None:
        top3_path = _screening_top3_path(results_root)
        if top3_path.exists():
            top3 = json.loads(top3_path.read_text(encoding="utf-8"))
            points += _curvature_points(list(top3))
    return points
