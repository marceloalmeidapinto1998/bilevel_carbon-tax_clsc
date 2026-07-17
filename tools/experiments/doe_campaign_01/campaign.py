"""doe_campaign_01 campaign orchestrator: `python -m tools.experiments.doe_campaign_01.campaign <command>`.

  generate   build design_matrix.csv for one or all families (experiments/manifests/<family>/)
  run        materialize instances + solve one or all design points in a family

Execution modes (per design point, set by the family spec):
  bilevel     -> materialize an instance variant, shell out to `tools.solver.solve_batch`
                 (the existing, unmodified DBP batch solver) with a per-run results-root.
  fixed_tax   -> no instance mutation; call `solve_fixed_tax_follower` directly in-process
                 (Family B: solves the follower MILP at a fixed tax, no leader optimization).

Resumable by design (plan §10): `run` skips any design point whose `campaign_manifest.json`
already records a terminal status. `--fail-fast` defaults to False so one run's exception never
aborts the batch; failures are caught, logged to the run's `campaign_manifest.json`, and a
campaign-level heartbeat line is appended either way.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from experiments.designs import (
    family_a_baseline,
    family_b_tax_frontier,
    family_c_screening_factorial,
    family_d_lever_factorial,
    family_e_response_surface,
    family_f_robustness,
    family_g_performance,
)
from experiments.designs._common import DesignPoint, rows_to_csv_dicts

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFESTS_ROOT = REPO_ROOT / "experiments" / "manifests"
INSTANCES_ROOT = REPO_ROOT / "data" / "instances" / "campaigns" / "doe_campaign_01"
RESULTS_ROOT = REPO_ROOT / "results" / "runs" / "doe_campaign_01"
HEARTBEAT_LOG = RESULTS_ROOT / "_heartbeat.log"

FAMILY_MODULES = {
    "A": family_a_baseline,
    "B": family_b_tax_frontier,
    "C": family_c_screening_factorial,
    "D": family_d_lever_factorial,
    "E": family_e_response_surface,
    "F": family_f_robustness,
    "G": family_g_performance,
}

FAMILY_DIR_NAMES = {
    "A": "A_baseline_benchmark",
    "B": "B_tax_emissions_frontier",
    "C": "C_factor_screening",
    "D": "D_lever_factorial",
    "E": "E_response_surface",
    "F": "F_robustness",
    "G": "G_performance",
}

BILEVEL_METHOD = "dbp_lex"


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

def build_design_matrix(family_id: str) -> list[DesignPoint]:
    return FAMILY_MODULES[family_id].build_design_matrix()


def generate(family_ids: list[str], *, dry_run: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    for family_id in family_ids:
        points = build_design_matrix(family_id)
        counts[family_id] = len(points)
        if not dry_run:
            rows = rows_to_csv_dicts(points)
            out_path = MANIFESTS_ROOT / FAMILY_DIR_NAMES[family_id] / "design_matrix.csv"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    return counts


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def _code_version() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_output_dir(point: DesignPoint) -> Path:
    base = RESULTS_ROOT / FAMILY_DIR_NAMES[point.family_id] / point.base_instance_id
    if point.family_id == "A":  # single-run family — run_code ("baseline") subfolder is redundant
        return base
    return base / point.run_code


def _manifest_path(point: DesignPoint) -> Path:
    return _run_output_dir(point) / "campaign_manifest.json"


def _is_terminal(manifest: dict[str, Any]) -> bool:
    return manifest.get("solve_status") in {"success", "censored", "failed", "infeasible"}


def _classify_solve_status(summary: dict[str, Any]) -> str:
    """success | censored (hit the time limit, incumbent retained per plan §5b) |
    infeasible (genuine Gurobi INFEASIBLE) | failed (anything else, e.g. a solver exception).

    Time-limit check is before success: a solve that returned an incumbent but stopped
    due to time limit (termination_reason='time_limit', success=True) must be censored,
    not success.
    """
    if summary.get("gurobi_status") == "TIME_LIMIT" or summary.get("termination_reason") in {"time_limit", "TIME_LIMIT"}:
        return "censored"
    if summary.get("success"):
        return "success"
    if summary.get("gurobi_status") == "INFEASIBLE":
        return "infeasible"
    return "failed"


def _append_heartbeat(message: str) -> None:
    HEARTBEAT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with HEARTBEAT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{_utc_now_iso()}\t{message}\n")


def _solve_bilevel(point: DesignPoint, instance_path: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_paths = list(out_dir.glob("**/summary.json"))
    if not summary_paths:
        # solve_batch mirrors the instance's data/instances/ subpath under whatever
        # --results-root it's given (e.g. base/campaigns/doe_campaign_01/.../f_lex_exact/),
        # so pointing it at out_dir directly used to leave that nested tree behind under
        # results/runs/ -- visible in the OneDrive-synced project and prone to the sync
        # engine's rmdir lock race (2026-07-01/03). Instead, point it at a scratch directory
        # under the OS temp folder (never synced, never part of the project tree), then move
        # only the final files into out_dir and discard the whole scratch tree. A killed
        # mid-solve attempt leaves at most a stray temp-folder entry, never a visible orphan
        # in results/runs/. Each invocation gets a fresh scratch dir, so solve_batch never
        # sees a pre-existing run directory there and --overwrite is not needed.
        scratch_root = Path(tempfile.mkdtemp(prefix="doe_campaign_01_"))
        try:
            cmd = [
                sys.executable, "-m", "tools.solver.solve_batch", str(instance_path),
                "--method", BILEVEL_METHOD,
                "--time-limit", str(point.per_subproblem_time_limit_seconds),
                "--results-root", str(scratch_root),
            ]
            if point.mip_gap is not None:
                cmd += ["--mip-gap", str(point.mip_gap)]
            if point.dbp_relative_gap is not None:
                cmd += ["--dbp-relative-gap", str(point.dbp_relative_gap)]
            if point.threads is not None:
                cmd += ["--threads", str(point.threads)]
            if point.mip_focus is not None:
                cmd += ["--mip-focus", str(point.mip_focus)]
            completed = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
            scratch_summaries = list(scratch_root.glob("**/summary.json"))
            if not scratch_summaries:
                raise RuntimeError(
                    f"{point.design_point_id}: solver subprocess produced no summary.json "
                    f"(returncode={completed.returncode}); stderr tail:\n{completed.stderr[-2000:]}"
                )
            for f in scratch_summaries[0].parent.iterdir():
                shutil.move(str(f), str(out_dir / f.name))
        finally:
            shutil.rmtree(scratch_root, ignore_errors=True)
        summary_paths = list(out_dir.glob("summary.json"))
    summary_payload = json.loads(summary_paths[0].read_text(encoding="utf-8"))
    # tools.solver.batch writes summary.json as a list of per-instance records (batch format),
    # even for a single-instance invocation.
    summary = summary_payload[0] if isinstance(summary_payload, list) else summary_payload
    summary["_summary_path"] = str(summary_paths[0].relative_to(REPO_ROOT))
    return summary


def _solve_fixed_tax(point: DesignPoint, instance_path: Path, out_dir: Path) -> dict[str, Any]:
    from clsc.models.instance import InstanceData
    from clsc.models.subproblems import solve_fixed_tax_follower
    from clsc.solvers.dbp_lex import relative_optimality_gap

    instance = InstanceData.from_file(instance_path)
    start = time.perf_counter()
    result = solve_fixed_tax_follower(
        instance, point.fixed_tax_index, time_limit=point.per_subproblem_time_limit_seconds,
        capture_solution=True,
    )
    solve_seconds = time.perf_counter() - start

    termination_reason = "optimal" if result.status_name == "OPTIMAL" else result.status_name.lower()
    relative_gap = None
    if result.objective_bound is not None and result.objective_value is not None:
        relative_gap = relative_optimality_gap(
            upper_bound=result.objective_value, lower_bound=result.objective_bound,
        )
    tax_rate = instance.tax_rate(point.fixed_tax_index)

    summary = {
        "instance": instance.name,
        "input_path": str(instance_path),
        "success": bool(result.has_solution),
        "termination_reason": termination_reason,
        "tax_index": point.fixed_tax_index,
        "effective_tax": tax_rate,
        "cost": result.cost,
        "emissions": result.emissions,
        "follower_objective": result.follower_objective,
        "lower_bound": result.objective_bound,
        "upper_bound": result.objective_value,
        "relative_gap": relative_gap,
        "mip_gap": result.mip_gap,
        "solve_seconds": solve_seconds,
    }
    out_dir.mkdir(parents=True, exist_ok=True)

    if result.variable_values is not None:
        solution_payload = {
            "schema_version": 3,
            "instance": instance.name,
            "leader": {"tax_index": point.fixed_tax_index, "effective_tax": effective_tax},
            "objectives": {
                "cost": result.cost,
                "emissions": result.emissions,
                "follower_objective": result.follower_objective,
            },
            "decision_variables": {
                "leader": {"tax_index": point.fixed_tax_index, "effective_tax": effective_tax},
                "follower": result.variable_values,
            },
            "variables": result.variable_values,
        }
        (out_dir / "solution.json").write_text(json.dumps(solution_payload, indent=2), encoding="utf-8")
        summary["solution_file"] = str((out_dir / "solution.json").relative_to(REPO_ROOT))

    (out_dir / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["_summary_path"] = str((out_dir / "result.json").relative_to(REPO_ROOT))
    return summary


def run_point(point: DesignPoint, *, overwrite: bool = False) -> dict[str, Any]:
    out_dir = _run_output_dir(point)
    manifest_path = _manifest_path(point)
    if manifest_path.exists() and not overwrite:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if _is_terminal(existing):
            _append_heartbeat(f"SKIP (already terminal) {point.family_id}/{point.base_instance_id}/{point.run_code}")
            return existing

    _append_heartbeat(f"START {point.family_id}/{point.base_instance_id}/{point.run_code}")
    manifest: dict[str, Any] = {
        "campaign_id": "doe_campaign_01",
        "family_id": point.family_id,
        "design_point_id": point.design_point_id,
        "base_instance_id": point.base_instance_id,
        "factor_levels": point.factor_levels,
        "technology_menu": point.technology_menu,
        "transport_menu": point.transport_menu,
        "seed_offset": point.seed_offset,
        "code_version": _code_version(),
        "solver_method": BILEVEL_METHOD if point.execution_mode == "bilevel" else "fixed_tax_follower",
        "time_limit_seconds": point.per_subproblem_time_limit_seconds,
        "wall_clock_cap_seconds": point.per_run_wall_clock_cap_seconds,
        "created_at_utc": _utc_now_iso(),
    }
    # Write a "running" marker immediately so the run's directory shows visible progress while
    # the (possibly multi-hour) solve is in flight -- solve_batch itself now writes to a scratch
    # temp dir, not here, so without this there would be nothing in out_dir until completion.
    # "running" is not in _is_terminal()'s set, so a kill mid-solve leaves this marker behind and
    # a later resume correctly re-runs the point rather than skipping it.
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({**manifest, "solve_status": "running"}, indent=2, default=str), encoding="utf-8"
    )
    try:
        from tools.experiments.doe_campaign_01.instances import materialize

        instance_path = materialize(point, output_root=INSTANCES_ROOT)
        manifest["input_instance_path"] = str(instance_path)

        if point.execution_mode == "bilevel":
            summary = _solve_bilevel(point, instance_path, out_dir)
        elif point.execution_mode == "fixed_tax":
            summary = _solve_fixed_tax(point, instance_path, out_dir)
        else:
            raise ValueError(f"Unknown execution_mode: {point.execution_mode!r}")

        manifest.update(
            {
                "solve_status": _classify_solve_status(summary),
                "termination_reason": summary.get("termination_reason"),
                "censored": summary.get("gurobi_status") == "TIME_LIMIT"
                or summary.get("termination_reason") in {"time_limit", "TIME_LIMIT"},
                "objective_values": {
                    "cost": summary.get("cost"),
                    "emissions": summary.get("emissions"),
                    "follower_objective": summary.get("follower_objective"),
                },
                "leader_tax": (
                    summary.get("tax_index", summary.get("hat_tau"))
                    if point.fixed_tax_index is None
                    else point.fixed_tax_index
                ),
                "runtime_seconds": summary.get("solve_seconds"),
                "mip_gap": summary.get("relative_gap"),
                "output_path": summary.get("_summary_path"),
                "validation_status": summary.get("validation_status"),
                "notes": point.notes,
            }
        )
        _append_heartbeat(f"DONE  {point.family_id}/{point.base_instance_id}/{point.run_code} "
                           f"status={manifest['solve_status']}")
    except Exception as exc:  # noqa: BLE001 -- campaign must continue past any single failure
        manifest.update({"solve_status": "failed", "error_type": type(exc).__name__, "error_message": str(exc)})
        _append_heartbeat(f"FAIL  {point.family_id}/{point.base_instance_id}/{point.run_code} "
                           f"error={type(exc).__name__}")

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return manifest


def run_family(
    family_id: str,
    *,
    fail_fast: bool = False,
    overwrite: bool = False,
    base_instance: str | None = None,
) -> list[dict[str, Any]]:
    points = build_design_matrix(family_id)
    if base_instance is not None:
        points = [p for p in points if p.base_instance_id == base_instance]
    results = []
    for point in points:
        manifest = run_point(point, overwrite=overwrite)
        results.append(manifest)
        if fail_fast and manifest.get("solve_status") == "failed":
            break
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_family_ids(family_arg: str) -> list[str]:
    if family_arg == "all":
        return list(FAMILY_MODULES)
    if family_arg not in FAMILY_MODULES:
        raise ValueError(f"Unknown family {family_arg!r}; choose from {list(FAMILY_MODULES)} or 'all'")
    return [family_arg]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.experiments.doe_campaign_01.campaign")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Build design_matrix.csv for one or all families.")
    gen.add_argument("--family", default="all", help="Family id (A-G) or 'all'.")
    gen.add_argument("--dry-run", action="store_true", help="Print counts only; do not write CSVs.")

    run_cmd = sub.add_parser("run", help="Materialize instances and solve one or all design points.")
    run_cmd.add_argument("--family", default="all", help="Family id (A-G) or 'all'.")
    run_cmd.add_argument("--fail-fast", action="store_true")
    run_cmd.add_argument("--overwrite", action="store_true", help="Re-run even if already terminal.")
    run_cmd.add_argument("--base-instance", default=None,
                          help="Restrict to design points on this base instance only (e.g. for a pilot).")

    args = parser.parse_args(argv)

    if args.command == "generate":
        family_ids = _resolve_family_ids(args.family)
        counts = generate(family_ids, dry_run=args.dry_run)
        total = sum(counts.values())
        for family_id, count in counts.items():
            print(f"  Family {family_id}: {count} design points")
        print(f"Total: {total} design points across {len(counts)} family(ies)"
              f"{' (dry run, no files written)' if args.dry_run else ''}")
        return 0

    if args.command == "run":
        family_ids = _resolve_family_ids(args.family)
        for family_id in family_ids:
            results = run_family(
                family_id, fail_fast=args.fail_fast, overwrite=args.overwrite,
                base_instance=args.base_instance,
            )
            n_success = sum(1 for r in results if r.get("solve_status") == "success")
            print(f"Family {family_id}: {n_success}/{len(results)} succeeded")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
