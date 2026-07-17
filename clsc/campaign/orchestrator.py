"""doe_campaign_02 campaign orchestrator: `python -m clsc.campaign.orchestrator <command>`.

Implements the redesigned experimental plan in `results/runs/doe_campaign_02/EXPERIMENTAL_PLAN.md`:
7 families (0, A-F) on a 12-instance grid (I in {17,25} x M in {4,8} x T in {3,6,12}), an 8
continuous + 5 structural factor registry, and Family B's merged tax-indexed / epsilon-constraint
cost-emissions frontier sweep. Every family's design lives in its own brand-new module under
`clsc/campaign/designs/` (family_0_solver_preflight, family_a_baseline_v2,
family_b_cost_emissions_frontier, family_c_oat_screening, family_d_scenario_analysis,
family_f_gap_robustness, plus the reused-as-is family_e_response_surface) -- none of
doe_campaign_01's original family modules (family_a_baseline.py, family_b_tax_frontier.py, etc.)
are imported or modified here, since those are doe_campaign_01's already-executed, archived design.

Bilevel (leader-optimizing) runs solve on a FINE carbon-tax grid: `--scale-factor 0.0001`
(`FINE_GRID_SCALE_FACTOR` below) refines each in-memory instance to index {0..2000} / 0.1 USD/t
resolution over the same 0-200 USD/t span, with no instance file touched; the outer DBP loop uses
`dbp_relative_gap = 1e-4` (`CAMPAIGN_DBP_RELATIVE_GAP`, tightened from `DEFAULT` = 1e-2 so it climbs
off the fine grid's flat plateau); and DBP Phase 2 (`REFINE_MIN_TAX = True`) recovers the exact
least-intervention tax. The per-MILP follower `mip_gap` is tightened to `1e-6` (`CAMPAIGN_MIP_GAP`,
from `DEFAULT` = 1e-2) to match the validated fine-grid solve and let the outer 1e-4 certify, for
every point that doesn't set it (Family F sets its own swept values -- it is a follower-`mip_gap`
probe). `stagnation_limit = 20`.
Family 0's own threads/MIPFocus sweep result gates the `threads`/`mip_focus` values
(`DEFAULT_THREADS`/`DEFAULT_MIP_FOCUS` below) applied to every other family's design points that
don't set them explicitly (Family 0's own 9 cells set threads/mip_focus per swept cell).

Commands:
  generate   build design_matrix.csv for one or all families (manifests/doe_campaign_02/<family>/)
  run        materialize instances + solve one or all design points in a family

Execution modes (per design point, set by the family spec):
  bilevel            -> materialize an instance variant, shell out to `clsc.solver_cli.solve_batch`
                         (the existing, unmodified DBP batch solver) with a per-run results-root.
  fixed_tax          -> no instance mutation; call `solve_fixed_tax_follower` directly in-process
                         (follower MILP at a fixed tax, no leader optimization).
  min_emissions      -> call `solve_fixed_tax_min_emissions` in-process (Family B's AUGMECON
                         payoff-table minimum-emissions anchor: tax_index=0, minimize emissions).
  epsilon_constraint -> call `solve_epsilon_constraint_follower` in-process (Family B's
                         intermediate epsilon-grid points: minimize cost s.t. emissions <= epsilon).

Family B is generated in two phases (mirrors Family E's data-driven pattern): `generate --family B`
before any solves exist returns only the context-free tax sweep + minimum-emissions anchors (36
runs); `run --family B` solves those, and a *subsequent* `generate --family B` call automatically
picks up the two anchors' solved emissions values from their own manifests
(`_family_b_epsilon_anchors` below) and expands the design matrix to the full 56 runs, ready for
`run --family B` to pick up the newly added intermediate epsilon-grid points.

Resumable by design (mirrors doe_campaign_01 plan §10): `run` skips any design point whose
`campaign_manifest.json` already records a terminal status. `--fail-fast` defaults to False so one
run's exception never aborts the batch; failures are caught, logged to the run's
`campaign_manifest.json`, and a campaign-level heartbeat line is appended either way.
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
    family_0_solver_preflight,
    family_a_baseline_v2,
    family_b_cost_emissions_frontier,
    family_c_oat_screening,
    family_d_scenario_analysis,
    family_e_response_surface,
    family_f_gap_robustness,
)
from clsc.campaign.designs._common import DesignPoint, rows_to_csv_dicts
# Reused as-is: reads the authoritative base-instance data under data/instances/base/ (repointed
# 2026-07-16 from the former data/instances/campaigns/doe_campaign_01/base copy, verified functionally
# identical -- same seeds/sets/parameters, differing only in a legacy tax-index JSON key name that
# InstanceData normalizes on load) and writes materialized variants under whatever output_root this
# module passes in (doe_campaign_02's own tree, below).
from clsc.campaign.instances import materialize

CAMPAIGN_ID = "doe_campaign_02"
REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFESTS_ROOT = REPO_ROOT / "manifests" / CAMPAIGN_ID
INSTANCES_ROOT = REPO_ROOT / "data" / "instances" / "campaigns" / CAMPAIGN_ID
RESULTS_ROOT = REPO_ROOT / "results" / "runs" / CAMPAIGN_ID
HEARTBEAT_LOG = RESULTS_ROOT / "_heartbeat.log"

# Family 0 (solver pre-flight) runs FIRST: its outcome under stagnation_limit=20 determines
# DEFAULT_MIP_FOCUS before families A-F are launched, making the campaign's solver-config choice
# self-contained. Unlike doe_campaign_01's equivalent sweep ("Family G", run last), this campaign's
# Family 0 runs the full 3x3 threads x MIPFocus grid (no cell excluded as "already covered"), since
# nothing here is decided ahead of this sweep's own result -- see family_0_solver_preflight.py.
SOLVER_PREFLIGHT_FAMILY_ID = "0"

FAMILY_MODULES = {
    SOLVER_PREFLIGHT_FAMILY_ID: family_0_solver_preflight,  # first: gates A-F's solver config
    "A": family_a_baseline_v2,
    "B": family_b_cost_emissions_frontier,
    "C": family_c_oat_screening,
    "D": family_d_scenario_analysis,
    "E": family_e_response_surface,
    "F": family_f_gap_robustness,
}

FAMILY_DIR_NAMES = {
    SOLVER_PREFLIGHT_FAMILY_ID: "0_solver_preflight",
    "A": "A_baseline_benchmark",
    "B": "B_tax_emissions_frontier",
    "C": "C_factor_screening",
    "D": "D_lever_factorial",
    "E": "E_response_surface",
    "F": "F_robustness",
}

BILEVEL_METHOD = "dbp_lex"
# Confirmed by Family 0's pre-flight sweep on STD_I25_M8_T6 (2026-07-08), full 3x3 threads x
# MIPFocus grid, single replicate per cell. threads=4/mip_focus=2 was the fastest cell (201.3 s),
# with threads=4 being the clear efficiency knee: 2->4 threads cuts wall-clock ~2.7x, but 4->6 gives
# no further gain (260.3 s at threads=6/mip_focus=0, the previously-used "robust default"). All 9
# cells converged exact (relative_gap, 2 DBP iterations, gap 0.17-0.35%), so mip_focus=2's slightly
# tighter final gaps at both threads=4 and threads=6 make it the balanced choice, not just the
# fastest single cell. Applied to every A-F design point that doesn't set threads/mip_focus
# explicitly (Family 0's own 9 cells keep their swept per-cell values and are unaffected).
DEFAULT_THREADS = 4
DEFAULT_MIP_FOCUS = 2

# Fine carbon-tax grid for the bilevel (leader-optimizing) runs. The stored base instances carry a
# coarse grid (index {0..20}, theta = 0.01 USD/kg = 10 USD/t per step); the campaign solves on the
# refined step below WITHOUT touching any instance file -- solve_batch's --scale-factor recomputes
# each in-memory instance's index bounds from its own tau range (overline_tau/theta), so
# overline_tax_index becomes 0.2/0.0001 = 2000 (index {0..2000}, 0.1 USD/t resolution over the same
# 0-200 USD/t span). Only the spatial+integer DBP master (McCormick + NonConvex=2) is used, so the
# fine grid costs ~log(N), not O(N). Applied to every bilevel solve below.
FINE_GRID_SCALE_FACTOR = 0.0001
# Outer DBP loop stopping tolerance for the bilevel runs. Tightened from DEFAULT (1e-2) to 1e-4:
# on the fine grid the emissions response has a long flat plateau, and only a gap this tight climbs
# off it to the certified optimum (a 1e-2 gap stops on the plateau). Stamped onto every design point
# that doesn't set dbp_relative_gap explicitly (Family F sets its own around 1e-4 too -- it is a
# per-MILP mip_gap probe, not an outer-gap probe).
CAMPAIGN_DBP_RELATIVE_GAP = 1e-4
# Per-MILP follower mip_gap for the bilevel runs. Tightened from DEFAULT (1e-2) to 1e-6 to match the
# validated fine-grid solve (the STD_I25 min-tax validation ran the follower at 1e-6): with the outer
# loop targeting 1e-4, a 1e-2 follower cannot certify it and would leave the emissions floor loose
# (the lexicographic freeze band, ~mip_gap wide, lets the cost-minimizing secondary drift emissions
# by up to a few % at low tax). Stamped onto every point that doesn't set mip_gap explicitly (Family
# F sets its own swept values -- it deliberately probes LOOSER follower gaps against this tight base).
CAMPAIGN_MIP_GAP = 1e-6
# DBP Phase 2 (min-tax bisection): after certifying minimum emissions E*, bisect the follower's
# monotone emissions(tau) to recover the EXACT least-intervention tax_index (the leader's
# lexicographic secondary objective). On -> correct + deterministic reported tax at ~2x per-run
# time; off -> the incumbent's tax (an upper bound), cheaper but over-reported and non-deterministic.
REFINE_MIN_TAX = True

# Stash root for solve-output files displaced ahead of a fresh/--overwrite solve, kept outside the
# project tree (never OneDrive-synced). `_solve_bilevel`/`_solve_fixed_tax` below decide whether to
# actually solve purely by "does a summary.json already exist in out_dir" -- NOT by whether
# overwrite was requested -- so a stale artifact from a previous attempt would otherwise make a
# requested re-solve silently return the old result. doe_campaign_01's D-06-seed1 point
# (2026-07-06) lost its solve-detail files this way: they were deleted (not stashed) ahead of a
# re-solve that was then interrupted, leaving neither the old nor the new result on disk. Stashing
# instead of deleting means an interrupted re-solve here always leaves the previous attempt
# recoverable.
OVERWRITE_STASH_ROOT = Path(tempfile.gettempdir()) / f"{CAMPAIGN_ID}_overwrite_stash"
_SOLVE_ARTIFACT_NAMES = ("summary.json", "solution.json", "result.json", "dbp_trace.csv",
                         "summary.csv", "manifest.json")


def _stash_existing_solve_outputs(out_dir: Path, design_point_id: str) -> list[str]:
    """Move any pre-existing solve-output files out of `out_dir` before a (re-)solve attempt.
    No-op (returns []) on a completely fresh out_dir, so this doesn't affect a first-time run.
    """
    if not out_dir.exists():
        return []
    candidates = {out_dir / name for name in _SOLVE_ARTIFACT_NAMES}
    candidates |= set(out_dir.glob("**/summary.json"))
    present = [p for p in candidates if p.exists()]
    if not present:
        return []
    dest = OVERWRITE_STASH_ROOT / design_point_id
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)  # drop a stale stash from an even earlier attempt
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for p in present:
        shutil.move(str(p), str(dest / p.name))
        moved.append(p.name)
    return moved


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

def _family_b_epsilon_anchors() -> dict[str, tuple[float, float]]:
    """Read Family B's own already-solved manifests to recover the two AUGMECON payoff-table
    anchors for each representative instance: the minimum-cost anchor's emissions (the
    `tax_index=0` tax-sweep run) and the minimum-emissions anchor's emissions (the dedicated
    `min_emissions` run). An instance is included only once BOTH of its anchor runs have a
    terminal, successful manifest on disk -- so before anything has been solved this returns {}
    and `family_b_cost_emissions_frontier.build_design_matrix()` falls back to its context-free
    Phase-1 design (see that module's docstring).
    """
    anchors: dict[str, tuple[float, float]] = {}
    for instance_id in family_b_cost_emissions_frontier.REPRESENTATIVE_INSTANCES:
        base = RESULTS_ROOT / FAMILY_DIR_NAMES["B"] / instance_id
        min_cost_manifest = base / "tau00" / "campaign_manifest.json"
        min_emissions_manifest = base / "eps_anchor_min_emissions" / "campaign_manifest.json"
        if not (min_cost_manifest.exists() and min_emissions_manifest.exists()):
            continue
        min_cost_data = json.loads(min_cost_manifest.read_text(encoding="utf-8"))
        min_emissions_data = json.loads(min_emissions_manifest.read_text(encoding="utf-8"))
        if min_cost_data.get("solve_status") != "success" or min_emissions_data.get("solve_status") != "success":
            continue
        min_cost_emissions = min_cost_data.get("objective_values", {}).get("emissions")
        min_emissions_value = min_emissions_data.get("objective_values", {}).get("emissions")
        if min_cost_emissions is None or min_emissions_value is None:
            continue
        anchors[instance_id] = (float(min_emissions_value), float(min_cost_emissions))
    return anchors


def build_design_matrix(family_id: str) -> list[DesignPoint]:
    if family_id == "B":
        points = family_b_cost_emissions_frontier.build_design_matrix(
            epsilon_anchors=_family_b_epsilon_anchors()
        )
    else:
        points = FAMILY_MODULES[family_id].build_design_matrix()
    # Apply the campaign-wide threads/MIPFocus defaults to every point that doesn't already set
    # them explicitly (Family 0 sets threads/mip_focus per swept cell).
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
    if point.family_id == "A":  # single-run family -- run_code ("baseline") subfolder is redundant
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
        # Scratch-then-move under the OS temp dir, not out_dir directly: avoids leaving
        # solve_batch's nested results-root mirror behind in the OneDrive-synced project tree
        # (see doe_campaign_01/campaign.py for the original rationale/incident).
        scratch_root = Path(tempfile.mkdtemp(prefix=f"{CAMPAIGN_ID}_"))
        try:
            cmd = [
                sys.executable, "-m", "clsc.solver_cli.solve_batch", str(instance_path),
                "--method", BILEVEL_METHOD,
                "--time-limit", str(point.per_subproblem_time_limit_seconds),
                "--results-root", str(scratch_root),
                # Fine tax grid ({0..2000}) resolved in-memory from each instance's own tau range;
                # stored files untouched. Campaign-invariant, so injected here rather than per-point.
                "--scale-factor", str(FINE_GRID_SCALE_FACTOR),
            ]
            if not REFINE_MIN_TAX:
                cmd += ["--no-refine-min-tax"]
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
    """Shared summary/solution.json-writing tail for the three in-process follower solves
    (fixed_tax, min_emissions, epsilon_constraint) -- all of them a single MILP, no DBP outer loop.
    """
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

    instance = InstanceData.from_file(instance_path)
    start = time.perf_counter()
    result = solve_fixed_tax_follower(
        instance, point.fixed_tax_index,
        time_limit=point.per_subproblem_time_limit_seconds,
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

    instance = InstanceData.from_file(instance_path)
    start = time.perf_counter()
    result = solve_fixed_tax_min_emissions(
        instance,
        time_limit=point.per_subproblem_time_limit_seconds,
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

    instance = InstanceData.from_file(instance_path)
    start = time.perf_counter()
    result = solve_epsilon_constraint_follower(
        instance, point.epsilon_emissions,
        time_limit=point.per_subproblem_time_limit_seconds,
        capture_solution=True,
        mip_gap=point.mip_gap, threads=point.threads, mip_focus=point.mip_focus,
    )
    solve_seconds = time.perf_counter() - start
    return _write_follower_result(
        point, instance, result, instance_path, out_dir,
        solve_seconds=solve_seconds, tax_index_for_report=0,
        extra={"epsilon_emissions": point.epsilon_emissions},
    )


def run_point(point: DesignPoint, *, overwrite: bool = False) -> dict[str, Any]:
    out_dir = _run_output_dir(point)
    manifest_path = _manifest_path(point)
    if manifest_path.exists() and not overwrite:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if _is_terminal(existing):
            _append_heartbeat(f"SKIP (already terminal) {point.family_id}/{point.base_instance_id}/{point.run_code}")
            return existing

    _append_heartbeat(f"START {point.family_id}/{point.base_instance_id}/{point.run_code}")
    solver_method_by_execution_mode = {
        "bilevel": BILEVEL_METHOD,
        "fixed_tax": "fixed_tax_follower",
        "min_emissions": "fixed_tax_min_emissions",
        "epsilon_constraint": "epsilon_constraint_follower",
    }
    manifest: dict[str, Any] = {
        "campaign_id": CAMPAIGN_ID,
        "family_id": point.family_id,
        "design_point_id": point.design_point_id,
        "base_instance_id": point.base_instance_id,
        "factor_levels": point.factor_levels,
        "technology_menu": point.technology_menu,
        "transport_menu": point.transport_menu,
        "production_technology_menu": point.production_technology_menu,
        "remanufacturing_technology_menu": point.remanufacturing_technology_menu,
        "road_menu": point.road_menu,
        "sea_menu": point.sea_menu,
        "air_menu": point.air_menu,
        "seed_offset": point.seed_offset,
        "epsilon_emissions": point.epsilon_emissions,
        "code_version": _code_version(),
        "solver_method": solver_method_by_execution_mode[point.execution_mode],
        "time_limit_seconds": point.per_subproblem_time_limit_seconds,
        "wall_clock_cap_seconds": point.per_run_wall_clock_cap_seconds,
        "created_at_utc": _utc_now_iso(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({**manifest, "solve_status": "running"}, indent=2, default=str), encoding="utf-8"
    )
    try:
        instance_path = materialize(point, output_root=INSTANCES_ROOT)
        manifest["input_instance_path"] = str(instance_path)

        stashed = _stash_existing_solve_outputs(out_dir, point.design_point_id)
        if stashed:
            _append_heartbeat(
                f"STASH {point.family_id}/{point.base_instance_id}/{point.run_code} "
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
    parser = argparse.ArgumentParser(prog="python -m clsc.campaign.orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Build design_matrix.csv for one or all families.")
    gen.add_argument("--family", default="all", help="Family id (0, A-F) or 'all'.")
    gen.add_argument("--dry-run", action="store_true", help="Print counts only; do not write CSVs.")

    run_cmd = sub.add_parser("run", help="Materialize instances and solve one or all design points.")
    run_cmd.add_argument("--family", default="all", help="Family id (0, A-F) or 'all'.")
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
