"""The tasks an experiment runs on one instance. Each writes its files to the job's directory and
returns a small summary for the job record.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import subprocess
import sys

from clsc.config.constants import KG_PER_TONNE
from clsc.config.defaults import DEFAULT
from clsc.models.follower import build_follower_model, solve_follower_lexicographic
from clsc.models.instance_data import InstanceData

from .profile import response_profile


def run_dbp(instance_path: Path, directory: Path, *, seed: int, run_time_limit: float | None = None,
            threads: int | None = None, leader_tax_weight_relative: float | None = None,
            mip_gap: float | None = None, environment: dict[str, str] | None = None) -> dict:
    """clsc-solve on the instance, in its own process, writing to ``directory``. ``environment`` adds
    variables to the solver's environment: the ablation's switches CLSC_STRENGTHENING and
    CLSC_PRODUCT_BOUNDS."""
    if directory.name != instance_path.stem:
        raise ValueError(f"clsc-solve writes {instance_path.stem}/, not {directory.name}/")
    command = [
        sys.executable, "-m", "clsc.solver_cli", str(instance_path),
        "--results-root", str(directory.parent), "--seed", str(seed), "--overwrite",
    ]
    if run_time_limit is not None:
        command += ["--run-time-limit", str(run_time_limit)]
    if threads is not None:
        command += ["--threads", str(threads)]
    if leader_tax_weight_relative is not None:
        command += ["--leader-tax-weight-relative", repr(leader_tax_weight_relative)]
    if mip_gap is not None:
        command += ["--mip-gap", repr(mip_gap)]
    env = None if not environment else {**os.environ, **environment}
    completed = subprocess.run(command, check=False, env=env)
    summary_path = directory / "summary.json"
    if not summary_path.exists():
        raise RuntimeError(f"clsc-solve wrote no summary (exit code {completed.returncode})")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary = summary[0] if isinstance(summary, list) else summary
    if not summary.get("success"):
        raise RuntimeError(f"clsc-solve failed: {summary.get('error_type')}: {summary.get('error_message')}")
    return {
        "exit_code": completed.returncode, "result_class": summary.get("result_class"),
        "relative_gap": summary.get("relative_gap"), "tax": summary.get("tax"), "solve_seconds": summary.get("solve_seconds"),
    }


def run_follower(instance_path: Path, directory: Path, *, seed: int, taxes: tuple[float, ...],
                 threads: int | None = None, time_limit: float | None = DEFAULT.time_limit) -> dict:
    """The follower's optimistic response at each tax, solved as the DBP solves it, with its profile.
    Writes follower.csv."""
    instance = InstanceData.from_file(instance_path)
    follower = build_follower_model(instance)
    rows = []
    for tax in taxes:
        result = solve_follower_lexicographic(follower, tax, time_limit=time_limit, threads=threads, seed=seed, capture_solution=True)
        if not result.has_solution:
            raise RuntimeError(f"the follower found no solution at tax {tax} ({result.status_name})")
        rows.append({
            "tax": tax, "status": result.status_name, "mip_gap": result.mip_gap, "seconds": result.runtime,
            "emissions": result.emissions, "cost": result.cost, "tax_base": result.tax_base,
            "tax_paid": tax / KG_PER_TONNE * result.tax_base,
            **response_profile(instance, result.variable_values or {}),
        })
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "follower.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {"taxes": list(taxes), "statuses": [row["status"] for row in rows]}


TASKS = {"dbp": run_dbp, "follower": run_follower}


def run_enumeration(instance_path: Path, directory: Path, *, seed: int, method: str = "enumeration",
                    run_time_limit: float | None = None, threads: int | None = None,
                    leader_tax_weight_relative: float | None = None, step: float = 1.0) -> dict:
    """The exact alternatives to the DBP for one tax: the break points of the follower's value function
    (``method="enumeration"``) or a grid of taxes (``method="grid"``). Writes evaluations.csv, every tax
    evaluated, and summary.json."""
    from clsc.solvers.enumeration import enumerate_break_points, grid_search

    instance = InstanceData.from_file(instance_path)
    options = dict(seed=seed, run_time_limit=run_time_limit, threads=threads,
                   leader_tax_weight_relative=leader_tax_weight_relative)
    if method == "enumeration":
        result = enumerate_break_points(instance, **options)
    elif method == "grid":
        result = grid_search(instance, step=step, **options)
    else:
        raise ValueError(f"unknown method {method!r}")
    candidate_taxes = {evaluation.tax for evaluation in result.candidates}
    rows = [{
        "tax": e.tax, "candidate": e.tax in candidate_taxes, "emissions": e.emissions, "cost": e.cost,
        "tax_base": e.tax_base, "follower_objective": e.follower_objective,
        "leader_objective": e.leader_objective, "solved": e.solved, "seconds": e.seconds,
    } for e in result.evaluations]
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "evaluations.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    best = result.best
    profile = {}
    if best is not None:
        # The network at the best tax: the same two-stage solve again, keeping the solution, with the
        # subproblems' time limit. A failure here loses the profile, not the enumeration.
        try:
            response = solve_follower_lexicographic(build_follower_model(instance), best.tax, threads=threads, seed=seed,
                                                    capture_solution=True, time_limit=DEFAULT.time_limit)
            if response.has_solution:
                profile = response_profile(instance, response.variable_values or {})
        except Exception as error:  # noqa: BLE001 -- recorded in the summary
            profile = {"error": f"{type(error).__name__}: {error}"}
    summary = {
        "method": result.method, "complete": result.complete, "certified": result.certified,
        "follower_solves": result.follower_solves, "break_points": result.break_points,
        "tax": best.tax if best else None, "emissions": best.emissions if best else None,
        "leader_objective": best.leader_objective if best else None,
        "tax_weight_per_eur_t": result.tax_weight_per_eur_t, "reference_emissions": result.reference_emissions,
        "seconds": result.seconds, "scale_seconds": result.scale_seconds,
        "cost": best.cost if best else None, "tax_base": best.tax_base if best else None,
        "profile": profile,
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {key: summary[key] for key in ("complete", "certified", "follower_solves", "tax", "seconds")}


TASKS["enumeration"] = run_enumeration
