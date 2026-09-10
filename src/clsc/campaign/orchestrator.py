"""campaign_01 orchestrator: `python -m clsc.campaign.orchestrator <command>`.

Implements the 4-Experiment plan in docs/Experimental_Plan.md. Each experiment's design lives in
its own module under `clsc/campaign/designs/` (exp1_verification .. exp4_sensitivity) and exposes
`build_design_matrix()`. Experiment 3 (policy value & calibration) is generated in stages: local
plateau refinement depends on Experiment 2's M0 manifests, and the rho*-anchored suite depends on
its own ratio-sweep results -- both read back from disk.

Bilevel (leader-optimizing) runs solve on the project's one tax resolution (`TAX_SCALE_FACTOR`) with
`dbp_relative_gap = 1e-4`, follower `mip_gap = 1e-6`, and in-loop min-tax confirmation
(`confirm_min_tax`, Soares et al. 2021's Lemma-3 stopping rule) ON. The computational-performance
experiment (Exp2) selects weakened variants by algorithm_variant -> solver flags
(`_VARIANT_FLAGS`): A1 no min-tax confirmation and A5 no incumbent objective-upper-bound cut are
scheduled by this campaign's design matrix; A2 (no lexicographic Stage-2 master), A3 (no warm
start), and A4 (coarse tax resolution, via a design point's own scale_factor rather than a solver flag)
remain supported but are not scheduled (the prior campaign found no measurable A2/A3 effect, and
A4's coarse-grid aliasing bias is no longer a design-matrix claim). M0 is the full method.

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

Provenance: `run` refuses to start unless the result-bearing paths (`PROVENANCE_PATHS`: src/,
data/instances/base/, pyproject.toml) match HEAD, because every manifest records `code_version` as
a commit hash and a dirty tree makes that hash describe something other than what ran. Each
manifest carries `code_version`, `code_dirty`, `code_dirty_paths` and two digests of the
materialized instance: `instance_sha256` (the exact bytes solved) and `instance_content_sha256`
(only the problem-defining fields, so it is comparable across re-materializations, which rewrite
`generated_at_utc`). `--allow-dirty` lifts the refusal for development runs and stamps
`code_dirty: true` on everything it produces.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
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
    exp2_computational_performance,
    exp3_policy_value,
    exp4_sensitivity,
)
from clsc.campaign.designs._common import DesignPoint, rows_to_csv_dicts
from clsc.config.tax_scale import TAX_SCALE_FACTOR
from clsc.campaign.instances import materialize

CAMPAIGN_ID = "campaign_01"
REPO_ROOT = Path(__file__).resolve().parents[3]  # src/clsc/campaign/orchestrator.py -> repo root
MANIFESTS_ROOT = REPO_ROOT / "experiments" / CAMPAIGN_ID
INSTANCES_ROOT = REPO_ROOT / "data" / "instances" / "campaigns" / CAMPAIGN_ID
RESULTS_ROOT = REPO_ROOT / "results" / "runs" / CAMPAIGN_ID
HEARTBEAT_LOG = RESULTS_ROOT / "_heartbeat.log"

EXPERIMENT_MODULES = {
    "exp1": exp1_verification,
    "exp2": exp2_computational_performance,
    "exp3": exp3_policy_value,
    "exp4": exp4_sensitivity,
}

EXPERIMENT_DIR_NAMES = {
    "exp1": "exp1_verification",
    "exp2": "exp2_computational_performance",
    "exp3": "exp3_policy_value",
    "exp4": "exp4_sensitivity",
}

# Experiments whose design matrix depends on other solved results, read back from disk by the
# module's build_design_matrix(results_root=...). Exp3 has two such stages internally (see its
# module docstring); Exp1/Exp2/Exp4 are fully static.
TWO_PHASE_EXPERIMENTS = ("exp3",)

BILEVEL_METHOD = "dbp_lex"

# Campaign-wide solver defaults. Chosen from the prior campaign's solver-configuration experiment
# and re-confirmed by an ad hoc 2-point spot check on the hardest cell (not a formal experiment in
# this campaign -- see docs/Experimental_Plan.md's implementation notes).
DEFAULT_THREADS = 4
DEFAULT_MIP_FOCUS = 2
CAMPAIGN_DBP_RELATIVE_GAP = 1e-4
CAMPAIGN_MIP_GAP = 1e-6
CONFIRM_MIN_TAX = True

# Ablation variant -> extra solver flags for the bilevel (DBP) subprocess. M0 = full method (no
# extra flags). A4 (coarse grid) is handled via the point's own scale_factor, not a flag here --
# it has no flag effect of its own, hence the empty list.
_VARIANT_FLAGS: dict[str, list[str]] = {
    "M0": [],
    "A1": ["--no-confirm-min-tax"],
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

# Tracked paths whose state can change a run's NUMBERS. A dirty paper/, docs/ or tests/ must not
# block a campaign -- editing the manuscript while the solver runs is normal and harmless -- but a
# dirty src/ or data/instances/base/ means the recorded commit hash does not describe the code and
# data that produced the result, which is exactly the failure this guard exists to prevent.
# experiments/ is excluded because `run` rebuilds each design matrix in memory rather than reading
# the committed CSV.
PROVENANCE_PATHS = ("src", "data/instances/base", "pyproject.toml")


class DirtyWorkingTreeError(RuntimeError):
    """A campaign run was attempted against code or data that matches no commit.

    Every `campaign_manifest.json` records `code_version` as a commit hash. If the working tree
    differs from that commit, the hash describes something other than what actually ran and the
    run's provenance is unrecoverable after the fact. Refusing up front is the only point at which
    this is cheap to fix; `--allow-dirty` exists for development runs whose results are not
    destined for publication, and stamps `code_dirty: true` on every manifest it produces.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class CodeProvenance:
    """The commit a run was executed at, and whether the tree actually matched it.

    `dirty is None` means git could not be consulted at all (no git, not a repository). That is
    NOT the same as clean, and is never treated as publication-safe.
    """

    commit: str
    dirty: bool | None
    dirty_paths: tuple[str, ...] = ()

    @property
    def is_publication_safe(self) -> bool:
        return self.commit != "unknown" and self.dirty is False

    def as_manifest_fields(self) -> dict[str, Any]:
        return {
            "code_version": self.commit,
            "code_dirty": self.dirty,
            "code_dirty_paths": list(self.dirty_paths),
        }


