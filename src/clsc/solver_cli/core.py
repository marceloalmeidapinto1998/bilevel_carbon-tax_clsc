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

from clsc.config.constants import INTEGER_SNAP_TOL
from clsc.config.defaults import DEFAULT
from clsc.models.follower import (
    build_follower_master,
    solve_follower_lexicographic,
    validate_fixed_tax_solution,
)
from clsc.models.instance_data import InstanceData, InstanceValidationError
from clsc.solvers.dbp import (
    BilevelSolveError,
    SubproblemStatusError,
    relative_optimality_gap,
    solve_bilevel_dbp,
)

SUPPORTED_SOLVER_METHODS = (
    "dbp",
)

DBP_SOLVER_METHODS = {
    "dbp",
}

SOLVER_METHOD_RESULT_DIRS = {
    "dbp": "dbp",
}

RESULT_SCHEMA_VERSION = 3
SUMMARY_FIELDNAMES = [
    "instance",
    "input_path",
    "success",
    "exact",
    "result_class",
    "termination_reason",
    "iterations",
    "tax_index",
    "leader_tax_weight",
    "tax_rate",
    "cost",
    "emissions",
    "follower_objective",
    "emissions_leader_lb",
    "emissions_follower_ub",
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
    "relaxation_tax_index",
    "relaxation_lower_bound",
    "follower_seconds",
    "follower_objective",
    "incumbent_emissions",
    "relaxation_seconds",
    "next_relaxation_tax_index",
    "next_relaxation_lower_bound",
    "relaxation_mip_gap",
    "relaxation_partial",
    "relaxation_elastic_slack",
    "follower_mip_gap",
    "follower_time_limited",
    "follower_improved",
    "follower_stage2_fallback",
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
        default="dbp",
        help=(
            "DBP algorithm variant. 'dbp' is Soares et al. (2021)'s DBP for the "
            "single-objective leader F = E + w*tau (see --leader-tax-weight*)."
        ),
    )
    parser.add_argument(
        "--time-limit",
        type=float,
        help=(
            "Gurobi time limit in seconds for ONE follower subproblem, and for the master too "
            "unless --master-time-limit is given (default: clsc.config.defaults.DEFAULT.time_limit, "
            "600 s). Pass inf to remove it."
        ),
    )
    parser.add_argument(
        "--leader-tax-weight",
        type=float,
        help=(
            "The leader minimises F = E + w*tau, with w this many kg CO2e per USD/t of tax: how "
            "much emissions the regulator gives up to avoid 1 USD/t. A POLICY assumption, not a "
            "tolerance. Give at most one tax-weight flag; with neither, "
            "--leader-tax-weight-relative defaults to clsc.config.defaults.DEFAULT.tax_weight_relative. "
            ""
        ),
    )
    parser.add_argument(
        "--leader-tax-weight-relative",
        type=float,
        help=(
            "Like --leader-tax-weight, but w = this fraction q of the least emissions the cut-free "
            "master can reach, per USD/t of tax -- the same meaning on every instance. q = 1e-4 "
            "reads 'lose 1%% of the minimum emissions to avoid 100 USD/t of tax'. The run resolves "
            "the tax to about eps / q USD/t (eps = --dbp-relative-gap)."
        ),
    )
    parser.add_argument(
        "--master-time-limit",
        type=float,
        help=(
            "Gurobi time limit in seconds for ONE relaxation-master solve (default: the same "
            "as --time-limit)."
        ),
    )
    parser.add_argument(
        "--wall-clock-cap",
        type=float,
        help=(
            "Total wall-clock budget for the whole DBP run, in seconds. Enforced inside the "
            "solve: each subproblem's limit is clamped to the budget that remains and the loop "
            "stops between iterations once it is exhausted, so an exhausted budget still "
            "reports the incumbent, its variable values and the certified gap "
            "(termination_reason=incumbent_wall_clock_cap)."
        ),
    )
    parser.add_argument(
        "--mip-gap",
        type=float,
        help=(
            "Gurobi MIPGap target for every follower sub-solve "
            "(default: clsc.config.defaults.DEFAULT.mip_gap, 1e-2)."
        ),
    )
    parser.add_argument(
        "--master-mip-gap",
        type=float,
        help=(
            "Gurobi MIPGap target for the DBP relaxation master only (default: "
            "clsc.config.defaults.DEFAULT.master_mip_gap, 1e-4). The master's gap only loosens the lower bound -- its dual "
            "bound stays valid -- so it can be looser than the follower's. A master that "
            "stops on its time limit still contributes its dual bound and a tax proposal."
        ),
    )
    parser.add_argument(
        "--dbp-relative-gap",
        type=float,
        help=(
            "Override the DBP loop's own relative-gap stopping criterion "
            "(default: clsc.config.defaults.DEFAULT.dbp_relative_gap). This is the "
            "outer algorithm's stopping tolerance, not a Gurobi parameter."
        ),
    )
    parser.add_argument(
        "--threads",
        type=int,
        help=(
            "Override Gurobi Threads for every sub-solve (default: "
            "clsc.config.defaults.DEFAULT.threads)."
        ),
    )
    parser.add_argument(
        "--mip-focus",
        type=int,
        choices=(0, 1, 2, 3),
        help=(
            "Override Gurobi MIPFocus for every sub-solve (default: "
            "clsc.config.defaults.DEFAULT.mip_focus)."
        ),
    )
    parser.add_argument(
        "--scale-factor",
        type=float,
        help=(
            "Grid-resolution override theta (USD/kg CO2e per integer tax_index step). "
            "When set, each in-memory instance's tax resolution is refined to this step "
            "WHILE PRESERVING its real tax range [underline_tax_rate, overline_tax_rate]: the "
            "index bounds are recomputed as round(tau / theta) so overline_tax_index "
            "becomes overline_tax_rate/theta (e.g. 0.2/0.001 = 200). The stored instance "
            "files are never touched. Omit to use each instance's stored grid, which "
            "is already the project's one grid (theta = TAX_SCALE_FACTOR = 1e-3, "
            "index {0..200}, a whole USD/tonne per step) for every base instance -- this "
            "flag exists for a deliberate probe at a different resolution."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        help=(
            "Gurobi Seed parameter for every sub-solve (MIP performance-variability "
            "probes). Omit for Gurobi's default seed."
        ),
    )
    parser.add_argument(
        "--no-warm-start",
        dest="use_warm_start",
        action="store_false",
        help="Ablation A3: disable warm starts between successive follower solves.",
    )
    parser.add_argument(
        "--no-emissions-cap",
        dest="use_emissions_cap",
        action="store_false",
        help="Ablation A5: disable the incumbent objective-upper-bound cut in the relaxation master.",
    )
    parser.add_argument(
        "--no-follower-improvement",
        dest="use_follower_improvement",
        action="store_false",
        help="Disable Soares et al. (2021)'s subproblem (P6) for a follower that stops on its time limit.",
    )
    parser.add_argument(
        "--no-elastic-master",
        dest="use_elastic_master",
        action="store_false",
        help=(
            "Disable the elastic-cut remedy (Soares et al. 2021's P5-D): by default, the first time "
            "the relaxation master returns no point its cuts are made elastic and it is re-solved."
        ),
    )
    parser.set_defaults(
        use_warm_start=True, use_emissions_cap=True,
        use_follower_improvement=True, use_elastic_master=True,
    )
    parser.add_argument("--solver-output", action="store_true", help="Show raw Gurobi output.")
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
        args.method, args.dbp_mode = canonicalize_solver_method(args.method)
    except ValueError as error:
        parser.error(str(error))
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
            if args.scale_factor is not None:
                instance = instance.with_tax_grid_step(args.scale_factor)
            solve_started_at = time.perf_counter()
            if args.method == "dbp":
                result = solve_bilevel_dbp(
                    instance,
                    output_flag=args.solver_output,
                    time_limit=args.time_limit,
                    master_time_limit=args.master_time_limit,
                    leader_tax_weight=args.leader_tax_weight,
                    leader_tax_weight_relative=args.leader_tax_weight_relative,
                    wall_clock_cap=args.wall_clock_cap,
                    mip_gap=args.mip_gap,
                    master_mip_gap=args.master_mip_gap,
                    dbp_relative_gap=args.dbp_relative_gap,
                    threads=args.threads,
                    mip_focus=args.mip_focus,
                    seed=args.seed,
                    use_warm_start=args.use_warm_start,
                    use_emissions_cap=args.use_emissions_cap,
                    use_follower_improvement=args.use_follower_improvement,
                    use_elastic_master=args.use_elastic_master,
                )
            else:
                raise ValueError(f"Unsupported solver method {args.method!r}")
            result = canonicalize_result_solution(instance=instance, result=result)
            dbp_solve_seconds = round(time.perf_counter() - solve_started_at, 6)
            validation_started_at = time.perf_counter()
            solution_validation = validate_result_solution(instance=instance, result=result)
            oracle_validation = None
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
            write_csv(
                instance_results_dir / "dbp_trace.csv",
                TRACE_FIELDNAMES,
                build_dbp_trace_rows(result),
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


def build_method_results_dir(method: str, mode: str = "") -> str:
    canonical_method, _ = canonicalize_solver_method(method)
    return SOLVER_METHOD_RESULT_DIRS[canonical_method]


def canonicalize_solver_method(method: str) -> tuple[str, str]:
    if method == "dbp":
        return "dbp", "exact"
    raise ValueError(f"Unknown solver method {method!r}. Choose from {SUPPORTED_SOLVER_METHODS}.")


def build_manifest(
    *,
    run_id: str,
    target: Path,
    instance_paths: list[Path],
    run_scope: str | None,
    args: argparse.Namespace,
) -> dict[str, object]:
    per_instance_outputs = ["result.json", "dbp_trace.csv", "solution.json", "diagnostics.json"]
    tolerance_config: dict[str, object] = {
        "eps": DEFAULT.eps,
        "mip_gap": DEFAULT.mip_gap if args.mip_gap is None else args.mip_gap,
        "master_mip_gap": DEFAULT.master_mip_gap if args.master_mip_gap is None else args.master_mip_gap,
        "dbp_relative_gap": DEFAULT.dbp_relative_gap if args.dbp_relative_gap is None else args.dbp_relative_gap,
        "lex_epsilon_prime": DEFAULT.lex_epsilon_prime,
        "dbp_cut_epsilon": DEFAULT.dbp_cut_epsilon,
        "dbp_cut_epsilon_relative": DEFAULT.dbp_cut_epsilon_relative,
        "stagnation_limit": DEFAULT.stagnation_limit,
        "elastic_penalty_mult": DEFAULT.elastic_penalty_mult,
        "threads": DEFAULT.threads if args.threads is None else args.threads,
        "mip_focus": DEFAULT.mip_focus if args.mip_focus is None else args.mip_focus,
        "output_flag": DEFAULT.output_flag,
    }
    solver_manifest: dict[str, object] = {
        "method": args.method,
        "mode": args.dbp_mode,
        "time_limit": DEFAULT.time_limit if args.time_limit is None else args.time_limit,
        "master_time_limit": (
            (DEFAULT.time_limit if args.time_limit is None else args.time_limit)
            if args.master_time_limit is None
            else args.master_time_limit
        ),
        "leader_tax_weight": args.leader_tax_weight,
        "leader_tax_weight_relative": args.leader_tax_weight_relative,
        "wall_clock_cap": args.wall_clock_cap,
        "tolerances": tolerance_config,
        "tax_scale_factor": args.scale_factor,
        "gurobi_seed": args.seed,
        "use_warm_start": bool(args.use_warm_start),
        "use_emissions_cap": bool(args.use_emissions_cap),
        "use_follower_improvement": bool(args.use_follower_improvement),
        "use_elastic_master": bool(args.use_elastic_master),
        "fail_fast": bool(args.fail_fast),
    }
    if args.method == "dbp":
        # The leader's POLICY assumption, deliberately recorded here and not under "tolerances":
        # the reported tax_index is a function of it, so a run is not reproducible or
        # interpretable without it. The effective w (kg per USD/t) is in each summary.
        solver_manifest["leader_objective"] = "emissions_plus_weighted_tax"
        solver_manifest["leader_tax_weight_relative_effective"] = (
            args.leader_tax_weight_relative
            if args.leader_tax_weight_relative is not None or args.leader_tax_weight is not None
            else DEFAULT.tax_weight_relative
        )

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


def classify_result(result) -> str:
    """How strong a claim the result supports, in Soares et al. (2021)'s terms.

    ``certified``        gap <= dbp_relative_gap with every certificate in hand (``exact``).
    ``epsilon_optimal``  gap <= dbp_relative_gap, but the tax or a bound is not certified.
    ``bounded``          the gap did not close: the result is the interval [LB, UB] and the
                         incumbent that attains UB -- "optimal or nearly optimal" at best, with
                         convergence not guaranteed under positive subproblem gaps.
    """
    if result.exact:
        return "certified"
    if result.termination_reason.startswith(("optimal", "epsilon_optimal")):
        return "epsilon_optimal"
    return "bounded"


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
        "result_class": classify_result(result),
        "termination_reason": result.termination_reason,
        "iterations": result.iterations,
        "tax_index": result.incumbent.tax_index,
        # kg CO2e per USD/t in the leader's objective F = E + w*tau. The bounds below
        # (emissions_leader_lb / emissions_follower_ub) are bounds on F, not on emissions alone.
        "leader_tax_weight": getattr(result, "leader_tax_weight", 0.0),
        "tax_rate": result.incumbent.tax_rate,
        "cost": result.incumbent.cost,
        "emissions": result.incumbent.emissions,
        "follower_objective": result.incumbent.follower_objective,
        "emissions_leader_lb": result.emissions_leader_lb,
        "emissions_follower_ub": result.emissions_follower_ub,
        "relative_gap": relative_optimality_gap(
            emissions_follower_ub=result.emissions_follower_ub,
            emissions_leader_lb=result.emissions_leader_lb,
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
    dbp_overhead_seconds = round(
        max(0.0, dbp_solve_seconds - result.dbp_timing.total_subproblem_seconds),
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
            "tax_index": result.incumbent.tax_index,
            "tax_rate": result.incumbent.tax_rate,
        },
        "follower": {
            "cost": result.incumbent.cost,
            "emissions": result.incumbent.emissions,
            "objective": result.incumbent.follower_objective,
            "lex_primary_mip_gap": getattr(result.incumbent_solution, "lex_primary_mip_gap", None),
            "lex_secondary_mip_gap": getattr(result.incumbent_solution, "lex_secondary_mip_gap", None),
        },
        "bounds": {
            "emissions_leader_lb": result.emissions_leader_lb,
            "emissions_follower_ub": result.emissions_follower_ub,
            "relative_gap": relative_optimality_gap(
                emissions_follower_ub=result.emissions_follower_ub,
                emissions_leader_lb=result.emissions_leader_lb,
            ),
            "certificates": {
                "lower": asdict(result.emissions_leader_lb_certificate),
                "upper": asdict(result.emissions_follower_ub_certificate),
            },
        },
        "runtime": {
            "solve_seconds": solve_seconds,
            "dbp_seconds": dbp_solve_seconds,
            "validation_seconds": validation_seconds,
            "dbp_overhead_seconds": dbp_overhead_seconds,
            "phase_seconds": {
                "dbp_subproblems": result.dbp_timing.total_subproblem_seconds,
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
        "files": {
            "solution_file": "solution.json",
            "diagnostics_file": None,
        },
    }


def build_phase_summary(result) -> dict[str, object]:
    # The leader's single objective F = E + w*tax_index is resolved inside the DBP loop itself,
    # so there is only one phase.
    return {
        "dbp_iterations": len(result.iteration_records),
        "final_tax_index": result.incumbent.tax_index,
    }


def build_dbp_trace_rows(result) -> list[dict[str, object]]:
    return [build_dbp_trace_row(record) for record in result.iteration_records]


def build_dbp_trace_row(record) -> dict[str, object]:
    return {
        "iteration": record.iteration,
        "relaxation_tax_index": record.relaxation_tax_index,
        "relaxation_lower_bound": record.relaxation_lower_bound,
        "follower_seconds": record.follower_seconds,
        "follower_objective": record.follower_objective,
        "incumbent_emissions": record.incumbent_emissions,
        "relaxation_seconds": record.relaxation_seconds,
        "next_relaxation_tax_index": record.next_relaxation_tax_index,
        "next_relaxation_lower_bound": record.next_relaxation_lower_bound,
        "relaxation_mip_gap": getattr(record, "relaxation_mip_gap", None),
        "relaxation_partial": getattr(record, "relaxation_partial", False),
        "relaxation_elastic_slack": getattr(record, "relaxation_elastic_slack", None),
        "follower_mip_gap": getattr(record, "follower_mip_gap", None),
        "follower_time_limited": getattr(record, "follower_time_limited", False),
        "follower_improved": getattr(record, "follower_improved", None),
        "follower_stage2_fallback": getattr(record, "follower_stage2_fallback", False),
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
        "tax_index": result.incumbent.tax_index,
        "tax_rate": result.incumbent.tax_rate,
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


def canonicalize_result_solution(*, instance: InstanceData, result):
    optimistic = result.incumbent_solution
    if optimistic is None or not optimistic.has_solution or optimistic.variable_values is None:
        return result

    recomputed = validate_fixed_tax_solution(
        instance,
        tax_index=result.incumbent.tax_index,
        variable_values=optimistic.variable_values,
    )
    if (
        (not recomputed.has_solution or recomputed.status_name != "OPTIMAL")
        and result.method in DBP_SOLVER_METHODS
    ):
        repaired = rebuild_solution_with_fixed_discrete_values(
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
                tax_index=result.incumbent.tax_index,
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


def rebuild_solution_with_fixed_discrete_values(*, instance: InstanceData, result):
    optimistic = result.incumbent_solution
    if optimistic is None or not optimistic.has_solution or optimistic.variable_values is None:
        return None

    follower_master = build_follower_master(instance)
    model = follower_master.artifacts.model
    model.update()
    for variable in model.getVars():
        if variable.VType == "C":
            continue
        target_value = float(optimistic.variable_values.get(variable.VarName, 0.0))
        emissions_leader_lb = float(variable.LB)
        emissions_follower_ub = float(variable.UB)
        if abs(target_value - round(target_value)) <= INTEGER_SNAP_TOL:
            target_value = float(round(target_value))
        if target_value < emissions_leader_lb - DEFAULT.eps or target_value > emissions_follower_ub + DEFAULT.eps:
            raise ValueError(
                f"Saved solution value {target_value} for {variable.VarName} violates [{emissions_leader_lb}, {emissions_follower_ub}]",
            )
        if target_value < emissions_leader_lb:
            target_value = emissions_leader_lb
        if target_value > emissions_follower_ub:
            target_value = emissions_follower_ub
        variable.LB = target_value
        variable.UB = target_value

    return solve_follower_lexicographic(
        follower_master,
        result.incumbent.tax_index,
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
        tax_index=result.incumbent.tax_index,
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
        "result_class": "failed",
        "termination_reason": "failed",
        "iterations": None,
        "tax_index": None,
        "tax_rate": None,
        "cost": None,
        "emissions": None,
        "follower_objective": None,
        "emissions_leader_lb": None,
        "emissions_follower_ub": None,
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
        "files": {
            "solution_file": None,
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
