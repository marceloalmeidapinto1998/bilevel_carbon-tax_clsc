"""Unit tests for the exhaustive grid-enumeration baseline (Exp8).

`enumerate_tax_grid` is DBP's benchmark opponent: solve the fixed-tax lexicographic follower at
every grid point and report the same lexmin(emissions, tax_index) quantity DBP's own loop reports,
so the two methods are compared on identical terms. These tests stub out
`solve_fixed_tax_lexicographic` (no Gurobi) to pin the pure-Python control flow: budget expiry,
incumbent selection, and the exact/censored distinction.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from clsc.models.subproblems import SolveResult
from clsc.solvers import enumeration as enum_mod
from clsc.solvers.dbp_lex import SubproblemStatusError


def _instance(*, lower=0, upper=9, scale_factor=1e-4) -> SimpleNamespace:
    return SimpleNamespace(
        iter_tax_index=lambda: range(lower, upper + 1),
        scale_factor=scale_factor,
    )


def _result(tax_index: int, emissions: float, *, cost: float = 1.0, status="OPTIMAL") -> SolveResult:
    return SolveResult(
        status_code=2, status_name=status, has_solution=(status != "FAILED"),
        objective_value=cost, cost=cost, emissions=emissions, follower_objective=cost,
        tax_index=tax_index, mip_gap=1e-6, runtime=0.1, variable_values={"x": float(tax_index)},
    )


def test_visits_every_grid_point_when_unbudgeted(monkeypatch) -> None:
    # Monotone non-increasing emissions, as H1.3 predicts.
    emissions_by_index = {i: 100.0 - i for i in range(10)}
    monkeypatch.setattr(
        enum_mod, "solve_fixed_tax_lexicographic",
        lambda *a, tax_index, **kw: _result(tax_index, emissions_by_index[tax_index]),
    )

    result = enum_mod.enumerate_tax_grid(_instance(upper=9), _instance(upper=9))

    assert result.termination_reason == "exhausted"
    assert result.exact is True
    assert result.points_visited == result.points_total == 10
    # Smallest emissions is at the largest index (99.0 - 9 = 91.0)... i.e. index 9.
    assert result.incumbent.tax_index == 9
    assert result.incumbent.emissions == pytest.approx(91.0)


def test_stops_at_the_wall_clock_cap_and_keeps_the_best_incumbent_so_far(monkeypatch) -> None:
    calls = []

    def fake_solve(*a, tax_index, **kw):
        calls.append(tax_index)
        if len(calls) > 3:
            # Simulate the budget having expired between calls: the NEXT solve would exceed it.
            raise AssertionError("should not be called past the budget")
        return _result(tax_index, 100.0 - tax_index)

    monkeypatch.setattr(enum_mod, "solve_fixed_tax_lexicographic", fake_solve)

    # A budget object that reports "expired" starting on the 4th check.
    real_budget_cls = enum_mod._WallClockBudget
    calls_to_expired = {"n": 0}

    class FakeBudget(real_budget_cls):
        def expired(self):
            calls_to_expired["n"] += 1
            return calls_to_expired["n"] > 3

    monkeypatch.setattr(enum_mod, "_WallClockBudget", FakeBudget)

    result = enum_mod.enumerate_tax_grid(_instance(upper=9), _instance(upper=9), wall_clock_cap=1.0)

    assert result.termination_reason == "wall_clock_cap"
    assert result.exact is False
    assert result.points_visited == 3
    assert result.points_total == 10
    # Best of the 3 visited (indices 0,1,2 -> emissions 100,99,98): index 2.
    assert result.incumbent.tax_index == 2


def test_tie_break_prefers_the_smaller_tax_at_equal_emissions(monkeypatch) -> None:
    # A genuine plateau: emissions floor reached at index 3 and unchanged afterward.
    emissions_by_index = {0: 100.0, 1: 80.0, 2: 50.0, 3: 50.0, 4: 50.0, 5: 50.0}
    monkeypatch.setattr(
        enum_mod, "solve_fixed_tax_lexicographic",
        lambda *a, tax_index, **kw: _result(tax_index, emissions_by_index[tax_index]),
    )

    result = enum_mod.enumerate_tax_grid(_instance(upper=5), _instance(upper=5))

    assert result.exact is True
    # Same selection rule DBP's own loop uses: the LEFT edge of the plateau (the first index that
    # reaches the floor, index 2), not the last point visited -- this is the exact quantity the
    # the enumeration-benchmark comparison needs to match against DBP's own tau*.
    assert result.incumbent.tax_index == 2
    assert result.incumbent.emissions == pytest.approx(50.0)


def test_a_subproblem_timeout_stops_the_scan_rather_than_accepting_a_bad_point(monkeypatch) -> None:
    monkeypatch.setattr(
        enum_mod, "solve_fixed_tax_lexicographic",
        lambda *a, tax_index, **kw: _result(tax_index, 100.0, status="TIME_LIMIT"),
    )

    with pytest.raises(SubproblemStatusError):
        # index 0 times out immediately and no incumbent was ever set -> no result to report.
        enum_mod.enumerate_tax_grid(_instance(upper=3), _instance(upper=3))


def test_follower_seconds_are_accumulated_across_visited_points(monkeypatch) -> None:
    monkeypatch.setattr(
        enum_mod, "solve_fixed_tax_lexicographic",
        lambda *a, tax_index, **kw: _result(tax_index, 100.0 - tax_index),
    )

    result = enum_mod.enumerate_tax_grid(_instance(upper=2), _instance(upper=2))

    assert result.follower_seconds_total == pytest.approx(0.3)  # 3 points x 0.1s each
    assert len(result.grid_records) == 3


# --- regression: plateau tie tolerance (found on real data, STD_I17_M4_T6) --------------------

def test_tie_tolerance_survives_cumulative_solve_noise_on_a_long_scan(monkeypatch) -> None:
    """Pins the enumeration-benchmark bug found on STD_I17_M4_T6: emissions=E* held from index 1264 to 2000, but
    ~1e-8-relative Gurobi solve noise per point crossed the OLD near-machine tolerance (eps=1e-7)
    around index 1900, dragging the reported tau* out from 126.4 to 190.3 USD/t -- while DBP's own
    Phase-2 bisection, visiting O(log n) points instead of O(n), never saw enough accumulated noise
    to drift. The campaign-matching PLATEAU_RELATIVE_GAP=1e-4 must not drift the same way."""
    import random

    random.seed(0)
    base = 90223120.0
    # Emissions flat within noise from index 1264 onward: +-a few units, matching the real trace's
    # observed spread (std ~2, max drift ~10 over 737 points).
    noisy_plateau = {i: base + random.uniform(-5.0, 5.0) for i in range(1264, 2001)}
    emissions_by_index = {i: 200_000_000.0 - 80_000.0 * i for i in range(0, 1264)}  # descending
    emissions_by_index.update(noisy_plateau)
    emissions_by_index[1264] = base  # the TRUE left edge, exact

    monkeypatch.setattr(
        enum_mod, "solve_fixed_tax_lexicographic",
        lambda *a, tax_index, **kw: _result(tax_index, emissions_by_index[tax_index]),
    )

    result = enum_mod.enumerate_tax_grid(_instance(upper=2000), _instance(upper=2000))

    assert result.exact is True
    assert result.incumbent.tax_index == 1264, (
        "incumbent drifted past the true left edge -- the tie tolerance is too tight for this "
        f"scan length (got {result.incumbent.tax_index}, expected 1264)"
    )


def test_is_better_on_plateau_matches_dbp_phase2_tolerance_formula() -> None:
    from clsc.config.gap_tol import DEFAULT

    from clsc.solvers.dbp_lex import IncumbentSolution as Inc

    incumbent = Inc(tax_index=100, cost=1.0, emissions=1_000_000.0, follower_objective=1.0)
    tol = max(DEFAULT.eps, enum_mod.PLATEAU_RELATIVE_GAP * abs(incumbent.emissions))

    just_inside = Inc(tax_index=50, cost=1.0, emissions=1_000_000.0 + tol * 0.5, follower_objective=1.0)
    just_outside = Inc(tax_index=50, cost=1.0, emissions=1_000_000.0 + tol * 2.0, follower_objective=1.0)

    # Within tolerance and a smaller tax -> accepted (same plateau, prefer the smaller tax).
    assert enum_mod._is_better_on_plateau(just_inside, incumbent, relative_gap=enum_mod.PLATEAU_RELATIVE_GAP)
    # Outside tolerance -> genuinely worse (higher emissions), not accepted.
    assert not enum_mod._is_better_on_plateau(just_outside, incumbent, relative_gap=enum_mod.PLATEAU_RELATIVE_GAP)
