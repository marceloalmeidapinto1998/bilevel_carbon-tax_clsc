"""Experiment-3 DBP ablation switches (A2/A3/A5): each weakens one component but must leave the
certified emissions optimum unchanged (docs/Experimental_Plan.md §5, H3.2/H3.3/H3.5).

A1 (no Phase-2 bisection) and A4 (coarse grid) are exercised elsewhere: A1 via refine_min_tax
(pre-existing), A4 via the tax-grid scale factor (not a solver flag).
"""
from __future__ import annotations

import math

import pytest

from clsc.solvers.dbp_lex import solve_bilevel_dbp_lex

pytestmark = pytest.mark.slow

INSTANCE = "data/instances/base/STD_I17_M4_T3.json"


def _emissions_close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-4, abs_tol=1.0)


@pytest.fixture(scope="module")
def reference():
    """Full DBP (M0) on the instance's native (coarse) grid — the reference optimum."""
    return solve_bilevel_dbp_lex(INSTANCE, mip_gap=1e-6, dbp_relative_gap=1e-4, threads=4)


@pytest.mark.parametrize("flag", ["use_lex_master_stage2", "use_warm_start", "use_incumbent_cut"])
def test_ablation_preserves_certified_optimum(reference, flag):
    variant = solve_bilevel_dbp_lex(
        INSTANCE, mip_gap=1e-6, dbp_relative_gap=1e-4, threads=4, **{flag: False},
    )
    assert variant.exact, f"{flag}=False must still terminate exact"
    assert _emissions_close(variant.incumbent.emissions, reference.incumbent.emissions), (
        f"{flag}=False changed the certified emissions optimum: "
        f"{variant.incumbent.emissions} vs {reference.incumbent.emissions}"
    )


def test_full_method_is_exact(reference):
    assert reference.exact
    assert reference.termination_reason == "relative_gap"


def test_seed_is_solution_invariant():
    """Gurobi Seed changes the search path (H1.4 seed-invariance witness), not the reported optimum."""
    a = solve_bilevel_dbp_lex(INSTANCE, mip_gap=1e-6, dbp_relative_gap=1e-4, threads=4, seed=1)
    b = solve_bilevel_dbp_lex(INSTANCE, mip_gap=1e-6, dbp_relative_gap=1e-4, threads=4, seed=2)
    assert _emissions_close(a.incumbent.emissions, b.incumbent.emissions)
