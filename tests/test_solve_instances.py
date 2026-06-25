from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
from gurobipy import GRB

from data.generator import ArcConnectivityConfig, GeneratorConfig, generate_instance, write_instance
from src.models.instance_loader import InstanceData
from src.models.shared_models import SolveResult
from src.solvers.dbp_exact import (
    BilevelSolveResult,
    BoundCertificate,
    DbpTimingSummary,
    IncumbentSolution,
    SubproblemStatusError,
)


def _load_solve_instances_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "solver" / "solve_batch.py"
    spec = importlib.util.spec_from_file_location("solve_instances_tool", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def method_results_dir(method: str, mode: str) -> str:
    if method == "dbp_exact":
        return "exact"
    if method == "dbp_certified":
        return "certified"
    if method == "dbp_f_lex_exact":
        return "f_lex_exact"
    if method == "dbp_lf_lex_exact":
        return "lf_lex_exact"
    if method == "enumeration_lf_lex_exact":
        return "enum_lf_lex_exact"
    return f"{method}_{mode}"


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

    run_root = results_root / "base" / "tiny_cli_case" / method_results_dir("dbp_exact", "exact")
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
    assert manifest["solver"]["method"] == "dbp_exact"
    assert manifest["solver"]["mode"] == "exact"
    assert manifest["solver"]["tolerances"]["dbp_relative_gap"] == 1.0e-4
    assert manifest["solver"]["tolerances"]["lex_epsilon_prime"] == 0.1
    assert manifest["solver"]["tolerances"]["mip_gap"] == 1.0e-4
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
    assert result_payload["runtime"]["lexicographic"] == 0.0
    assert result_payload["runtime"]["phase_seconds"]["dbp_subproblems"] >= 0.0
    assert result_payload["runtime"]["phase_seconds"]["lexicographic_tiebreak"] == 0.0
    assert result_payload["runtime"]["subproblem_seconds"]["total"] >= 0.0
    assert result_payload["validation"]["status"] == "validated"
    assert result_payload["bounds"]["certificates"]["lower"]["source"] == "relaxation"
    assert result_payload["bounds"]["certificates"]["upper"]["source"] == "optimistic"
    assert result_payload["dbp"]["trace_file"] == "dbp_trace.csv"
    assert result_payload["dbp"]["timings"]["initial_relaxation_seconds"] >= 0.0
    assert len(result_payload["dbp"]["timings"]["iterations"]) == result_payload["dbp"]["trace_rows"]
    assert result_payload["phase_summary"]["phase_1_dbp_iterations"] == result_payload["dbp"]["trace_rows"]
    assert result_payload["phase_summary"]["phase_2_lexicographic_iterations"] == 0
    assert result_payload["lexicographic_tiebreak"] is None
    assert result_payload["files"]["solution_file"] == "solution.json"
    assert result_payload["files"]["lex_trace_file"] is None

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
    run_root = results_root / "base" / "tiny_base_case" / method_results_dir("dbp_exact", "exact")
    assert (run_root / "result.json").exists()
    assert (run_root / "dbp_trace.csv").exists()
    assert (run_root / "solution.json").exists()


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
    run_root = results_root / "experiments" / "scenarios" / "custom" / "tiny_custom_case" / method_results_dir("dbp_exact", "exact")
    assert (run_root / "result.json").exists()
    assert (run_root / "dbp_trace.csv").exists()
    assert (run_root / "solution.json").exists()


def test_solve_single_scenario_scope_writes_method_dir(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_root = tmp_path / "data" / "instances" / "experiments" / "scenarios" / "tech"
    instance_path = input_root / "tiny_scenario_case.json"
    results_root = tmp_path / "results"
    run_id = "tech_lf_lex"

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
            "dbp_lf_lex_exact",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    run_root = results_root / "experiments" / "scenarios" / "tech" / "tiny_scenario_case" / method_results_dir(
        "dbp_lf_lex_exact",
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
            "--results-root",
            str(results_root),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first_run.returncode == 0, first_run.stderr

    run_root = results_root / "base" / "tiny_overwrite_case" / method_results_dir("dbp_exact", "exact")
    stale_file = run_root / "stale.txt"
    stale_file.write_text("old", encoding="utf-8")

    second_run = subprocess.run(
        [
            sys.executable,
            "tools/solver/solve_batch.py",
            str(instance_path),
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
            "--results-root",
            str(results_root),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first_run.returncode == 0, first_run.stderr

    run_root = results_root / "base" / "tiny_skip_case" / method_results_dir("dbp_exact", "exact")
    marker_file = run_root / "marker.txt"
    marker_file.write_text("keep", encoding="utf-8")

    second_run = subprocess.run(
        [
            sys.executable,
            "tools/solver/solve_batch.py",
            str(instance_path),
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
            "dbp_f_lex_exact",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr

    run_root = results_root / "base" / "tiny_lex_case" / method_results_dir("dbp_f_lex_exact", "exact")
    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    result_payload = json.loads((run_root / "result.json").read_text(encoding="utf-8"))

    assert manifest["solver"]["method"] == "dbp_f_lex_exact"
    assert manifest["solver"]["mode"] == "exact"
    assert manifest["solver"]["tolerances"]["dbp_relative_gap"] == 1.0e-4
    assert manifest["solver"]["tolerances"]["mip_gap"] == 1.0e-4
    assert result_payload["solve_status"]["method"] == "dbp_f_lex_exact"
    assert result_payload["solve_status"]["mode"] == "exact"
    assert result_payload["bounds"]["certificates"]["upper"]["source"] == "lexicographic"
    assert "lex_primary_mip_gap" in result_payload["follower"]
    assert "lex_secondary_mip_gap" in result_payload["follower"]
    assert result_payload["runtime"]["subproblem_seconds"]["optimistic_total"] == 0.0
    assert result_payload["runtime"]["lexicographic"] == 0.0
    assert result_payload["lexicographic_tiebreak"] is None
def test_solve_instances_supports_dbp_lf_lex_method(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_root = tmp_path / "data" / "instances" / "base"
    instance_path = input_root / "tiny_lf_lex_case.json"
    results_root = tmp_path / "results"
    run_id = "run_lf_lex_test"

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
            seed=41,
            instance_name="tiny_lf_lex_case",
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
            "dbp_lf_lex_exact",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr

    run_root = results_root / "base" / "tiny_lf_lex_case" / method_results_dir("dbp_lf_lex_exact", "exact")
    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    result_payload = json.loads((run_root / "result.json").read_text(encoding="utf-8"))

    assert manifest["solver"]["method"] == "dbp_lf_lex_exact"
    assert manifest["solver"]["mode"] == "exact"
    assert manifest["solver"]["tolerances"]["dbp_relative_gap"] == 1.0e-4
    assert manifest["solver"]["tolerances"]["mip_gap"] == 1.0e-4
    assert manifest["solver"]["tolerances"]["eps"] == 1.0e-7
    assert manifest["solver"]["tolerances"]["lex_epsilon_prime"] == 0.1
    assert manifest["solver"]["leader_objective"] == "lex_emissions_then_min_hat_tau"
    assert "lex_trace.csv" in manifest["outputs"]["per_instance"]
    assert result_payload["solve_status"]["method"] == "dbp_lf_lex_exact"
    assert result_payload["solve_status"]["mode"] == "exact"
    assert result_payload["lexicographic_tiebreak"] is not None
    assert result_payload["lexicographic_tiebreak"]["trace_rows"] == result_payload["lexicographic_tiebreak"]["attempt_count"]
    assert result_payload["phase_summary"]["phase_1_dbp_iterations"] == result_payload["dbp"]["trace_rows"]
    assert (
        result_payload["phase_summary"]["phase_2_lexicographic_iterations"]
        == result_payload["lexicographic_tiebreak"]["trace_rows"]
    )
    assert result_payload["phase_summary"]["phase_1_selected_hat_tau"] == result_payload["lexicographic_tiebreak"]["initial_hat_tau"]
    assert result_payload["phase_summary"]["phase_2_selected_hat_tau"] == result_payload["lexicographic_tiebreak"]["selected_hat_tau"]
    assert result_payload["phase_summary"]["final_hat_tau"] == result_payload["leader"]["hat_tau"]
    assert result_payload["files"]["lex_trace_file"] == "lex_trace.csv"

    with (run_root / "dbp_trace.csv").open("r", encoding="utf-8", newline="") as handle:
        dbp_trace_rows = list(csv.DictReader(handle))
    assert dbp_trace_rows
    assert "relaxation_hat_tau" in dbp_trace_rows[0]
    assert "next_relaxation_hat_tau" in dbp_trace_rows[0]

    with (run_root / "lex_trace.csv").open("r", encoding="utf-8", newline="") as handle:
        refinement_trace_rows = list(csv.DictReader(handle))
    assert refinement_trace_rows
    assert "tested_hat_tau" in refinement_trace_rows[0]
    assert "matched_incumbent_emissions" in refinement_trace_rows[0]
    assert "follower_objective" in refinement_trace_rows[0]
    assert any(row["selected"] == "True" for row in refinement_trace_rows)


def test_solve_instances_supports_enumeration_lf_lex_method(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_root = tmp_path / "data" / "instances" / "base"
    instance_path = input_root / "tiny_enum_lf_lex_case.json"
    results_root = tmp_path / "results"
    run_id = "run_enum_lf_lex_test"

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
            instance_name="tiny_enum_lf_lex_case",
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
            "enumeration_lf_lex_exact",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr

    run_root = results_root / "base" / "tiny_enum_lf_lex_case" / method_results_dir(
        "enumeration_lf_lex_exact",
        "exact",
    )
    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    result_payload = json.loads((run_root / "result.json").read_text(encoding="utf-8"))
    enumeration_solutions_path = run_root / "enumeration_solutions.json"

    assert manifest["solver"]["method"] == "enumeration_lf_lex_exact"
    assert manifest["solver"]["mode"] == "exact"
    assert manifest["solver"]["tolerances"]["mip_gap"] == 1.0e-4
    assert manifest["solver"]["tolerances"]["eps"] == 1.0e-7
    assert manifest["solver"]["tolerances"]["lex_epsilon_prime"] == 0.1
    assert manifest["solver"]["enumeration_oracle"] is True
    assert manifest["solver"]["leader_objective"] == "lex_emissions_then_min_hat_tau"
    assert "enumeration_solutions.json" in manifest["outputs"]["per_instance"]
    assert result_payload["solve_status"]["method"] == "enumeration_lf_lex_exact"
    assert result_payload["solve_status"]["termination_reason"] == "enumerated_tax_range"
    assert result_payload["files"]["enumeration_solutions_file"] == "enumeration_solutions.json"
    expected_iterations = len(tuple(InstanceData.from_dict(instance.to_dict()).iter_hat_tau()))
    assert result_payload["solve_status"]["iterations"] == expected_iterations
    assert result_payload["bounds"]["relative_gap"] == 0.0

    solution_payload = json.loads((run_root / "solution.json").read_text(encoding="utf-8"))
    assert solution_payload["decision_variables"]["leader"]["hat_tau"] == solution_payload["leader"]["hat_tau"]
    assert solution_payload["decision_variables"]["leader"]["effective_tax"] == solution_payload["leader"]["effective_tax"]
    assert solution_payload["decision_variables"]["follower"] == solution_payload["variables"]
    assert solution_payload["decision_variables"]["follower"]

    assert enumeration_solutions_path.exists()
    enumeration_payload = json.loads(enumeration_solutions_path.read_text(encoding="utf-8"))
    assert enumeration_payload["selected_hat_tau"] == solution_payload["leader"]["hat_tau"]
    assert len(enumeration_payload["tax_solutions"]) == expected_iterations
    assert any(candidate["selected_incumbent"] for candidate in enumeration_payload["tax_solutions"])
    first_candidate = enumeration_payload["tax_solutions"][0]
    assert first_candidate["decision_variables"]["leader"]["hat_tau"] == first_candidate["leader"]["hat_tau"]
    assert first_candidate["decision_variables"]["leader"]["effective_tax"] == first_candidate["leader"]["effective_tax"]
    assert first_candidate["decision_variables"]["follower"] == first_candidate["variables"]
    assert first_candidate["decision_variables"]["follower"]


def test_solve_instances_can_validate_dbp_with_enumeration_oracle(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_root = tmp_path / "data" / "instances" / "base"
    instance_path = input_root / "tiny_oracle_validation_case.json"
    results_root = tmp_path / "results"
    run_id = "run_oracle_validation_test"

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
            instance_name="tiny_oracle_validation_case",
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
            "dbp_lf_lex_exact",
            "--validate-with-enumeration-oracle",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr

    run_root = results_root / "base" / "tiny_oracle_validation_case" / method_results_dir(
        "dbp_lf_lex_exact",
        "exact",
    )
    result_payload = json.loads((run_root / "result.json").read_text(encoding="utf-8"))

    assert result_payload["solve_status"]["method"] == "dbp_lf_lex_exact"
    assert result_payload["oracle_validation"]["status"] == "validated"
    assert result_payload["oracle_validation"]["hat_tau_match"] is True
    assert result_payload["oracle_validation"]["emissions_match"] is True


def test_extract_failure_trace_rows_reads_partial_trace_from_subproblem_error() -> None:
    module = _load_solve_instances_module()
    error = SubproblemStatusError(
        "DBP relaxation after iteration 2",
        SolveResult(GRB.INFEASIBLE, "INFEASIBLE", False, None, None, None, None, None, None, 0.0),
        trace_rows=(
            {
                "iteration": 1,
                "relaxation_hat_tau": 0,
                "relaxation_lower_bound": 0.1,
                "follower_seconds": 1.0,
                "follower_objective": 2.0,
                "incumbent_emissions": 4.0,
                "relaxation_seconds": 5.0,
                "next_relaxation_hat_tau": -1,
                "next_relaxation_lower_bound": float("nan"),
            },
        ),
    )

    trace_rows = module.extract_failure_trace_rows(error)

    assert len(trace_rows) == 1
    assert trace_rows[0]["iteration"] == 1
    assert trace_rows[0]["next_relaxation_hat_tau"] == -1


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
        method="dbp_exact",
        mode="exact",
        termination_reason="relative_gap",
        exact=True,
        iterations=1,
        lower_bound=20.0,
        upper_bound=20.0,
        lower_bound_certificate=BoundCertificate(20.0, True, 0.0, 0.0, "relaxation"),
        upper_bound_certificate=BoundCertificate(20.0, True, 0.0, 0.0, "optimistic"),
        incumbent=IncumbentSolution(hat_tau=1, cost=1.0, emissions=2.0, follower_objective=3.0),
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
        method="dbp_lf_lex_exact",
        mode="exact",
        termination_reason="relative_gap",
        exact=True,
        iterations=1,
        lower_bound=19.5,
        upper_bound=19.5,
        lower_bound_certificate=BoundCertificate(19.5, True, 0.0, 0.0, "relaxation"),
        upper_bound_certificate=BoundCertificate(19.5, True, 0.0, 0.0, "optimistic"),
        incumbent=IncumbentSolution(hat_tau=1, cost=10.0, emissions=20.0, follower_objective=30.0),
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
