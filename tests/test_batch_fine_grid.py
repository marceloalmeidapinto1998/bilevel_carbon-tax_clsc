"""Unit tests for the batch runner's fine-grid / Phase-2 wiring (tools/solver/batch/core.py).

These exercise the campaign-config plumbing added for doe_campaign_02 -- the --scale-factor
fine-grid override and the --no-refine-min-tax Phase-2 toggle -- WITHOUT invoking Gurobi, so they
stay in the fast suite. The end-to-end solve behaviour of the fine grid + Phase 2 is covered by the
solver tests; here we only assert that the CLI accepts the flags and that the in-memory grid
override recomputes the index bounds correctly while preserving the instance's real tax range.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from src.config.gap_tol import DEFAULT
from src.models.instance import InstanceData

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_INSTANCE = REPO_ROOT / "data" / "instances" / "base" / "STD_I17_M4_T3.json"


def _load_solve_batch_module():
    module_path = REPO_ROOT / "tools" / "solver" / "solve_batch.py"
    spec = importlib.util.spec_from_file_location("solve_batch_tool", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parser_defaults_leave_grid_and_phase2_at_stored_settings():
    core = _load_solve_batch_module()
    args = core.build_parser().parse_args(["some/instance.json"])
    # No override by default: the stored coarse grid (theta = 0.01) is used as-is...
    assert args.scale_factor is None
    # ...and Phase 2 defaults ON (matches solve_bilevel_dbp_lex's own default).
    assert args.refine_min_tax is True


def test_parser_accepts_fine_grid_and_phase2_toggle():
    core = _load_solve_batch_module()
    args = core.build_parser().parse_args(
        ["some/instance.json", "--scale-factor", "0.0001", "--no-refine-min-tax"]
    )
    assert args.scale_factor == pytest.approx(1e-4)
    assert args.refine_min_tax is False


def test_with_tax_grid_step_refines_index_and_preserves_tax_range():
    instance = InstanceData.from_file(BASE_INSTANCE)
    # Sanity: the stored instance is the coarse campaign grid.
    assert instance.upper_tax_index == 20
    assert instance.scale_factor == pytest.approx(0.01)
    stored_underline_tau = float(instance.parameters["underline_tau"])
    stored_overline_tau = float(instance.parameters["overline_tau"])

    refined = instance.with_tax_grid_step(1e-4)

    # Immutable: a NEW instance is returned; the original stays on the coarse grid
    # and its stored parameters are never rewritten.
    assert refined is not instance
    assert instance.tax_grid_step is None
    assert instance.upper_tax_index == 20
    assert refined.parameters["overline_tax_index"] == 20
    # Index bounds DERIVED from the instance's own tau range: 0.2 / 1e-4 = 2000.
    assert refined.lower_tax_index == 0
    assert refined.upper_tax_index == 2000
    # The scale_factor is now exactly the requested theta.
    assert refined.scale_factor == pytest.approx(1e-4)
    # The real tax RANGE is untouched -- only the resolution changed.
    assert float(refined.parameters["underline_tau"]) == pytest.approx(stored_underline_tau)
    assert float(refined.parameters["overline_tau"]) == pytest.approx(stored_overline_tau)
    # And an interior fine-grid index maps to the expected real rate (index 102 -> 0.0102 USD/kg).
    assert refined.tax_rate(102) == pytest.approx(0.0102)


def test_with_tax_grid_step_rejects_nonpositive_and_collapsing_theta():
    instance = InstanceData.from_file(BASE_INSTANCE)
    with pytest.raises(ValueError):
        instance.with_tax_grid_step(0.0)
    # A theta coarser than the whole tax span would collapse the grid to a single point.
    with pytest.raises(ValueError):
        instance.with_tax_grid_step(1.0)
