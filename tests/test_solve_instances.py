from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

import pytest
from gurobipy import GRB

from data.generator import ArcConnectivityConfig, GeneratorConfig, generate_instance, write_instance
from clsc.config.gap_tol import DEFAULT
from clsc.models.instance import InstanceData
from clsc.models.subproblems import SolveResult
from clsc.solvers.dbp_lex import (
    BilevelSolveResult,
    BoundCertificate,
    DbpTimingSummary,
    IncumbentSolution,
    SubproblemStatusError,
)
from clsc.solvers.dbp_lex import solve_bilevel_dbp_lex


def _load_solve_instances_module():
    """Return the batch runner's canonical module namespace.

    Previously this loaded ``tools/solver/solve_batch.py`` via importlib (the
    exec-wrapper era, when each load produced its own copy of the runner's
    functions). ``solve_batch.py`` is now a thin re-export of
    ``tools.solver.batch.core``, which is the single source of truth, so return
    ``core`` directly. Tests that ``monkeypatch.setattr`` a runner function on the
    returned module now patch the name the runner's own cross-function calls
    actually resolve against (e.g. canonicalize_result_solution ->
    validate_fixed_tax_solution).
    """
    from tools.solver.batch import core

    return core


def method_results_dir(method: str, mode: str) -> str:
    if method == "dbp_lex":
        return "f_lex_exact"
    return f"{method}_{mode}"


@pytest.mark.gurobi
@pytest.mark.slow
def test_solve_instances_writes_structured_results(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_root = tmp_path / "inputs"
    instance_path = input_root / "base" / "tiny_cli_case.json"
    results_root = tmp_path / "results"
    run_id = "run_test"

    instance = generate_instance(
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
            seed=23,
            instance_name="tiny_cli_case",
            tax_lower=0.0,
            tax_upper=20.0,
            connectivity=ArcConnectivityConfig(
                sf_neighbors=1,
                fw_neighbors=1,
                wr_neighbors=1,
                rf_neighbors=1,
            ),
        ),
    )
    write_instance(instance, instance_path)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/solver/solve_batch.py",
            str(input_root),
            "--recursive",
            "--method",
            "dbp_lex",
            "--results-root",
            str(results_root),
            "--run-id",
            run_id,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr

    run_root = results_root / "base" / "tiny_cli_case" / method_results_dir("dbp_lex", "exact")
    manifest_path = run_root / "manifest.json"
    summary_json_path = run_root / "summary.json"
    summary_csv_path = run_root / "summary.csv"
    result_json_path = run_root / "result.json"
    trace_csv_path = run_root / "dbp_trace.csv"
    solution_json_path = run_root / "solution.json"

    assert manifest_path.exists()
    assert summary_json_path.exists()
    assert summary_csv_path.exists()
    assert result_json_path.exists()
    assert trace_csv_path.exists()
    assert solution_json_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == run_id
    assert manifest["input"]["instance_count"] == 1
    assert manifest["solver"]["method"] == "dbp_lex"
    assert manifest["solver"]["mode"] == "exact"
    assert manifest["solver"]["tolerances"]["dbp_relative_gap"] == DEFAULT.dbp_relative_gap
    assert manifest["solver"]["tolerances"]["lex_epsilon_prime"] == 1.0e-6
    assert manifest["solver"]["tolerances"]["mip_gap"] == DEFAULT.mip_gap
    assert manifest["solver"]["tolerances"]["mip_focus"] == 0
    assert manifest["solver"]["tolerances"]["eps"] == 1.0e-7
    assert manifest["results_scope"] == "base"

    summary_records = json.loads(summary_json_path.read_text(encoding="utf-8"))
    assert len(summary_records) == 1
    assert summary_records[0]["instance"] == "tiny_cli_case"
    assert summary_records[0]["success"] is True
    assert summary_records[0]["validation_status"] == "validated"

    with summary_csv_path.open("r", encoding="utf-8", newline="") as handle:
        summary_rows = list(csv.DictReader(handle))
    assert len(summary_rows) == 1
    assert summary_rows[0]["instance"] == "tiny_cli_case"
    assert summary_rows[0]["success"] == "True"
    assert summary_rows[0]["validation_status"] == "validated"

    result_payload = json.loads(result_json_path.read_text(encoding="utf-8"))
    assert result_payload["instance"]["name"] == "tiny_cli_case"
    assert result_payload["instance"]["relative_result_dir"] == "."
    assert result_payload["solve_status"]["success"] is True
    assert result_payload["solve_status"]["mode"] == "exact"
    assert result_payload["runtime"]["solve_seconds"] >= 0.0
    assert result_payload["runtime"]["dbp_seconds"] >= 0.0
    assert result_payload["runtime"]["validation_seconds"] >= 0.0
    assert result_payload["runtime"]["phase_seconds"]["dbp_subproblems"] >= 0.0
    assert result_payload["runtime"]["subproblem_seconds"]["total"] >= 0.0
    assert result_payload["validation"]["status"] == "validated"
    assert result_payload["bounds"]["certificates"]["lower"]["source"] == "relaxation"
    assert result_payload["bounds"]["certificates"]["upper"]["source"] == "lexicographic"
    assert result_payload["dbp"]["trace_file"] == "dbp_trace.csv"
    assert result_payload["dbp"]["timings"]["initial_relaxation_seconds"] >= 0.0
    assert len(result_payload["dbp"]["timings"]["iterations"]) == result_payload["dbp"]["trace_rows"]
    assert result_payload["phase_summary"]["dbp_iterations"] == result_payload["dbp"]["trace_rows"]
    assert result_payload["files"]["solution_file"] == "solution.json"

    solution_payload = json.loads(solution_json_path.read_text(encoding="utf-8"))
    assert solution_payload["instance"] == "tiny_cli_case"
    assert solution_payload["validation"]["status"] == "validated"
    assert solution_payload["validation"]["max_abs_delta"] <= solution_payload["validation"]["tolerance"]
    assert solution_payload["decision_variables"]["leader"] == solution_payload["leader"]
    assert solution_payload["decision_variables"]["follower"] == solution_payload["variables"]
    assert "variables" in solution_payload
    assert solution_payload["variables"]

    with trace_csv_path.open("r", encoding="utf-8", newline="") as handle:
        trace_rows = list(csv.DictReader(handle))
    assert trace_rows
    assert "follower_seconds" in trace_rows[0]
    assert "relaxation_seconds" in trace_rows[0]


