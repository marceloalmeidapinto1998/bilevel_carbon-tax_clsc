"""Experiment 7 - Carbon-Price Validity and Policy Calibration (docs/Experimental_Plan.md §9).

The only experiment reporting absolute USD/t. Two phases on the fast cell (I17-M4-T3):
- Phase 1 (always): a valuation-ratio sweep rho in {1,5,10,20,50,100,200}, each a full bilevel DBP
  solve, to trace tau*(rho) and locate the defensible ratio rho*.
- Phase 2 (after rho* is identified): the anchored-instance suite at rho* -- one bilevel solve, an
  11-point tax-indexed frontier (follower-only), and an AUGMECON min-emissions anchor. The 10
  intermediate epsilon-constraint points depend on the two solved anchors' emissions and are a
  further data-dependent stage (see Family-B pattern), not emitted here.

Two-phase gate: `build_design_matrix(results_root=...)` appends Phase 2 once
`<results_root>/exp7_policy_calibration/_rho_star.json` (a JSON number) exists.
"""
from __future__ import annotations

import json
from pathlib import Path

from clsc.campaign.designs._cells import cell_id, time_limits
from clsc.campaign.designs._common import FINE_CEILING_INDEX, DesignPoint
from clsc.campaign.doe.frontier_sweep import tax_grid

EXPERIMENT_ID = "exp7"
ANCHOR_CELL = cell_id(17, 4, 3)
RATIO_VALUES = (1.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0)
# 11 points over the same real tax range as the bilevel runs, on the fine grid: 0, 200, ..., 2000.
FRONTIER_TAX_INDICES = tuple(
    tax_grid(FINE_CEILING_INDEX, n_points=11, step=FINE_CEILING_INDEX // 10)
)


def _rho_star_path(results_root: Path) -> Path:
    return Path(results_root) / "exp7_policy_calibration" / "_rho_star.json"


def _ratio_sweep_points() -> list[DesignPoint]:
    sub, wall = time_limits(ANCHOR_CELL)
    points: list[DesignPoint] = []
    for ratio in RATIO_VALUES:
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID, design_point_id=f"exp7-rho-{ratio:g}",
            run_code=f"rho_{ratio:g}", base_instance_id=ANCHOR_CELL,
            execution_mode="bilevel", valuation_ratio=ratio,
            per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
            notes="Valuation-ratio sweep (H7.1).",
        ))
    return points


def _anchored_suite_points(rho_star: float) -> list[DesignPoint]:
    sub, wall = time_limits(ANCHOR_CELL)
    points: list[DesignPoint] = []
    # Certified bilevel optimum at rho*.
    points.append(DesignPoint(
        experiment_id=EXPERIMENT_ID, design_point_id=f"exp7-anchor-bilevel-{rho_star:g}",
        run_code="anchor_bilevel", base_instance_id=ANCHOR_CELL,
        execution_mode="bilevel", valuation_ratio=rho_star,
        per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
        notes="Anchored certified bilevel optimum at rho* (H7.2).",
    ))
    # 11-point tax-indexed frontier (follower-only) at rho*.
    for tax_index in FRONTIER_TAX_INDICES:
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID,
            design_point_id=f"exp7-frontier-tau{tax_index:04d}",
            run_code=f"frontier_tau{tax_index:04d}", base_instance_id=ANCHOR_CELL,
            execution_mode="fixed_tax", fixed_tax_index=tax_index, valuation_ratio=rho_star,
            per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
            notes="Tax-indexed frontier point at rho*.",
        ))
    # AUGMECON minimum-emissions anchor at rho*.
    points.append(DesignPoint(
        experiment_id=EXPERIMENT_ID, design_point_id=f"exp7-eps-anchor-{rho_star:g}",
        run_code="eps_anchor_min_emissions", base_instance_id=ANCHOR_CELL,
        execution_mode="min_emissions", valuation_ratio=rho_star,
        per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
        notes="AUGMECON payoff-table minimum-emissions anchor at rho*.",
    ))
    return points


def build_design_matrix(*, results_root: Path | None = None) -> list[DesignPoint]:
    points = _ratio_sweep_points()
    if results_root is not None:
        rho_path = _rho_star_path(results_root)
        if rho_path.exists():
            rho_star = float(json.loads(rho_path.read_text(encoding="utf-8")))
            points += _anchored_suite_points(rho_star)
    return points
