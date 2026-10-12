"""Command-line batch solver: argument parsing, the run directory layout, the manifest, and
the main loop over instances (``python -m clsc.solver_cli`` or ``clsc-solve``).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time

from clsc.config.defaults import DEFAULT
from clsc.models.instance_data import InstanceData
from clsc.solvers.dbp import solve_bilevel_dbp
from .validation import canonicalize_result_solution, validate_result_solution
from .results import (
    RESULT_SCHEMA_VERSION,
    SUMMARY_FIELDNAMES,
    TRACE_FIELDNAMES,
    build_dbp_trace_rows,
    build_failure_result_payload,
    build_failure_summary_record,
    build_instance_result_payload,
    build_solution_payload,
    build_summary_record,
    extract_failure_trace_rows,
    to_posix,
    utc_now_iso,
    write_csv,
    write_json,
)


SUPPORTED_SOLVER_METHODS = (
    "dbp",
)


SOLVER_METHOD_RESULT_DIRS = {
    "dbp": "dbp",
}


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
            "(default: clsc.config.defaults.DEFAULT.mip_gap, 1e-4)."
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


def build_canonical_instance_dir(instance_path: Path, target: Path) -> Path:
    dataset_dir = infer_dataset_instance_dir(instance_path)
    if dataset_dir is not None:
        return dataset_dir
    if target.is_file():
        return Path(instance_path.stem)
    return instance_path.relative_to(target).with_suffix("")


def infer_dataset_instance_dir(instance_path: Path) -> Path | None:
    # data/<X> mirrors results/runs/<X>, so reuse the subpath after data/ verbatim
    # (e.g. base/<inst>, experiments/scenarios/<type>/<inst>, experiments/sensitivity/oat/<base>/<SA>).
    # Anything not under a known top scope defaults to base/.
    parts = instance_path.with_suffix("").parts
    for index, part in enumerate(parts):
        if part != "data" or index + 1 >= len(parts):
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


if __name__ == "__main__":
    raise SystemExit(main())
