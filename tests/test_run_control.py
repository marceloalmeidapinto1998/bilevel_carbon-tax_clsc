"""Tests of how a DBP run is bounded and observed: the run budget, the iteration cap, the callback
that receives each iteration as it ends, the log of every iteration, and the trace file that is
appended to while the run goes.

The trace-file test needs no Gurobi licence. The rest solve a tiny generated instance (the DBP takes
about half a second on it) and are skipped when no licence is found.
"""
from __future__ import annotations

import csv
import logging
import time

import pytest

from clsc.solver_cli.results import TRACE_FIELDNAMES, append_dbp_trace_row, classify_result
from clsc.solvers.dbp import BilevelSolveError, DbpIterationRecord


def _gurobi_available() -> bool:
    try:
        import gurobipy as gp

        with gp.Env(params={"OutputFlag": 0}):
            return True
    except Exception:
        return False


requires_gurobi = pytest.mark.skipif(not _gurobi_available(), reason="no usable Gurobi licence")


def _record(iteration: int) -> DbpIterationRecord:
    return DbpIterationRecord(
        iteration=iteration,
        relaxation_tax=float(iteration),
        relaxation_lower_bound=100.0,
        follower_seconds=1.5,
        follower_objective=10.0,
        optimistic_seconds=0.0,
        optimistic_cost=8.0,
        optimistic_emissions=50.0,
        leader_objective_ub=120.0,
        relaxation_seconds=2.5,
        next_relaxation_tax=float(iteration) + 1.0,
        next_relaxation_lower_bound=101.0,
    )


def test_trace_rows_are_appended_with_one_header(tmp_path) -> None:
    path = tmp_path / "dbp_trace.csv"
    append_dbp_trace_row(path, _record(1))
    # The file is complete after the first iteration, before the run has ended.
    assert len(list(csv.DictReader(path.open(encoding="utf-8")))) == 1
    append_dbp_trace_row(path, _record(2))
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert [row["iteration"] for row in rows] == ["1", "2"]
    assert list(rows[0]) == TRACE_FIELDNAMES
    assert path.read_text(encoding="utf-8").count("iteration,") == 1


@pytest.fixture(scope="module")
def tiny_instance():
    from clsc.generator.config import GeneratorConfig
    from clsc.generator.instance_builder import generate_instance
    from clsc.models.instance_data import InstanceData

    config = GeneratorConfig(
        suppliers=2, factories=1, warehouses=2, retailers=2, airports=1, seaports=1, products=1,
        raw_materials=2, production_technologies=2, remanufacturing_technologies=2, periods=3,
        seed=0, instance_name="tiny0",
    )
    return InstanceData.from_dict(generate_instance(config).to_dict())


def _solve(instance, **kwargs):
    from clsc.solvers.dbp import solve_bilevel_dbp

    return solve_bilevel_dbp(instance, threads=1, seed=0, time_limit=60, **kwargs)


@requires_gurobi
def test_callback_receives_every_iteration_as_it_ends(tiny_instance) -> None:
    received = []
    result = _solve(tiny_instance, on_iteration=received.append)
    assert received == list(result.iteration_records)
    assert [record.iteration for record in received] == list(range(1, result.iterations + 1))


@requires_gurobi
def test_every_iteration_is_logged(tiny_instance, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="clsc.solvers.dbp"):
        result = _solve(tiny_instance)
    messages = [record.getMessage() for record in caplog.records]
    assert sum(message.startswith("iteration ") for message in messages) == result.iterations
    assert any(message.startswith("finished: ") for message in messages)


@requires_gurobi
def test_iteration_cap_ends_the_run_with_the_incumbent(tiny_instance) -> None:
    result = _solve(tiny_instance, max_iterations=1)
    assert result.termination_reason == "incumbent_iteration_limit"
    assert result.iterations == 1
    assert not result.exact
    assert classify_result(result) == "bounds"
    assert result.incumbent_solution is not None and result.incumbent_solution.has_solution
    # The follower was solved within its time limit, so the upper bound is certified.
    assert result.leader_objective_ub_certificate.exact


@requires_gurobi
def test_run_budget_ends_the_run_with_the_incumbent(tiny_instance) -> None:
    # The callback uses up the budget during the first iteration, so the run stops at the start of the second.
    result = _solve(tiny_instance, run_time_limit=2.0, on_iteration=lambda record: time.sleep(2.5))
    assert result.termination_reason == "incumbent_time_limit"
    assert result.iterations == 1
    assert not result.exact
    assert classify_result(result) == "bounds"
    assert result.leader_objective_lb <= result.leader_objective_ub


@requires_gurobi
def test_run_budget_spent_before_any_incumbent_is_an_error(tiny_instance) -> None:
    # Depending on where the budget runs out (the first relaxation or the start of the first
    # iteration) the error is a subproblem status error or the "no incumbent" error; both are
    # BilevelSolveErrors, and neither returns a result without an incumbent.
    with pytest.raises(BilevelSolveError):
        _solve(tiny_instance, run_time_limit=1e-6)


@requires_gurobi
@pytest.mark.parametrize("name", ["run_time_limit", "max_iterations"])
def test_nonpositive_limits_are_rejected(tiny_instance, name: str) -> None:
    with pytest.raises(ValueError):
        _solve(tiny_instance, **{name: 0})