def _git(*args: str) -> str | None:
    """Run a git command in the repo, or return None if git cannot answer.

    Only the trailing newline is stripped, never leading whitespace: `git status --porcelain`
    puts the index status in column 0 and the worktree status in column 1, and column 0 is a
    SIGNIFICANT SPACE for an unstaged change. Stripping it shifts every path left by one
    character, which is silent -- the paths still look plausible.
    """
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
    except Exception:  # noqa: BLE001 -- no git, no repository, or a broken index: all "unknown"
        return None
    return out.stdout.rstrip(chr(10))


def _porcelain_paths(status: str) -> tuple[str, ...]:
    """Paths named by `git status --porcelain` (v1) output.

    Columns 0-1 are the index/worktree status codes and column 2 is the separator, so the path
    starts at index 3. A rename is reported as ``old -> new``; the destination is the path that
    exists now, so that is the one recorded. Paths containing unusual characters come back
    double-quoted (core.quotepath), hence the unquoting.
    """
    paths: list[str] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip().strip('"'))
    return tuple(sorted(set(paths)))


def capture_code_provenance() -> CodeProvenance:
    """Snapshot the commit and the dirtiness of the result-bearing paths, once per campaign.

    Taken once and threaded through every design point so that a whole campaign's manifests
    describe the same verified snapshot, rather than each run re-asking git and possibly
    disagreeing with its neighbours.
    """
    commit = (_git("rev-parse", "HEAD") or "").strip() or "unknown"
    status = _git("status", "--porcelain", "--untracked-files=normal", "--", *PROVENANCE_PATHS)
    if status is None:
        return CodeProvenance(commit=commit, dirty=None)
    paths = _porcelain_paths(status)
    return CodeProvenance(commit=commit, dirty=bool(paths), dirty_paths=paths)


