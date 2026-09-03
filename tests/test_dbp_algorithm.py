"""Correctness of the DBP algorithm itself: its certificate, its ablation components, its
min-tax confirmation stopping rule, and one whole-pipeline sanity pin.

Per-coefficient model correctness lives in `test_subproblems.py`; this file is about whether the
*procedure* built on top of a correct model is itself correct:

  * **Certificate.** The reported lower bound must never exceed the reported upper bound, whatever
    the internals do -- `relative_optimality_gap` clips a negative gap to zero instead of
    surfacing an inversion, so this has to be checked directly.
  * **Ablation (A1-A5).** Each weakens one DBP component. A1 (no in-loop min-tax confirmation) and
    A4 (coarse grid) are claim-carrying -- they change the certified guarantee -- and are exercised
    via the campaign's own design points (`clsc.campaign.designs.exp2_computational_performance`,
    A4 no longer scheduled), not here. A2 (no lexicographic Stage-2 master), A3 (no warm start),
    A5 (no incumbent cut) are efficiency-only: removing any of them must leave the certified
    emissions optimum unchanged.
  * **Min-tax confirmation.** An earlier design closed the DBP's bound interval over emissions
    alone and recovered tax-minimality afterwards with a bolt-on bisection (valid only when
    physical emissions are monotone in the tax) or an O(grid) ascending scan. `confirm_min_tax`
    replaces both with a single in-loop mechanism (Soares et al. 2021's Lemma-3 stopping rule) that
    needs no monotonicity assumption, so it is validated against exhaustive enumeration on both an
    undiscounted and a discounted instance.
  * **Golden-master toy solve.** The six toy instances in `clsc.campaign.toy` are described as
    "hand-verifiable," but nothing pinned their solved values in a fast regression test -- they
    were only ever checked once, manually, during a full campaign run. This solves the smallest
    one (`STD_TOY1`: 1 supplier/factory/warehouse/retailer, 1 product, 1 raw material, 1 period)
    and pins its certified result, so a change to the model or the algorithm that moves the
    simplest possible instance's answer is caught in under a second, not discovered mid-campaign.
"""
from __future__ import annotations

import math

import pytest

from clsc.campaign.toy import TOY_SPECS_BY_NAME, build_toy_instance
from clsc.generator import ArcConnectivityConfig, GeneratorConfig, generate_instance
from clsc.generator.benchmark import build_base_benchmark_specs
from clsc.generator.instance import generate_instance as generate_instance_from_config
from clsc.models.instance import InstanceData
from clsc.models.subproblems import is_discounted
from clsc.solvers.dbp_lex import solve_bilevel_dbp_lex
from clsc.solvers.enumeration import enumerate_tax_grid


def _emissions_close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-4, abs_tol=1.0)


# ===========================================================================
# Certificate
# ===========================================================================

@pytest.mark.gurobi
@pytest.mark.slow
def test_solve_bilevel_dbp_lex_lower_bound_never_exceeds_upper_bound() -> None:
    """General safety net for the certified-gap framework: whatever the solver internals do, the
    reported lower bound must never exceed the reported upper bound (beyond a tiny numerical
    allowance) -- this is exactly the invariant a Stage-2 LB leak (or any other cross-model
    floating-point drift) could otherwise violate silently, since relative_optimality_gap clips
    negative gaps to zero instead of surfacing the inversion.
    """
    instance = generate_instance(
        GeneratorConfig(
            suppliers=1, factories=1, warehouses=1, retailers=1,
            products=1, raw_materials=1,
            production_technologies=1, remanufacturing_technologies=1,
            periods=2, seed=59, instance_name="tiny_lb_ub_invariant_case",
            tax_lower=0.0, tax_upper=20.0,
            connectivity=ArcConnectivityConfig(
                sf_neighbors=1, fw_neighbors=1, wr_neighbors=1, rf_neighbors=1,
            ),
        ),
    )

    result = solve_bilevel_dbp_lex(InstanceData.from_dict(instance.to_dict()))

    tolerance = max(1e-6, 1e-6 * abs(result.upper_bound))
    assert result.lower_bound <= result.upper_bound + tolerance


# ===========================================================================
# Ablation (A2/A3/A5 -- efficiency only; A1 is exercised via the campaign)
# ===========================================================================

INSTANCE = "data/instances/base/STD_I17_M4_T3.json"


@pytest.fixture(scope="module")
def reference():
    """Full DBP (M0) on the instance's native (coarse) grid -- the reference optimum."""
    return solve_bilevel_dbp_lex(INSTANCE, mip_gap=1e-6, dbp_relative_gap=1e-4, threads=4)


@pytest.mark.slow
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


@pytest.mark.slow
def test_full_method_is_exact(reference):
    assert reference.exact
    assert reference.termination_reason == "relative_gap"


