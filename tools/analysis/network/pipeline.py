"""Orchestrator and output writers for per-instance network analysis."""

from __future__ import annotations

import csv
import json
import platform
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from . import io as ts_io
from .io import (
    DEFAULT,
    AnalysisConfig,
    attach_file_handler,
    detach_handler,
    ensure_stream_handler,
    get_logger,
)
from .models import TauSnapshot, TauStructureResult
from .core import (
    aggregate_snapshot_metrics,
    build_alignment,
    build_summary_dataframe,
    build_transport_mode_dataframe,
    compute_structural_signature,
    detect_phases,
    detect_transitions,
    enrich_summary,
    parse_follower_into_rows,
    phases_to_rows,
    transitions_to_rows,
)

_TRACKED_PACKAGES = ("pandas", "numpy")


# ---------------------------------------------------------------------------
# CSV / JSON writers
# ---------------------------------------------------------------------------

def write_table(df: pd.DataFrame, path: Path, *, float_format: str = "%.6g") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, float_format=float_format)


def write_long_csv(
    rows: list[dict[str, Any]],
    path: Path,
    *,
    fieldnames: Iterable[str] | None = None,
) -> None:
    if not rows:
        return
    if fieldnames is None:
        seen: dict[str, None] = {}
        for row in rows:
            for key in row.keys():
                seen.setdefault(key, None)
        fieldnames = list(seen.keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_alignment_json(rep, path: Path) -> None:
    payload = {
        "instance": rep.instance,
        "lf_lex_present": rep.lf_lex_present,
        "lf_lex_hat_tau": rep.lf_lex_hat_tau,
        "enumeration_incumbent_hat_tau": rep.enum_selected_hat_tau,
        "hat_tau_match": rep.hat_tau_match,
        "emissions_match": rep.emissions_match,
        "deltas_at_same_tau": {
            "cost_delta": rep.cost_delta_at_same_tau,
            "emissions_delta": rep.emissions_delta_at_same_tau,
            "follower_objective_delta": rep.follower_objective_delta_at_same_tau,
        },
        "tolerance": rep.tolerance,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def write_long_family_csvs(result: TauStructureResult, data_dir: Path) -> list[str]:
    """Emit one CSV per variable-family filename plus leader.csv and unknown_vars.csv."""
    data_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    leader_rows = [
        {
            "hat_tau": s.hat_tau,
            "effective_tax": s.effective_tax,
            "is_lf_lex_incumbent": int(s.is_lf_lex_incumbent),
        }
        for s in result.snapshots
    ]
    write_long_csv(
        leader_rows,
        data_dir / "leader.csv",
        fieldnames=["hat_tau", "effective_tax", "is_lf_lex_incumbent"],
    )
    written.append("leader.csv")

    for filename, rows in result.rows_by_file.items():
        if not rows:
            continue
        write_long_csv(rows, data_dir / filename)
        written.append(filename)

    if result.unknown_rows:
        write_long_csv(result.unknown_rows, data_dir / "unknown_vars.csv")
        written.append("unknown_vars.csv")

    return sorted(written)


def alignment_to_row(rep) -> dict[str, Any]:
    return asdict(rep)


def _package_versions() -> dict[str, str]:
    out: dict[str, str] = {"python": platform.python_version()}
    for pkg in _TRACKED_PACKAGES:
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "not_installed"
    return out


def build_manifest(
    cfg: AnalysisConfig,
    instance: str,
    source_files: list[tuple[Path, bool, str | None]],
    outputs: dict[str, list[str]],
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    inputs = [{"path": str(p), "present": present, "sha256": sha}
              for p, present, sha in source_files]
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "tool": "tools.analysis.network",
        "run_id": "run_" + now.strftime("%Y%m%dT%H%M%SZ"),
        "created_at_utc": now.isoformat(),
        "instance": instance,
        "argv": sys.argv,
        "config": cfg.to_dict(),
        "inputs": inputs,
        "outputs": outputs,
        "versions": _package_versions(),
    }
    if extras:
        manifest.update(extras)
    return manifest


def write_manifest(manifest: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)


# ---------------------------------------------------------------------------
# Snapshot assembly
# ---------------------------------------------------------------------------

def _snapshots_from_payload(
    enum_payload: dict[str, Any],
    lf_lex_hat_tau: int | None,
    cfg: AnalysisConfig,
) -> tuple[list[TauSnapshot], dict[str, list[dict]], list[dict]]:
    snapshots: list[TauSnapshot] = []
    rows_by_file: dict[str, list[dict]] = defaultdict(list)
    unknown_rows: list[dict] = []

    for snap in enum_payload["tax_solutions"]:
        leader = snap["leader"]
        hat_tau = int(leader["hat_tau"])
        is_incumbent = (lf_lex_hat_tau is not None and hat_tau == lf_lex_hat_tau)
        base_row = {
            "hat_tau": hat_tau,
            "effective_tax": float(leader["effective_tax"]),
            "is_lf_lex_incumbent": int(is_incumbent),
        }
        follower = snap["decision_variables"]["follower"]
        snap_rows_by_file, snap_unknown = parse_follower_into_rows(follower, base_row, cfg.eps)
        for fname, rows in snap_rows_by_file.items():
            rows_by_file[fname].extend(rows)
        unknown_rows.extend(snap_unknown)

        metrics = aggregate_snapshot_metrics(snap_rows_by_file)
        signature = compute_structural_signature(snap_rows_by_file, cfg.structural_families)

        objectives = snap["objectives"]
        runtime = snap.get("runtime") or {}
        gaps = snap.get("gaps") or {}
        snapshots.append(TauSnapshot(
            hat_tau=hat_tau,
            effective_tax=float(leader["effective_tax"]),
            cost=float(objectives.get("cost", float("nan"))),
            emissions=float(objectives.get("emissions", float("nan"))),
            follower_objective=float(objectives.get("follower_objective", float("nan"))),
            objective_value=float(objectives.get("objective_value", float("nan"))),
            solve_seconds=runtime.get("solve_seconds"),
            mip_gap=gaps.get("mip_gap"),
            lex_primary_mip_gap=gaps.get("lex_primary_mip_gap"),
            lex_secondary_mip_gap=gaps.get("lex_secondary_mip_gap"),
            rows_by_family=dict(snap_rows_by_file),
            metrics=metrics,
            structural_signature=signature,
            is_lf_lex_incumbent=is_incumbent,
        ))

    snapshots.sort(key=lambda s: s.hat_tau)
    for fname, rows in rows_by_file.items():
        rows.sort(key=lambda r: (r.get("hat_tau"), r.get("family", ""), tuple(
            (k, v) for k, v in r.items() if k not in (
                "hat_tau", "effective_tax", "is_lf_lex_incumbent", "family", "value", "active"
            )
        )))
    return snapshots, dict(rows_by_file), unknown_rows


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_instance(
    instance: str,
    cfg: AnalysisConfig = DEFAULT,
) -> TauStructureResult:
    """Compute and write all per-instance network artifacts."""
    ensure_stream_handler(cfg.log_level)
    paths = ts_io.ensure_output_dirs(instance, cfg)
    handler = attach_file_handler(paths.log, cfg.log_level)
    log = get_logger()

    try:
        log.info("starting network analysis instance=%s", instance)
        enum_payload = ts_io.load_enumeration_payload(instance, cfg)
        lf_lex_payload = ts_io.load_lf_lex_payload(instance, cfg)
        lf_lex_tau = (None if lf_lex_payload is None
                      else int(lf_lex_payload["leader"]["hat_tau"]))
        log.info("loaded payloads: enum_taus=%d lf_lex_present=%s",
                 len(enum_payload.get("tax_solutions", [])),
                 lf_lex_payload is not None)

        snapshots, rows_by_file, unknown_rows = _snapshots_from_payload(
            enum_payload, lf_lex_tau, cfg,
        )

        summary_df = build_summary_dataframe(snapshots)
        summary_df = enrich_summary(summary_df, snapshots, cfg.baseline_tau, cfg.eps)

        phases = detect_phases(snapshots)
        transitions = detect_transitions(snapshots)
        alignment = build_alignment(enum_payload, lf_lex_payload, cfg.eps)

        result = TauStructureResult(
            instance=instance,
            snapshots=snapshots,
            summary=summary_df,
            phases=phases,
            transitions=transitions,
            alignment=alignment,
            unknown_rows=unknown_rows,
            rows_by_file=rows_by_file,
        )

        write_table(summary_df, paths.root / "summary.csv")
        write_table(pd.DataFrame(phases_to_rows(phases)), paths.root / "phases.csv")
        write_table(pd.DataFrame(transitions_to_rows(transitions)), paths.root / "transitions.csv")
        write_table(build_transport_mode_dataframe(rows_by_file), paths.root / "transport_modes.csv")
        write_table(pd.DataFrame([alignment_to_row(alignment)]), paths.root / "alignment.csv")
        write_alignment_json(alignment, paths.alignment_json)
        long_written = write_long_family_csvs(result, paths.root)

        sources = [
            (ts_io.enum_path(instance, cfg), True,
             ts_io.sha256_file(ts_io.enum_path(instance, cfg))),
        ]
        lf_path = ts_io.lf_lex_path(instance, cfg)
        sources.append((lf_path, lf_path.is_file(),
                        ts_io.sha256_file(lf_path) if lf_path.is_file() else None))

        manifest = build_manifest(
            cfg=cfg,
            instance=instance,
            source_files=sources,
            outputs={
                "network": sorted(p.name for p in paths.root.iterdir() if p.is_file()),
                "data": long_written,
                "alignment_json": paths.alignment_json.name,
            },
            extras={
                "n_taus": len(snapshots),
                "n_phases": len(phases),
                "n_transitions": len(transitions),
                "hat_tau_match": alignment.hat_tau_match,
                "emissions_match": alignment.emissions_match,
                "lf_lex_present": alignment.lf_lex_present,
                "unknown_var_rows": len(unknown_rows),
            },
        )
        write_manifest(manifest, paths.manifest)
        log.info("done instance=%s phases=%d transitions=%d hat_tau_match=%s",
                 instance, len(phases), len(transitions), alignment.hat_tau_match)
        return result
    finally:
        detach_handler(handler)

