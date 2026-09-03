"""Experiment 3 - Policy Value and Carbon-Price Calibration (docs/Experimental_Plan.md §3).

Merges the prior campaign's "value of the bilevel leader" and "policy calibration" experiments:
both ultimately ask what the regulator should do and how much it matters. This is the campaign's
headline experiment -- the emissions-optimal tax is a plateau, not a point, and tau* (the
lexicographic least-intervention choice) is the defensible selection from it.

Four cells carry the plateau/burden-ratio claim: the fast anchor (STD_I17_M4_T3), one medium cell,
and BOTH hard cells -- I25-M8-T6 (where the prior campaign found a genuine tau*-precision
limitation against an independently re-solved cold check) and I25-M8-T12 (where the prior campaign
found its most dramatic burden ratio, 18.6x). Losing either hard cell would drop a distinct,
separately-reportable finding, so both are kept despite the smaller campaign.

Three stages:
1. (always) Policy rules P0/P1/P2 (no-tax / ceiling / mid-grid fixed-tax follower solves) on all 4
   cells. P3 (tau*, bilevel lexicographic) is read from Experiment 2's M0 result on the same cell,
   not re-solved.
2. (data-dependent, once Experiment 2's M0 manifests exist) Local plateau refinement: 2 points
   below tau*, 2 above, per cell -- enough to resolve the descending slope for the staircase figure.
3. (always + data-dependent) The valuation-ratio sweep rho in {1, 10, 50, 100, 200} on the anchor
   cell to locate the defensible ratio rho*, then (once rho* is identified) the anchored suite at
   rho*: one bilevel solve, an 11-point tax-indexed frontier, and an AUGMECON min-emissions anchor.
"""
from __future__ import annotations

import json
from pathlib import Path

from clsc.campaign.designs._cells import HARD_CELLS, MEDIUM_CELLS, cell_id, time_limits
from clsc.campaign.designs._common import FINE_CEILING_INDEX, DesignPoint
from clsc.campaign.doe.frontier_sweep import tax_grid

EXPERIMENT_ID = "exp3"

ANCHOR_CELL = cell_id(17, 4, 3)
POLICY_CELLS = (ANCHOR_CELL, MEDIUM_CELLS[0], HARD_CELLS[0], cell_id(25, 8, 12))

# Policy rules solved as fixed-tax follower runs on the campaign's fine grid (index 0..2000):
#   P0 no tax; P1 tax ceiling; P2 mid-grid flat tax. (P3 = Experiment 2's M0; P4 dropped -- it
# would duplicate P1 on this grid, per the prior campaign's finding.)
POLICY_RULES = {
    "P0_no_tax": 0,
    "P1_ceiling": FINE_CEILING_INDEX,
    "P2_mid": FINE_CEILING_INDEX // 2,
}

# Local refinement around tau*: fewer points than the prior campaign (2 below + 2 above instead of
# 4+3), since this campaign only needs to establish the descending slope's shape, not survey it
# densely.
REFINEMENT_BELOW_N = 2
REFINEMENT_ABOVE_N = 2
REFINEMENT_ABOVE_SPAN = 4  # points above tau* span up to tau* * this factor (clipped to the grid)

