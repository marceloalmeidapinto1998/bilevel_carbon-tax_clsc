"""Regression tests for `per_run_wall_clock_cap_seconds` enforcement (campaign_01).

The cap was written into every `campaign_manifest.json` but never acted on: only the
per-subproblem `--time-limit` bound anything, and that bounds ONE MILP, not the DBP loop.
A run could therefore consume an unbounded multiple of its budget and still be recorded as
`success` -- exp2's `threads4_focus0` ran 94,911 s against a nominal 50,400 s cap.

Enforcement is INSIDE the solve, not a kill from outside, because a killed process reports
nothing: no incumbent, no variables, no gap. Three paths are pinned here:
  * bilevel -> `--wall-clock-cap` clamps each subproblem to the remaining budget and stops the
    DBP loop between iterations, returning `termination_reason="wall_clock_cap"` WITH the
    incumbent, its variable values and the certified bounds;
  * in-process follower solves -> the single Gurobi call's own limit is clamped to the cap;
  * a subprocess kill remains only as a backstop, and is reported distinctly
    (`wall_clock_cap_killed`) precisely because it is the one case that loses the results.
"""

from __future__ import annotations

import subprocess

import pytest

from clsc.campaign import orchestrator as campaign
from clsc.campaign.designs._common import DesignPoint


def _point(**overrides) -> DesignPoint:
    kwargs = {
        "experiment_id": "exp2",
        "design_point_id": "exp2-t4-f0",
        "run_code": "threads4_focus0",
        "base_instance_id": "STD_I25_M8_T6",
        "execution_mode": "bilevel",
        "per_subproblem_time_limit_seconds": 10_800.0,
        "per_run_wall_clock_cap_seconds": 50_400.0,
    }
    kwargs.update(overrides)
    return DesignPoint(**kwargs)


def test_cap_is_passed_to_the_solver_and_the_kill_is_only_a_backstop(tmp_path, monkeypatch) -> None:
    seen: dict[str, object] = {}
    seen_cmd: list[str] = []

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        seen_cmd.extend(cmd)
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(campaign.subprocess, "run", fake_run)
    point = _point()

    with pytest.raises(campaign.WallClockCapExceeded):
        campaign._solve_bilevel(point, tmp_path / "instance.json", tmp_path / "out")

    # The solver enforces the cap itself, so that it can stop with its incumbent intact...
    assert "--wall-clock-cap" in seen_cmd
    assert seen_cmd[seen_cmd.index("--wall-clock-cap") + 1] == "50400.0"
    # ...and the external kill is slack, firing only if the solver failed to stop itself.
    assert seen["timeout"] == 50_400.0 + campaign._WALL_CLOCK_BACKSTOP_GRACE


