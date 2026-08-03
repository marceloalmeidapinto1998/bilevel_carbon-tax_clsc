from __future__ import annotations

import json
from pathlib import Path

import pytest

from clsc.analysis.campaign_01.aggregate import _flatten


def _synthetic_manifest(
    *,
    experiment: str = "exp3",
    base_instance: str = "STD_I17_M4_T3",
    solve_status: str = "success",
    factor_levels: dict | None = None,
) -> dict:
    return {
        "campaign_id": "campaign_01",
        "experiment_id": experiment,
        "design_point_id": f"{experiment}-M0-{base_instance}-s0",
        "base_instance_id": base_instance,
        "algorithm_variant": "M0",
        "seed_offset": 0,
        "gurobi_seed": None,
        "valuation_ratio": None,
        "code_version": "abc123",
        "solver_method": "dbp_lex",
        "solve_status": solve_status,
        "termination_reason": "relative_gap" if solve_status == "success" else None,
        "censored": False,
        "objective_values": {"cost": 1_000_000.0, "emissions": 500_000.0, "follower_objective": 2_000_000.0},
        "leader_tax": 10,
        # A tax index is uninterpretable without its grid step, and the campaign has two grids
        # 100x apart -- so the orchestrator records the step on every run.
        "tax_grid_step_usd_per_kg": 1e-4,
        "runtime_seconds": 42.0,
        "mip_gap": 1e-8,
        "time_limit_seconds": 3600,
        "wall_clock_cap_seconds": 28800,
        "validation_status": "validated",
        "error_type": None,
        "output_path": f"results/runs/campaign_01/{experiment}/{base_instance}/base/summary.json",
        "notes": None,
        "factor_levels": {"demand": 1.0, "capacity": 0.9} if factor_levels is None else factor_levels,
    }


def test_flatten_extracts_standard_fields() -> None:
    row = _flatten(_synthetic_manifest())
    assert row["campaign_id"] == "campaign_01"
    assert row["experiment_id"] == "exp3"
    assert row["base_instance_id"] == "STD_I17_M4_T3"
    assert row["algorithm_variant"] == "M0"
    assert row["solve_status"] == "success"
    assert row["cost"] == 1_000_000.0
    assert row["emissions"] == 500_000.0
    assert row["leader_tax_index"] == 10
    # 10 x 1e-4 USD/kg = 1e-3 USD/kg = 1 USD/t. The old constant (10 USD/t per index, the COARSE
    # grid) reported this run 100x too high.
    assert row["leader_tax_usd_per_tonne"] == pytest.approx(1.0)
    assert row["runtime_seconds"] == 42.0


def test_flatten_reports_no_rate_when_the_grid_is_unknown() -> None:
    # A pre-grid-unification manifest whose solve output is also gone: the index cannot be
    # converted. Absent is correct; a guess would silently be on the wrong grid.
    manifest = _synthetic_manifest()
    manifest.pop("tax_grid_step_usd_per_kg")
    row = _flatten(manifest)
    assert row["leader_tax_index"] == 10
    assert row["leader_tax_usd_per_tonne"] is None


def test_flatten_prefers_the_solver_reported_rate() -> None:
    manifest = _synthetic_manifest()
    manifest["effective_tax_usd_per_kg"] = 0.1673  # what the solver actually applied
    row = _flatten(manifest)
    assert row["leader_tax_usd_per_tonne"] == pytest.approx(167.3)


def test_flatten_parses_imt_from_instance_name() -> None:
    row = _flatten(_synthetic_manifest(base_instance="STD_I17_M4_T3"))
    assert (row["I"], row["M"], row["T"]) == (17, 4, 3)


def test_flatten_parses_large_instance_name() -> None:
    row = _flatten(_synthetic_manifest(base_instance="STD_I25_M8_T12"))
    assert (row["I"], row["M"], row["T"]) == (25, 8, 12)


def test_flatten_promotes_factor_levels_as_prefixed_columns() -> None:
    row = _flatten(_synthetic_manifest(factor_levels={"demand": 1.1, "capacity": 0.8}))
    assert row["factor__demand"] == pytest.approx(1.1)
    assert row["factor__capacity"] == pytest.approx(0.8)


def test_flatten_handles_missing_objective_values() -> None:
    manifest = _synthetic_manifest()
    manifest.pop("objective_values")
    row = _flatten(manifest)
    assert row["cost"] is None
    assert row["emissions"] is None
    assert row["follower_objective"] is None


def test_flatten_handles_empty_factor_levels() -> None:
    row = _flatten(_synthetic_manifest(factor_levels={}))
    assert not any(k.startswith("factor__") for k in row)


def test_flatten_censored_run_has_correct_status() -> None:
    manifest = _synthetic_manifest(solve_status="censored")
    manifest["censored"] = True
    row = _flatten(manifest)
    assert row["solve_status"] == "censored"
    assert row["censored"] is True


def test_aggregate_reads_manifests_and_returns_dataframe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for experiment, instance in [("exp3", "STD_I17_M4_T3"), ("exp3", "STD_I25_M8_T6")]:
        run_dir = tmp_path / "runs" / experiment / instance / "base"
        run_dir.mkdir(parents=True)
        manifest = _synthetic_manifest(experiment=experiment, base_instance=instance)
        (run_dir / "campaign_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()

    import clsc.analysis.campaign_01.aggregate as agg_mod

    monkeypatch.setattr(agg_mod, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(agg_mod, "TABLES", tables_dir)
    monkeypatch.setattr(agg_mod, "ensure_analysis_dirs", lambda: None)

    df = agg_mod.aggregate()

    assert len(df) == 2
    assert set(df["experiment_id"]) == {"exp3"}
    assert "cost" in df.columns
    assert "factor__demand" in df.columns
    assert (tables_dir / "master_runs_campaign_01.csv").exists()
