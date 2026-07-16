"""Shared pytest fixtures.

Tests that touch matplotlib should set the Agg backend themselves so this
file stays neutral for the existing solver tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _follower_for(tax_index: int) -> dict[str, float]:
    """Two structural regimes: tau<=1 opens supplier s1 only, tau>=2 also opens s2."""
    follower: dict[str, float] = {
        "y_s[s1]": 1.0,
        "y_f[f1]": 1.0,
        "u_prod[f1,p_tech]": 1.0,
        "u_rem[f1,r_tech]": 1.0,
        "q[prod1,f1,p_tech,t1]": 10.0 + tax_index,
        "rem[prod1,f1,r_tech,t1]": 2.0 + 0.5 * tax_index,
        "x[prod1,f1,w1,mrd1,t1]": 8.0,
        "trip[f1,w1,mrd1,t1]": 2.0,
        "zt[f1,w1,mrd1,t1]": 1.0,
        "contract[mrd1,t1]": 1.0,
    }
    if tax_index >= 2:
        follower["y_s[s2]"] = 1.0
    return follower


def _tax_solution(tax_index: int) -> dict:
    cost = 1000.0 + 100.0 * tax_index
    emissions = 5000.0 - 200.0 * tax_index
    return {
        "leader": {"tax_index": tax_index, "effective_tax": 0.01 * tax_index},
        "objectives": {
            "cost": cost,
            "emissions": emissions,
            "follower_objective": cost + 0.01 * tax_index * emissions,
            "objective_value": cost + 0.01 * tax_index * emissions,
        },
        "runtime": {"solve_seconds": 0.1 * (tax_index + 1)},
        "gaps": {"mip_gap": 1e-5, "lex_primary_mip_gap": 0.0, "lex_secondary_mip_gap": 1e-5},
        "decision_variables": {"follower": _follower_for(tax_index)},
    }


@pytest.fixture
def synthetic_results_base(tmp_path) -> Path:
    """Write a tiny synthetic results/base tree and return the base path."""
    instance = "SYN_I2_M1_T1"
    base = tmp_path / "results_base"
    lf_dir = base / instance / "lf_lex_exact"
    lf_dir.mkdir(parents=True)

    lf_lex = _tax_solution(2)
    (lf_dir / "solution.json").write_text(json.dumps(lf_lex), encoding="utf-8")

    return base


@pytest.fixture
def synthetic_instance() -> str:
    return "SYN_I2_M1_T1"
