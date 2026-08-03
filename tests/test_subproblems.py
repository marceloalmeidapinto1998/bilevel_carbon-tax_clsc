from __future__ import annotations

from dataclasses import replace

import pytest
from gurobipy import GRB

from clsc.generator import ArcConnectivityConfig, GeneratorConfig, generate_instance
from clsc.config.gap_tol import DEFAULT
import clsc.models.subproblems as subproblems
from clsc.models.instance import InstanceData
from clsc.models.subproblems import (
    DbpFollowerCut,
    build_dbp_relaxation_master,
    build_fixed_tax_follower_master,
    lex_freeze_tolerance,
    solve_dbp_relaxation,
    solve_dbp_relaxation_lexicographic,
    solve_fixed_tax_lexicographic,
    validate_fixed_tax_solution,
    _dbp_cut_epsilon,
)


def _build_tiny_instance() -> InstanceData:
    generated = generate_instance(
        GeneratorConfig(
            suppliers=1,
            factories=1,
            warehouses=1,
            retailers=1,
            products=1,
            raw_materials=1,
            production_technologies=1,
            remanufacturing_technologies=1,
            periods=2,
            seed=53,
            instance_name="tiny_shared_model_case",
            tax_lower=0.0,
            tax_upper=0.2,
            connectivity=ArcConnectivityConfig(
                sf_neighbors=1,
                fw_neighbors=1,
                wr_neighbors=1,
                rf_neighbors=1,
            ),
        ),
    )
    return InstanceData.from_dict(generated.to_dict())


def _assert_matching_lex_results(actual, expected, *, tax_index: int) -> None:
    assert actual.status_code == GRB.OPTIMAL
    assert expected.status_code == GRB.OPTIMAL
    assert actual.tax_index == tax_index
    assert expected.tax_index == tax_index
    # DEFAULT.mip_gap is 1% (matching Tautenhain et al.'s stopping criterion, see gap_tol.py) --
    # Gurobi accepts the first incumbent within that gap of the true optimum and stops, so it does
    # not certify a single canonical optimal solution. A fresh solve and a warm-started solve over
    # the reused model can explore the B&B tree differently and land on two different (both valid)
    # incumbents, each within its own reported gap of the true optimum but up to ~2*mip_gap apart
    # from each other -- empirically confirmed (2026-07-08): one run closes to gap 0% while the
    # other stops at gap ~0.67%, giving a ~0.16% difference in objective_value. The tolerance below
    # reflects that band rather than assuming bit-for-bit reproducibility.
    band = 2.0 * DEFAULT.mip_gap
    assert actual.objective_value == pytest.approx(expected.objective_value, rel=band)
    assert actual.cost == pytest.approx(expected.cost, rel=band)
    assert actual.emissions == pytest.approx(expected.emissions, rel=band)
    assert actual.follower_objective == pytest.approx(expected.follower_objective, rel=band)
    # Warm-started and cold solves can reach the configured MIP-gap target
    # via different branch-and-bound paths, so the exact reported gap is not
    # expected to match bit-for-bit -- only that both are within tolerance.
    assert actual.mip_gap <= DEFAULT.mip_gap
    assert expected.mip_gap <= DEFAULT.mip_gap
    assert actual.lex_primary_mip_gap <= DEFAULT.mip_gap
    assert expected.lex_primary_mip_gap <= DEFAULT.mip_gap
    assert actual.lex_secondary_mip_gap <= DEFAULT.mip_gap
    assert expected.lex_secondary_mip_gap <= DEFAULT.mip_gap
    # Not compared variable-by-variable: two incumbents that both fall within a nonzero MIP gap of
    # the true optimum need not share the same nonzero-variable support (e.g. a different but
    # equally-within-gap transport routing) even when their objective values are close -- see the
    # `band` comment above. Presence of a captured solution is what the reuse mechanism needs to
    # guarantee; exact solution-structure reproducibility is not a valid invariant once mip_gap > 0.
    assert actual.variable_values is not None
    assert expected.variable_values is not None


