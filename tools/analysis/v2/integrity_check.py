"""Post-campaign integrity pass (plan §10, OneDrive-sync risk acceptance).

Since the campaign's working directories (`data/instances/campaigns/v2/`,
`results/runs/v2/`) live inside an actively-synced OneDrive folder, a sync-induced partial
write could in principle leave a truncated or corrupted file behind without raising an
exception during the run itself. This is a read-only check, run after a family (or the full
campaign) completes: every JSON file under the campaign's output trees must parse cleanly,
and every design point in a family's design_matrix.csv must have a corresponding
campaign_manifest.json.

Usage: `python -m tools.analysis.v2.integrity_check [--family A]`
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.analysis.v2.paths import INSTANCES, MANIFESTS, RUNS


def check_json_files_parse(root: Path) -> list[str]:
    """Return paths (relative to `root`) of every .json file that fails to parse."""
    broken: list[str] = []
    for path in root.glob("**/*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            broken.append(f"{path.relative_to(root)} ({type(exc).__name__}: {exc})")
    return broken


def check_design_points_have_manifests(family_id: str) -> list[str]:
    """Return design_point_ids from the family's design_matrix.csv with no manifest on disk."""
    design_matrix_path = MANIFESTS / family_id / "design_matrix.csv"
    if not design_matrix_path.exists():
        return [f"no design_matrix.csv found at {design_matrix_path}"]

    import csv

    missing: list[str] = []
    with design_matrix_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            run_dir = RUNS / family_id / row["base_instance_id"] / row["run_code"]
            if not (run_dir / "campaign_manifest.json").exists():
                missing.append(row["design_point_id"])
    return missing


def run_integrity_check(family_ids: list[str]) -> bool:
    all_ok = True

    for root, label in ((INSTANCES, "instances"), (RUNS, "results")):
        broken = check_json_files_parse(root)
        if broken:
            all_ok = False
            print(f"[FAIL] {len(broken)} unparseable JSON file(s) under {label} ({root}):")
            for entry in broken:
                print(f"    {entry}")
        else:
            print(f"[OK]   all JSON files under {label} parse cleanly")

    for family_id in family_ids:
        missing = check_design_points_have_manifests(family_id)
        if missing:
            all_ok = False
            print(f"[FAIL] Family {family_id}: {len(missing)} design point(s) with no campaign_manifest.json:")
            for design_point_id in missing:
                print(f"    {design_point_id}")
        else:
            print(f"[OK]   Family {family_id}: every design point has a campaign_manifest.json")

    return all_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", default="all", help="Family id (A-G) or 'all'.")
    args = parser.parse_args(argv)

    family_ids = list("ABCDEFG") if args.family == "all" else [args.family]
    ok = run_integrity_check(family_ids)
    print("ALL CHECKS PASSED" if ok else "INTEGRITY CHECK FAILED -- see above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
