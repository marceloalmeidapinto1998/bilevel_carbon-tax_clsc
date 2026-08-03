"""Unit tests for Exp5's local plateau refinement (Experimental_Plan.md §4).

The static P0/P1/P2/P3 points bracket the plateau at 0/100/200 USD/t and tau*, but tau* itself
sits well below 100 USD/t on most cells (measured range 0.5-167 USD/t across the 12 base cells),
so without a refinement stage there is no resolution on the falling slope of E(tax) the plateau
figure needs. These tests cover the two pure-Python pieces: the geometric spacing helper, and
`_tau_star_index`'s read of Exp3's already-completed M0 result (no re-solve, no Gurobi).
"""
from __future__ import annotations

import json

import pytest

from clsc.campaign.designs import exp5_leader_value as exp5
from clsc.campaign.designs._common import FINE_CEILING_INDEX


# ---------------------------------------------------------------------------
# _geometric_indices
# ---------------------------------------------------------------------------

def test_geometric_indices_stay_within_bounds_and_ascending() -> None:
    idx = exp5._geometric_indices(10, 1000, 5)
    assert idx == sorted(idx)
    assert all(10 <= i <= 1000 for i in idx)


def test_geometric_indices_span_orders_of_magnitude() -> None:
    # tau* ranges from ~14 to ~1673 across cells -- linear spacing anchored to the small end
    # would place every point within a couple of grid steps of tau* on the largest cells.
    idx = exp5._geometric_indices(200, 1670, 4)
    ratios = [b / a for a, b in zip(idx, idx[1:])]
    # Consecutive ratios should be roughly comparable (geometric, not front-loaded).
    assert max(ratios) / min(ratios) < 3.0


def test_geometric_indices_degenerate_range_returns_single_point() -> None:
    assert exp5._geometric_indices(5, 5, 4) == [5]


def test_geometric_indices_deduplicates_when_range_is_narrow() -> None:
    # A range too narrow for n distinct integer points must not raise or return duplicates.
    idx = exp5._geometric_indices(1, 3, 6)
    assert idx == sorted(set(idx))
    assert all(1 <= i <= 3 for i in idx)


# ---------------------------------------------------------------------------
# _tau_star_index
# ---------------------------------------------------------------------------

def test_tau_star_index_reads_leader_tax_from_exp3_manifest(tmp_path) -> None:
    cell = "STD_I17_M4_T3"
    manifest_dir = tmp_path / "exp3_ablation" / cell / "M0_seed0"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "campaign_manifest.json").write_text(
        json.dumps({"leader_tax": 80, "solve_status": "success"}), encoding="utf-8",
    )

    assert exp5._tau_star_index(tmp_path, cell) == 80


def test_tau_star_index_is_none_when_exp3_has_not_run_yet(tmp_path) -> None:
    assert exp5._tau_star_index(tmp_path, "STD_I17_M4_T3") is None


# ---------------------------------------------------------------------------
# _refinement_points / build_design_matrix integration
# ---------------------------------------------------------------------------

def _seed_exp3_m0(root, cell: str, tau_star: int) -> None:
    manifest_dir = root / "exp3_ablation" / cell / "M0_seed0"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "campaign_manifest.json").write_text(
        json.dumps({"leader_tax": tau_star, "solve_status": "success"}), encoding="utf-8",
    )


def test_refinement_points_bracket_tau_star_without_repeating_it(tmp_path) -> None:
    cell = "STD_I17_M4_T3"
    _seed_exp3_m0(tmp_path, cell, tau_star=80)

    points = exp5._refinement_points(tmp_path)
    cell_points = [p for p in points if p.base_instance_id == cell]

    assert cell_points, "expected refinement points once Exp3's M0 result exists"
    indices = [p.fixed_tax_index for p in cell_points]
    assert 80 not in indices              # tau* itself is already P3, not re-solved
    assert any(i < 80 for i in indices)   # falling slope below tau*
    assert any(i > 80 for i in indices)   # flatness confirmation above tau*
    assert all(0 <= i <= FINE_CEILING_INDEX for i in indices)
    assert len(indices) == len(set(indices))  # no duplicate design points for one cell


def test_refinement_skips_a_cell_whose_exp3_result_is_not_ready(tmp_path) -> None:
    # No manifest seeded at all -> every cell's tau* lookup returns None.
    assert exp5._refinement_points(tmp_path) == []


def test_refinement_never_duplicates_a_reserved_policy_index(tmp_path) -> None:
    # tau* exactly at the P2 midpoint: the refinement must not re-schedule that index.
    cell = "STD_I17_M4_T3"
    _seed_exp3_m0(tmp_path, cell, tau_star=exp5.FINE_CEILING_INDEX // 2)

    points = exp5._refinement_points(tmp_path)
    indices = {p.fixed_tax_index for p in points if p.base_instance_id == cell}
    assert exp5.POLICY_RULES["P2_mid"] not in indices


def test_build_design_matrix_includes_refinement_when_results_root_given(tmp_path) -> None:
    for cell in exp5.ALL_CELLS:
        _seed_exp3_m0(tmp_path, cell, tau_star=50)

    with_root = exp5.build_design_matrix(results_root=tmp_path)
    without_root = exp5.build_design_matrix(results_root=None)

    assert len(with_root) > len(without_root)
    assert len(without_root) == len(exp5.ALL_CELLS) * len(exp5.POLICY_RULES)
    refine_ids = [p.design_point_id for p in with_root if "refine" in p.run_code]
    assert len(refine_ids) == len(set(refine_ids))  # globally unique across all 12 cells