@pytest.mark.gurobi
@pytest.mark.slow
def test_solve_fixed_tax_lexicographic_reuses_follower_master_across_tax_index_values() -> None:
    instance = _build_tiny_instance()
    follower_master = build_fixed_tax_follower_master(instance)
    reused_model = follower_master.artifacts.model

    lower_tax_index = instance.lower_tax_index
    upper_tax_index = instance.upper_tax_index

    expected_lower = solve_fixed_tax_lexicographic(instance, lower_tax_index, capture_solution=True)
    reused_lower = solve_fixed_tax_lexicographic(follower_master, lower_tax_index, capture_solution=True)
    _assert_matching_lex_results(reused_lower, expected_lower, tax_index=lower_tax_index)
    assert follower_master.artifacts.model is reused_model

    expected_upper = solve_fixed_tax_lexicographic(instance, upper_tax_index, capture_solution=True)
    reused_upper = solve_fixed_tax_lexicographic(
        follower_master,
        upper_tax_index,
        capture_solution=True,
        warm_start_values=reused_lower.variable_values,
    )
    _assert_matching_lex_results(reused_upper, expected_upper, tax_index=upper_tax_index)
    assert follower_master.artifacts.model is reused_model


@pytest.mark.gurobi
@pytest.mark.slow
def test_solve_fixed_tax_follower_drives_factory_area_from_throughput() -> None:
    instance = _build_tiny_instance()
    solved = solve_fixed_tax_lexicographic(instance, instance.lower_tax_index, capture_solution=True)

    assert solved.status_code == GRB.OPTIMAL
    assert solved.variable_values is not None

    factory = instance.sets["F"][0]
    product = instance.sets["P"][0]
    apur_p = instance.parameters["apur_p"][product]
    installed = solved.variable_values[f"YC[{factory}]"]

    for period in instance.sets["T"]:
        produced = sum(
            value
            for name, value in solved.variable_values.items()
            if (name.startswith(f"q[{product},{factory},") or name.startswith(f"rem[{product},{factory},"))
            and name.endswith(f",{period}]")
        )
        assert installed >= apur_p * produced - 1e-6


@pytest.mark.gurobi
@pytest.mark.slow
def test_validate_fixed_tax_solution_accepts_tiny_bound_noise() -> None:
    instance = _build_tiny_instance()
    solved = solve_fixed_tax_lexicographic(instance, instance.lower_tax_index, capture_solution=True)

    assert solved.status_code == GRB.OPTIMAL
    assert solved.variable_values is not None

    follower_master = build_fixed_tax_follower_master(instance)
    follower_master.artifacts.model.update()
    variable = next(
        variable
        for variable in follower_master.artifacts.model.getVars()
        if (
            variable.VType == GRB.CONTINUOUS
            and float(variable.LB) == 0.0
            and solved.variable_values.get(variable.VarName, 0.0) == 0.0
        )
    )

    noisy_values = dict(solved.variable_values)
    noisy_values[variable.VarName] = -2.5e-7

    recomputed = validate_fixed_tax_solution(
        instance,
        tax_index=instance.lower_tax_index,
        variable_values=noisy_values,
    )

    assert recomputed.status_code == GRB.OPTIMAL


@pytest.mark.gurobi
@pytest.mark.slow
def test_validate_fixed_tax_solution_accepts_tiny_integer_noise() -> None:
    instance = _build_tiny_instance()
    solved = solve_fixed_tax_lexicographic(instance, instance.lower_tax_index, capture_solution=True)

    assert solved.status_code == GRB.OPTIMAL
    assert solved.variable_values is not None

    follower_master = build_fixed_tax_follower_master(instance)
    follower_master.artifacts.model.update()
    variable = next(
        variable
        for variable in follower_master.artifacts.model.getVars()
        if (
            variable.VType != GRB.CONTINUOUS
            and solved.variable_values.get(variable.VarName, 0.0) == 0.0
        )
    )

    noisy_values = dict(solved.variable_values)
    noisy_values[variable.VarName] = 8e-6

    recomputed = validate_fixed_tax_solution(
        instance,
        tax_index=instance.lower_tax_index,
        variable_values=noisy_values,
    )

    assert recomputed.status_code == GRB.OPTIMAL


