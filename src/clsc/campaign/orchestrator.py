"""campaign_01 orchestrator: `python -m clsc.campaign.orchestrator <command>`.

Implements the 7-Experiment plan in docs/Experimental_Plan.md. Each experiment's design lives in
its own module under `clsc/campaign/designs/` (exp1_verification .. exp7_policy_calibration) and
exposes `build_design_matrix()`. Experiments 6 and 7 are generated in two phases (their second
stage depends on the first stage's solved results, read back from disk).

Bilevel (leader-optimizing) runs solve on a FINE carbon-tax grid (`FINE_GRID_SCALE_FACTOR`) with
`dbp_relative_gap = 1e-4`, follower `mip_gap = 1e-6`, and DBP Phase 2 (min-tax bisection) ON. The
ablation experiment (Exp3) selects weakened variants by algorithm_variant -> solver flags
(`_VARIANT_FLAGS`): A1 no Phase-2, A2 no lexicographic Stage-2 master, A3 no warm start, A4 coarse
grid, A5 no incumbent objective-upper-bound cut. M0 is the full method.

Commands:
  generate   build design_matrix.csv for one/all experiments (experiments/campaign_01/<exp>/)
  run        materialize instances + solve one/all design points in an experiment

Execution modes (per design point, set by the experiment spec):
  bilevel            -> materialize a variant, shell out to `clsc.solver_cli.solve_batch` (DBP).
  fixed_tax          -> `solve_fixed_tax_follower` in-process (follower MILP at a fixed tax).
  min_emissions      -> `solve_fixed_tax_min_emissions` in-process (AUGMECON min-emissions anchor).
  epsilon_constraint -> `solve_epsilon_constraint_follower` in-process (emissions <= epsilon).

Two time budgets bound every design point. `per_subproblem_time_limit_seconds` is handed to Gurobi
and bounds ONE MILP; `per_run_wall_clock_cap_seconds` bounds the whole run and is enforced here --
by killing the DBP subprocess for bilevel points, and by clamping the single solve's own limit for
the in-process follower modes. A run stopped by the cap is recorded as `censored` with
`termination_reason="wall_clock_cap"`.

Resumable (plan §10): `run` skips any design point whose `campaign_manifest.json` already records a
terminal status. `--fail-fast` defaults to False so one run's exception never aborts the batch.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clsc.campaign.designs import (
    exp1_verification,
    exp2_solver_config,
    exp3_ablation,
    exp4_scalability,
    exp5_leader_value,
    exp6_sensitivity,
    exp7_policy_calibration,
    exp8_benchmark,
)
from clsc.campaign.designs._common import FINE_SCALE_FACTOR, DesignPoint, rows_to_csv_dicts
from clsc.campaign.instances import materialize

CAMPAIGN_ID = "campaign_01"
REPO_ROOT = Path(__file__).resolve().parents[3]  # src/clsc/campaign/orchestrator.py -> repo root
MANIFESTS_ROOT = REPO_ROOT / "experiments" / CAMPAIGN_ID
INSTANCES_ROOT = REPO_ROOT / "data" / "instances" / "campaigns" / CAMPAIGN_ID
RESULTS_ROOT = REPO_ROOT / "results" / "runs" / CAMPAIGN_ID
HEARTBEAT_LOG = RESULTS_ROOT / "_heartbeat.log"

EXPERIMENT_MODULES = {
    "exp1": exp1_verification,
    "exp2": exp2_solver_config,
    "exp3": exp3_ablation,
    "exp4": exp4_scalability,
    "exp5": exp5_leader_value,
    "exp6": exp6_sensitivity,
    "exp7": exp7_policy_calibration,
    "exp8": exp8_benchmark,
}

EXPERIMENT_DIR_NAMES = {
    "exp1": "exp1_verification",
    "exp2": "exp2_solver_config",
    "exp3": "exp3_ablation",
    "exp4": "exp4_scalability",
    "exp5": "exp5_leader_value",
    "exp6": "exp6_sensitivity",
    "exp7": "exp7_policy_calibration",
    "exp8": "exp8_benchmark",
}

# Experiments whose second-stage design matrix depends on first-stage solved results (read back
# from disk by the module's build_design_matrix(results_root=...)).
TWO_PHASE_EXPERIMENTS = ("exp5", "exp6", "exp7")

BILEVEL_METHOD = "dbp_lex"

# Campaign-wide solver defaults (Exp2 fixes threads/mip_focus; see docs/Experimental_Plan.md §2.3).
DEFAULT_THREADS = 4
DEFAULT_MIP_FOCUS = 2
FINE_GRID_SCALE_FACTOR = FINE_SCALE_FACTOR  # single definition lives in designs/_common.py
CAMPAIGN_DBP_RELATIVE_GAP = 1e-4
CAMPAIGN_MIP_GAP = 1e-6
REFINE_MIN_TAX = True

# Ablation variant -> extra solver flags for the bilevel (DBP) subprocess. M0 = full method (no
# extra flags). A4 (coarse grid) is handled via the point's own scale_factor, not a flag here.
_VARIANT_FLAGS: dict[str, list[str]] = {
    "M0": [],
    "A1": ["--no-refine-min-tax"],
    "A2": ["--no-lex-master-stage2"],
    "A3": ["--no-warm-start"],
    "A4": [],
    "A5": ["--no-incumbent-cut"],
}

# Stash root for solve-output files displaced ahead of a fresh/--overwrite solve, kept outside the
# project tree (never OneDrive-synced). Stashing instead of deleting means an interrupted re-solve
# always leaves the previous attempt recoverable.
OVERWRITE_STASH_ROOT = Path(tempfile.gettempdir()) / f"{CAMPAIGN_ID}_overwrite_stash"
_SOLVE_ARTIFACT_NAMES = ("summary.json", "solution.json", "result.json", "dbp_trace.csv",
                         "summary.csv", "manifest.json")


# Slack allowed past the cap before the backstop kill fires. The solver stops itself at the cap
# between iterations, but Gurobi can overrun a clamped limit slightly and the result still has to
# be written, validated and moved -- so a kill at exactly the cap would destroy usable results.
_WALL_CLOCK_BACKSTOP_GRACE = 900.0


class WallClockCapExceeded(RuntimeError):
    """A run blew past its cap AND the backstop grace, and was killed with nothing recoverable.

    The normal cap path is not this exception: the solver stops itself at the cap and returns a
    `wall_clock_cap` result carrying the incumbent. This is the pathological case only.
    """


def _stash_existing_solve_outputs(out_dir: Path, design_point_id: str) -> list[str]:
    """Move any pre-existing solve-output files out of `out_dir` before a (re-)solve attempt."""
    if not out_dir.exists():
        return []
    candidates = {out_dir / name for name in _SOLVE_ARTIFACT_NAMES}
    candidates |= set(out_dir.glob("**/summary.json"))
    present = [p for p in candidates if p.exists()]
    if not present:
        return []
    dest = OVERWRITE_STASH_ROOT / design_point_id
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for p in present:
        shutil.move(str(p), str(dest / p.name))
        moved.append(p.name)
    return moved


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

def _build_raw_points(experiment_id: str) -> list[DesignPoint]:
    module = EXPERIMENT_MODULES[experiment_id]
    if experiment_id in TWO_PHASE_EXPERIMENTS:
        return module.build_design_matrix(results_root=RESULTS_ROOT)
    return module.build_design_matrix()


def build_design_matrix(experiment_id: str) -> list[DesignPoint]:
    points = _build_raw_points(experiment_id)
    # Stamp campaign-wide defaults onto every point that doesn't set them explicitly.
    return [
        dataclasses.replace(
            p,
            threads=DEFAULT_THREADS if p.threads is None else p.threads,
            mip_focus=DEFAULT_MIP_FOCUS if p.mip_focus is None else p.mip_focus,
            dbp_relative_gap=CAMPAIGN_DBP_RELATIVE_GAP if p.dbp_relative_gap is None else p.dbp_relative_gap,
            mip_gap=CAMPAIGN_MIP_GAP if p.mip_gap is None else p.mip_gap,
        )
        for p in points
    ]


def generate(experiment_ids: list[str], *, dry_run: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    for experiment_id in experiment_ids:
        points = build_design_matrix(experiment_id)
        counts[experiment_id] = len(points)
        if not dry_run:
            rows = rows_to_csv_dicts(points)
            out_path = MANIFESTS_ROOT / EXPERIMENT_DIR_NAMES[experiment_id] / "design_matrix.csv"
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
    return RESULTS_ROOT / EXPERIMENT_DIR_NAMES[point.experiment_id] / point.base_instance_id / point.run_code


def _manifest_path(point: DesignPoint) -> Path:
    return _run_output_dir(point) / "campaign_manifest.json"


def _is_terminal(manifest: dict[str, Any]) -> bool:
    return manifest.get("solve_status") in {"success", "censored", "failed", "infeasible"}


_CENSORING_REASONS = {"time_limit", "TIME_LIMIT", "wall_clock_cap"}


def _classify_solve_status(summary: dict[str, Any]) -> str:
    if summary.get("gurobi_status") == "TIME_LIMIT" or summary.get("termination_reason") in _CENSORING_REASONS:
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


def _effective_subproblem_time_limit(point: DesignPoint) -> float:
    """Time limit for an in-process follower solve.

    These modes are a single Gurobi call, so clamping that call's own limit to the run's
    wall-clock cap enforces the cap exactly -- no external kill needed.
    """
    return min(point.per_subproblem_time_limit_seconds, point.per_run_wall_clock_cap_seconds)


def _salvage_partial_dbp_trace(scratch_root: Path, out_dir: Path) -> None:
    """Keep a killed run's partial DBP trace: it is the only record of how far the loop got."""
    traces = sorted(scratch_root.glob("**/dbp_trace.csv"))
    if not traces:
        return
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # Deliberately NOT named dbp_trace.csv: a partial trace must never be mistaken for a
        # completed run's, and `summary.json` is absent so the run stays non-terminal.
        shutil.copy2(str(traces[0]), str(out_dir / "_partial_dbp_trace.csv"))
    except OSError:
        pass