@pytest.mark.gurobi
@pytest.mark.slow
def test_solve_single_base_instance_preserves_base_folder(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_root = tmp_path / "data" / "instances"
    instance_path = input_root / "tiny_base_case.json"
    results_root = tmp_path / "results"
    run_id = "run_base_single"

    instance = generate_instance(
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
            seed=23,
            instance_name="tiny_base_case",
            tax_lower=0.0,
            tax_upper=20.0,
            connectivity=ArcConnectivityConfig(
                sf_neighbors=1,
                fw_neighbors=1,
                wr_neighbors=1,
                rf_neighbors=1,
            ),
        ),
    )
    write_instance(instance, instance_path)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/solver/solve_batch.py",
            str(instance_path),
            "--method",
            "dbp_lex",
            "--results-root",
            str(results_root),
            "--run-id",
            run_id,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    run_root = results_root / "base" / "tiny_base_case" / method_results_dir("dbp_lex", "exact")
    assert (run_root / "result.json").exists()
    assert (run_root / "dbp_trace.csv").exists()
    assert (run_root / "solution.json").exists()


@pytest.mark.gurobi
@pytest.mark.slow
def test_solve_single_non_base_instance_preserves_scenarios_folder(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_root = tmp_path / "data" / "instances" / "experiments" / "scenarios" / "custom"
    instance_path = input_root / "tiny_custom_case.json"
    results_root = tmp_path / "results"
    run_id = "run_scenario_single"

    instance = generate_instance(
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
            seed=31,
            instance_name="tiny_custom_case",
            tax_lower=10.0,
            tax_upper=30.0,
            connectivity=ArcConnectivityConfig(
                sf_neighbors=1,
                fw_neighbors=1,
                wr_neighbors=1,
                rf_neighbors=1,
            ),
        ),
    )
    write_instance(instance, instance_path)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/solver/solve_batch.py",
            str(instance_path),
            "--method",
            "dbp_lex",
            "--results-root",
            str(results_root),
            "--run-id",
            run_id,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    run_root = results_root / "experiments" / "scenarios" / "custom" / "tiny_custom_case" / method_results_dir("dbp_lex", "exact")
    assert (run_root / "result.json").exists()
    assert (run_root / "dbp_trace.csv").exists()
    assert (run_root / "solution.json").exists()


