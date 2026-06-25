from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config.gap_tol import DEFAULT
from src.models.shared_models import (
    build_fixed_tax_follower_master,
    solve_fixed_tax_lexicographic,
    validate_fixed_tax_solution,
)
from src.models.instance_loader import InstanceData, InstanceValidationError
from src.solvers.dbp_exact import (
    BilevelSolveError,
    DEFAULT_DBP_MODE,
    SubproblemStatusError,
    relative_optimality_gap,
    solve_bilevel_dbp,
)
from src.solvers.dbp_f_lex_exact import solve_bilevel_dbp_f_lex_exact
from src.solvers.dbp_lf_lex_exact import solve_bilevel_dbp_lf_lex_exact
from src.solvers.enum_lf_lex_exact import (
    solve_bilevel_enumeration_lf_lex_exact,
    validate_result_against_enumeration_oracle,
)

SUPPORTED_SOLVER_METHODS = (
    "dbp_exact",
    "dbp_certified",
    "dbp_f_lex_exact",
    "dbp_lf_lex_exact",
    "enumeration_lf_lex_exact",
)

LEXICOGRAPHIC_SOLVER_METHODS = {
    "dbp_f_lex_exact",
    "dbp_lf_lex_exact",
    "enumeration_lf_lex_exact",
}

SOLVER_METHOD_RESULT_DIRS = {
    "dbp_exact": "exact",
    "dbp_certified": "certified",
    "dbp_f_lex_exact": "f_lex_exact",
    "dbp_lf_lex_exact": "lf_lex_exact",
    "enumeration_lf_lex_exact": "enum_lf_lex_exact",
}

RESULT_SCHEMA_VERSION = 2
INTEGER_SNAP_TOL = max(DEFAULT.eps, 1e-5)
SUMMARY_FIELDNAMES = [
    "instance",
    "input_path",
    "success",
    "exact",
    "termination_reason",
    "iterations",
    "hat_tau",
    "effective_tax",
    "cost",
    "emissions",
    "follower_objective",
    "lower_bound",
    "upper_bound",
    "relative_gap",
    "validation_status",
    "failure_stage",
    "error_type",
    "error_message",
    "gurobi_status",
    "objective_bound",
    "iis_constraints",
    "solve_seconds",
]
TRACE_FIELDNAMES = [
    "iteration",
    "relaxation_hat_tau",
    "relaxation_lower_bound",
    "follower_seconds",
    "follower_objective",
    "incumbent_emissions",
    "relaxation_seconds",
    "next_relaxation_hat_tau",
    "next_relaxation_lower_bound",
]
TAU_REFINEMENT_TRACE_FIELDNAMES = [
    "iteration",
    "tested_hat_tau",
    "solve_seconds",
    "emissions",
    "follower_objective",
    "matched_incumbent_emissions",
    "selected",
]