def require_clean_worktree(provenance: CodeProvenance) -> None:
    if provenance.is_publication_safe:
        return
    if provenance.dirty is None:
        raise DirtyWorkingTreeError(
            "Cannot verify the working tree against a commit (git unavailable or this is not a "
            "git repository), so the campaign's recorded code_version cannot be trusted. "
            "Re-run with --allow-dirty to proceed anyway; every manifest will record "
            "code_dirty: null."
        )
    listed = "\n  ".join(provenance.dirty_paths[:20])
    more = (
        ""
        if len(provenance.dirty_paths) <= 20
        else f"\n  ... and {len(provenance.dirty_paths) - 20} more"
    )
    raise DirtyWorkingTreeError(
        f"Refusing to start: {len(provenance.dirty_paths)} result-bearing path(s) differ from "
        f"HEAD ({provenance.commit[:12]}), so every manifest would record a commit hash that "
        f"does not describe the code and data that ran.\n  {listed}{more}\n"
        "Commit (or stash) these, or re-run with --allow-dirty for a development run whose "
        "results are not destined for publication."
    )


# Instance fields that DEFINE the optimization problem. Everything else in the file is
# bookkeeping -- notably `metadata.generated_at_utc`, which materialize() rewrites on every run.
_INSTANCE_CONTENT_KEYS = ("name", "sets", "parameters")