RATIO_VALUES = (1.0, 10.0, 50.0, 100.0, 200.0)
# 11-point tax-indexed frontier over the same real tax range as the bilevel runs.
FRONTIER_TAX_INDICES = tuple(
    tax_grid(FINE_CEILING_INDEX, n_points=11, step=FINE_CEILING_INDEX // 10)
)


def _exp2_m0_manifest_path(results_root: Path, cell: str) -> Path:
    return Path(results_root) / "exp2_computational_performance" / cell / "M0_seed0" / "campaign_manifest.json"


def _tau_star_index(results_root: Path, cell: str) -> int | None:
    """Experiment 2's M0 seed-0 tau* for ``cell``, read directly off its manifest (a completed
    run, not a re-solve). Both experiments' bilevel arms use the same campaign fine grid, so the
    raw ``leader_tax`` index is directly comparable to this module's own indices without
    conversion. Returns None if that run has not reached a terminal, tax-index-bearing state yet.
    """
    path = _exp2_m0_manifest_path(results_root, cell)
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    tax_index = manifest.get("leader_tax")
    return int(tax_index) if tax_index is not None else None


def _geometric_indices(lo: int, hi: int, n: int) -> list[int]:
    """``n`` integer indices geometrically spaced in ``[lo, hi]`` (deduplicated, ascending).

    Geometric rather than linear spacing because tau* itself spans nearly three orders of
    magnitude across cells: linear spacing anchored to the smallest cells would place every point
    within 1-2 grid steps of tau* on the largest ones.
    """
    if lo >= hi:
        return [lo] if 0 <= lo <= hi or lo == hi else []
    lo = max(lo, 1)
    ratio = (hi / lo) ** (1.0 / (n - 1)) if n > 1 else 1.0
    return sorted({max(lo, min(hi, round(lo * ratio**i))) for i in range(n)})


def _refinement_points(results_root: Path) -> list[DesignPoint]:
    points: list[DesignPoint] = []
    reserved = set(POLICY_RULES.values())  # avoid duplicating an already-scheduled index
    for cell in POLICY_CELLS:
        tau_star = _tau_star_index(results_root, cell)
        if tau_star is None:
            continue  # Experiment 2's M0 arm for this cell has not produced a tax index yet
        sub, wall = time_limits(cell)

        below = _geometric_indices(max(1, tau_star // 8), max(1, tau_star - 1), REFINEMENT_BELOW_N)
        above_hi = min(FINE_CEILING_INDEX - 1, tau_star * REFINEMENT_ABOVE_SPAN)
        above = _geometric_indices(tau_star + 1, max(tau_star + 1, above_hi), REFINEMENT_ABOVE_N)

        for tax_index in below + above:
            if tax_index in reserved or tax_index == tau_star:
                continue
            side = "below" if tax_index < tau_star else "above"
            points.append(DesignPoint(
                experiment_id=EXPERIMENT_ID,
                design_point_id=f"exp3-refine-{side}-tau{tax_index:04d}-{cell}",
                run_code=f"refine_{side}_tau{tax_index:04d}", base_instance_id=cell,
                execution_mode="fixed_tax", fixed_tax_index=tax_index,
                per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
                notes="Local plateau refinement around tau* (H3.1).",
            ))
    return points


def _rho_star_path(results_root: Path) -> Path:
    return Path(results_root) / "exp3_policy_value" / "_rho_star.json"


def _ratio_sweep_points() -> list[DesignPoint]:
    sub, wall = time_limits(ANCHOR_CELL)
    points: list[DesignPoint] = []
    for ratio in RATIO_VALUES:
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID, design_point_id=f"exp3-rho-{ratio:g}",
            run_code=f"rho_{ratio:g}", base_instance_id=ANCHOR_CELL,
            execution_mode="bilevel", valuation_ratio=ratio,
            per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
            notes="Valuation-ratio sweep (H3.2).",
        ))
    return points


def _anchored_suite_points(rho_star: float) -> list[DesignPoint]:
    sub, wall = time_limits(ANCHOR_CELL)
    points: list[DesignPoint] = []
    points.append(DesignPoint(
        experiment_id=EXPERIMENT_ID, design_point_id=f"exp3-anchor-bilevel-{rho_star:g}",
        run_code="anchor_bilevel", base_instance_id=ANCHOR_CELL,
        execution_mode="bilevel", valuation_ratio=rho_star,
        per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
        notes="Anchored certified bilevel optimum at rho* (H3.3).",
    ))
    for tax_index in FRONTIER_TAX_INDICES:
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID,
            design_point_id=f"exp3-frontier-tau{tax_index:04d}",
            run_code=f"frontier_tau{tax_index:04d}", base_instance_id=ANCHOR_CELL,
            execution_mode="fixed_tax", fixed_tax_index=tax_index, valuation_ratio=rho_star,
            per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
            notes="Tax-indexed frontier point at rho*.",
        ))
    points.append(DesignPoint(
        experiment_id=EXPERIMENT_ID, design_point_id=f"exp3-eps-anchor-{rho_star:g}",
        run_code="eps_anchor_min_emissions", base_instance_id=ANCHOR_CELL,
        execution_mode="min_emissions", valuation_ratio=rho_star,
        per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
        notes="AUGMECON payoff-table minimum-emissions anchor at rho*.",
    ))
    return points


def build_design_matrix(*, results_root: Path | None = None) -> list[DesignPoint]:
    points: list[DesignPoint] = []
    for cell in POLICY_CELLS:
        sub, wall = time_limits(cell)
        for run_code, tax_index in POLICY_RULES.items():
            points.append(DesignPoint(
                experiment_id=EXPERIMENT_ID, design_point_id=f"exp3-{run_code}-{cell}",
                run_code=run_code, base_instance_id=cell,
                execution_mode="fixed_tax", fixed_tax_index=tax_index,
                per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
                notes="Policy-rule follower solve (H3.1).",
            ))

    points += _ratio_sweep_points()

    if results_root is not None:
        points += _refinement_points(Path(results_root))

        rho_path = _rho_star_path(results_root)
        if rho_path.exists():
            rho_star = float(json.loads(rho_path.read_text(encoding="utf-8")))
            points += _anchored_suite_points(rho_star)

    return points