@pytest.mark.gurobi
@pytest.mark.slow
def test_solve_single_scenario_scope_writes_method_dir(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_root = tmp_path / "data" / "instances" / "experiments" / "scenarios" / "tech"
    instance_path = input_root / "tiny_scenario_case.json"
    results_root = tmp_path / "results"
    run_id = "tech_f_lex"

    instance = generate_instance(
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
            seed=37,
            instance_name="tiny_scenario_case",
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
    write_instance(instance, instance_path)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/solver/solve_batch.py",
            str(instance_path),
            "--results-root",
            str(results_root),
            "--run-id",
            run_id,
            "--method",
            "dbp_lex",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    run_root = results_root / "experiments" / "scenarios" / "tech" / "tiny_scenario_case" / method_results_dir(
        "dbp_lex",
        "exact",
    )
    instance_root = run_root
    assert (run_root / "manifest.json").exists()
    assert (run_root / "summary.json").exists()
    assert (instance_root / "result.json").exists()
    assert (instance_root / "dbp_trace.csv").exists()
    assert (instance_root / "solution.json").exists()

    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["results_scope"] == "experiments"
    result_payload = json.loads((instance_root / "result.json").read_text(encoding="utf-8"))
    assert result_payload["instance"]["relative_result_dir"] == "."


@pytest.mark.gurobi
@pytest.mark.slow
def test_solve_single_instance_overwrite_replaces_existing_results(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_root = tmp_path / "data" / "instances"
    instance_path = input_root / "tiny_overwrite_case.json"
    results_root = tmp_path / "results"

    instance = generate_instance(
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
            seed=43,
            instance_name="tiny_overwrite_case",
            tax_lower=0.0,
            tax_upper=20.0,
            connectivity=ArcConnectivityConfig(
                sf_neighbors=1,
                fw_neighbors=1,
                wr_neighbors=1,
                rf_neighbors=1,
            ),
        ),
    )
    write_instance(instance, instance_path)

    first_run = subprocess.run(
        [
            sys.executable,
            "tools/solver/solve_batch.py",
            str(instance_path),
            "--method",
            "dbp_lex",
            "--results-root",
            str(results_root),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first_run.returncode == 0, first_run.stderr

    run_root = results_root / "base" / "tiny_overwrite_case" / method_results_dir("dbp_lex", "exact")
    stale_file = run_root / "stale.txt"
    stale_file.write_text("old", encoding="utf-8")

    second_run = subprocess.run(
        [
            sys.executable,
            "tools/solver/solve_batch.py",
            str(instance_path),
            "--method",
            "dbp_lex",
            "--results-root",
            str(results_root),
            "--overwrite",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert second_run.returncode == 0, second_run.stderr
    assert not stale_file.exists()
    assert (run_root / "result.json").exists()


@pytest.mark.gurobi
@pytest.mark.slow
def test_solve_single_instance_skip_existing_keeps_existing_results(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_root = tmp_path / "data" / "instances"
    instance_path = input_root / "tiny_skip_case.json"
    results_root = tmp_path / "results"

    instance = generate_instance(
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
            seed=47,
            instance_name="tiny_skip_case",
            tax_lower=0.0,
            tax_upper=20.0,
            connectivity=ArcConnectivityConfig(
                sf_neighbors=1,
                fw_neighbors=1,
                wr_neighbors=1,
                rf_neighbors=1,
            ),
        ),
    )
    write_instance(instance, instance_path)

    first_run = subprocess.run(
        [
            sys.executable,
            "tools/solver/solve_batch.py",
            str(instance_path),
            "--method",
            "dbp_lex",
            "--results-root",
            str(results_root),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first_run.returncode == 0, first_run.stderr

    run_root = results_root / "base" / "tiny_skip_case" / method_results_dir("dbp_lex", "exact")
    marker_file = run_root / "marker.txt"
    marker_file.write_text("keep", encoding="utf-8")

    second_run = subprocess.run(
        [
            sys.executable,
            "tools/solver/solve_batch.py",
            str(instance_path),
            "--method",
            "dbp_lex",
            "--results-root",
            str(results_root),
            "--skip-existing",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert second_run.returncode == 0, second_run.stderr
    assert "Skipping existing run directory" in second_run.stderr
    assert marker_file.read_text(encoding="utf-8") == "keep"


def test_prepare_run_root_overwrite_clears_contents_when_root_delete_is_denied(tmp_path, monkeypatch) -> None:
    solve_instances_module = _load_solve_instances_module()
    run_root = tmp_path / "locked_run_root"
    nested_dir = run_root / "nested"
    nested_dir.mkdir(parents=True)
    stale_file = nested_dir / "stale.txt"
    stale_file.write_text("stale", encoding="utf-8")

    original_rmtree = solve_instances_module.shutil.rmtree

    def fake_rmtree(path, *args, **kwargs):
        if Path(path) == run_root:
            raise PermissionError("locked root")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(solve_instances_module.shutil, "rmtree", fake_rmtree)

    assert solve_instances_module.prepare_run_root(run_root, overwrite=True, skip_existing=False) is True
    assert run_root.exists()
    assert list(run_root.iterdir()) == []


def test_solve_instances_continues_after_failed_instance_and_writes_diagnostics(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_root = tmp_path / "inputs"
    valid_instance_path = input_root / "base" / "tiny_valid_case.json"
    invalid_instance_path = input_root / "base" / "tiny_invalid_case.json"
    results_root = tmp_path / "results"
    run_id = "run_mixed_batch"

    valid_instance = generate_instance(
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
            seed=23,
            instance_name="tiny_valid_case",
            tax_lower=0.0,
            tax_upper=20.0,
            connectivity=ArcConnectivityConfig(
                sf_neighbors=1,
                fw_neighbors=1,
                wr_neighbors=1,
                rf_neighbors=1,
            ),
        ),
    )
    write_instance(valid_instance, valid_instance_path)

    invalid_payload = generate_instance(
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
            seed=41,
            instance_name="tiny_invalid_case",
            tax_lower=0.0,
            tax_upper=20.0,
            connectivity=ArcConnectivityConfig(
                sf_neighbors=1,
                fw_neighbors=1,
                wr_neighbors=1,
                rf_neighbors=1,
            ),
        ),
    ).to_dict()
    invalid_payload["metadata"].setdefault("unit_convention", {})["raw_material_flow"] = "kg"
    invalid_instance_path.parent.mkdir(parents=True, exist_ok=True)
    invalid_instance_path.write_text(json.dumps(invalid_payload, indent=2), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "tools/solver/solve_batch.py",
            str(input_root),
            "--recursive",
            "--results-root",
            str(results_root),
            "--run-id",
            run_id,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1

    run_root = results_root / "base" / run_id
    summary_records = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    assert len(summary_records) == 2
    assert any(record["instance"] == "tiny_valid_case" and record["success"] is True for record in summary_records)
    failed_record = next(record for record in summary_records if record["instance"] == "tiny_invalid_case")
    assert failed_record["success"] is False
    assert failed_record["failure_stage"] == "instance_validation"

    assert (run_root / "tiny_valid_case" / "solution.json").exists()
    invalid_result = json.loads((run_root / "tiny_invalid_case" / "result.json").read_text(encoding="utf-8"))
    invalid_diagnostics = json.loads((run_root / "tiny_invalid_case" / "diagnostics.json").read_text(encoding="utf-8"))
    assert invalid_result["solve_status"]["success"] is False
    assert invalid_result["files"]["solution_file"] is None
    assert invalid_diagnostics["failure_stage"] == "instance_validation"


@pytest.mark.gurobi
@pytest.mark.slow
def test_solve_bilevel_dbp_lex_lower_bound_never_exceeds_upper_bound() -> None:
    """General safety net for the certified-gap framework: whatever the
    solver internals do, the reported lower bound must never exceed the
    reported upper bound (beyond a tiny numerical allowance) -- this is
    exactly the invariant a Stage-2 LB leak (or any other cross-model
    floating-point drift) could otherwise violate silently, since
    relative_optimality_gap clips negative gaps to zero instead of
    surfacing the inversion.
    """
    instance = generate_instance(
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
            seed=59,
            instance_name="tiny_lb_ub_invariant_case",
            tax_lower=0.0,
            tax_upper=20.0,
            connectivity=ArcConnectivityConfig(
                sf_neighbors=1,
                fw_neighbors=1,
                wr_neighbors=1,
                rf_neighbors=1,
            ),
        ),
    )

    result = solve_bilevel_dbp_lex(InstanceData.from_dict(instance.to_dict()))

    tolerance = max(1e-6, 1e-6 * abs(result.upper_bound))
    assert result.lower_bound <= result.upper_bound + tolerance


@pytest.mark.gurobi
@pytest.mark.slow
def test_solve_instances_supports_dbp_lex_method(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_root = tmp_path / "data" / "instances" / "base"
    instance_path = input_root / "tiny_lex_case.json"
    results_root = tmp_path / "results"
    run_id = "run_lex_test"

    instance = generate_instance(
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
            seed=29,
            instance_name="tiny_lex_case",
            tax_lower=0.0,
            tax_upper=20.0,
            connectivity=ArcConnectivityConfig(
                sf_neighbors=1,
                fw_neighbors=1,
                wr_neighbors=1,
                rf_neighbors=1,
            ),
        ),
    )
    write_instance(instance, instance_path)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/solver/solve_batch.py",
            str(instance_path),
            "--results-root",
            str(results_root),
            "--run-id",
            run_id,
            "--method",
            "dbp_lex",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr

    run_root = results_root / "base" / "tiny_lex_case" / method_results_dir("dbp_lex", "exact")
    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    result_payload = json.loads((run_root / "result.json").read_text(encoding="utf-8"))

    assert manifest["solver"]["method"] == "dbp_lex"
    assert manifest["solver"]["mode"] == "exact"
    assert manifest["solver"]["tolerances"]["dbp_relative_gap"] == DEFAULT.dbp_relative_gap
    assert manifest["solver"]["tolerances"]["mip_gap"] == DEFAULT.mip_gap
    assert manifest["solver"]["leader_objective"] == "lex_emissions_then_min_tax_index"
    assert result_payload["solve_status"]["method"] == "dbp_lex"
    assert result_payload["solve_status"]["mode"] == "exact"
    assert result_payload["bounds"]["certificates"]["upper"]["source"] == "lexicographic"
    assert "lex_primary_mip_gap" in result_payload["follower"]
    assert "lex_secondary_mip_gap" in result_payload["follower"]
    assert result_payload["runtime"]["subproblem_seconds"]["optimistic_total"] == 0.0
    assert result_payload["phase_summary"]["dbp_iterations"] == result_payload["dbp"]["trace_rows"]
    assert result_payload["phase_summary"]["final_tax_index"] == result_payload["leader"]["tax_index"]

    with (run_root / "dbp_trace.csv").open("r", encoding="utf-8", newline="") as handle:
        dbp_trace_rows = list(csv.DictReader(handle))
    assert dbp_trace_rows
    assert "relaxation_tax_index" in dbp_trace_rows[0]
    assert "next_relaxation_tax_index" in dbp_trace_rows[0]


def test_is_better_candidate_treats_large_scale_near_ties_as_ties() -> None:
    """At realistic emissions magnitudes (~1e8 kg, per the project's
    instances), a bare absolute eps (1e-7) sits far below ordinary
    cross-model floating-point reconstruction noise. The clearest place
    this bites: the strict-improvement branch is a plain linear inequality
    with no magnitude scaling at all (unlike math.isclose's branch, which
    gets an incidental assist from its own default relative tolerance) --
    so a noise-level emissions "decrease" of a few kg, well above 1e-7 but
    utterly negligible at this scale, used to be accepted as a genuine
    improvement even when it meant switching to a *larger* tax. That
    violates the leader's least-intervention tie-break (eq:leader_obj):
    never pay a heavier tax than the emissions target requires.
    """
    from clsc.solvers.dbp_lex import IncumbentSolution, _is_better_candidate

    smaller_tax_incumbent = IncumbentSolution(tax_index=14, cost=1.0, emissions=1.5e8, follower_objective=1.0)
    larger_tax_noise_candidate = IncumbentSolution(
        tax_index=20, cost=1.0, emissions=1.5e8 - 1.0, follower_objective=1.0
    )
    # 1 kg "lower" emissions out of 1.5e8 kg is noise, not a real
    # improvement -- paying a higher tax for it must be rejected.
    assert _is_better_candidate(larger_tax_noise_candidate, smaller_tax_incumbent) is False

    larger_tax_incumbent = IncumbentSolution(tax_index=20, cost=1.0, emissions=1.5e8, follower_objective=1.0)
    smaller_tax_tied_candidate = IncumbentSolution(
        tax_index=14, cost=1.0, emissions=1.5e8 + 1e-3, follower_objective=1.0
    )
    # The reverse direction: a smaller-tax candidate within noise-level
    # tolerance of the incumbent's emissions must still win the tie-break.
    assert _is_better_candidate(smaller_tax_tied_candidate, larger_tax_incumbent) is True

    genuinely_worse_candidate = IncumbentSolution(tax_index=14, cost=1.0, emissions=1.5e8 + 1000.0, follower_objective=1.0)
    # A difference far above the magnitude-scaled tolerance is still a
    # real emissions regression, regardless of how small its tax index is.
    assert _is_better_candidate(genuinely_worse_candidate, larger_tax_incumbent) is False


def test_extract_failure_trace_rows_reads_partial_trace_from_subproblem_error() -> None:
    module = _load_solve_instances_module()
    error = SubproblemStatusError(
        "DBP relaxation after iteration 2",
        SolveResult(GRB.INFEASIBLE, "INFEASIBLE", False, None, None, None, None, None, None, 0.0),
        trace_rows=(
            {
                "iteration": 1,
                "relaxation_tax_index": 0,
                "relaxation_lower_bound": 0.1,
                "follower_seconds": 1.0,
                "follower_objective": 2.0,
                "incumbent_emissions": 4.0,
                "relaxation_seconds": 5.0,
                "next_relaxation_tax_index": -1,
                "next_relaxation_lower_bound": float("nan"),
            },
        ),
    )

    trace_rows = module.extract_failure_trace_rows(error)

    assert len(trace_rows) == 1
    assert trace_rows[0]["iteration"] == 1
    assert trace_rows[0]["next_relaxation_tax_index"] == -1


def test_canonicalize_result_solution_uses_recomputed_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_solve_instances_module()
    instance = object()
    optimistic = SolveResult(
        GRB.OPTIMAL,
        "OPTIMAL",
        True,
        30.0,
        10.0,
        20.0,
        30.0,
        1,
        0.0,
        0.0,
        variable_values={"x": 1.0},
    )
    result = BilevelSolveResult(
        method="dbp_lex",
        mode="exact",
        termination_reason="relative_gap",
        exact=True,
        iterations=1,
        lower_bound=20.0,
        upper_bound=20.0,
        lower_bound_certificate=BoundCertificate(20.0, True, 0.0, 0.0, "relaxation"),
        upper_bound_certificate=BoundCertificate(20.0, True, 0.0, 0.0, "optimistic"),
        incumbent=IncumbentSolution(tax_index=1, cost=1.0, emissions=2.0, follower_objective=3.0),
        iteration_records=(),
        dbp_timing=DbpTimingSummary(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ()),
        incumbent_solution=optimistic,
    )

    def fake_validate_fixed_tax_solution(*args, **kwargs):
        return SolveResult(
            GRB.OPTIMAL,
            "OPTIMAL",
            True,
            31.0,
            11.0,
            20.0,
            31.0,
            1,
            0.0,
            0.0,
        )

    monkeypatch.setattr(module, "validate_fixed_tax_solution", fake_validate_fixed_tax_solution)

    canonical = module.canonicalize_result_solution(instance=instance, result=result)

    assert canonical.incumbent.cost == pytest.approx(11.0)
    assert canonical.incumbent.emissions == pytest.approx(20.0)
    assert canonical.incumbent.follower_objective == pytest.approx(31.0)
    assert canonical.incumbent_solution is not None
    assert canonical.incumbent_solution.cost == pytest.approx(11.0)
    assert canonical.incumbent_solution.emissions == pytest.approx(20.0)
    assert canonical.incumbent_solution.follower_objective == pytest.approx(31.0)


def test_canonicalize_result_solution_repairs_lexicographic_cached_solution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_solve_instances_module()
    instance = object()
    optimistic = SolveResult(
        GRB.OPTIMAL,
        "OPTIMAL",
        True,
        30.0,
        10.0,
        20.0,
        30.0,
        1,
        0.0,
        0.0,
        variable_values={"trip[a,b,m,t]": 8e-6, "x[u,a,b,m,t]": 0.1},
    )
    repaired = SolveResult(
        GRB.OPTIMAL,
        "OPTIMAL",
        True,
        31.0,
        11.0,
        19.5,
        31.0,
        1,
        0.0,
        0.0,
        variable_values={"trip[a,b,m,t]": 1.0, "x[u,a,b,m,t]": 0.1},
    )
    result = BilevelSolveResult(
        method="dbp_lex",
        mode="exact",
        termination_reason="relative_gap",
        exact=True,
        iterations=1,
        lower_bound=19.5,
        upper_bound=19.5,
        lower_bound_certificate=BoundCertificate(19.5, True, 0.0, 0.0, "relaxation"),
        upper_bound_certificate=BoundCertificate(19.5, True, 0.0, 0.0, "optimistic"),
        incumbent=IncumbentSolution(tax_index=1, cost=10.0, emissions=20.0, follower_objective=30.0),
        iteration_records=(),
        dbp_timing=DbpTimingSummary(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ()),
        incumbent_solution=optimistic,
    )

    calls = {"count": 0}

    def fake_validate_fixed_tax_solution(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return SolveResult(
                GRB.INFEASIBLE,
                "INFEASIBLE",
                False,
                None,
                None,
                None,
                None,
                1,
                None,
                0.0,
            )
        return SolveResult(
            GRB.OPTIMAL,
            "OPTIMAL",
            True,
            31.0,
            11.0,
            19.5,
            31.0,
            1,
            0.0,
            0.0,
        )

    monkeypatch.setattr(module, "validate_fixed_tax_solution", fake_validate_fixed_tax_solution)
    monkeypatch.setattr(
        module,
        "rebuild_lexicographic_solution_with_fixed_discrete_values",
        lambda **kwargs: repaired,
    )

    canonical = module.canonicalize_result_solution(instance=instance, result=result)

    assert calls["count"] == 2
    assert canonical.incumbent.cost == pytest.approx(11.0)
    assert canonical.incumbent.emissions == pytest.approx(19.5)
    assert canonical.incumbent.follower_objective == pytest.approx(31.0)
    assert canonical.incumbent_solution is not None
    assert canonical.incumbent_solution.variable_values == repaired.variable_values
