"""Tests of the exact abatement curve on a tiny generated instance (seconds; skipped without a Gurobi licence)."""
from __future__ import annotations

import json
import random

import pytest

from clsc.config.constants import KG_PER_TONNE


def _gurobi_available() -> bool:
    try:
        import gurobipy as gp

        with gp.Env(params={"OutputFlag": 0}):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _gurobi_available(), reason="no usable Gurobi licence")


@pytest.fixture(scope="module")
def tiny():
    from clsc.generator.config import GeneratorConfig
    from clsc.generator.instance_builder import generate_instance
    from clsc.models.instance_data import InstanceData
    from clsc.analysis.abatement import abatement_curve

    config = GeneratorConfig(
        suppliers=2, factories=1, warehouses=2, retailers=2, airports=1, seaports=1, products=1,
        raw_materials=2, production_technologies=2, remanufacturing_technologies=2, periods=3,
        seed=0, instance_name="tiny0",
    )
    instance = InstanceData.from_dict(generate_instance(config).to_dict())
    return instance, abatement_curve(instance, threads=1, seed=0)


def test_break_points_lie_in_the_range_and_slopes_fall(tiny) -> None:
    instance, curve = tiny
    candidates = curve.candidates() + [curve.upper_response]
    taxes = [response.tax for response in candidates]
    assert taxes == sorted(taxes)
    assert instance.lower_tax <= taxes[0] and taxes[-1] <= instance.upper_tax
    # The envelope is concave: its slope, the tax base, never rises with the tax.
    bases = [response.tax_base for response in candidates]
    assert all(later <= earlier * (1 + 1e-6) for earlier, later in zip(bases, bases[1:]))
    assert curve.break_points  # this instance has at least one change of response


def test_the_curve_reproduces_the_follower_value_at_other_taxes(tiny) -> None:
    from clsc.models.follower import solve_follower_lexicographic

    instance, curve = tiny
    lines = curve.candidates() + [curve.upper_response]
    for tax in random.Random(0).sample(range(int(instance.lower_tax), int(instance.upper_tax) + 1), 6):
        result = solve_follower_lexicographic(instance, float(tax), mip_gap=1e-6, threads=1, seed=0)
        envelope = min(line.cost + tax / KG_PER_TONNE * line.tax_base for line in lines)
        assert result.follower_objective == pytest.approx(envelope, rel=1e-5)


def test_the_leader_optimum_agrees_with_the_dbp(tiny, tmp_path) -> None:
    from clsc.analysis.abatement import write_curve
    from clsc.solvers.dbp import solve_bilevel_dbp

    instance, curve = tiny
    result = solve_bilevel_dbp(instance, threads=1, seed=0, time_limit=60)
    weight = result.leader_tax_weight
    best, value = curve.leader_optimum(weight)
    # The curve's optimum is an exact solution up to the follower's MIP gap: the DBP's lower bound lies
    # below it and its upper bound within the stopping tolerance above it.
    assert result.leader_objective_lb <= value * (1 + 1e-6)
    assert result.leader_objective_ub == pytest.approx(value, rel=1e-4)
    summary = write_curve(curve, weight, tmp_path / "tiny0", "tiny0")
    assert summary["leader_optimum"]["tax"] == best.tax
    assert json.loads((tmp_path / "tiny0" / "abatement.json").read_text(encoding="utf-8"))["break_points"] == len(curve.break_points)
    assert (tmp_path / "tiny0" / "abatement_curve.csv").read_text(encoding="utf-8").count("\n") == len(curve.break_points) + 3
