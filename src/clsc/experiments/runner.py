"""Expand an experiment into jobs and run them one at a time, resumably.

A job is one task on one instance, scenario and seed. Its files go to

    <root>/<experiment>/seed<seed>/<instance>[__<scenario>]/

and end with job.json, written last: a job whose job.json says ``ok`` is skipped when the experiment
is run again, so a run that is killed (a reboot, a closed laptop) resumes where it stopped. The
scenario instances are written once to <root>/instances/. Each run of an experiment appends one line
per job to <root>/<experiment>/status.jsonl and records the code and solver versions in
<root>/<experiment>/environment.json.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import platform
import subprocess
import time
import traceback

from .plan import Experiment
from .scenarios import SCENARIOS, Scenario, variant_name, write_variant
from .tasks import TASKS

logger = logging.getLogger(__name__)

JOB_FILE = "job.json"


@dataclass(frozen=True)
class Job:
    experiment: Experiment
    instance_path: Path
    scenario: Scenario
    seed: int

    @property
    def name(self) -> str:
        return variant_name(self.instance_path.stem, self.scenario)

    def directory(self, root: Path) -> Path:
        return root / self.experiment.key / f"seed{self.seed}" / self.name

    def is_done(self, root: Path) -> bool:
        path = self.directory(root) / JOB_FILE
        return path.exists() and json.loads(path.read_text(encoding="utf-8")).get("status") == "ok"


def expand(experiment: Experiment, *, instances: list[str] | None = None) -> list[Job]:
    """The experiment's jobs, ordered by seed, then instance, then scenario; ``instances`` keeps only
    the instances whose file name contains one of the given strings."""
    paths = [Path(path) for path in experiment.instances]
    if instances:
        paths = [path for path in paths if any(fragment in path.stem for fragment in instances)]
    return [
        Job(experiment, path, SCENARIOS[scenario], seed)
        for seed in experiment.seeds
        for path in paths
        for scenario in experiment.scenarios
    ]


def _git(*arguments: str) -> str:
    try:
        return subprocess.run(["git", *arguments], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def environment() -> dict:
    try:
        import gurobipy

        gurobi = ".".join(map(str, gurobipy.gurobi.version()))
    except Exception:  # noqa: BLE001 -- recorded, not needed
        gurobi = "unavailable"
    return {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "python": platform.python_version(),
        "gurobi": gurobi,
        "machine": platform.platform(),
        "processor": platform.processor(),
    }


def run_job(job: Job, root: Path, *, threads: int | None = None) -> dict:
    directory = job.directory(root)
    instance_path = write_variant(job.instance_path, job.scenario, root / "instances")
    options = {**job.experiment.options, **job.scenario.solver_options}
    if threads is not None:
        options["threads"] = threads
    started = time.perf_counter()
    record = {
        "experiment": job.experiment.key, "task": job.experiment.task, "instance": job.instance_path.stem,
        "scenario": job.scenario.name, "seed": job.seed, "instance_path": instance_path.as_posix(),
        "options": options, "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        result = TASKS[job.experiment.task](instance_path, directory, seed=job.seed, **options)
        record.update(status="ok", result=result)
    except Exception as error:  # noqa: BLE001 -- one failed job must not stop the experiment
        logger.exception("%s failed", job.name)
        record.update(status="failed", error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
    record["seconds"] = round(time.perf_counter() - started, 3)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / JOB_FILE).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def run_experiment(experiment: Experiment, root: Path, *, instances: list[str] | None = None,
                   threads: int | None = None, dry_run: bool = False) -> list[dict]:
    jobs = expand(experiment, instances=instances)
    pending = [job for job in jobs if not job.is_done(root)]
    logger.info("%s: %d jobs, %d done, %d to run", experiment.key, len(jobs), len(jobs) - len(pending), len(pending))
    if dry_run:
        for job in pending:
            print(job.directory(root).as_posix())
        return []
    base = root / experiment.key
    base.mkdir(parents=True, exist_ok=True)
    (base / "environment.json").write_text(json.dumps(environment(), indent=2), encoding="utf-8")
    records = []
    for number, job in enumerate(pending, start=1):
        logger.info("[%d/%d] %s %s seed %d", number, len(pending), experiment.task, job.name, job.seed)
        record = run_job(job, root, threads=threads)
        logger.info("[%d/%d] %s: %s in %.0f s", number, len(pending), job.name, record["status"], record["seconds"])
        with (base / "status.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({key: record[key] for key in ("instance", "scenario", "seed", "status", "seconds")}) + "\n")
        records.append(record)
    return records
