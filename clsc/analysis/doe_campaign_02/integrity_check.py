"""Post-campaign integrity pass for doe_campaign_02 (mirrors archive.campaign_01.analysis.integrity_check,
including the Family-A single-run-layout fallback fixed there on 2026-07-06).

Read-only check, run after a family (or the full campaign) completes: every JSON file under the
campaign's output trees must parse cleanly, and every design point in a family's
design_matrix.csv must have a corresponding campaign_manifest.json.

Usage: `python -m clsc.analysis.doe_campaign_02.integrity_check [--family A]`
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from clsc.analysis.doe_campaign_02.paths import INSTANCES, MANIFESTS, RUNS
from clsc.campaign.orchestrator import FAMILY_DIR_NAMES


def check_json_files_parse(root: Path) -> list[str]:
    """Return paths (relative to `root`) of every .json file that fails to parse."""
    broken: list[str] = []
    for path in root.glob("**/*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            broken.append(f"{path.relative_to(root)} ({type(exc).__name__}: {exc})")
    return broken


def _manifest_matches(path: Path, design_point_id: str) -> bool:
    """True if `path` is a campaign_manifest.json that identifies itself as `design_point_id`."""
    if not path.exists():
        return False
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return manifest.get("design_point_id") == design_point_id


def check_design_points_have_manifests(family_id: str) -> list[str]:
    """Return design_point_ids from the family's design_matrix.csv with no manifest on disk.

    Multi-run families (B/C/D/F/G) nest each run under its ``run_code`` subdirectory. Family A
    has exactly one run per instance, so its orchestrator writes the manifest directly in the
    instance directory with no ``run_code`` level. Both layouts are accepted.
    """
    design_matrix_path = MANIFESTS / FAMILY_DIR_NAMES[family_id] / "design_matrix.csv"
    if not design_matrix_path.exists():
        return [f"no design_matrix.csv found at {design_matrix_path}"]

    import csv

    missing: list[str] = []
    with design_matrix_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            instance_dir = RUNS / FAMILY_DIR_NAMES[family_id] / row["base_instance_id"]
            candidates = (
                instance_dir / row["run_code"] / "campaign_manifest.json",  # multi-run layout
                instance_dir / "campaign_manifest.json",                    # Family A layout
            )
            if not any(_manifest_matches(path, row["design_point_id"]) for path in candidates):
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
    parser.add_argument("--family", default="all", help="Family id (0, A-F) or 'all'.")
    args = parser.parse_args(argv)

    family_ids = ["0", *"ABCDEF"] if args.family == "all" else [args.family]
    ok = run_integrity_check(family_ids)
    print("ALL CHECKS PASSED" if ok else "INTEGRITY CHECK FAILED -- see above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
