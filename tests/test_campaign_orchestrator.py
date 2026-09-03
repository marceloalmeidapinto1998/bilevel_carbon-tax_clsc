"""The campaign orchestrator (`clsc.campaign.orchestrator`): materializing and running design
points correctly. Four concerns, each pinning a real, previously-shipped bug:

  * **Tax-grid consistency.** Bilevel runs were solved on the fine grid (1e-4 USD/kg per index)
    while in-process `fixed_tax` runs used the instances' native coarse grid (1e-2), so index 80
    meant 8 USD/t in one mode and 800 USD/t in the other. Nothing crashed -- Exp1's invariance
    probes and Exp3's policy rules were simply being compared against a bilevel tau* on a 100x
    different scale. Design points state fine-grid indices, the orchestrator re-grids every
    execution mode onto the point's own step, and the aggregator reports a RATE rather than
    recomputing one from a global constant.
  * **Wall-clock enforcement.** `per_run_wall_clock_cap_seconds` was written into every
    `campaign_manifest.json` but never acted on -- only the per-subproblem `--time-limit` bound
    anything, and that bounds ONE MILP, not the DBP loop. One run consumed 94911s against a
    nominal 50400s cap and was still recorded `success`. Enforcement is INSIDE the solve, not a
    kill from outside, because a killed process reports nothing: no incumbent, no variables, no
    gap. A subprocess kill remains only as a backstop, reported distinctly
    (`wall_clock_cap_killed`) precisely because it is the one case that loses the results.
  * **Follower-output writing.** `_write_follower_result` (the shared summary/solution.json
    writer for fixed_tax/min_emissions/epsilon_constraint solves) once raised a `NameError`
    (`effective_tax` used but never assigned) the moment it tried to serialise a captured
    solution -- a path with no prior coverage, which is exactly why it slipped in.
  * **Experiment 3's data-dependent staging.** Local plateau refinement and the rho*-anchored
    suite only materialise once Experiment 2's M0 manifests (respectively, Experiment 3's own
    ratio-sweep result) exist on disk -- these tests cover the pure-Python pieces that decide
    when and where.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from clsc.analysis.campaign_01.aggregate import _effective_tax_usd_per_kg
from clsc.campaign import orchestrator as campaign
from clsc.campaign.designs import exp1_verification, exp3_policy_value
from clsc.campaign.designs import exp3_policy_value as exp3
from clsc.campaign.designs._common import (
    COARSE_SCALE_FACTOR,
    FINE_CEILING_INDEX,
    FINE_SCALE_FACTOR,
    TAX_CEILING_USD_PER_KG,
    DesignPoint,
    fine_index,
)
from clsc.models.subproblems import SolveResult


# ===========================================================================
# Tax-grid consistency
# ===========================================================================

def test_the_two_grids_span_the_same_real_tax_range() -> None:
    # This is what makes a RATE comparable across grids while an INDEX is not.
    assert FINE_CEILING_INDEX * FINE_SCALE_FACTOR == pytest.approx(TAX_CEILING_USD_PER_KG)
    assert 20 * COARSE_SCALE_FACTOR == pytest.approx(TAX_CEILING_USD_PER_KG)
    assert fine_index(TAX_CEILING_USD_PER_KG) == FINE_CEILING_INDEX


def test_fine_index_rejects_rates_off_the_grid() -> None:
    with pytest.raises(ValueError):
        fine_index(TAX_CEILING_USD_PER_KG * 2)


@pytest.mark.parametrize("module", [exp1_verification, exp3_policy_value])
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


def test_exp3_frontier_spans_the_fine_grid() -> None:
    # Exp3's frontier points only materialise once rho* is solved, so the grid is asserted on the
    # constant that builder stage consumes.
    indices = exp3_policy_value.FRONTIER_TAX_INDICES
    assert len(indices) == 11
    assert indices[0] == 0
    assert indices[-1] == FINE_CEILING_INDEX


def test_exp1_invariant_probes_sit_at_their_intended_rates() -> None:
    intended = exp1_verification.INVARIANT_TAX_RATES_USD_PER_KG
    actual = [idx * FINE_SCALE_FACTOR for idx in exp1_verification.INVARIANT_TAX_INDICES]
    assert actual == pytest.approx(list(intended))


def test_exp3_policy_rules_bracket_the_full_grid() -> None:
    # P1 is "the tax ceiling" -- on the coarse grid its index 20 was 1% of the ceiling here.
    assert exp3_policy_value.POLICY_RULES["P0_no_tax"] == 0
    assert exp3_policy_value.POLICY_RULES["P1_ceiling"] == FINE_CEILING_INDEX
    assert exp3_policy_value.POLICY_RULES["P2_mid"] == FINE_CEILING_INDEX // 2


def test_orchestrator_grid_step_is_fine_unless_the_variant_asks_otherwise() -> None:
    base = dict(
        experiment_id="exp3", design_point_id="d", run_code="r", base_instance_id="STD_I17_M4_T3",
        execution_mode="fixed_tax", per_subproblem_time_limit_seconds=600.0,
        per_run_wall_clock_cap_seconds=3600.0,
    )
    assert campaign._tax_grid_step(DesignPoint(**base)) == FINE_SCALE_FACTOR
    # Any design point can override the grid via its own scale_factor (no scheduled point
    # currently does, but the mechanism -- once used by the retired A4 variant -- must still work).
    coarse = DesignPoint(**base, scale_factor=COARSE_SCALE_FACTOR)
    assert campaign._tax_grid_step(coarse) == COARSE_SCALE_FACTOR


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


# ===========================================================================
# Wall-clock enforcement
# ===========================================================================

def _wcc_point(**overrides) -> DesignPoint:
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
    point = _wcc_point()

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

    manifest = campaign.run_point(_wcc_point())

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

    manifest = campaign.run_point(_wcc_point())

    assert manifest["solve_status"] == "censored"
    assert manifest["censored"] is True
    # The whole point of in-solver enforcement: a censored run still reports its incumbent, its
    # tax, and the certified gap bounding how far that incumbent may be from E*.
    assert manifest["objective_values"]["emissions"] == 2.1e8
    assert manifest["objective_values"]["cost"] == 2_182_927.0
    assert manifest["leader_tax"] == 1673
    assert manifest["mip_gap"] == 0.0081
    assert manifest["effective_tax_usd_per_kg"] == 0.1673


def test_in_process_solve_limit_is_clamped_to_the_cap() -> None:
    # Fixed-tax/min-emissions follower solves: cap below the per-subproblem limit must win.
    tight = _wcc_point(execution_mode="fixed_tax", per_subproblem_time_limit_seconds=3_600.0,
                       per_run_wall_clock_cap_seconds=600.0)
    assert campaign._effective_subproblem_time_limit(tight) == 600.0

    # ...and a generous cap must not inflate the solver's own limit.
    loose = _wcc_point(execution_mode="fixed_tax", per_subproblem_time_limit_seconds=3_600.0,
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


# ===========================================================================
# Enumeration execution mode (folded into exp2, computational performance)
# ===========================================================================

def test_enumeration_is_a_registered_execution_mode() -> None:
    from clsc.campaign.designs._common import EXECUTION_MODES
    assert "enumeration" in EXECUTION_MODES


def test_exp2_design_matrix_includes_enumeration_points() -> None:
    assert "exp2" in campaign.EXPERIMENT_MODULES
    assert "exp2" in campaign.EXPERIMENT_DIR_NAMES
    points = campaign.build_design_matrix("exp2")  # builds without error
    assert any(p.execution_mode == "enumeration" for p in points)


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

    point = _wcc_point(experiment_id="exp2", design_point_id="exp2-enum-STD_I17_M4_T3",
                       run_code="enumeration", base_instance_id="STD_I17_M4_T3",
                       execution_mode="enumeration")
    manifest = campaign.run_point(point)

    assert seen.get("called") is True
    assert manifest["solve_status"] == "success"
    assert manifest["solver_method"] == "exhaustive_grid_enumeration"


# ===========================================================================
# Follower-output writing (_write_follower_result)
# ===========================================================================

def _make_follower_result(*, variable_values: dict[str, float] | None) -> SolveResult:
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


def _make_follower_instance() -> SimpleNamespace:
    # Only .name and .tax_rate(idx) are used by _write_follower_result.
    return SimpleNamespace(name="STD_I17_M4_T3", tax_rate=lambda idx: 0.01 * idx)


def test_write_follower_result_serialises_captured_solution(tmp_path, monkeypatch) -> None:
    # out_dir must live under REPO_ROOT (the writer reports paths relative to it).
    monkeypatch.setattr(campaign, "REPO_ROOT", tmp_path)
    out_dir = tmp_path / "B_tax_emissions_frontier" / "STD_I17_M4_T3" / "eps_01"
    tax_index = 6

    summary = campaign._write_follower_result(
        None,  # point is unused by the function body
        _make_follower_instance(),
        _make_follower_result(variable_values={"y_f[f1]": 1.0, "x[p1,f1,w1,t1]": 42.0}),
        Path("data/instances/base/STD_I17_M4_T3.json"),
        out_dir,
        solve_seconds=3.5,
        tax_index_for_report=tax_index,
    )

    expected_tax = 0.01 * tax_index
    assert summary["effective_tax"] == expected_tax
    assert (out_dir / "solution.json").is_file()

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
        _make_follower_instance(),
        _make_follower_result(variable_values=None),
        Path("data/instances/base/STD_I17_M4_T3.json"),
        out_dir,
        solve_seconds=1.0,
        tax_index_for_report=0,
    )

    assert summary["effective_tax"] == 0.0
    assert not (out_dir / "solution.json").exists()
    assert (out_dir / "result.json").is_file()


# ===========================================================================
# Experiment 3's data-dependent staging (refinement, rho*-anchored suite)
# ===========================================================================

def test_geometric_indices_stay_within_bounds_and_ascending() -> None:
    idx = exp3._geometric_indices(10, 1000, 5)
    assert idx == sorted(idx)
    assert all(10 <= i <= 1000 for i in idx)


def test_geometric_indices_span_orders_of_magnitude() -> None:
    # tau* ranges from ~14 to ~1673 across cells -- linear spacing anchored to the small end
    # would place every point within a couple of grid steps of tau* on the largest cells.
    idx = exp3._geometric_indices(200, 1670, 4)
    ratios = [b / a for a, b in zip(idx, idx[1:])]
    # Consecutive ratios should be roughly comparable (geometric, not front-loaded).
    assert max(ratios) / min(ratios) < 3.0


def test_geometric_indices_degenerate_range_returns_single_point() -> None:
    assert exp3._geometric_indices(5, 5, 4) == [5]


def test_geometric_indices_deduplicates_when_range_is_narrow() -> None:
    # A range too narrow for n distinct integer points must not raise or return duplicates.
    idx = exp3._geometric_indices(1, 3, 6)
    assert idx == sorted(set(idx))
    assert all(1 <= i <= 3 for i in idx)


def test_tau_star_index_reads_leader_tax_from_exp2_manifest(tmp_path) -> None:
    cell = "STD_I17_M4_T3"
    manifest_dir = tmp_path / "exp2_computational_performance" / cell / "M0_seed0"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "campaign_manifest.json").write_text(
        json.dumps({"leader_tax": 80, "solve_status": "success"}), encoding="utf-8",
    )

    assert exp3._tau_star_index(tmp_path, cell) == 80


def test_tau_star_index_is_none_when_exp2_has_not_run_yet(tmp_path) -> None:
    assert exp3._tau_star_index(tmp_path, "STD_I17_M4_T3") is None


def _seed_exp2_m0(root, cell: str, tau_star: int) -> None:
    manifest_dir = root / "exp2_computational_performance" / cell / "M0_seed0"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "campaign_manifest.json").write_text(
        json.dumps({"leader_tax": tau_star, "solve_status": "success"}), encoding="utf-8",
    )


def test_refinement_points_bracket_tau_star_without_repeating_it(tmp_path) -> None:
    cell = "STD_I17_M4_T3"
    _seed_exp2_m0(tmp_path, cell, tau_star=80)

    points = exp3._refinement_points(tmp_path)
    cell_points = [p for p in points if p.base_instance_id == cell]

    assert cell_points, "expected refinement points once Exp2's M0 result exists"
    indices = [p.fixed_tax_index for p in cell_points]
    assert 80 not in indices              # tau* itself is already P3, not re-solved
    assert any(i < 80 for i in indices)   # falling slope below tau*
    assert any(i > 80 for i in indices)   # flatness confirmation above tau*
    assert all(0 <= i <= FINE_CEILING_INDEX for i in indices)
    assert len(indices) == len(set(indices))  # no duplicate design points for one cell


def test_refinement_skips_a_cell_whose_exp2_result_is_not_ready(tmp_path) -> None:
    # No manifest seeded at all -> every cell's tau* lookup returns None.
    assert exp3._refinement_points(tmp_path) == []


def test_refinement_never_duplicates_a_reserved_policy_index(tmp_path) -> None:
    # tau* exactly at the P2 midpoint: the refinement must not re-schedule that index.
    cell = "STD_I17_M4_T3"
    _seed_exp2_m0(tmp_path, cell, tau_star=exp3.FINE_CEILING_INDEX // 2)

    points = exp3._refinement_points(tmp_path)
    indices = {p.fixed_tax_index for p in points if p.base_instance_id == cell}
    assert exp3.POLICY_RULES["P2_mid"] not in indices


def test_build_design_matrix_includes_refinement_when_results_root_given(tmp_path) -> None:
    for cell in exp3.POLICY_CELLS:
        _seed_exp2_m0(tmp_path, cell, tau_star=50)

    with_root = exp3.build_design_matrix(results_root=tmp_path)
    without_root = exp3.build_design_matrix(results_root=None)

    assert len(with_root) > len(without_root)
    # Static points: P0/P1/P2 per policy cell, plus the rho sweep (present regardless of results_root).
    assert len(without_root) == len(exp3.POLICY_CELLS) * len(exp3.POLICY_RULES) + len(exp3.RATIO_VALUES)
    refine_ids = [p.design_point_id for p in with_root if "refine" in p.run_code]
    assert len(refine_ids) == len(set(refine_ids))  # globally unique across all policy cells