class OutputValidationError(RuntimeError):
    """Raised when a saved incumbent cannot be revalidated from solution data."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Solve generated CLSC bilevel instances and write structured run results.",
    )
    parser.add_argument("path", help="Path to an instance JSON file or a directory containing instance files.")
    parser.add_argument("--pattern", default="*.json", help="Glob pattern used when path is a directory.")
    parser.add_argument("--recursive", action="store_true", help="Search directories recursively.")
    parser.add_argument(
        "--method",
        choices=SUPPORTED_SOLVER_METHODS,
        default="dbp_exact",
        help=(
            "DBP algorithm variant. Accepted values are 'dbp_exact', 'dbp_certified', "
            "'dbp_f_lex_exact', 'dbp_lf_lex_exact', and 'enumeration_lf_lex_exact'."
        ),
    )
    parser.add_argument("--max-iterations", type=int, help="Maximum DBP iterations.")
    parser.add_argument("--time-limit", type=float, help="Per-subproblem Gurobi time limit in seconds.")
    parser.add_argument(
        "--dbp-mode",
        choices=("exact", "certified"),
        help=(
            "Optional consistency check for the chosen method. When omitted, the method's natural mode is used."
        ),
    )
    parser.add_argument("--solver-output", action="store_true", help="Show raw Gurobi output.")
    parser.add_argument(
        "--validate-with-enumeration-oracle",
        action="store_true",
        help=(
            "After solving dbp_lf_lex_exact, solve the pure enumeration lex-follower oracle "
            "and fail the run if the DBP incumbent differs in emissions or hat_tau."
        ),
    )
    parser.add_argument(
        "--results-root",
        default="results/runs",
        help="Root directory where run folders are created.",
    )
    parser.add_argument(
        "--results-scope",
        choices=("auto", "sensitivity"),
        default="auto",
        help=(
            "Optional output layout override. Use 'sensitivity' to write results under "
            "<results-root>/sensitivity/<run-id>/<instance-name>."
        ),
    )
    parser.add_argument(
        "--run-id",
        help="Optional run identifier. Defaults to a UTC timestamp-based id.",
    )
    parser.add_argument(
        "--output",
        help="Optional compatibility path where the aggregated summary JSON is also written.",
    )
    existing_results_group = parser.add_mutually_exclusive_group()
    existing_results_group.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete an existing target run directory before writing new results.",
    )
    existing_results_group.add_argument(
        "--skip-existing",
        action="store_true",
        help="Return success without solving when the target run directory already exists.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Abort the batch after the first failed instance instead of continuing to the remaining files.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.method, args.dbp_mode = canonicalize_solver_method(args.method, args.dbp_mode)
    except ValueError as error:
        parser.error(str(error))
    if args.validate_with_enumeration_oracle and args.method != "dbp_lf_lex_exact":
        parser.error("--validate-with-enumeration-oracle is currently only supported for dbp_lf_lex_exact")

    target = Path(args.path)
    instance_paths = collect_instance_paths(target, pattern=args.pattern, recursive=args.recursive)
    single_instance_run = len(instance_paths) == 1
    run_id = args.run_id or build_run_id()
    canonical_dirs = {instance_path: build_canonical_instance_dir(instance_path, target) for instance_path in instance_paths}
    inferred_run_scope = infer_run_scope(canonical_dirs.values())
    run_scope = "sensitivity" if args.results_scope == "sensitivity" else inferred_run_scope
    run_root = build_run_root(
        Path(args.results_root),
        run_scope,
        run_id,
        canonical_dirs=canonical_dirs,
        single_instance_run=single_instance_run,
        method=args.method,
        mode=args.dbp_mode,
    )
    if not prepare_run_root(
        run_root,
        overwrite=bool(args.overwrite),
        skip_existing=bool(args.skip_existing),
    ):
        return 0
    run_root.mkdir(parents=True, exist_ok=bool(args.overwrite))

    write_json(
        run_root / "manifest.json",
        build_manifest(
            run_id=run_id,
            target=target,
            instance_paths=instance_paths,
            run_scope=run_scope,
            args=args,
        ),
    )

    summary_records: list[dict[str, object]] = []
    failed_instances = 0
    for instance_path in instance_paths:
        relative_instance_dir = build_relative_instance_dir(
            canonical_dirs[instance_path],
            run_scope,
            single_instance_run=single_instance_run,
            method=args.method,
            mode=args.dbp_mode,
        )
        instance_results_dir = run_root / relative_instance_dir
        instance_results_dir.mkdir(parents=True, exist_ok=True)

        started_at = time.perf_counter()
        instance: InstanceData | None = None
        try:
            instance = InstanceData.from_file(instance_path)
            solve_started_at = time.perf_counter()
            if args.method == "dbp_f_lex_exact":
                result = solve_bilevel_dbp_f_lex_exact(
                    instance,
                    max_iterations=args.max_iterations,
                    output_flag=args.solver_output,
                    time_limit=args.time_limit,
                )
            elif args.method == "dbp_lf_lex_exact":
                result = solve_bilevel_dbp_lf_lex_exact(
                    instance,
                    max_iterations=args.max_iterations,
                    output_flag=args.solver_output,
                    time_limit=args.time_limit,
                )
            elif args.method == "enumeration_lf_lex_exact":
                result = solve_bilevel_enumeration_lf_lex_exact(
                    instance,
                    output_flag=args.solver_output,
                    time_limit=args.time_limit,
                )
            elif args.method in {"dbp_exact", "dbp_certified"}:
                result = solve_bilevel_dbp(
                    instance,
                    max_iterations=args.max_iterations,
                    output_flag=args.solver_output,
                    time_limit=args.time_limit,
                    mode=args.dbp_mode,
                )
            else:
                raise ValueError(f"Unsupported solver method {args.method!r}")
            result = canonicalize_result_solution(instance=instance, result=result)
            dbp_solve_seconds = round(time.perf_counter() - solve_started_at, 6)
            validation_started_at = time.perf_counter()
            solution_validation = validate_result_solution(instance=instance, result=result)
            oracle_validation = None
            if args.validate_with_enumeration_oracle:
                oracle_validation_result, _oracle = validate_result_against_enumeration_oracle(
                    instance,
                    result,
                    output_flag=args.solver_output,
                    time_limit=args.time_limit,
                )
                oracle_validation = asdict(oracle_validation_result)
                if not oracle_validation_result.matched:
                    raise OutputValidationError(
                        "Enumeration oracle mismatch: "
                        f"candidate hat_tau={oracle_validation_result.candidate_hat_tau}, "
                        f"oracle hat_tau={oracle_validation_result.oracle_hat_tau}, "
                        f"emissions_delta={oracle_validation_result.emissions_delta}"
                    )
            validation_seconds = round(time.perf_counter() - validation_started_at, 6)
            solve_seconds = round(time.perf_counter() - started_at, 6)

            summary_record = build_summary_record(
                instance=instance,
                instance_path=instance_path,
                result=result,
                solve_seconds=solve_seconds,
                solution_validation=solution_validation,
            )
            summary_records.append(summary_record)
            print(json.dumps(summary_record))

            write_json(
                instance_results_dir / "result.json",
                build_instance_result_payload(
                    run_id=run_id,
                    instance=instance,
                    instance_path=instance_path,
                    relative_instance_dir=relative_instance_dir,
                    result=result,
                    solve_seconds=solve_seconds,
                    dbp_solve_seconds=dbp_solve_seconds,
                    validation_seconds=validation_seconds,
                    solution_validation=solution_validation,
                    oracle_validation=oracle_validation,
                ),
            )
            write_json(
                instance_results_dir / "solution.json",
                build_solution_payload(
                    instance=instance,
                    result=result,
                    solution_validation=solution_validation,
                ),
            )
            enumeration_solutions_payload = build_enumeration_solutions_payload(
                instance=instance,
                result=result,
            )
            if enumeration_solutions_payload is not None:
                write_json(
                    instance_results_dir / "enumeration_solutions.json",
                    enumeration_solutions_payload,
                )
            write_csv(
                instance_results_dir / "dbp_trace.csv",
                TRACE_FIELDNAMES,
                build_dbp_trace_rows(result),
            )
            tau_refinement_trace_rows = build_tau_refinement_trace_rows(result)
            if tau_refinement_trace_rows:
                write_csv(
                    instance_results_dir / "lex_trace.csv",
                    TAU_REFINEMENT_TRACE_FIELDNAMES,
                    tau_refinement_trace_rows,
                )
        except Exception as error:
            failed_instances += 1
            solve_seconds = round(time.perf_counter() - started_at, 6)
            failure_trace_rows = extract_failure_trace_rows(error)
            summary_record = build_failure_summary_record(
                instance=instance,
                instance_path=instance_path,
                error=error,
                solve_seconds=solve_seconds,
            )
            summary_records.append(summary_record)
            print(json.dumps(summary_record))

            failure_payload = build_failure_result_payload(
                run_id=run_id,
                instance=instance,
                instance_path=instance_path,
                relative_instance_dir=relative_instance_dir,
                error=error,
                solve_seconds=solve_seconds,
                method=args.method,
                mode=args.dbp_mode,
            )
            write_json(instance_results_dir / "result.json", failure_payload)
            if failure_trace_rows:
                write_csv(
                    instance_results_dir / "dbp_trace.csv",
                    TRACE_FIELDNAMES,
                    failure_trace_rows,
                )

            diagnostics = failure_payload.get("diagnostics")
            if diagnostics is not None:
                write_json(instance_results_dir / "diagnostics.json", diagnostics)

            if args.fail_fast:
                break

    write_json(run_root / "summary.json", summary_records)
    write_csv(run_root / "summary.csv", SUMMARY_FIELDNAMES, summary_records)

    if args.output:
        write_json(Path(args.output), summary_records)

    return 0 if failed_instances == 0 else 1


def collect_instance_paths(path: Path, *, pattern: str, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(f"{path} does not exist")

    paths = path.rglob(pattern) if recursive else path.glob(pattern)
    return sorted(candidate for candidate in paths if candidate.is_file())


def prepare_run_root(
    run_root: Path,
    *,
    overwrite: bool,
    skip_existing: bool,
) -> bool:
    if not run_root.exists():
        return True
    if skip_existing:
        print(f"Skipping existing run directory: {run_root}", file=sys.stderr)
        return False
    if overwrite:
        if run_root.is_dir():
            try:
                shutil.rmtree(run_root)
            except PermissionError:
                # Windows/OneDrive can temporarily deny removing the root
                # directory even when its contents are removable.
                _clear_directory_contents(run_root)
        else:
            run_root.unlink()
        return True
    raise FileExistsError(f"Run directory already exists: {run_root}")


def _clear_directory_contents(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def build_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{timestamp}"


def build_method_results_dir(method: str, mode: str) -> str:
    canonical_method, _ = canonicalize_solver_method(method, mode)
    return SOLVER_METHOD_RESULT_DIRS[canonical_method]


def canonicalize_solver_method(method: str, mode: str | None = None) -> tuple[str, str]:
    if method == "dbp_exact":
        _require_compatible_mode(method, mode, expected_mode="exact")
        return "dbp_exact", "exact"
    if method == "dbp_certified":
        _require_compatible_mode(method, mode, expected_mode="certified")
        return "dbp_certified", "certified"
    if method == "dbp_f_lex_exact":
        _require_compatible_mode(method, mode, expected_mode="exact")
        return "dbp_f_lex_exact", "exact"
    if method == "dbp_lf_lex_exact":
        _require_compatible_mode(method, mode, expected_mode="exact")
        return "dbp_lf_lex_exact", "exact"
    if method == "enumeration_lf_lex_exact":
        _require_compatible_mode(method, mode, expected_mode="exact")
        return "enumeration_lf_lex_exact", "exact"
    raise ValueError(f"Unknown solver method {method!r}. Choose from {SUPPORTED_SOLVER_METHODS}.")


def _require_compatible_mode(method: str, mode: str | None, *, expected_mode: str) -> None:
    if mode is None:
        return
    if mode != expected_mode:
        raise ValueError(
            f"--dbp-mode {mode!r} is not available with method {method!r}; expected {expected_mode!r}."
        )


def build_manifest(
    *,
    run_id: str,
    target: Path,
    instance_paths: list[Path],
    run_scope: str | None,
    args: argparse.Namespace,
) -> dict[str, object]:
    enumeration_method = args.method == "enumeration_lf_lex_exact"
    per_instance_outputs = ["result.json", "dbp_trace.csv", "solution.json", "diagnostics.json"]
    if args.method == "dbp_lf_lex_exact":
        per_instance_outputs.append("lex_trace.csv")
    if enumeration_method:
        per_instance_outputs.append("enumeration_solutions.json")
    tolerance_config: dict[str, object] = {
        "eps": DEFAULT.eps,
        "mip_gap": DEFAULT.mip_gap,
        "dbp_relative_gap": DEFAULT.dbp_relative_gap,
        "lex_epsilon_prime": DEFAULT.lex_epsilon_prime,
        "dbp_cut_epsilon": DEFAULT.dbp_cut_epsilon,
        "stagnation_limit": DEFAULT.stagnation_limit,
        "elastic_penalty_mult": DEFAULT.elastic_penalty_mult,
        "threads": DEFAULT.threads,
        "mip_focus": DEFAULT.mip_focus,
        "output_flag": DEFAULT.output_flag,
    }
    solver_manifest: dict[str, object] = {
        "method": args.method,
        "mode": args.dbp_mode,
        "max_iterations": args.max_iterations,
        "time_limit": args.time_limit,
        "tolerances": tolerance_config,
        "fail_fast": bool(args.fail_fast),
        "validate_with_enumeration_oracle": bool(args.validate_with_enumeration_oracle),
    }
    if args.method in {"dbp_lf_lex_exact", "enumeration_lf_lex_exact"}:
        solver_manifest["leader_objective"] = "lex_emissions_then_min_hat_tau"
    if enumeration_method:
        solver_manifest["enumeration_oracle"] = True

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "input": {
            "path": to_posix(target),
            "pattern": args.pattern,
            "recursive": bool(args.recursive),
            "instance_count": len(instance_paths),
        },
        "solver": solver_manifest,
        "results_scope": run_scope,
        "outputs": {
            "summary_json": "summary.json",
            "summary_csv": "summary.csv",
            "per_instance": per_instance_outputs,
        },
    }


def build_summary_record(
    *,
    instance: InstanceData,
    instance_path: Path,
    result,
    solve_seconds: float,
    solution_validation: dict[str, object],
) -> dict[str, object]:
    return {
        "instance": instance.name,
        "input_path": to_posix(instance_path),
        "success": True,
        "exact": result.exact,
        "termination_reason": result.termination_reason,
        "iterations": result.iterations,
        "hat_tau": result.incumbent.hat_tau,
        "effective_tax": result.incumbent.effective_tax,
        "cost": result.incumbent.cost,
        "emissions": result.incumbent.emissions,
        "follower_objective": result.incumbent.follower_objective,
        "lower_bound": result.lower_bound,
        "upper_bound": result.upper_bound,
        "relative_gap": relative_optimality_gap(
            upper_bound=result.upper_bound,
            lower_bound=result.lower_bound,
        ),
        "validation_status": solution_validation["status"],
        "failure_stage": None,
        "error_type": None,
        "error_message": None,
        "gurobi_status": None,
        "objective_bound": None,
        "iis_constraints": 0,
        "solve_seconds": solve_seconds,
    }


def build_instance_result_payload(
    *,
    run_id: str,
    instance: InstanceData,
    instance_path: Path,
    relative_instance_dir: Path,
    result,
    solve_seconds: float,
    dbp_solve_seconds: float,
    validation_seconds: float,
    solution_validation: dict[str, object],
    oracle_validation: dict[str, object] | None = None,
) -> dict[str, object]:
    relative_result_dir = "." if not relative_instance_dir.parts else to_posix(relative_instance_dir)
    dbp_trace_rows = build_dbp_trace_rows(result)
    tau_refinement_trace_rows = build_tau_refinement_trace_rows(result)
    lexicographic_tiebreak_seconds = round(
        result.final_refinement.total_seconds if result.final_refinement is not None else 0.0,
        6,
    )
    dbp_overhead_seconds = round(
        max(0.0, dbp_solve_seconds - result.dbp_timing.total_subproblem_seconds - lexicographic_tiebreak_seconds),
        6,
    )
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "run_id": run_id,
        "instance": {
            "name": instance.name,
            "input_path": to_posix(instance_path),
            "relative_result_dir": relative_result_dir,
        },
        "solve_status": {
            "method": result.method,
            "mode": result.mode,
            "success": True,
            "exact": result.exact,
            "termination_reason": result.termination_reason,
            "iterations": result.iterations,
        },
        "phase_summary": build_phase_summary(result),
        "leader": {
            "hat_tau": result.incumbent.hat_tau,
            "effective_tax": result.incumbent.effective_tax,
        },
        "follower": {
            "cost": result.incumbent.cost,
            "emissions": result.incumbent.emissions,
            "objective": result.incumbent.follower_objective,
            "lex_primary_mip_gap": getattr(result.incumbent_solution, "lex_primary_mip_gap", None),
            "lex_secondary_mip_gap": getattr(result.incumbent_solution, "lex_secondary_mip_gap", None),
        },
        "bounds": {
            "lower_bound": result.lower_bound,
            "upper_bound": result.upper_bound,
            "relative_gap": relative_optimality_gap(
                upper_bound=result.upper_bound,
                lower_bound=result.lower_bound,
            ),
            "certificates": {
                "lower": asdict(result.lower_bound_certificate),
                "upper": asdict(result.upper_bound_certificate),
            },
        },
        "runtime": {
            "solve_seconds": solve_seconds,
            "dbp_seconds": dbp_solve_seconds,
            "validation_seconds": validation_seconds,
            "lexicographic": lexicographic_tiebreak_seconds,
            "dbp_overhead_seconds": dbp_overhead_seconds,
            "phase_seconds": {
                "dbp_subproblems": result.dbp_timing.total_subproblem_seconds,
                "lexicographic_tiebreak": lexicographic_tiebreak_seconds,
                "dbp_overhead": dbp_overhead_seconds,
                "validation": validation_seconds,
            },
            "subproblem_seconds": {
                "initial_relaxation": result.dbp_timing.initial_relaxation_seconds,
                "follower_total": result.dbp_timing.follower_total_seconds,
                "optimistic_total": result.dbp_timing.optimistic_total_seconds,
                "iterative_relaxation_total": result.dbp_timing.iterative_relaxation_total_seconds,
                "relaxation_total": result.dbp_timing.relaxation_total_seconds,
                "total": result.dbp_timing.total_subproblem_seconds,
            },
        },
        "validation": solution_validation,
        "oracle_validation": oracle_validation,
        "dbp": {
            "trace_file": "dbp_trace.csv",
            "trace_rows": len(dbp_trace_rows),
            "timings": {
                "initial_relaxation_seconds": result.dbp_timing.initial_relaxation_seconds,
                "iterations": [
                    {
                        "iteration": timing.iteration,
                        "follower_seconds": timing.follower_seconds,
                        "optimistic_seconds": timing.optimistic_seconds,
                        "relaxation_seconds": timing.relaxation_seconds,
                    }
                    for timing in result.dbp_timing.iteration_timings
                ],
            },
        },
        "lexicographic_tiebreak": build_lexicographic_tiebreak_payload(
            result=result,
            trace_rows=tau_refinement_trace_rows,
        ),
        "files": {
            "solution_file": "solution.json",
            "enumeration_solutions_file": "enumeration_solutions.json" if result.enumeration_solutions else None,
            "lex_trace_file": "lex_trace.csv" if tau_refinement_trace_rows else None,
            "diagnostics_file": None,
        },
    }


def build_phase_summary(result) -> dict[str, object]:
    refinement = getattr(result, "final_refinement", None)
    phase_1_selected_hat_tau = refinement.initial_hat_tau if refinement is not None else result.incumbent.hat_tau
    phase_2_selected_hat_tau = refinement.selected_hat_tau if refinement is not None else None
    phase_2_iterations = refinement.attempt_count if refinement is not None else 0

    return {
        "phase_1_dbp_iterations": len(result.iteration_records),
        "phase_2_lexicographic_iterations": phase_2_iterations,
        "phase_1_selected_hat_tau": phase_1_selected_hat_tau,
        "phase_2_selected_hat_tau": phase_2_selected_hat_tau,
        "final_hat_tau": result.incumbent.hat_tau,
    }


def build_lexicographic_tiebreak_payload(
    *,
    result,
    trace_rows: list[dict[str, object]],
) -> dict[str, object] | None:
    refinement = getattr(result, "final_refinement", None)
    if refinement is None:
        return None

    payload = {
        "trace_file": "lex_trace.csv",
        "trace_rows": len(trace_rows),
        "initial_hat_tau": refinement.initial_hat_tau,
        "selected_hat_tau": refinement.selected_hat_tau,
        "lower_hat_tau": refinement.lower_hat_tau,
        "seconds": refinement.total_seconds,
        "attempt_count": refinement.attempt_count,
        "changed_incumbent": refinement.changed_incumbent,
        "attempts": [
            {
                "hat_tau": attempt.hat_tau,
                "solve_seconds": attempt.solve_seconds,
                "emissions": attempt.emissions,
                "follower_objective": attempt.follower_objective,
                "matched_incumbent_emissions": attempt.matched_incumbent_emissions,
            }
            for attempt in refinement.attempts
        ],
    }
    if refinement.termination_reason is not None:
        payload["termination_reason"] = refinement.termination_reason
    if refinement.exact is not None:
        payload["exact"] = refinement.exact
    if refinement.lower_bound is not None:
        payload["lower_bound"] = refinement.lower_bound
    if refinement.upper_bound is not None:
        payload["upper_bound"] = refinement.upper_bound
    if refinement.emissions_target is not None:
        payload["emissions_target"] = refinement.emissions_target
    if refinement.emissions_cap is not None:
        payload["emissions_cap"] = refinement.emissions_cap
    return payload


def build_dbp_trace_rows(result) -> list[dict[str, object]]:
    return [build_dbp_trace_row(record) for record in result.iteration_records]


def build_tau_refinement_trace_rows(result) -> list[dict[str, object]]:
    refinement = getattr(result, "final_refinement", None)
    if refinement is None:
        return []
    selected_hat_tau = refinement.selected_hat_tau
    return [
        build_tau_refinement_trace_row(
            iteration=index,
            attempt=attempt,
            selected=attempt.hat_tau == selected_hat_tau,
        )
        for index, attempt in enumerate(refinement.attempts, start=1)
    ]


def build_dbp_trace_row(record) -> dict[str, object]:
    return {
        "iteration": record.iteration,
        "relaxation_hat_tau": record.relaxation_hat_tau,
        "relaxation_lower_bound": record.relaxation_lower_bound,
        "follower_seconds": record.follower_seconds,
        "follower_objective": record.follower_objective,
        "incumbent_emissions": record.incumbent_emissions,
        "relaxation_seconds": record.relaxation_seconds,
        "next_relaxation_hat_tau": record.next_relaxation_hat_tau,
        "next_relaxation_lower_bound": record.next_relaxation_lower_bound,
    }


def build_tau_refinement_trace_row(*, iteration: int, attempt, selected: bool) -> dict[str, object]:
    return {
        "iteration": iteration,
        "tested_hat_tau": attempt.hat_tau,
        "solve_seconds": attempt.solve_seconds,
        "emissions": attempt.emissions,
        "follower_objective": attempt.follower_objective,
        "matched_incumbent_emissions": attempt.matched_incumbent_emissions,
        "selected": selected,
    }


def build_solution_payload(
    *,
    instance: InstanceData,
    result,
    solution_validation: dict[str, object],
) -> dict[str, object]:
    optimistic = result.incumbent_solution
    if optimistic is None or not optimistic.has_solution:
        raise RuntimeError(f"Missing cached optimistic incumbent solution for {instance.name}")
    if optimistic.variable_values is None:
        raise RuntimeError(f"Cached optimistic incumbent solution for {instance.name} has no variable values")

    leader_variables = {
        "hat_tau": result.incumbent.hat_tau,
        "effective_tax": result.incumbent.effective_tax,
    }
    follower_variables = optimistic.variable_values

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "instance": instance.name,
        "leader": leader_variables,
        "objectives": {
            "cost": optimistic.cost if optimistic.cost is not None else result.incumbent.cost,
            "emissions": optimistic.emissions if optimistic.emissions is not None else result.incumbent.emissions,
            "follower_objective": optimistic.follower_objective
            if optimistic.follower_objective is not None
            else result.incumbent.follower_objective,
        },
        "validation": solution_validation,
        "decision_variables": {
            "leader": leader_variables,
            "follower": follower_variables,
        },
        "variables": follower_variables,
    }


def build_enumeration_solutions_payload(
    *,
    instance: InstanceData,
    result,
) -> dict[str, object] | None:
    if not result.enumeration_solutions:
        return None

    selected_hat_tau = result.incumbent.hat_tau
    selected_emissions = result.incumbent.emissions
    tolerance = max(DEFAULT.eps, DEFAULT.eps * abs(selected_emissions))
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "instance": instance.name,
        "selected_hat_tau": selected_hat_tau,
        "tax_solutions": [
            {
                "iteration": snapshot.iteration,
                "leader": {
                    "hat_tau": snapshot.hat_tau,
                    "effective_tax": snapshot.effective_tax,
                },
                "objectives": {
                    "cost": snapshot.cost,
                    "emissions": snapshot.emissions,
                    "follower_objective": snapshot.follower_objective,
                    "objective_value": snapshot.objective_value,
                },
                "runtime": {
                    "solve_seconds": snapshot.solve_seconds,
                },
                "gaps": {
                    "mip_gap": snapshot.mip_gap,
                    "lex_primary_mip_gap": snapshot.lex_primary_mip_gap,
                    "lex_secondary_mip_gap": snapshot.lex_secondary_mip_gap,
                },
                "selected_incumbent": snapshot.hat_tau == selected_hat_tau
                and abs(snapshot.emissions - selected_emissions) <= tolerance,
                "decision_variables": {
                    "leader": {
                        "hat_tau": snapshot.hat_tau,
                        "effective_tax": snapshot.effective_tax,
                    },
                    "follower": snapshot.variable_values,
                },
                "variables": snapshot.variable_values,
            }
            for snapshot in result.enumeration_solutions
        ],
    }


def canonicalize_result_solution(*, instance: InstanceData, result):
    optimistic = result.incumbent_solution
    if optimistic is None or not optimistic.has_solution or optimistic.variable_values is None:
        return result

    recomputed = validate_fixed_tax_solution(
        instance,
        hat_tau=result.incumbent.hat_tau,
        variable_values=optimistic.variable_values,
    )
    if (
        (not recomputed.has_solution or recomputed.status_name != "OPTIMAL")
        and result.method in LEXICOGRAPHIC_SOLVER_METHODS
    ):
        repaired = rebuild_lexicographic_solution_with_fixed_discrete_values(
            instance=instance,
            result=result,
        )
        if repaired is not None and repaired.has_solution and repaired.status_name == "OPTIMAL":
            result = replace(
                result,
                incumbent=replace(
                    result.incumbent,
                    cost=float(repaired.cost),
                    emissions=float(repaired.emissions),
                    follower_objective=float(repaired.follower_objective),
                ),
                incumbent_solution=repaired,
            )
            optimistic = repaired
            recomputed = validate_fixed_tax_solution(
                instance,
                hat_tau=result.incumbent.hat_tau,
                variable_values=optimistic.variable_values or {},
            )
    if not recomputed.has_solution or recomputed.status_name != "OPTIMAL":
        return result

    canonical_incumbent = replace(
        result.incumbent,
        cost=float(recomputed.cost),
        emissions=float(recomputed.emissions),
        follower_objective=float(recomputed.follower_objective),
    )
    canonical_optimistic = replace(
        optimistic,
        cost=float(recomputed.cost),
        emissions=float(recomputed.emissions),
        follower_objective=float(recomputed.follower_objective),
    )
    return replace(
        result,
        incumbent=canonical_incumbent,
        incumbent_solution=canonical_optimistic,
    )


def rebuild_lexicographic_solution_with_fixed_discrete_values(*, instance: InstanceData, result):
    optimistic = result.incumbent_solution
    if optimistic is None or not optimistic.has_solution or optimistic.variable_values is None:
        return None

    follower_master = build_fixed_tax_follower_master(instance)
    model = follower_master.artifacts.model
    model.update()
    for variable in model.getVars():
        if variable.VType == "C":
            continue
        target_value = float(optimistic.variable_values.get(variable.VarName, 0.0))
        lower_bound = float(variable.LB)
        upper_bound = float(variable.UB)
        if abs(target_value - round(target_value)) <= INTEGER_SNAP_TOL:
            target_value = float(round(target_value))
        if target_value < lower_bound - DEFAULT.eps or target_value > upper_bound + DEFAULT.eps:
            raise ValueError(
                f"Saved solution value {target_value} for {variable.VarName} violates [{lower_bound}, {upper_bound}]",
            )
        if target_value < lower_bound:
            target_value = lower_bound
        if target_value > upper_bound:
            target_value = upper_bound
        variable.LB = target_value
        variable.UB = target_value

    return solve_fixed_tax_lexicographic(
        follower_master,
        result.incumbent.hat_tau,
        output_flag=False,
        time_limit=None,
        capture_solution=True,
        warm_start_values=optimistic.variable_values,
        mip_gap=DEFAULT.eps,
    )


def validate_result_solution(*, instance: InstanceData, result) -> dict[str, object]:
    optimistic = result.incumbent_solution
    if optimistic is None or not optimistic.has_solution:
        raise OutputValidationError(f"Missing cached optimistic incumbent solution for {instance.name}")
    if optimistic.variable_values is None:
        raise OutputValidationError(f"Cached optimistic incumbent solution for {instance.name} has no variable values")

    recomputed = validate_fixed_tax_solution(
        instance,
        hat_tau=result.incumbent.hat_tau,
        variable_values=optimistic.variable_values,
    )
    if not recomputed.has_solution or recomputed.status_name != "OPTIMAL":
        raise OutputValidationError(
            f"Saved incumbent for {instance.name} could not be revalidated (status={recomputed.status_name})",
        )

    deltas = {
        "cost": float(recomputed.cost) - float(result.incumbent.cost),
        "emissions": float(recomputed.emissions) - float(result.incumbent.emissions),
        "follower_objective": float(recomputed.follower_objective) - float(result.incumbent.follower_objective),
    }
    max_abs_delta = max(abs(value) for value in deltas.values())
    if max_abs_delta > DEFAULT.eps:
        raise OutputValidationError(
            f"Saved incumbent metrics for {instance.name} are inconsistent with the recomputed fixed solution: {deltas}",
        )

    return {
        "status": "validated",
        "tolerance": DEFAULT.eps,
        "recomputed": {
            "cost": recomputed.cost,
            "emissions": recomputed.emissions,
            "follower_objective": recomputed.follower_objective,
        },
        "deltas": deltas,
        "max_abs_delta": max_abs_delta,
    }


def build_failure_summary_record(
    *,
    instance: InstanceData | None,
    instance_path: Path,
    error: Exception,
    solve_seconds: float,
) -> dict[str, object]:
    diagnostics = extract_failure_diagnostics(error)
    return {
        "instance": instance.name if instance is not None else instance_path.stem,
        "input_path": to_posix(instance_path),
        "success": False,
        "exact": False,
        "termination_reason": "failed",
        "iterations": None,
        "hat_tau": None,
        "effective_tax": None,
        "cost": None,
        "emissions": None,
        "follower_objective": None,
        "lower_bound": None,
        "upper_bound": None,
        "relative_gap": None,
        "validation_status": "failed",
        "failure_stage": diagnostics["failure_stage"],
        "error_type": type(error).__name__,
        "error_message": str(error),
        "gurobi_status": diagnostics["gurobi_status"],
        "objective_bound": diagnostics["objective_bound"],
        "iis_constraints": diagnostics["iis_constraint_count"],
        "solve_seconds": solve_seconds,
    }


def build_failure_result_payload(
    *,
    run_id: str,
    instance: InstanceData | None,
    instance_path: Path,
    relative_instance_dir: Path,
    error: Exception,
    solve_seconds: float,
    method: str,
    mode: str,
) -> dict[str, object]:
    relative_result_dir = "." if not relative_instance_dir.parts else to_posix(relative_instance_dir)
    diagnostics = extract_failure_diagnostics(error)
    trace_rows = extract_failure_trace_rows(error)
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "run_id": run_id,
        "instance": {
            "name": instance.name if instance is not None else instance_path.stem,
            "input_path": to_posix(instance_path),
            "relative_result_dir": relative_result_dir,
        },
        "solve_status": {
            "method": method,
            "mode": mode,
            "success": False,
            "exact": False,
            "termination_reason": "failed",
            "iterations": None,
        },
        "phase_summary": None,
        "runtime": {
            "solve_seconds": solve_seconds,
        },
        "error": {
            "type": type(error).__name__,
            "message": str(error),
        },
        "diagnostics": diagnostics,
        "dbp": {
            "trace_file": "dbp_trace.csv" if trace_rows else None,
            "trace_rows": len(trace_rows),
        },
        "lexicographic_tiebreak": None,
        "files": {
            "solution_file": None,
            "enumeration_solutions_file": None,
            "lex_trace_file": None,
            "diagnostics_file": "diagnostics.json",
        },
    }


def extract_failure_diagnostics(error: Exception) -> dict[str, object]:
    diagnostics = {
        "failure_stage": "unexpected",
        "gurobi_status": None,
        "objective_bound": None,
        "iis_constraint_count": 0,
        "iis_constraints": [],
        "iis_variable_bounds": [],
    }

    if isinstance(error, InstanceValidationError):
        diagnostics["failure_stage"] = "instance_validation"
        return diagnostics
    if isinstance(error, OutputValidationError):
        diagnostics["failure_stage"] = "output_validation"
        return diagnostics
    if isinstance(error, SubproblemStatusError):
        diagnostics["failure_stage"] = error.label
        result = error.result
        diagnostics["gurobi_status"] = result.status_name
        diagnostics["objective_bound"] = result.objective_bound
        diagnostics["iis_constraints"] = list(result.iis_constraints)
        diagnostics["iis_variable_bounds"] = list(result.iis_variable_bounds)
        diagnostics["iis_constraint_count"] = len(result.iis_constraints)
        diagnostics["status_history"] = list(result.status_history or (result.status_name,))
        diagnostics["has_solution"] = result.has_solution
        diagnostics["mip_gap"] = result.mip_gap
        diagnostics["runtime"] = result.runtime
        return diagnostics
    if isinstance(error, BilevelSolveError):
        diagnostics["failure_stage"] = "solve"
        return diagnostics
    return diagnostics


def extract_failure_trace_rows(error: Exception) -> list[dict[str, object]]:
    trace_rows = getattr(error, "trace_rows", ())
    if not trace_rows:
        return []
    return [dict(row) for row in trace_rows]


def build_canonical_instance_dir(instance_path: Path, target: Path) -> Path:
    dataset_dir = infer_dataset_instance_dir(instance_path)
    if dataset_dir is not None:
        return dataset_dir
    if target.is_file():
        return Path(instance_path.stem)
    return instance_path.relative_to(target).with_suffix("")


def infer_dataset_instance_dir(instance_path: Path) -> Path | None:
    # data/instances/<X> mirrors results/runs/<X>, so reuse the subpath after instances/ verbatim
    # (e.g. base/<inst>, experiments/scenarios/<type>/<inst>, experiments/sensitivity/oat/<base>/<SA>).
    # Anything not under a known top scope defaults to base/.
    parts = instance_path.with_suffix("").parts
    for index, part in enumerate(parts):
        if part != "instances" or index + 1 >= len(parts):
            continue
        remaining_parts = parts[index + 1 :]
        if remaining_parts[0] in {"base", "experiments"}:
            return Path(*remaining_parts)
        return Path("base", *remaining_parts)
    return None


def normalize_results_scope_name(scope: str) -> str:
    return scope


def infer_run_scope(canonical_dirs) -> str | None:
    first_parts = {normalize_results_scope_name(canonical_dir.parts[0]) for canonical_dir in canonical_dirs if canonical_dir.parts}
    if first_parts == {"base"}:
        return "base"
    if first_parts == {"experiments"}:
        return "experiments"
    return None


def build_run_root(
    results_root: Path,
    run_scope: str | None,
    run_id: str,
    *,
    canonical_dirs: dict[Path, Path],
    single_instance_run: bool,
    method: str,
    mode: str,
) -> Path:
    # Single-instance runs get a deterministic per-instance path (no run_id wrapper).
    # This branch is checked first so that sensitivity single-instance runs land at
    # results/sensitivity/{instance_name}/{method}/ rather than results/sensitivity/{run_id}/.
    if single_instance_run and canonical_dirs:
        canonical_dir = next(iter(canonical_dirs.values()))
        if canonical_dir.parts:
            first_part = normalize_results_scope_name(canonical_dir.parts[0])
            if first_part in {"base", "experiments"}:
                return results_root.joinpath(
                    *canonical_dir.parts,
                    build_method_results_dir(method, mode),
                )
    if run_scope == "sensitivity":
        return results_root / "sensitivity" / run_id
    if run_scope is None:
        return results_root / run_id
    return results_root / run_scope / run_id


def build_relative_instance_dir(
    canonical_dir: Path,
    run_scope: str | None,
    *,
    single_instance_run: bool,
    method: str | None = None,
    mode: str | None = None,
) -> Path:
    if single_instance_run:
        return Path()
    if run_scope == "sensitivity":
        if len(canonical_dir.parts) >= 3 and normalize_results_scope_name(canonical_dir.parts[0]) == "scenarios":
            return Path(*canonical_dir.parts[2:])
        if len(canonical_dir.parts) >= 2 and normalize_results_scope_name(canonical_dir.parts[0]) in {"base", "scenarios"}:
            return Path(*canonical_dir.parts[1:])
        return canonical_dir
    if run_scope is None or not canonical_dir.parts:
        return canonical_dir
    if normalize_results_scope_name(canonical_dir.parts[0]) != run_scope:
        return canonical_dir
    if len(canonical_dir.parts) == 1:
        return canonical_dir
    return Path(*canonical_dir.parts[1:])


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_posix(path: Path) -> str:
    return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
