"""Experiment 5 - Value of the Bilevel Leader (docs/Experimental_Plan.md §6).

Compares the bilevel leader's tax against simpler policy rules on all 12 cells. P3 (tau* bilevel
lexicographic) is Experiment 3's M0 result on the same cell -- not re-solved here. P0/P1/P2 are
one fresh follower-only lexicographic solve each per cell.

P4 (plateau right edge) is the LARGEST tax still achieving the certified emissions floor E*, which
is data-dependent (it needs the solved plateau). It is therefore a second stage: once
`<results_root>/exp5_leader_value/_plateau_right_edge.json` (a JSON dict of base_instance_id ->
tax_index) exists, `build_design_matrix(results_root=...)` appends one P4 follower solve per cell.

The local refinement (docs/Experimental_Plan.md §4) is a third, unconditional stage: once Exp3's
M0 seed-0 result exists for a cell (it already does -- this is a read, not a re-solve), it adds a
handful of follower points geometrically spaced BELOW tau* and a few just ABOVE it. P0/P1/P2/P3
alone bracket the plateau at 0, 100, 200 USD/t and tau* -- they show THAT the plateau is wide, not
its shape. The measured tau* values (0.5-167 USD/t across cells) are mostly far below the 100 USD/t
P2 point, so without this refinement there is no resolution on the falling part of E(tax) that the
paper's staircase figure needs.
"""
from __future__ import annotations

import json
from pathlib import Path

from clsc.campaign.designs._cells import ALL_CELLS, time_limits
from clsc.campaign.designs._common import FINE_CEILING_INDEX, DesignPoint

EXPERIMENT_ID = "exp5"

# Policy rules solved as fixed-tax follower runs, on the campaign's fine grid (index 0..2000):
#   P0 no tax; P1 tax ceiling; P2 mid-grid flat tax. (P3 = Exp3 M0; P4 = plateau right edge, stage 2.)
# The grid MUST match the bilevel runs': P3 is a fine-grid tau* and P4 is read off the fine-grid
# plateau, so a coarse-grid P0/P1/P2 would compare rules at taxes 100x apart.
POLICY_RULES = {
    "P0_no_tax": 0,
    "P1_ceiling": FINE_CEILING_INDEX,
    "P2_mid": FINE_CEILING_INDEX // 2,
}

# Local refinement around tau*: N points on the falling slope below it, M points confirming
# flatness just above it.
REFINEMENT_BELOW_N = 4
REFINEMENT_ABOVE_N = 3
REFINEMENT_ABOVE_SPAN = 4  # points above tau* span up to tau* * this factor (clipped to the grid)


def _plateau_path(results_root: Path) -> Path:
    return Path(results_root) / "exp5_leader_value" / "_plateau_right_edge.json"


def _exp3_m0_manifest_path(results_root: Path, cell: str) -> Path:
    return Path(results_root) / "exp3_ablation" / cell / "M0_seed0" / "campaign_manifest.json"


def _tau_star_index(results_root: Path, cell: str) -> int | None:
    """Exp3's M0 seed-0 tau* for ``cell``, read directly off its manifest (a completed run, not a
    re-solve). Both experiments' bilevel arms use the same campaign fine grid (§3), so the raw
    ``leader_tax`` index is directly comparable to this module's own indices without conversion.
    Returns None if that run has not reached a terminal, non-tax-index-bearing state yet."""
    path = _exp3_m0_manifest_path(results_root, cell)
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    tax_index = manifest.get("leader_tax")
    return int(tax_index) if tax_index is not None else None


def _geometric_indices(lo: int, hi: int, n: int) -> list[int]:
    """``n`` integer indices geometrically spaced in ``[lo, hi]`` (deduplicated, ascending).

    Geometric rather than linear spacing because tau* itself spans nearly three orders of
    magnitude across cells (index ~14 to ~1673 on the fine grid): linear spacing anchored to the
    smallest cells would place every point within 1-2 grid steps of tau* on the largest ones.
    """
    if lo >= hi:
        return [lo] if 0 <= lo <= hi or lo == hi else []
    lo = max(lo, 1)
    ratio = (hi / lo) ** (1.0 / (n - 1)) if n > 1 else 1.0
    return sorted({max(lo, min(hi, round(lo * ratio**i))) for i in range(n)})


def _refinement_points(results_root: Path) -> list[DesignPoint]:
    points: list[DesignPoint] = []
    reserved = set(POLICY_RULES.values())  # avoid duplicating an already-scheduled index
    for cell in ALL_CELLS:
        tau_star = _tau_star_index(results_root, cell)
        if tau_star is None:
            continue  # Exp3's M0 arm for this cell has not produced a tax index yet
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
                design_point_id=f"exp5-refine-{side}-tau{tax_index:04d}-{cell}",
                run_code=f"refine_{side}_tau{tax_index:04d}", base_instance_id=cell,
                execution_mode="fixed_tax", fixed_tax_index=tax_index,
                per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
                notes=f"Local plateau refinement {side} tau* (Experimental_Plan.md §4).",
            ))
    return points


def build_design_matrix(*, results_root: Path | None = None) -> list[DesignPoint]:
    points: list[DesignPoint] = []
    for cell in ALL_CELLS:
        sub, wall = time_limits(cell)
        for run_code, tax_index in POLICY_RULES.items():
            points.append(DesignPoint(
                experiment_id=EXPERIMENT_ID, design_point_id=f"exp5-{run_code}-{cell}",
                run_code=run_code, base_instance_id=cell,
                execution_mode="fixed_tax", fixed_tax_index=tax_index,
                per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
                notes="Policy-rule follower solve (H5.1/H5.2).",
            ))

    if results_root is not None:
        points += _refinement_points(Path(results_root))

        # P4 (data-dependent): plateau right edge per cell, once the solved plateau is available.
        plateau_path = _plateau_path(results_root)
        if plateau_path.exists():
            plateau = json.loads(plateau_path.read_text(encoding="utf-8"))
            for cell in ALL_CELLS:
                if cell not in plateau:
                    continue
                sub, wall = time_limits(cell)
                points.append(DesignPoint(
                    experiment_id=EXPERIMENT_ID, design_point_id=f"exp5-P4_plateau_edge-{cell}",
                    run_code="P4_plateau_edge", base_instance_id=cell,
                    execution_mode="fixed_tax", fixed_tax_index=int(plateau[cell]),
                    per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
                    notes="Plateau right-edge follower solve (H5.2).",
                ))
    return points