def _sha256_file(path: Path) -> str:
    """Digest of the exact bytes handed to the solver.

    The instance path alone is not provenance: campaign instances are regenerated in place on
    every run, so a path recorded today can point at different numbers tomorrow. This pins what
    was actually read, and is what verifies a run against the committed instance artifact.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_instance_content(path: Path) -> str | None:
    """Digest of the instance's PROBLEM CONTENT, stable across re-materialization.

    `_sha256_file` answers "were these the same bytes?", which materialize() breaks on every run
    by stamping a fresh `generated_at_utc`: two runs of an identical instance get different file
    digests for a reason that has nothing to do with the optimization problem. This digest covers
    only the fields that define that problem, so it answers the question actually being asked --
    "did these two runs solve the same instance?" -- and stays comparable across regenerations,
    machines and campaigns.

    Canonicalized with sorted keys and no whitespace. Float formatting is Python's shortest
    round-trip repr, so the digest is comparable across runs of the same interpreter major
    version; it is a comparison aid, not a cross-language checksum. Returns None if the file is
    not the expected JSON shape -- the file digest above is always recorded regardless.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        content = {key: payload[key] for key in _INSTANCE_CONTENT_KEYS}
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    """The tax-scale step (USD/kg CO2e per index) this design point is solved on.

    Applies to EVERY execution mode, not just bilevel: a fixed-tax index means nothing without
    the grid it indexes, so the in-process follower solves must be re-gridded onto the same step
    the bilevel runs use before their `tax_index` is interpreted. A design point overrides
    this via its own `scale_factor` (e.g. the retired A4 coarse-grid variant); none currently do.
    """
    return point.scale_factor if point.scale_factor is not None else TAX_SCALE_FACTOR


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
            if not CONFIRM_MIN_TAX:
                cmd += ["--no-confirm-min-tax"]
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
        "tax_rate": tax_rate,
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
            "leader": {"tax_index": tax_index_for_report, "tax_rate": tax_rate},
            "objectives": {
                "cost": result.cost,
                "emissions": result.emissions,
                "follower_objective": result.follower_objective,
            },
            "decision_variables": {
                "leader": {"tax_index": tax_index_for_report, "tax_rate": tax_rate},
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
        instance, point.tax_index,
        time_limit=_effective_subproblem_time_limit(point),
        capture_solution=True,
        mip_gap=point.mip_gap, threads=point.threads, mip_focus=point.mip_focus,
    )
    solve_seconds = time.perf_counter() - start
    return _write_follower_result(
        point, instance, result, instance_path, out_dir,
        solve_seconds=solve_seconds, tax_index_for_report=point.tax_index,
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
    """The enumeration execution mode's baseline: solve the fixed-tax lexicographic follower at
    EVERY grid point.

    Exact by construction (no cuts, no theory) -- the naive method a referee would propose as
    DBP's alternative. Reused fields (cost/emissions/tax_index/solution.json) come from
    `_write_follower_result` so the aggregator reads enumeration rows the same way it reads any
    other follower-mode row; enumeration-specific fields (follower-solve count, grid coverage,
    total follower time) ride along in ``extra``.
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


def run_point(
    point: DesignPoint,
    *,
    overwrite: bool = False,
    provenance: CodeProvenance | None = None,
) -> dict[str, Any]:
    """Solve one design point and write its `campaign_manifest.json`.

    `provenance` is normally the single snapshot `run_experiment` captured for the whole campaign.
    When called on its own (a one-off point, a test) it is captured here instead. No cleanliness
    guard fires at this level: enforcing it belongs to `run_experiment`, so a deliberate single
    point stays runnable while a campaign does not.
    """
    if provenance is None:
        provenance = capture_code_provenance()
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
        **provenance.as_manifest_fields(),
        # Filled in after materialization; declared here so the "running" manifest already shows
        # which provenance fields a completed run is expected to carry.
        "input_instance_path": None,
        "instance_sha256": None,
        "instance_content_sha256": None,
        "solver_method": solver_method_by_execution_mode[point.execution_mode],
        # Without the scale factor a tax index is uninterpretable, and the two campaign grids are
        # 100x apart -- so it is recorded per run rather than assumed downstream.
        "tax_step_usd_per_kg": _tax_grid_step(point),
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
        manifest["instance_sha256"] = _sha256_file(instance_path)
        manifest["instance_content_sha256"] = _sha256_instance_content(instance_path)

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
                "tax_index": (
                    summary.get("tax_index", summary.get("hat_tau"))
                    if point.tax_index is None
                    else point.tax_index
                ),
                # The solver's own rate, in the one unit that IS comparable across grids.
                "tax_rate": summary.get("tax_rate"),
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
                "tax_index": None,
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
    allow_dirty: bool = False,
    provenance: CodeProvenance | None = None,
) -> list[dict[str, Any]]:
    """Solve every design point of one experiment.

    Refuses to start unless the result-bearing paths (`PROVENANCE_PATHS`) match HEAD, so a
    campaign can never record a commit hash that does not describe what ran. `allow_dirty=True`
    lifts the refusal for development runs and leaves `code_dirty: true` on every manifest.
    """
    if provenance is None:
        provenance = capture_code_provenance()
    if not allow_dirty:
        require_clean_worktree(provenance)
    points = build_design_matrix(experiment_id)
    if base_instance is not None:
        points = [p for p in points if p.base_instance_id == base_instance]
    results = []
    for point in points:
        manifest = run_point(point, overwrite=overwrite, provenance=provenance)
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
    gen.add_argument("--experiment", default="all", help="Experiment id (exp1..exp4 or 1..4) or 'all'.")
    gen.add_argument("--dry-run", action="store_true", help="Print counts only; do not write CSVs.")

    run_cmd = sub.add_parser("run", help="Materialize instances and solve one or all design points.")
    run_cmd.add_argument("--experiment", default="all", help="Experiment id (exp1..exp4 or 1..4) or 'all'.")
    run_cmd.add_argument("--fail-fast", action="store_true")
    run_cmd.add_argument("--overwrite", action="store_true", help="Re-run even if already terminal.")
    run_cmd.add_argument("--base-instance", default=None,
                          help="Restrict to design points on this base instance only (e.g. for a pilot).")
    run_cmd.add_argument("--allow-dirty", action="store_true",
                          help="Run even though src/, data/instances/base/ or pyproject.toml "
                               "differ from HEAD. Development only: every manifest is stamped "
                               "code_dirty: true and the results are not publication-safe.")

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
        # Captured once for the whole invocation: every manifest written below describes the same
        # verified snapshot, and the guard is evaluated before any solve starts rather than
        # part-way through experiment 3.
        provenance = capture_code_provenance()
        if not args.allow_dirty:
            try:
                require_clean_worktree(provenance)
            except DirtyWorkingTreeError as error:
                print(str(error), file=sys.stderr)
                return 3
        elif not provenance.is_publication_safe:
            print(
                f"WARNING: --allow-dirty; recording code_dirty="
                f"{'null' if provenance.dirty is None else 'true'} on every manifest. "
                "These results are not publication-safe.",
                file=sys.stderr,
            )
        for experiment_id in experiment_ids:
            results = run_experiment(
                experiment_id, fail_fast=args.fail_fast, overwrite=args.overwrite,
                base_instance=args.base_instance, allow_dirty=True, provenance=provenance,
            )
            n_success = sum(1 for r in results if r.get("solve_status") == "success")
            print(f"{experiment_id}: {n_success}/{len(results)} succeeded")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