@pytest.mark.slow
def test_seed_is_solution_invariant():
    """Gurobi Seed changes the search path (H1.4 seed-invariance witness), not the reported optimum."""
    a = solve_bilevel_dbp_lex(INSTANCE, mip_gap=1e-6, dbp_relative_gap=1e-4, threads=4, seed=1)
    b = solve_bilevel_dbp_lex(INSTANCE, mip_gap=1e-6, dbp_relative_gap=1e-4, threads=4, seed=2)
    assert _emissions_close(a.incumbent.emissions, b.incumbent.emissions)


# ===========================================================================
# Min-tax confirmation (Soares et al. 2021, Lemma 3)
# ===========================================================================

ARCHIVED_UNDISCOUNTED = "data/instances/base/STD_I17_M4_T3.json"
_CONFIRM_SOLVER = dict(mip_gap=1e-6, dbp_relative_gap=1e-4, threads=4)


@pytest.fixture(scope="module")
def confirmed():
    return solve_bilevel_dbp_lex(ARCHIVED_UNDISCOUNTED, confirm_min_tax=True, **_CONFIRM_SOLVER)


@pytest.fixture(scope="module")
def enumerated_undiscounted():
    return enumerate_tax_grid(
        ARCHIVED_UNDISCOUNTED, InstanceData.from_file(ARCHIVED_UNDISCOUNTED),
        mip_gap=1e-6, threads=4,
    )


@pytest.fixture(scope="module")
def discounted_instance() -> InstanceData:
    """Freshly generated, so it carries interest_rate: the case that motivated dropping the
    monotonicity-dependent bisection."""
    spec = next(s for s in build_base_benchmark_specs(seed_base=9) if s.name == "STD_I17_M4_T3")
    instance = InstanceData.from_dict(generate_instance_from_config(spec.to_config()).to_dict())
    assert is_discounted(instance.parameters)
    return instance


@pytest.fixture(scope="module")
def confirmed_discounted(discounted_instance):
    return solve_bilevel_dbp_lex(discounted_instance, confirm_min_tax=True, **_CONFIRM_SOLVER)


@pytest.fixture(scope="module")
def enumerated_discounted(discounted_instance):
    return enumerate_tax_grid(discounted_instance, discounted_instance, mip_gap=1e-6, threads=4)


@pytest.mark.slow
def test_confirmation_terminates_exact(confirmed):
    assert confirmed.exact
    assert confirmed.termination_reason == "relative_gap"


@pytest.mark.slow
def test_confirmation_matches_exhaustive_enumeration_undiscounted(confirmed, enumerated_undiscounted):
    assert enumerated_undiscounted.exact
    assert _emissions_close(confirmed.incumbent.emissions, enumerated_undiscounted.incumbent.emissions)
    assert confirmed.incumbent.tax_index == enumerated_undiscounted.incumbent.tax_index


@pytest.mark.slow
def test_confirmation_matches_exhaustive_enumeration_discounted(confirmed_discounted, enumerated_discounted):
    assert confirmed_discounted.exact
    assert enumerated_discounted.exact
    assert _emissions_close(confirmed_discounted.incumbent.emissions, enumerated_discounted.incumbent.emissions)
    assert confirmed_discounted.incumbent.tax_index == enumerated_discounted.incumbent.tax_index


@pytest.mark.slow
def test_confirmation_degrades_silently_without_the_master_stage2():
    """A2 (no lexicographic Stage-2 master) leaves no Stage-2 proposal to confirm, so
    confirm_min_tax=True has nothing to do there: the run still terminates with a certified
    emissions optimum, just without a certified minimal tax. No exception -- this is a
    deterministic consequence of disabling use_lex_master_stage2, not user error.
    """
    result = solve_bilevel_dbp_lex(
        ARCHIVED_UNDISCOUNTED, confirm_min_tax=True, use_lex_master_stage2=False, **_CONFIRM_SOLVER,
    )
    assert result.exact
    assert result.termination_reason == "relative_gap"


# ===========================================================================
# Golden-master toy solve
# ===========================================================================

@pytest.mark.gurobi
@pytest.mark.slow
def test_toy1_solve_matches_its_pinned_certified_result() -> None:
    """STD_TOY1 (1 supplier/factory/warehouse/retailer, 1 product, 1 raw material, 1 period) is
    the smallest instance the generator can produce. Its certified (cost, emissions, tax_index)
    are pinned from an actual solve, captured 2026-09-02; a change to the model or the algorithm
    that moves the simplest possible instance's answer is caught here, fast, rather than
    discovered mid-campaign.
    """
    spec = TOY_SPECS_BY_NAME["STD_TOY1"]
    instance = InstanceData.from_dict(build_toy_instance(spec).to_dict())

    result = solve_bilevel_dbp_lex(instance, mip_gap=1e-6, dbp_relative_gap=1e-4, threads=4)

    assert result.exact
    assert result.termination_reason == "relative_gap"
    assert result.incumbent.tax_index == 0
    assert result.incumbent.cost == pytest.approx(160090.49045651997, rel=1e-6)
    assert result.incumbent.emissions == pytest.approx(3416671.8189322376, rel=1e-6)
