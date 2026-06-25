from __future__ import annotations

import pytest
from gurobipy import GRB

from data.generator import ArcConnectivityConfig, GeneratorConfig, generate_instance
from src.config.gap_tol import DEFAULT
from src.models.instance_loader import InstanceData
from src.models.shared_models import (
    build_fixed_tax_follower_master,
    solve_fixed_tax_lexicographic,
    validate_fixed_tax_solution,
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


def _assert_matching_lex_results(actual, expected, *, hat_tau: int) -> None:
    assert actual.status_code == GRB.OPTIMAL
    assert expected.status_code == GRB.OPTIMAL
    assert actual.hat_tau == hat_tau
    assert expected.hat_tau == hat_tau
    assert actual.objective_value == pytest.approx(expected.objective_value)
    assert actual.cost == pytest.approx(expected.cost)
    assert actual.emissions == pytest.approx(expected.emissions)
    assert actual.follower_objective == pytest.approx(expected.follower_objective)
    # Warm-started and cold solves can reach the configured MIP-gap target
    # via different branch-and-bound paths, so the exact reported gap is not
    # expected to match bit-for-bit -- only that both are within tolerance.
    assert actual.mip_gap <= DEFAULT.mip_gap
    assert expected.mip_gap <= DEFAULT.mip_gap
    assert actual.lex_primary_mip_gap <= DEFAULT.mip_gap
    assert expected.lex_primary_mip_gap <= DEFAULT.mip_gap
    assert actual.lex_secondary_mip_gap <= DEFAULT.mip_gap
    assert expected.lex_secondary_mip_gap <= DEFAULT.mip_gap
    assert actual.variable_values is not None
    assert expected.variable_values is not None
    assert set(actual.variable_values) == set(expected.variable_values)
    for variable_name, expected_value in expected.variable_values.items():
        assert actual.variable_values[variable_name] == pytest.approx(expected_value)


def test_solve_fixed_tax_lexicographic_reuses_follower_master_across_hat_tau_values() -> None:
    instance = _build_tiny_instance()
    follower_master = build_fixed_tax_follower_master(instance)
    reused_model = follower_master.artifacts.model

    lower_hat_tau = instance.lower_hat_tau
    upper_hat_tau = instance.upper_hat_tau

    expected_lower = solve_fixed_tax_lexicographic(instance, lower_hat_tau, capture_solution=True)
    reused_lower = solve_fixed_tax_lexicographic(follower_master, lower_hat_tau, capture_solution=True)
    _assert_matching_lex_results(reused_lower, expected_lower, hat_tau=lower_hat_tau)
    assert follower_master.artifacts.model is reused_model

    expected_upper = solve_fixed_tax_lexicographic(instance, upper_hat_tau, capture_solution=True)
    reused_upper = solve_fixed_tax_lexicographic(
        follower_master,
        upper_hat_tau,
        capture_solution=True,
        warm_start_values=reused_lower.variable_values,
    )
    _assert_matching_lex_results(reused_upper, expected_upper, hat_tau=upper_hat_tau)
    assert follower_master.artifacts.model is reused_model


def test_solve_fixed_tax_follower_drives_factory_area_from_throughput() -> None:
    instance = _build_tiny_instance()
    solved = solve_fixed_tax_lexicographic(instance, instance.lower_hat_tau, capture_solution=True)

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


def test_validate_fixed_tax_solution_accepts_tiny_bound_noise() -> None:
    instance = _build_tiny_instance()
    solved = solve_fixed_tax_lexicographic(instance, instance.lower_hat_tau, capture_solution=True)

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
        hat_tau=instance.lower_hat_tau,
        variable_values=noisy_values,
    )

    assert recomputed.status_code == GRB.OPTIMAL


def test_validate_fixed_tax_solution_accepts_tiny_integer_noise() -> None:
    instance = _build_tiny_instance()
    solved = solve_fixed_tax_lexicographic(instance, instance.lower_hat_tau, capture_solution=True)

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
        hat_tau=instance.lower_hat_tau,
        variable_values=noisy_values,
    )

    assert recomputed.status_code == GRB.OPTIMAL


def test_validate_fixed_tax_solution_rejects_material_bound_violation() -> None:
    instance = _build_tiny_instance()
    solved = solve_fixed_tax_lexicographic(instance, instance.lower_hat_tau, capture_solution=True)

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
            hat_tau=instance.lower_hat_tau,
            variable_values=invalid_values,
        )
