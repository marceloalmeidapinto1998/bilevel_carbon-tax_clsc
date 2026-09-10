"""Solve only the 12 base structural cells of campaign_01 / exp1.

The orchestrator CLI has no filter for `run_code == "base"`: `--base-instance` selects a cell,
but the invariant and seed probes share their base instance, so it would drag 6 extra points in.
This driver selects the 12 base design points exactly, and keeps run_experiment's provenance
guarantee: one snapshot for the whole invocation, and a hard refusal on a dirty worktree.

Resumable: overwrite=False, so an interrupted run picks up where it stopped.
"""
from __future__ import annotations

import sys
import time

from clsc.campaign.orchestrator import (
    DirtyWorkingTreeError,
    build_design_matrix,
    capture_code_provenance,
    require_clean_worktree,
    run_point,
)

EXPECTED_CELLS = 12


def main() -> int:
    provenance = capture_code_provenance()
    try:
        require_clean_worktree(provenance)
    except DirtyWorkingTreeError as error:
        print(str(error), file=sys.stderr)
        return 3

    points = [p for p in build_design_matrix("exp1") if p.run_code == "base"]
    if len(points) != EXPECTED_CELLS:
        print(f"expected {EXPECTED_CELLS} base design points, found {len(points)}", file=sys.stderr)
        return 2

    print(f"commit={provenance.commit} dirty={provenance.dirty}", flush=True)
    print(f"solving {len(points)} base cells", flush=True)

    results = []
    for n, point in enumerate(points, start=1):
        started = time.perf_counter()
        print(f"[{n}/{len(points)}] START {point.base_instance_id} "
              f"(cap {point.per_run_wall_clock_cap_seconds:.0f}s)", flush=True)
        manifest = run_point(point, overwrite=False, provenance=provenance)
        results.append(manifest)
        print(f"[{n}/{len(points)}] DONE  {point.base_instance_id} "
              f"status={manifest.get('solve_status')} "
              f"reason={manifest.get('termination_reason')} "
              f"elapsed={time.perf_counter() - started:.1f}s", flush=True)

    n_success = sum(1 for r in results if r.get("solve_status") == "success")
    print(f"exp1 base cells: {n_success}/{len(results)} succeeded", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