@pytest.mark.gurobi
@pytest.mark.slow
def test_solve_dbp_relaxation_lexicographic_picks_smallest_tied_tax_index() -> None:
    """With no cuts yet, every tax_index ties the (cut-free) emissions minimum,
    so the master's Stage 2 (min tax_index among Stage-1 emissions-minimisers)
    must deterministically select the smallest tax index -- the whole point
    of solve_dbp_relaxation_lexicographic, replacing the post-hoc bisection
    tax-tiebreak search. The single-stage solve has no such guarantee, so it
    is not asserted to return any particular tax_index, only the same Stage-1
    emissions value.
    """
    instance = _build_tiny_instance()
    master = build_dbp_relaxation_master(instance)

    single_stage = solve_dbp_relaxation(master)
    assert single_stage.status_code == GRB.OPTIMAL

    two_stage = solve_dbp_relaxation_lexicographic(master)
    assert two_stage.status_code == GRB.OPTIMAL
    assert two_stage.tax_index == instance.lower_tax_index
    assert two_stage.emissions == pytest.approx(single_stage.emissions)
    assert two_stage.lex_primary_mip_gap is not None
    assert two_stage.lex_secondary_mip_gap is not None
    assert two_stage.lex_primary_mip_gap <= DEFAULT.mip_gap
    assert two_stage.lex_secondary_mip_gap <= DEFAULT.mip_gap


