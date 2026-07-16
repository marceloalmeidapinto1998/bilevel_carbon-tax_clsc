from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.analysis.doe_campaign_01.aggregate import _flatten


def _synthetic_manifest(
    *,
    family: str = "A",
    base_instance: str = "STD_I17_M4_T3",
    solve_status: str = "success",
    factor_levels: dict | None = None,
) -> dict:
    return {
        "campaign_id": "doe_campaign_01",
        "family_id": family,
        "design_point_id": f"{family}-001",
        "base_instance_id": base_instance,
        "technology_menu": "base",
        "transport_menu": "base",
        "seed_offset": 0,
        "code_version": "abc123",
        "solver_method": "dbp_lex",
        "solve_status": solve_status,
        "termination_reason": "optimal" if solve_status == "success" else None,
        "censored": False,
        "objective_values": {
            "cost": 1_000_000.0,
            "emissions": 500_000.0,
            "follower_objective": 1_050_000.0,
        },
        "leader_tax": 10,
        "runtime_seconds": 42.0,
        "mip_gap": 1e-5,
        "time_limit_seconds": 3600,
        "wall_clock_cap_seconds": 7200,
        "validation_status": "valid",
        "error_type": None,
        "output_path": f"results/runs/doe_campaign_01/{family}/{base_instance}/{family}-001/summary.json",
        "notes": None,
        "factor_levels": {"demand": 1.0, "capacity": 0.9} if factor_levels is None else factor_levels,
    }


# ---------------------------------------------------------------------------
# _flatten
# ---------------------------------------------------------------------------

def test_flatten_extracts_standard_fields() -> None:
    row = _flatten(_synthetic_manifest())
    assert row["campaign_id"] == "doe_campaign_01"
    assert row["family_id"] == "A"
    assert row["base_instance_id"] == "STD_I17_M4_T3"
    assert row["solve_status"] == "success"
    assert row["cost"] == 1_000_000.0
    assert row["emissions"] == 500_000.0
    assert row["leader_tax_index"] == 10
    assert row["leader_tax_usd_per_tonne"] == pytest.approx(100.0)
    assert row["runtime_seconds"] == 42.0


def test_flatten_parses_imt_from_instance_name() -> None:
    row = _flatten(_synthetic_manifest(base_instance="STD_I17_M4_T3"))
    assert row["I"] == 17
    assert row["M"] == 4
    assert row["T"] == 3


def test_flatten_parses_large_instance_name() -> None:
    row = _flatten(_synthetic_manifest(base_instance="STD_I25_M8_T12"))
    assert row["I"] == 25
    assert row["M"] == 8
    assert row["T"] == 12


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


# ---------------------------------------------------------------------------
# aggregate (smoke test via monkeypatch)
# ---------------------------------------------------------------------------

def test_aggregate_reads_manifests_and_returns_dataframe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Write two synthetic manifests to tmp_path
    for family, instance in [("A", "STD_I17_M4_T3"), ("G", "STD_I25_M8_T6")]:
        run_dir = tmp_path / "runs" / family / instance / f"{family}-001"
        run_dir.mkdir(parents=True)
        manifest = _synthetic_manifest(family=family, base_instance=instance)
        (run_dir / "campaign_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()

    import tools.analysis.doe_campaign_01.aggregate as agg_mod

    monkeypatch.setattr(agg_mod, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(agg_mod, "TABLES", tables_dir)
    monkeypatch.setattr(agg_mod, "ensure_analysis_dirs", lambda: None)

    df = agg_mod.aggregate()

    assert len(df) == 2
    assert set(df["family_id"]) == {"A", "G"}
    assert "cost" in df.columns
    assert "factor__demand" in df.columns
    assert (tables_dir / "master_runs_doe_campaign_01.csv").exists()
