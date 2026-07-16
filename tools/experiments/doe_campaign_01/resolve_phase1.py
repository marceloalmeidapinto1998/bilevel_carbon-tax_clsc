"""Phase-1 targeted re-solves of soft/censored doe_campaign_01 points with MIPFocus=1.

Rebuilds each target design point from its family spec, overrides only ``mip_focus`` (leaving the
global gap_tol.py default at 0 — see project memory), and re-runs it in place via the campaign
orchestrator's ``run_point(overwrite=True)``. Reads the pre-existing manifest first so each point
is logged before -> after. Read/run only; touches no WIP files.

Usage:
  python -m tools.experiments.doe_campaign_01.resolve_phase1 --dry-run
  python -m tools.experiments.doe_campaign_01.resolve_phase1 --targets A-07,D-02-seed2,...
  python -m tools.experiments.doe_campaign_01.resolve_phase1            # all 13, cheap->expensive
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from tools.experiments.doe_campaign_01.campaign import (
    REPO_ROOT,
    build_design_matrix,
    run_point,
    _manifest_path,
    _run_output_dir,
)

# Ordered cheap -> expensive (by original runtime), so a partial/interrupted run still lands the
# cheap fixes. A-07 first (validates the mechanism end-to-end on a real hard-ish instance).
DEFAULT_TARGETS = [
    ("A", "A-07"),          # STD_I25_M8_T3, ~634 s orig
    ("D", "D-02-seed2"),    # STD_I17_M4_T3, 138 s
    ("D", "D-04-seed2"),    # 139 s
    ("D", "D-10-seed1"),    # 576 s
    ("D", "D-04-seed1"),    # 738 s
    ("D", "D-14-seed1"),    # 3633 s (censored)
    ("D", "D-08-seed1"),    # 3649 s (censored)
    ("D", "D-16-seed1"),    # 3860 s (censored)
    ("D", "D-06-seed1"),    # 14806 s
    ("D", "D-24"),          # STD_I25_M8_T6, 12167 s (censored)
    ("D", "D-27"),          # 10854 s (censored, 42% gap)
    ("D", "D-29"),          # 11183 s (censored, 42% gap)
    ("D", "D-31"),          # 38144 s (censored, 42% gap)
]


# Files written by the solve (solve_batch + run_point). `_solve_bilevel` skips the actual solve if
# a summary.json already exists in out_dir, so a genuine re-solve must move these out first; leaving
# them would also collide with solve_batch's shutil.move of the fresh outputs. We STASH (move) rather
# than delete so an interrupted re-solve leaves the originals recoverable -- results/ is gitignored,
# so deletion has no safety net (this is how the D-06-seed1 detail files were lost on 2026-07-06).
SOLVE_ARTIFACTS = ("summary.json", "solution.json", "result.json", "dbp_trace.csv",
                   "summary.csv", "manifest.json")
# Outside the project tree (never OneDrive-synced), keyed by design point.
STASH_ROOT = Path(tempfile.gettempdir()) / "doe_campaign_01_phase1_stash"


def _stash_solve_outputs(out_dir, design_point_id):
    dest = STASH_ROOT / design_point_id
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)  # drop a stale stash from a prior attempt
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in SOLVE_ARTIFACTS:
        p = out_dir / name
        if p.exists():
            shutil.move(str(p), str(dest / name))
            moved.append(name)
    for p in list(out_dir.glob("**/summary.json")):  # defensive: any nested leftovers
        shutil.move(str(p), str(dest / p.name))
    return moved, dest


def _index_points(family_ids):
    idx = {}
    for fam in family_ids:
        for p in build_design_matrix(fam):
            idx[p.design_point_id] = p
    return idx


def _snapshot(manifest):
    if not manifest:
        return "(no prior manifest)"
    ov = manifest.get("objective_values") or {}
    return (f"status={manifest.get('solve_status')} term={manifest.get('termination_reason')} "
            f"gap={manifest.get('mip_gap')} tax={manifest.get('leader_tax')} "
            f"emis={ov.get('emissions')} rt={manifest.get('runtime_seconds')}s")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Resolve targets and print plan; do not solve.")
    ap.add_argument("--targets", default=None, help="Comma-separated design_point_ids (default: all 13).")
    args = ap.parse_args(argv)

    if args.targets:
        wanted = args.targets.split(",")
        # keep DEFAULT_TARGETS order where possible
        order = {dp: i for i, (_, dp) in enumerate(DEFAULT_TARGETS)}
        targets = sorted(wanted, key=lambda d: order.get(d, 999))
        fam_of = {dp: fam for fam, dp in DEFAULT_TARGETS}
        targets = [(fam_of.get(dp, dp.split("-")[0]), dp) for dp in targets]
    else:
        targets = DEFAULT_TARGETS

    idx = _index_points({fam for fam, _ in targets})

    missing = [dp for _, dp in targets if dp not in idx]
    if missing:
        print(f"[ERROR] {len(missing)} target id(s) not found in design matrices: {missing}")
        return 1

    print(f"{'DRY-RUN: ' if args.dry_run else ''}{len(targets)} targets, MIPFocus 0 -> 1, overwrite in place\n")
    results = []
    for n, (fam, dp) in enumerate(targets, 1):
        point = idx[dp]
        out_dir = _run_output_dir(point)
        mpath = _manifest_path(point)
        before = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
        print(f"[{n}/{len(targets)}] {dp}  ({point.base_instance_id}, run_code={point.run_code}, "
              f"tlim={point.per_subproblem_time_limit_seconds:.0f}s)")
        print(f"        out_dir : {out_dir.relative_to(REPO_ROOT)}")
        print(f"        BEFORE  : {_snapshot(before)}")
        if args.dry_run:
            print(f"        WOULD RUN with mip_focus=1 (was {point.mip_focus}); "
                  f"would stash {[n for n in SOLVE_ARTIFACTS if (out_dir / n).exists()]}\n")
            continue
        moved, stash = _stash_solve_outputs(out_dir, dp)
        print(f"        stashed : {moved} -> {stash}", flush=True)
        t0 = time.time()
        manifest = run_point(replace(point, mip_focus=1), overwrite=True)
        dt = time.time() - t0
        print(f"        AFTER   : {_snapshot(manifest)}")
        print(f"        wall    : {dt:.1f}s   [{n}/{len(targets)} done]\n", flush=True)
        results.append({"design_point_id": dp, "before": _snapshot(before),
                        "after": _snapshot(manifest), "wall_seconds": dt,
                        "after_status": manifest.get("solve_status"),
                        "after_gap": manifest.get("mip_gap")})

    if not args.dry_run:
        print("=== SUMMARY ===")
        for r in results:
            print(f"  {r['design_point_id']:14s} -> {r['after_status']:9s} gap={r['after_gap']} ({r['wall_seconds']:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
