"""Regression tests for the doe_campaign_02 follower-solve output tail.

`_write_follower_result` is the shared summary/solution.json writer for the three
single-MILP follower solves (fixed_tax, min_emissions, epsilon_constraint) used by
Families B and D. It is a pure post-processing function (no Gurobi), so it is unit-
testable directly with a hand-built ``SolveResult``.

These tests pin the bug that a `NameError` (`effective_tax` used but never assigned)
made every follower solve crash the moment it tried to serialise a captured solution
-- a path with no prior coverage, which is exactly why it slipped in. The write only
happens when ``result.variable_values is not None``, so the first test deliberately
supplies a captured solution.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from clsc.models.subproblems import SolveResult
from clsc.campaign import orchestrator as campaign


def _make_result(*, variable_values: dict[str, float] | None) -> SolveResult:
    return SolveResult(
        status_code=2,
        status_name="OPTIMAL",
        has_solution=True,
        objective_value=1_500_000.0,
        cost=1_400_000.0,
        emissions=77_700_000.0,
        follower_objective=1_500_000.0,
        tax_index=0,
        mip_gap=1e-6,
        runtime=1.23,
        variable_values=variable_values,
        objective_bound=1_499_999.0,
    )


def _make_instance() -> SimpleNamespace:
    # Only .name and .tax_rate(idx) are used by _write_follower_result.
    return SimpleNamespace(name="STD_I17_M4_T3", tax_rate=lambda idx: 0.01 * idx)


def test_write_follower_result_serialises_captured_solution(tmp_path, monkeypatch) -> None:
    # out_dir must live under REPO_ROOT (the writer reports paths relative to it).
    monkeypatch.setattr(campaign, "REPO_ROOT", tmp_path)
    out_dir = tmp_path / "B_tax_emissions_frontier" / "STD_I17_M4_T3" / "eps_01"
    tax_index = 6

    summary = campaign._write_follower_result(
        None,  # point is unused by the function body
        _make_instance(),
        _make_result(variable_values={"y_f[f1]": 1.0, "x[p1,f1,w1,t1]": 42.0}),
        Path("data/instances/base/STD_I17_M4_T3.json"),
        out_dir,
        solve_seconds=3.5,
        tax_index_for_report=tax_index,
    )

    expected_tax = 0.01 * tax_index
    assert summary["effective_tax"] == expected_tax
    assert (out_dir / "solution.json").is_file()

    import json

    solution = json.loads((out_dir / "solution.json").read_text(encoding="utf-8"))
    # The regression: these came out of `effective_tax` (undefined) before the fix.
    assert solution["leader"]["effective_tax"] == expected_tax
    assert solution["decision_variables"]["leader"]["effective_tax"] == expected_tax
    assert solution["decision_variables"]["follower"] == {"y_f[f1]": 1.0, "x[p1,f1,w1,t1]": 42.0}


def test_write_follower_result_without_solution_skips_solution_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(campaign, "REPO_ROOT", tmp_path)
    out_dir = tmp_path / "cell"

    summary = campaign._write_follower_result(
        None,
        _make_instance(),
        _make_result(variable_values=None),
        Path("data/instances/base/STD_I17_M4_T3.json"),
        out_dir,
        solve_seconds=1.0,
        tax_index_for_report=0,
    )

    assert summary["effective_tax"] == 0.0
    assert not (out_dir / "solution.json").exists()
    assert (out_dir / "result.json").is_file()
