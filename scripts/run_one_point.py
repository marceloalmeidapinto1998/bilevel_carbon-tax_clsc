"""Solve exactly one exp1 design point, by design_point_id. Development use against a dirty tree.

Unlike run_exp1_base_cells.py (all 12 base cells), this is for single-point smoke tests --
e.g. checking a WIP solver change on one cell before committing to a full campaign run.
"""
from __future__ import annotations

import sys
import time

from clsc.campaign.orchestrator import build_design_matrix, capture_code_provenance, run_point


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: run_one_point.py <design_point_id>", file=sys.stderr)
        return 2
    target = sys.argv[1]

    provenance = capture_code_provenance()
    print(f"commit={provenance.commit} dirty={provenance.dirty} "
          f"pub_safe={provenance.is_publication_safe}", flush=True)

    points = [p for p in build_design_matrix("exp1") if p.design_point_id == target]
    if len(points) != 1:
        print(f"expected exactly 1 match for {target!r}, found {len(points)}", file=sys.stderr)
        return 2
    point = points[0]

    print(f"solving {point.design_point_id} ({point.base_instance_id}, "
          f"cap {point.per_run_wall_clock_cap_seconds:.0f}s)", flush=True)
    started = time.perf_counter()
    manifest = run_point(point, overwrite=False, provenance=provenance)
    print(f"DONE status={manifest.get('solve_status')} "
          f"reason={manifest.get('termination_reason')} "
          f"elapsed={time.perf_counter() - started:.1f}s", flush=True)
    return 0 if manifest.get("solve_status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