def _tax_grid_step(point: DesignPoint) -> float:
    """The tax-grid step (USD/kg CO2e per index) this design point is solved on.

    Applies to EVERY execution mode, not just bilevel: a fixed-tax index means nothing without
    the grid it indexes, so the in-process follower solves must be re-gridded onto the same step
    the bilevel runs use before their `fixed_tax_index` is interpreted. A4 (coarse grid) is the
    only variant that deliberately sets its own.
    """
    return point.scale_factor if point.scale_factor is not None else FINE_GRID_SCALE_FACTOR


def _solve_bilevel(point: DesignPoint, instance_path: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_paths = list(out_dir.glob("**/summary.json"))
    if not summary_paths:
        # Scratch-then-move under the OS temp dir: avoids leaving solve_batch's nested results-root
        # mirror behind in the OneDrive-synced project tree.
        scratch_root = Path(tempfile.mkdtemp(prefix=f"{CAMPAIGN_ID}_"))
        try:
            cmd = [
                sys.executable, "-m", "clsc.solver_cli.solve_batch", str(instance_path),
                "--method", BILEVEL_METHOD,
                "--time-limit", str(point.per_subproblem_time_limit_seconds),
                # The solver enforces the cap itself and stops between iterations with its
                # incumbent intact; the subprocess timeout below is only a backstop.
                "--wall-clock-cap", str(point.per_run_wall_clock_cap_seconds),
                "--results-root", str(scratch_root),
                "--scale-factor", str(_tax_grid_step(point)),
            ]
            if not REFINE_MIN_TAX:
                cmd += ["--no-refine-min-tax"]
            cmd += _VARIANT_FLAGS.get(point.algorithm_variant, [])
            if point.mip_gap is not None:
                cmd += ["--mip-gap", str(point.mip_gap)]
            if point.dbp_relative_gap is not None:
                cmd += ["--dbp-relative-gap", str(point.dbp_relative_gap)]
            if point.threads is not None:
                cmd += ["--threads", str(point.threads)]
            if point.mip_focus is not None:
                cmd += ["--mip-focus", str(point.mip_focus)]
            if point.gurobi_seed is not None:
                cmd += ["--seed", str(point.gurobi_seed)]
            # BACKSTOP ONLY. The cap is enforced inside the solver (`--wall-clock-cap`), which
            # stops between DBP iterations and writes a summary carrying the incumbent, its
            # variables and the certified gap. Killing the process here would throw all of that
            # away, so this timeout is deliberately slack: it fires only if the solver has hung
            # past its own budget and is no longer stopping itself.
            try:
                completed = subprocess.run(
                    cmd, cwd=REPO_ROOT, capture_output=True, text=True,
                    timeout=point.per_run_wall_clock_cap_seconds + _WALL_CLOCK_BACKSTOP_GRACE,
                )
            except subprocess.TimeoutExpired as exc:
                _salvage_partial_dbp_trace(scratch_root, out_dir)
                raise WallClockCapExceeded(
                    f"{point.design_point_id}: killed after "
                    f"{point.per_run_wall_clock_cap_seconds:.0f}s wall-clock cap "
                    f"(per-subproblem limit {point.per_subproblem_time_limit_seconds:.0f}s)"
                ) from exc
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
    summary = summary_payload[0] if isinstance(summary_payload, list) else summary_payload
    summary["_summary_path"] = str(summary_paths[0].relative_to(REPO_ROOT))
    return summary


def _write_follower_result(
    point: DesignPoint,
    instance: Any,
    result: Any,
    instance_path: Path,
    out_dir: Path,
    *,
    solve_seconds: float,
    tax_index_for_report: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shared summary/solution-writing tail for the three in-process follower solves."""
    from clsc.solvers.dbp_lex import relative_optimality_gap

    termination_reason = "optimal" if result.status_name == "OPTIMAL" else result.status_name.lower()
    relative_gap = None
    if result.objective_bound is not None and result.objective_value is not None:
        relative_gap = relative_optimality_gap(
            upper_bound=result.objective_value, lower_bound=result.objective_bound,
        )
    tax_rate = instance.tax_rate(tax_index_for_report)

    summary = {
        "instance": instance.name,
        "input_path": str(instance_path),
        "success": bool(result.has_solution),
        "termination_reason": termination_reason,
        "tax_index": tax_index_for_report,
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
    if extra:
        summary.update(extra)
    out_dir.mkdir(parents=True, exist_ok=True)

    if result.variable_values is not None:
        solution_payload = {
            "schema_version": 3,
            "instance": instance.name,
            "leader": {"tax_index": tax_index_for_report, "effective_tax": tax_rate},
            "objectives": {
                "cost": result.cost,
                "emissions": result.emissions,
                "follower_objective": result.follower_objective,
            },
            "decision_variables": {
                "leader": {"tax_index": tax_index_for_report, "effective_tax": tax_rate},
                "follower": result.variable_values,
            },
            "variables": result.variable_values,
        }
        (out_dir / "solution.json").write_text(json.dumps(solution_payload, indent=2), encoding="utf-8")
        summary["solution_file"] = str((out_dir / "solution.json").relative_to(REPO_ROOT))

    (out_dir / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["_summary_path"] = str((out_dir / "result.json").relative_to(REPO_ROOT))
    return summary


def _solve_fixed_tax(point: DesignPoint, instance_path: Path, out_dir: Path) -> dict[str, Any]:
    from clsc.models.instance import InstanceData
    from clsc.models.subproblems import solve_fixed_tax_follower

    instance = InstanceData.from_file(instance_path).with_tax_grid_step(_tax_grid_step(point))
    start = time.perf_counter()
    result = solve_fixed_tax_follower(
        instance, point.fixed_tax_index,
        time_limit=_effective_subproblem_time_limit(point),
        capture_solution=True,
        mip_gap=point.mip_gap, threads=point.threads, mip_focus=point.mip_focus,
    )
    solve_seconds = time.perf_counter() - start
    return _write_follower_result(
        point, instance, result, instance_path, out_dir,
        solve_seconds=solve_seconds, tax_index_for_report=point.fixed_tax_index,
    )


def _solve_min_emissions(point: DesignPoint, instance_path: Path, out_dir: Path) -> dict[str, Any]:
    from clsc.models.instance import InstanceData
    from clsc.models.subproblems import solve_fixed_tax_min_emissions

    instance = InstanceData.from_file(instance_path).with_tax_grid_step(_tax_grid_step(point))
    start = time.perf_counter()
    result = solve_fixed_tax_min_emissions(
        instance,
        time_limit=_effective_subproblem_time_limit(point),
        capture_solution=True,
        mip_gap=point.mip_gap, threads=point.threads, mip_focus=point.mip_focus,
    )
    solve_seconds = time.perf_counter() - start
    return _write_follower_result(
        point, instance, result, instance_path, out_dir,
        solve_seconds=solve_seconds, tax_index_for_report=0,
    )


def _solve_epsilon_constraint(point: DesignPoint, instance_path: Path, out_dir: Path) -> dict[str, Any]:
    from clsc.models.instance import InstanceData
    from clsc.models.subproblems import solve_epsilon_constraint_follower

    instance = InstanceData.from_file(instance_path).with_tax_grid_step(_tax_grid_step(point))
    start = time.perf_counter()
    result = solve_epsilon_constraint_follower(
        instance, point.epsilon_emissions,
        time_limit=_effective_subproblem_time_limit(point),
        capture_solution=True,
        mip_gap=point.mip_gap, threads=point.threads, mip_focus=point.mip_focus,
    )
    solve_seconds = time.perf_counter() - start
    return _write_follower_result(
        point, instance, result, instance_path, out_dir,
        solve_seconds=solve_seconds, tax_index_for_report=0,
        extra={"epsilon_emissions": point.epsilon_emissions},
    )


def _solve_enumeration(point: DesignPoint, instance_path: Path, out_dir: Path) -> dict[str, Any]:
    """Exp8's baseline: solve the fixed-tax lexicographic follower at EVERY grid point.

    Exact by construction (no cuts, no theory) -- the naive method a referee would propose as
    DBP's alternative. Reused fields (cost/emissions/tax_index/solution.json) come from
    `_write_follower_result` so the aggregator reads exp8 rows the same way it reads any other
    follower-mode row; enumeration-specific fields (follower-solve count, grid coverage, total
    follower time) ride along in ``extra``.
    """
    import csv as _csv

    from clsc.models.instance import InstanceData
    from clsc.solvers.enumeration import enumerate_tax_grid

    instance = InstanceData.from_file(instance_path).with_tax_grid_step(_tax_grid_step(point))
    start = time.perf_counter()
    enum_result = enumerate_tax_grid(
        instance, instance,
        time_limit=point.per_subproblem_time_limit_seconds,
        wall_clock_cap=point.per_run_wall_clock_cap_seconds,
        mip_gap=point.mip_gap, threads=point.threads, mip_focus=point.mip_focus,
        seed=point.gurobi_seed,
    )
    solve_seconds = time.perf_counter() - start

    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / "enumeration_trace.csv"
    with trace_path.open("w", newline="", encoding="utf-8") as fh:
        writer = _csv.writer(fh)
        writer.writerow(["tax_index", "emissions", "cost", "solve_seconds"])
        for record in enum_result.grid_records:
            writer.writerow([record.tax_index, record.emissions, record.cost, record.solve_seconds])

    summary = _write_follower_result(
        point, instance, enum_result.incumbent_solution, instance_path, out_dir,
        solve_seconds=solve_seconds, tax_index_for_report=enum_result.incumbent.tax_index,
        extra={
            "termination_reason": enum_result.termination_reason,
            "exact": enum_result.exact,
            "follower_solve_count": enum_result.points_visited,
            "grid_points_total": enum_result.points_total,
            "grid_coverage_fraction": enum_result.points_visited / enum_result.points_total,
            "follower_seconds_total": enum_result.follower_seconds_total,
            "enumeration_trace_file": str(trace_path.relative_to(REPO_ROOT)),
        },
    )
    return summary


def run_point(point: DesignPoint, *, overwrite: bool = False) -> dict[str, Any]:
    out_dir = _run_output_dir(point)
    manifest_path = _manifest_path(point)
    if manifest_path.exists() and not overwrite:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if _is_terminal(existing):
            _append_heartbeat(f"SKIP (already terminal) {point.experiment_id}/{point.base_instance_id}/{point.run_code}")
            return existing

    _append_heartbeat(f"START {point.experiment_id}/{point.base_instance_id}/{point.run_code}")
    solver_method_by_execution_mode = {
        "bilevel": BILEVEL_METHOD,
        "fixed_tax": "fixed_tax_follower",
        "min_emissions": "fixed_tax_min_emissions",
        "epsilon_constraint": "epsilon_constraint_follower",
        "enumeration": "exhaustive_grid_enumeration",
    }
    manifest: dict[str, Any] = {
        "campaign_id": CAMPAIGN_ID,
        "experiment_id": point.experiment_id,
        "design_point_id": point.design_point_id,
        "base_instance_id": point.base_instance_id,
        "algorithm_variant": point.algorithm_variant,
        "factor_levels": point.factor_levels,
        "production_technology_menu": point.production_technology_menu,
        "remanufacturing_technology_menu": point.remanufacturing_technology_menu,
        "road_menu": point.road_menu,
        "sea_menu": point.sea_menu,
        "air_menu": point.air_menu,
        "seed_offset": point.seed_offset,
        "valuation_ratio": point.valuation_ratio,
        "gurobi_seed": point.gurobi_seed,
        "epsilon_emissions": point.epsilon_emissions,
        "code_version": _code_version(),
        "solver_method": solver_method_by_execution_mode[point.execution_mode],
        # Without the grid step a tax index is uninterpretable, and the two campaign grids are
        # 100x apart -- so it is recorded per run rather than assumed downstream.
        "tax_grid_step_usd_per_kg": _tax_grid_step(point),
        "time_limit_seconds": point.per_subproblem_time_limit_seconds,
        "wall_clock_cap_seconds": point.per_run_wall_clock_cap_seconds,
        "created_at_utc": _utc_now_iso(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({**manifest, "solve_status": "running"}, indent=2, default=str), encoding="utf-8"
    )
    started = time.perf_counter()
    try:
        if point.is_toy:
            from clsc.campaign.toy import materialize_toy
            instance_path = materialize_toy(point, output_root=INSTANCES_ROOT)
        else:
            instance_path = materialize(point, output_root=INSTANCES_ROOT)
        manifest["input_instance_path"] = str(instance_path)

        stashed = _stash_existing_solve_outputs(out_dir, point.design_point_id)
        if stashed:
            _append_heartbeat(
                f"STASH {point.experiment_id}/{point.base_instance_id}/{point.run_code} "
                f"moved {stashed} -> {OVERWRITE_STASH_ROOT / point.design_point_id}"
            )

        if point.execution_mode == "bilevel":
            summary = _solve_bilevel(point, instance_path, out_dir)
        elif point.execution_mode == "fixed_tax":
            summary = _solve_fixed_tax(point, instance_path, out_dir)
        elif point.execution_mode == "min_emissions":
            summary = _solve_min_emissions(point, instance_path, out_dir)
        elif point.execution_mode == "epsilon_constraint":
            summary = _solve_epsilon_constraint(point, instance_path, out_dir)
        elif point.execution_mode == "enumeration":
            summary = _solve_enumeration(point, instance_path, out_dir)
        else:
            raise ValueError(f"Unknown execution_mode: {point.execution_mode!r}")

        manifest.update(
            {
                "solve_status": _classify_solve_status(summary),
                "termination_reason": summary.get("termination_reason"),
                "censored": summary.get("gurobi_status") == "TIME_LIMIT"
                or summary.get("termination_reason") in _CENSORING_REASONS,
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
                # The solver's own rate, in the one unit that IS comparable across grids.
                "effective_tax_usd_per_kg": summary.get("effective_tax"),
                "runtime_seconds": summary.get("solve_seconds"),
                "mip_gap": summary.get("relative_gap"),
                "output_path": summary.get("_summary_path"),
                "validation_status": summary.get("validation_status"),
                "notes": point.notes,
            }
        )
        _append_heartbeat(f"DONE  {point.experiment_id}/{point.base_instance_id}/{point.run_code} "
                           f"status={manifest['solve_status']}")
    except WallClockCapExceeded as exc:
        # Backstop kill only (the solver failed to stop itself within the grace period). The
        # normal cap path returns through the success branch above WITH objective values, so
        # reaching here means the process was killed mid-solve and nothing is recoverable.
        manifest.update(
            {
                "solve_status": "censored",
                "termination_reason": "wall_clock_cap_killed",
                "censored": True,
                "objective_values": {"cost": None, "emissions": None, "follower_objective": None},
                "leader_tax": None,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "notes": point.notes,
            }
        )
        _append_heartbeat(f"DONE  {point.experiment_id}/{point.base_instance_id}/{point.run_code} "
                           f"status=censored reason=wall_clock_cap")
    except Exception as exc:  # noqa: BLE001 -- campaign must continue past any single failure
        manifest.update({"solve_status": "failed", "error_type": type(exc).__name__, "error_message": str(exc)})
        _append_heartbeat(f"FAIL  {point.experiment_id}/{point.base_instance_id}/{point.run_code} "
                           f"error={type(exc).__name__}")

    # Measured end-to-end wall clock, independent of whatever the solver self-reports.
    manifest["wall_clock_seconds"] = time.perf_counter() - started
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return manifest


def run_experiment(
    experiment_id: str,
    *,
    fail_fast: bool = False,
    overwrite: bool = False,
    base_instance: str | None = None,
) -> list[dict[str, Any]]:
    points = build_design_matrix(experiment_id)
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

def _resolve_experiment_ids(experiment_arg: str) -> list[str]:
    if experiment_arg == "all":
        return list(EXPERIMENT_MODULES)
    normalized = experiment_arg if experiment_arg.startswith("exp") else f"exp{experiment_arg}"
    if normalized not in EXPERIMENT_MODULES:
        raise ValueError(
            f"Unknown experiment {experiment_arg!r}; choose from {list(EXPERIMENT_MODULES)} or 'all'"
        )
    return [normalized]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m clsc.campaign.orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Build design_matrix.csv for one or all experiments.")
    gen.add_argument("--experiment", default="all", help="Experiment id (exp1..exp7 or 1..7) or 'all'.")
    gen.add_argument("--dry-run", action="store_true", help="Print counts only; do not write CSVs.")

    run_cmd = sub.add_parser("run", help="Materialize instances and solve one or all design points.")
    run_cmd.add_argument("--experiment", default="all", help="Experiment id (exp1..exp7 or 1..7) or 'all'.")
    run_cmd.add_argument("--fail-fast", action="store_true")
    run_cmd.add_argument("--overwrite", action="store_true", help="Re-run even if already terminal.")
    run_cmd.add_argument("--base-instance", default=None,
                          help="Restrict to design points on this base instance only (e.g. for a pilot).")

    args = parser.parse_args(argv)

    if args.command == "generate":
        experiment_ids = _resolve_experiment_ids(args.experiment)
        counts = generate(experiment_ids, dry_run=args.dry_run)
        total = sum(counts.values())
        for experiment_id, count in counts.items():
            print(f"  {experiment_id}: {count} design points")
        print(f"Total: {total} design points across {len(counts)} experiment(s)"
              f"{' (dry run, no files written)' if args.dry_run else ''}")
        return 0

    if args.command == "run":
        experiment_ids = _resolve_experiment_ids(args.experiment)
        for experiment_id in experiment_ids:
            results = run_experiment(
                experiment_id, fail_fast=args.fail_fast, overwrite=args.overwrite,
                base_instance=args.base_instance,
            )
            n_success = sum(1 for r in results if r.get("solve_status") == "success")
            print(f"{experiment_id}: {n_success}/{len(results)} succeeded")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
