"""Regression tests: one carbon-tax grid across every execution mode (campaign_01).

The bug: bilevel runs were solved on the fine grid (1e-4 USD/kg per index) while the in-process
`fixed_tax` runs used the instances' native coarse grid (1e-2), so index 80 meant 8 USD/t in one
mode and 800 USD/t in the other. Nothing crashed -- Exp1's invariance probes and Exp5's policy
rules were simply being compared against a bilevel tau* on a 100x different scale, and Exp5's P4
would have fed a fine-grid plateau index into a coarse-grid follower.

Pinned here: design points state fine-grid indices, the orchestrator re-grids every execution
mode onto the point's own step, and the aggregator reports a RATE rather than recomputing one
from a global constant.
"""

from __future__ import annotations

import pytest

from clsc.analysis.campaign_01.aggregate import _effective_tax_usd_per_kg
from clsc.campaign import orchestrator as campaign
from clsc.campaign.designs import exp1_verification, exp5_leader_value, exp7_policy_calibration
from clsc.campaign.designs._common import (
    COARSE_SCALE_FACTOR,
    FINE_CEILING_INDEX,
    FINE_SCALE_FACTOR,
    TAX_CEILING_USD_PER_KG,
    fine_index,
)


def test_the_two_grids_span_the_same_real_tax_range() -> None:
    # This is what makes a RATE comparable across grids while an INDEX is not.
    assert FINE_CEILING_INDEX * FINE_SCALE_FACTOR == pytest.approx(TAX_CEILING_USD_PER_KG)
    assert 20 * COARSE_SCALE_FACTOR == pytest.approx(TAX_CEILING_USD_PER_KG)
    assert fine_index(TAX_CEILING_USD_PER_KG) == FINE_CEILING_INDEX


def test_fine_index_rejects_rates_off_the_grid() -> None:
    with pytest.raises(ValueError):
        fine_index(TAX_CEILING_USD_PER_KG * 2)


@pytest.mark.parametrize("module", [exp1_verification, exp5_leader_value])
def test_every_fixed_tax_design_point_is_on_the_fine_grid(module) -> None:
    try:
        points = module.build_design_matrix()
    except TypeError:  # two-phase modules take results_root
        points = module.build_design_matrix(results_root=None)

    fixed_tax = [p for p in points if p.execution_mode == "fixed_tax"]
    assert fixed_tax, "expected fixed-tax points to guard"
    for point in fixed_tax:
        # A coarse-grid index (0..20) would pass a naive bounds check, so assert the RATE:
        # anything still on the old grid lands at 1/100th of its intended tax.
        rate = point.fixed_tax_index * FINE_SCALE_FACTOR
        assert 0.0 <= rate <= TAX_CEILING_USD_PER_KG
        assert point.scale_factor is None  # None = campaign fine grid


def test_exp7_frontier_spans_the_fine_grid() -> None:
    # Exp7's fixed-tax points only materialise in phase 2 (after rho* is solved), so the grid is
    # asserted on the constant the phase-2 builder consumes.
    indices = exp7_policy_calibration.FRONTIER_TAX_INDICES
    assert len(indices) == 11
    assert indices[0] == 0
    assert indices[-1] == FINE_CEILING_INDEX


def test_exp1_invariant_probes_sit_at_their_intended_rates() -> None:
    intended = exp1_verification.INVARIANT_TAX_RATES_USD_PER_KG
    actual = [idx * FINE_SCALE_FACTOR for idx in exp1_verification.INVARIANT_TAX_INDICES]
    assert actual == pytest.approx(list(intended))


def test_exp5_policy_rules_bracket_the_full_grid() -> None:
    # P1 is "the tax ceiling" -- on the coarse grid its index 20 was 1% of the ceiling here.
    assert exp5_leader_value.POLICY_RULES["P0_no_tax"] == 0
    assert exp5_leader_value.POLICY_RULES["P1_ceiling"] == FINE_CEILING_INDEX
    assert exp5_leader_value.POLICY_RULES["P2_mid"] == FINE_CEILING_INDEX // 2


def test_orchestrator_grid_step_is_fine_unless_the_variant_asks_otherwise() -> None:
    from clsc.campaign.designs._common import DesignPoint

    base = dict(
        experiment_id="exp5", design_point_id="d", run_code="r", base_instance_id="STD_I17_M4_T3",
        execution_mode="fixed_tax", per_subproblem_time_limit_seconds=600.0,
        per_run_wall_clock_cap_seconds=3600.0,
    )
    assert campaign._tax_grid_step(DesignPoint(**base)) == FINE_SCALE_FACTOR
    # A4 (coarse grid) is the one variant that deliberately overrides it.
    a4 = DesignPoint(**base, scale_factor=COARSE_SCALE_FACTOR)
    assert campaign._tax_grid_step(a4) == COARSE_SCALE_FACTOR


def test_aggregate_prefers_the_recorded_rate_over_any_recomputation() -> None:
    # Same index, different grids -> different rates. A global constant cannot get both right.
    fine = {"leader_tax": 80, "tax_grid_step_usd_per_kg": FINE_SCALE_FACTOR}
    coarse = {"leader_tax": 80, "tax_grid_step_usd_per_kg": COARSE_SCALE_FACTOR}
    assert _effective_tax_usd_per_kg(fine) == pytest.approx(0.008)
    assert _effective_tax_usd_per_kg(coarse) == pytest.approx(0.8)

    # The solver's own reported rate wins over anything derived.
    assert _effective_tax_usd_per_kg({**fine, "effective_tax_usd_per_kg": 0.1673}) == 0.1673

    # Unknown grid -> absent, never a guess on the wrong scale.
    assert _effective_tax_usd_per_kg({"leader_tax": 80}) is None
