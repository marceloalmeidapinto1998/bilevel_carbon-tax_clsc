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
    """The baseline is the CLI's summary, which reports the canonicalised (revalidated) solution."""
    completed = subprocess.run(
        [sys.executable, "-m", "clsc.solver_cli", str(BASE_INSTANCES / "STD_I17_M4_T3.json"),
         "--results-root", str(tmp_path)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    summaries = list(tmp_path.glob("**/summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    summary = summary[0] if isinstance(summary, list) else summary

    assert summary["result_class"] == "certified"
    assert summary["termination_reason"] == "optimal"
    assert summary["iterations"] == 5
    assert summary["tax_index"] == 26
    assert summary["validation_status"] == "validated"
    assert summary["cost"] == pytest.approx(2525919.350079193, rel=1e-9)
    assert summary["emissions"] == pytest.approx(25406136.47956628, rel=1e-9)
    assert summary["leader_objective_lb"] == pytest.approx(25471977.012896396, rel=1e-9)
    assert summary["leader_objective_ub"] == pytest.approx(25471977.05849877, rel=1e-9)
