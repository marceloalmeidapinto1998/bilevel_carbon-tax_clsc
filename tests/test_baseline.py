"""Regression baselines: the generator reproduces the committed base and escalation instances, and the DBP
reproduces, through the CLI, the reference solve of STD_I17_M4_T3 with the default configuration.

Both need a Gurobi licence (the generator checks each instance's feasibility with Gurobi) and are
skipped without one. Run with ``python -m pytest``; ``-m "not slow"`` skips the solve.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_INSTANCES = REPO_ROOT / "data"


def _gurobi_available() -> bool:
    try:
        import gurobipy as gp

        with gp.Env(params={"OutputFlag": 0}):
            return True
    except Exception:
        return False


requires_gurobi = pytest.mark.skipif(not _gurobi_available(), reason="no usable Gurobi licence")


@requires_gurobi
@pytest.mark.gurobi
def test_generator_reproduces_base_instances(tmp_path: Path) -> None:
    from clsc.generator import generate_benchmark

    generate_benchmark(tmp_path)
    generated = sorted(tmp_path.glob("*.json"))
    assert len(generated) == 12
    for path in generated:
        new = json.loads(path.read_text(encoding="utf-8"))
        committed = json.loads((BASE_INSTANCES / path.name).read_text(encoding="utf-8"))
        new["metadata"].pop("generated_at_utc")
        committed["metadata"].pop("generated_at_utc")
        assert new == committed, path.name


@requires_gurobi
@pytest.mark.gurobi
def test_generator_reproduces_escalation_instances(tmp_path: Path) -> None:
    from clsc.generator import generate_escalation_bases

    generate_escalation_bases(tmp_path)
    generated = sorted(tmp_path.glob("*.json"))
    assert [path.name for path in generated] == [
        "STD_I25_M12_T6.json", "STD_I25_M16_T6.json", "STD_I33_M8_T6.json",
    ]
    for path in generated:
        new = json.loads(path.read_text(encoding="utf-8"))
        committed = json.loads((BASE_INSTANCES / path.name).read_text(encoding="utf-8"))
        new["metadata"].pop("generated_at_utc")
        committed["metadata"].pop("generated_at_utc")
        assert new == committed, path.name


@requires_gurobi
@pytest.mark.gurobi
@pytest.mark.slow
def test_cli_reference_solve(tmp_path: Path) -> None:
    """The baseline is the CLI's summary, which reports the canonicalised (revalidated) solution.

    Run on one thread with Gurobi seed 0, the setting the reference values were recorded under
    (Gurobi 13.0.1, about 40 minutes). The iteration count is not asserted: the HPR solves take
    hundreds of seconds against the 600 s limit, so a slower machine can take another path.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "clsc.solver_cli", str(BASE_INSTANCES / "STD_I17_M4_T3.json"),
         "--results-root", str(tmp_path), "--threads", "1", "--seed", "0"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    summaries = list(tmp_path.glob("**/summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    summary = summary[0] if isinstance(summary, list) else summary

    assert summary["result_class"] == "optimal"
    assert summary["termination_reason"] == "optimal"
    assert summary["tax_index"] == 34
    assert summary["validation_status"] == "validated"
    assert summary["leader_objective_lb"] <= summary["leader_objective_ub"]
    assert summary["relative_gap"] <= 1e-4
    assert summary["cost"] == pytest.approx(1551005.3165628714, rel=1e-6)
    assert summary["emissions"] == pytest.approx(24683049.835076936, rel=1e-6)
    assert summary["leader_objective_lb"] == pytest.approx(24764036.562738676, rel=1e-6)
    assert summary["leader_objective_ub"] == pytest.approx(24766491.94983398, rel=1e-6)
