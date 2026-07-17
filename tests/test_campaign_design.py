from __future__ import annotations

import pytest

from tools.experiments.doe_campaign_01.design.fractional_factorial import fractional_factorial_signs
from tools.experiments.doe_campaign_01.design.full_factorial import full_factorial_signs
from tools.experiments.doe_campaign_01.design.frontier_sweep import tax_grid
from tools.experiments.doe_campaign_01.design.response_surface import dense_levels
from tools.experiments.doe_campaign_01.design.robustness import TOLERANCE_SETTINGS, seed_grid


# ---------------------------------------------------------------------------
# full_factorial_signs
# ---------------------------------------------------------------------------

def test_full_factorial_produces_all_2k_runs() -> None:
    factors = ("a", "b", "c")
    runs = full_factorial_signs(factors)
    assert len(runs) == 2 ** len(factors)


def test_full_factorial_all_values_are_plus_minus_one() -> None:
    for run in full_factorial_signs(("x", "y", "z")):
        assert set(run) == {"x", "y", "z"}
        assert all(v in (-1, 1) for v in run.values())


def test_full_factorial_all_combinations_are_distinct() -> None:
    runs = full_factorial_signs(("a", "b", "c"))
    unique = {frozenset(r.items()) for r in runs}
    assert len(unique) == len(runs)


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


def test_fractional_factorial_has_fewer_runs_than_full_for_large_k() -> None:
    # For k=6, full factorial = 64 runs; fold-over fractional < 64
    factors = tuple(f"f{i}" for i in range(6))
    frac_runs = fractional_factorial_signs(factors)
    full_runs = full_factorial_signs(factors)
    assert len(frac_runs) < len(full_runs)


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


# ---------------------------------------------------------------------------
# dense_levels
# ---------------------------------------------------------------------------

def test_dense_levels_contains_baseline() -> None:
    levels = dense_levels(0.7, 1.3, n_levels=9, baseline=1.0)
    assert 1.0 in levels


def test_dense_levels_has_at_least_n_levels() -> None:
    levels = dense_levels(0.7, 1.3, n_levels=9)
    assert len(levels) >= 9


def test_dense_levels_stays_within_bounds() -> None:
    levels = dense_levels(0.5, 1.5, n_levels=7)
    assert min(levels) >= 0.5
    assert max(levels) <= 1.5


def test_dense_levels_is_sorted() -> None:
    levels = dense_levels(0.7, 1.3, n_levels=9)
    assert levels == sorted(levels)


# ---------------------------------------------------------------------------
# seed_grid
# ---------------------------------------------------------------------------

def test_seed_grid_returns_correct_count() -> None:
    assert len(seed_grid(n_seeds=4)) == 4


def test_seed_grid_seeds_are_sequential_from_base_plus_one() -> None:
    assert seed_grid(n_seeds=4, seed_base=0) == [1, 2, 3, 4]
    assert seed_grid(n_seeds=3, seed_base=10) == [11, 12, 13]


def test_seed_grid_seeds_are_unique() -> None:
    seeds = seed_grid(n_seeds=8, seed_base=100)
    assert len(set(seeds)) == 8


# ---------------------------------------------------------------------------
# TOLERANCE_SETTINGS
# ---------------------------------------------------------------------------

def test_tolerance_settings_are_ordered_tight_to_loose() -> None:
    mip_gaps = [s.mip_gap for s in TOLERANCE_SETTINGS]
    assert mip_gaps == sorted(mip_gaps)


def test_tolerance_settings_include_default_config_values() -> None:
    from clsc.config.gap_tol import DEFAULT
    default_setting = next((s for s in TOLERANCE_SETTINGS if s.label == "default"), None)
    assert default_setting is not None
    assert default_setting.mip_gap == DEFAULT.mip_gap
    assert default_setting.dbp_relative_gap == DEFAULT.dbp_relative_gap