def test_wall_clock_kill_is_recorded_as_censored_not_failed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(campaign, "RESULTS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(campaign, "HEARTBEAT_LOG", tmp_path / "runs" / "_heartbeat.log")
    monkeypatch.setattr(campaign, "materialize", lambda point, output_root: tmp_path / "inst.json")

    def blown_cap(point, instance_path, out_dir):
        raise campaign.WallClockCapExceeded("killed after 50400s wall-clock cap")

    monkeypatch.setattr(campaign, "_solve_bilevel", blown_cap)

    manifest = campaign.run_point(_point())

    # Censored, not failed: the point ran as specified, it just did not fit its budget.
    assert manifest["solve_status"] == "censored"
    # Distinguished from the graceful cap stop, which DOES carry objective values.
    assert manifest["termination_reason"] == "wall_clock_cap_killed"
    assert manifest["censored"] is True
    # Nothing survives a mid-solve kill, so no incumbent may be reported.
    assert manifest["objective_values"] == {"cost": None, "emissions": None, "follower_objective": None}
    assert manifest["leader_tax"] is None
    assert manifest["wall_clock_seconds"] >= 0.0


def test_graceful_cap_stop_is_censored_but_keeps_objective_values(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(campaign, "RESULTS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(campaign, "HEARTBEAT_LOG", tmp_path / "runs" / "_heartbeat.log")
    monkeypatch.setattr(campaign, "materialize", lambda point, output_root: tmp_path / "inst.json")

    # What the solver writes when it stops itself at the cap: a real incumbent plus a gap.
    monkeypatch.setattr(campaign, "_solve_bilevel", lambda point, instance_path, out_dir: {
        "termination_reason": "wall_clock_cap", "success": True,
        "cost": 2_182_927.0, "emissions": 2.1e8, "follower_objective": 4.4e7,
        "tax_index": 1673, "effective_tax": 0.1673, "relative_gap": 0.0081,
        "_summary_path": "results/x/summary.json",
    })

    manifest = campaign.run_point(_point())

    assert manifest["solve_status"] == "censored"
    assert manifest["censored"] is True
    # The whole point of in-solver enforcement: a censored run still reports its incumbent,
    # its tax, and the certified gap bounding how far that incumbent may be from E*.
    assert manifest["objective_values"]["emissions"] == 2.1e8
    assert manifest["objective_values"]["cost"] == 2_182_927.0
    assert manifest["leader_tax"] == 1673
    assert manifest["mip_gap"] == 0.0081
    assert manifest["effective_tax_usd_per_kg"] == 0.1673


def test_in_process_solve_limit_is_clamped_to_the_cap() -> None:
    # Exp6/Exp7 follower solves: cap below the per-subproblem limit must win.
    tight = _point(execution_mode="fixed_tax", per_subproblem_time_limit_seconds=3_600.0,
                   per_run_wall_clock_cap_seconds=600.0)
    assert campaign._effective_subproblem_time_limit(tight) == 600.0

    # ...and a generous cap must not inflate the solver's own limit.
    loose = _point(execution_mode="fixed_tax", per_subproblem_time_limit_seconds=3_600.0,
                   per_run_wall_clock_cap_seconds=28_800.0)
    assert campaign._effective_subproblem_time_limit(loose) == 3_600.0


def test_partial_dbp_trace_is_salvaged_under_a_non_terminal_name(tmp_path) -> None:
    scratch = tmp_path / "scratch" / "nested"
    scratch.mkdir(parents=True)
    (scratch / "dbp_trace.csv").write_text("iteration\n1\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    campaign._salvage_partial_dbp_trace(tmp_path / "scratch", out_dir)

    # Salvaged for diagnostics, but never as `dbp_trace.csv`/`summary.json` -- otherwise the
    # resume logic would treat the killed run as a completed one.
    assert (out_dir / "_partial_dbp_trace.csv").is_file()
    assert not (out_dir / "dbp_trace.csv").exists()
    assert not list(out_dir.glob("**/summary.json"))


# --- in-solver enforcement (clsc.solvers.dbp_lex) -------------------------------------------

def test_budget_clamps_each_subproblem_to_what_remains() -> None:
    from clsc.solvers.dbp_lex import _WallClockBudget

    budget = _WallClockBudget(cap=10.0, per_subproblem_limit=3600.0)
    # A 3600 s subproblem inside a 10 s budget would blow the cap by three orders of magnitude.
    assert budget.subproblem_time_limit() <= 10.0
    assert not budget.expired()

    # No cap -> the per-subproblem limit is handed through untouched.
    uncapped = _WallClockBudget(cap=None, per_subproblem_limit=3600.0)
    assert uncapped.subproblem_time_limit() == 3600.0
    assert not uncapped.expired()
    assert uncapped.remaining() is None


def test_expired_budget_never_hands_gurobi_a_non_positive_limit() -> None:
    from clsc.solvers.dbp_lex import _WallClockBudget

    budget = _WallClockBudget(cap=-5.0, per_subproblem_limit=3600.0)
    assert budget.expired()
    # Gurobi reads TimeLimit <= 0 as "no limit" -- the opposite of what an exhausted budget means.
    assert budget.subproblem_time_limit() > 0.0


def test_timeout_reason_distinguishes_the_two_budgets() -> None:
    from clsc.solvers.dbp_lex import _WallClockBudget, _timeout_reason

    assert _timeout_reason(_WallClockBudget(cap=-1.0, per_subproblem_limit=60.0)) == "wall_clock_cap"
    assert _timeout_reason(_WallClockBudget(cap=3600.0, per_subproblem_limit=60.0)) == "time_limit"
    assert _timeout_reason(_WallClockBudget(cap=None, per_subproblem_limit=60.0)) == "time_limit"


def test_cap_result_carries_incumbent_bounds_and_gap() -> None:
    from clsc.solvers.dbp_lex import (
        BoundCertificate, IncumbentSolution, _build_time_limit_result, relative_optimality_gap,
    )

    incumbent = IncumbentSolution(tax_index=1673, cost=2_182_927.0, emissions=2.10e8,
                                  follower_objective=4.4e7, scale_factor=1e-4)
    result = _build_time_limit_result(
        incumbent=incumbent, incumbent_solution=None,
        upper_bound_certificate=BoundCertificate(2.10e8, True, None, 0.0, "lexicographic"),
        best_lower_bound=2.08e8, iteration=3, iteration_records=[], iteration_timings=[],
        initial_relaxation_seconds=1.0, termination_reason="wall_clock_cap",
    )

    assert result.termination_reason == "wall_clock_cap"
    assert result.exact is False          # censored, and says so
    assert result.incumbent.emissions == 2.10e8   # ...but the incumbent is reported
    assert result.lower_bound == 2.08e8           # ...with a valid bound
    assert relative_optimality_gap(
        upper_bound=result.upper_bound, lower_bound=result.lower_bound
    ) == pytest.approx(0.00952, rel=1e-2)


# --- exp8 (enumeration execution mode) wiring -------------------------------------------------

def test_enumeration_is_a_registered_execution_mode() -> None:
    from clsc.campaign.designs._common import EXECUTION_MODES
    assert "enumeration" in EXECUTION_MODES


def test_exp8_is_registered_but_not_auto_included_by_running_experiments() -> None:
    # Registered so `--experiment exp8` (or a future `all`) can build it...
    assert "exp8" in campaign.EXPERIMENT_MODULES
    assert "exp8" in campaign.EXPERIMENT_DIR_NAMES
    assert campaign.build_design_matrix("exp8")  # builds without error


def test_run_point_dispatches_enumeration_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(campaign, "RESULTS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(campaign, "HEARTBEAT_LOG", tmp_path / "runs" / "_heartbeat.log")
    monkeypatch.setattr(campaign, "materialize", lambda point, output_root: tmp_path / "inst.json")

    seen = {}

    def fake_enum(point, instance_path, out_dir):
        seen["called"] = True
        return {
            "termination_reason": "exhausted", "success": True,
            "cost": 1.0, "emissions": 2.0, "follower_objective": 1.0,
            "tax_index": 5, "effective_tax": 0.0005, "relative_gap": 0.0,
            "follower_solve_count": 6, "grid_points_total": 6,
            "_summary_path": "results/x/result.json",
        }

    monkeypatch.setattr(campaign, "_solve_enumeration", fake_enum)

    point = _point(experiment_id="exp8", design_point_id="exp8-enum-STD_I17_M4_T3",
                   run_code="enumeration", base_instance_id="STD_I17_M4_T3",
                   execution_mode="enumeration")
    manifest = campaign.run_point(point)

    assert seen.get("called") is True
    assert manifest["solve_status"] == "success"
    assert manifest["solver_method"] == "exhaustive_grid_enumeration"