@pytest.mark.gurobi
@pytest.mark.slow
def test_solve_dbp_relaxation_lexicographic_reports_stage1_emissions_under_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stage 2 only enforces emissions <= Stage-1 optimum + freeze tolerance
    (an inequality, not equality), so a smaller tax_index that is only
    reachable by spending some of that tolerance can make Stage 2's own
    solution land strictly above the Stage-1 optimum. lem:lb_validity only
    certifies the exact Stage-1 value as a valid lower bound, so the
    returned ``emissions`` must always be that value, never Stage 2's
    possibly-drifted one.

    This test forces that exact scenario: a synthetic constraint makes
    ``tax_index == lower_tax_index`` reachable only at
    ``stage1_optimum + delta`` (with ``delta`` inside the freeze
    tolerance), while every other tax_index stays free at the Stage-1
    optimum -- so Stage 2 has a genuine incentive to drift. The ordinary
    MIP gap is tightened for this test so that gap alone cannot also
    explain a few-kg-level mismatch and mask the effect under test.
    """
    monkeypatch.setattr(subproblems, "DEFAULT", replace(DEFAULT, mip_gap=1e-9))

    instance = _build_tiny_instance()
    master = build_dbp_relaxation_master(instance)

    natural = solve_dbp_relaxation(master)
    assert natural.status_code == GRB.OPTIMAL

    artifacts = master.artifacts
    model = artifacts.model
    emissions_total_var = artifacts.emissions_total_var
    tax_index_var = artifacts.tax_index_var
    assert emissions_total_var is not None
    assert tax_index_var is not None

    natural_optimum_scaled = float(emissions_total_var.X)
    freeze_tolerance_scaled = lex_freeze_tolerance(natural_optimum_scaled, natural.mip_gap)
    delta = freeze_tolerance_scaled * 0.9
    # Must dominate natural_optimum_scaled + delta with margin to spare once
    # multiplied by a single unit step in tax_index_var, or the "every other
    # tax_index stays free" half of the construction silently fails to relax.
    big_m = 10.0 * (abs(natural_optimum_scaled) + abs(float(emissions_total_var.UB)) + 1.0)

    model.addConstr(
        emissions_total_var
        >= natural_optimum_scaled + delta - big_m * (tax_index_var - instance.lower_tax_index),
        name="force_smallest_tax_drift",
    )
    model.update()

    # Reference: what a plain, single-objective Stage-1 solve reports once
    # the constraint is in place. Adding the constraint is allowed to move
    # *which* tax_index attains the minimum (that's the point), but not the
    # minimum value itself -- this is the ground truth the lexicographic
    # solve's reported emissions must match.
    stage1_only = solve_dbp_relaxation(master)
    assert stage1_only.status_code == GRB.OPTIMAL
    assert stage1_only.tax_index != instance.lower_tax_index

    two_stage = solve_dbp_relaxation_lexicographic(master)

    assert two_stage.status_code == GRB.OPTIMAL
    # The smallest tax is now only reachable within the freeze tolerance,
    # not at the exact optimum -- exactly the drift scenario the bug
    # exploited.
    assert two_stage.tax_index == instance.lower_tax_index
    comparison_tolerance = 0.3
    assert two_stage.emissions == pytest.approx(stage1_only.emissions, abs=comparison_tolerance)
    # And the drift this guards against is itself comfortably larger than
    # the comparison tolerance above, so a regression could not slip past
    # as ordinary solve-precision noise.
    assert delta * subproblems.EMISSIONS_SCALE > 2.0 * comparison_tolerance


@pytest.mark.gurobi
@pytest.mark.slow
def test_dbp_cut_epsilon_scales_with_cost_magnitude() -> None:
    """A fixed absolute DBP-cut epsilon sized for this project's real
    instances (~1e5-1e6 USD) used to be a large fraction of cost
    differences between candidate tax solutions on a small (e.g.
    unit-test-scale) instance, weakening cuts more than a true
    floating-point round-off guard ever should. The slack must instead
    scale with the cut's own cost magnitude, with only a genuinely tiny
    absolute floor for near-zero-cost degenerate cases.
    """
    instance = _build_tiny_instance()
    master = build_dbp_relaxation_master(instance)

    small_cut = DbpFollowerCut(tax_index=instance.lower_tax_index, cost=10.0, emissions=1.0, iteration=1)
    large_cut = DbpFollowerCut(tax_index=instance.lower_tax_index, cost=2_000_000.0, emissions=1.0, iteration=2)

    small_epsilon = _dbp_cut_epsilon(master, small_cut)
    large_epsilon = _dbp_cut_epsilon(master, large_cut)

    # At small-instance cost scale, the epsilon must stay tiny -- not the
    # project's old fixed 0.1, which would dwarf cost differences this small.
    assert small_epsilon < 1e-4
    # At realistic instance cost scale, the relative term should dominate
    # and land close to the project's previous fixed 0.1 USD guard.
    assert large_epsilon == pytest.approx(DEFAULT.dbp_cut_epsilon_relative * large_cut.cost)
    assert 0.05 < large_epsilon < 1.0


@pytest.mark.gurobi
@pytest.mark.slow
def test_validate_fixed_tax_solution_rejects_material_bound_violation() -> None:
    instance = _build_tiny_instance()
    solved = solve_fixed_tax_lexicographic(instance, instance.lower_tax_index, capture_solution=True)

    assert solved.variable_values is not None

    follower_master = build_fixed_tax_follower_master(instance)
    follower_master.artifacts.model.update()
    variable = next(
        variable
        for variable in follower_master.artifacts.model.getVars()
        if (
            variable.VType == GRB.CONTINUOUS
            and float(variable.LB) == 0.0
            and solved.variable_values.get(variable.VarName, 0.0) == 0.0
        )
    )

    invalid_values = dict(solved.variable_values)
    invalid_values[variable.VarName] = -1e-4

    with pytest.raises(ValueError, match="violates"):
        validate_fixed_tax_solution(
            instance,
            tax_index=instance.lower_tax_index,
            variable_values=invalid_values,
        )
