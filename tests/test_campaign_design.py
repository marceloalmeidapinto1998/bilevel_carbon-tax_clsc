"""Unit tests for the DOE primitives campaign_01 actually uses.

`full_factorial_signs`, `dense_levels` (response_surface), `seed_grid`/`TOLERANCE_SETTINGS`
(robustness), and `epsilon_grid` (epsilon_sweep) were removed together with their modules: none
was referenced anywhere outside its own definition file (dead code left over from an earlier
campaign design). `fractional_factorial_signs` (Experiment 4's screening design) and `tax_grid`
(Experiment 3's frontier) are both live and covered here.
"""
from __future__ import annotations

import pytest

from clsc.campaign.doe.fractional_factorial import fractional_factorial_signs
from clsc.campaign.doe.frontier_sweep import tax_grid


# ---------------------------------------------------------------------------
# fractional_factorial_signs
# ---------------------------------------------------------------------------

def test_fractional_factorial_run_count_is_power_of_two() -> None:
    factors = tuple(f"f{i}" for i in range(6))
    runs = fractional_factorial_signs(factors)
    n = len(runs)
    assert n > 0 and (n & (n - 1)) == 0, f"Run count {n} is not a power of 2"


def test_fractional_factorial_all_values_are_plus_minus_one() -> None:
    factors = ("a", "b", "c", "d", "e")
    runs = fractional_factorial_signs(factors)
    for run in runs:
        assert set(run) == set(factors)
        assert all(v in (-1, 1) for v in run.values())


def test_fractional_factorial_run_count_matches_experiment_4s_8_factor_design() -> None:
    # Pinned so a change to the fold-over construction is caught here, not by a surprise
    # design-matrix row count in exp4_sensitivity.
    factors = tuple(f"f{i}" for i in range(8))
    assert len(fractional_factorial_signs(factors)) == 32


def test_fractional_factorial_requires_at_least_two_factors() -> None:
    with pytest.raises(ValueError):
        fractional_factorial_signs(("only_one",))


# ---------------------------------------------------------------------------
# tax_grid
# ---------------------------------------------------------------------------

def test_tax_grid_produces_correct_sequence() -> None:
    grid = tax_grid(20, n_points=11, step=2)
    assert grid == list(range(0, 21, 2))
    assert len(grid) == 11
    assert grid[0] == 0
    assert grid[-1] == 20


def test_tax_grid_starts_at_zero() -> None:
    assert tax_grid(10, n_points=6, step=2)[0] == 0


def test_tax_grid_raises_when_grid_does_not_reach_ceiling() -> None:
    with pytest.raises(ValueError, match="does not reach"):
        tax_grid(20, n_points=5, step=2)  # grid ends at 8, not 20
