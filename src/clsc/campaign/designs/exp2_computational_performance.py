"""Experiment 2 - Computational Performance (docs/Experimental_Plan.md §2).

Merges the prior campaign's ablation, scalability, and enumeration-benchmark experiments into one:
they all answer "does DBP work, and is it worth having." M0 (full DBP) runs on the 6 representative
cells (2 fast + 2 medium + 2 hard), with a light seed-noise check on 2 of them. Both ablation
variants run on the same 3 cells spanning the tiers (fast, medium, hard): A1 (no in-loop min-tax
confirmation), the claim-carrying one, and A5 (no incumbent cut), the one efficiency-only variant
that showed a real timing effect in the prior campaign (A2/A3 did not). Two scalability escalation
probes -- one per axis, materials/products richness (M8 -> M12 -> M16 at fixed I25-T6) and node
count (I17 -> I25 -> I33 at fixed M8-T6) -- and exhaustive-enumeration benchmarks on 2 cells (fast
+ medium) round out the module.

The escalation curves' first two points on each axis are free: `STD_I25_M4_T6`/`STD_I25_M8_T6`
(M-axis) and `STD_I17_M8_T6`/`STD_I25_M8_T6` (I-axis) are already solved as part of the M0
reference above. Only the third point on each axis -- past the standard 12-cell testbed -- is a
genuinely new escalation solve. A third axis, periods (T3 -> T6 -> T12), needs no new solves at
all: every T12 cell is already solved once in Experiment 1's base gate. None of this is a formal
scalability *experiment* of its own; it is three data points read off cells this module (or
Experiment 1) already schedules, plus the two new ones below.
"""
from __future__ import annotations

from clsc.campaign.designs._cells import (
    FAST_CELLS, HARD_CELLS, MEDIUM_CELLS, REPRESENTATIVE_CELLS, time_limits,
)
from clsc.campaign.designs._common import DesignPoint

EXPERIMENT_ID = "exp2"

# Ablation variants, both on the same 3 cells across tiers: A1 changes the certified guarantee
# (claim-carrying); A5 is the one efficiency-only variant with a measured effect in the prior
# campaign.
CLAIM_CARRYING_VARIANTS = ("A1",)
EFFICIENCY_VARIANTS = ("A5",)
ABLATION_CELLS = (FAST_CELLS[0], MEDIUM_CELLS[0], HARD_CELLS[0])

# Light seed-noise check on the M0 reference: 1 fast + 1 hard cell at a second seed.
SEED_CHECK_CELLS = (FAST_CELLS[0], HARD_CELLS[0])
SEED_CHECK_OFFSET = 1

# Scalability escalation probes: points beyond the standard 12-cell testbed, on two axes.
# Each lives alongside the standard 12 under data/instances/base/ but is generated separately
# (clsc.generator.build_escalation_specs / generate_escalation_bases), not by the standard
# `python -m clsc.generator benchmark` run. All are hard-tier: past M8/I25 the algorithm may
# censor rather than certify exact, which is itself the point of adding them (a scalability curve
# showing how the gap grows is more informative than one that stops exactly at the tractable edge).
ESCALATION_CELLS = {
    # M-axis (materials/products richness) at fixed I25-T6: M4, M8 read off the M0 reference above;
    # M12 and M16 are the 3rd/4th points, each its own solve.
    "escalation_M12": "STD_I25_M12_T6",
    "escalation_M16": "STD_I25_M16_T6",
    # I-axis (node count) at fixed M8-T6: I17, I25 read off the M0 reference above; I33 is the 3rd
    # point.
    "escalation_I33": "STD_I33_M8_T6",
}

# Exhaustive-enumeration benchmark: 1 fast + 1 medium cell (enumeration is exact by construction
# but expensive per point; 2 cells are enough to establish the follower-solve-count ratio).
BENCHMARK_CELLS = (FAST_CELLS[0], MEDIUM_CELLS[0])
BENCHMARK_MEDIUM_SUBPROBLEM_TIME_LIMIT_SECONDS = 1800.0   # 30 min: generous for one fixed-tax MILP
BENCHMARK_MEDIUM_WALL_CLOCK_CAP_SECONDS = 7200.0          # 2 h: bounds the tail


def _bilevel(cell: str, *, run_code: str, dpid: str, variant: str = "M0",
             seed_offset: int = 0, scale_factor: float | None = None, note: str = "") -> DesignPoint:
    sub, wall = time_limits(cell)
    return DesignPoint(
        experiment_id=EXPERIMENT_ID, design_point_id=dpid, run_code=run_code,
        base_instance_id=cell, execution_mode="bilevel", algorithm_variant=variant,
        seed_offset=seed_offset, scale_factor=scale_factor,
        per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall, notes=note,
    )


def build_design_matrix() -> list[DesignPoint]:
    points: list[DesignPoint] = []

    # M0 reference on the 6 representative cells (policy-value's P3 is read from this, not re-solved).
    for cell in REPRESENTATIVE_CELLS:
        points.append(_bilevel(
            cell, run_code="M0_seed0", dpid=f"exp2-M0-{cell}-s0",
            note="M0 reference (policy-value P3 / scalability core).",
        ))
    for cell in SEED_CHECK_CELLS:
        points.append(_bilevel(
            cell, run_code=f"M0_seed{SEED_CHECK_OFFSET}", dpid=f"exp2-M0-{cell}-s{SEED_CHECK_OFFSET}",
            seed_offset=SEED_CHECK_OFFSET, note="Seed-noise check on the M0 reference.",
        ))

    # A1 / A5, both on the same 3 cells across tiers, seed 0.
    for cell in ABLATION_CELLS:
        points.append(_bilevel(
            cell, run_code="A1", dpid=f"exp2-A1-{cell}", variant="A1",
            note="A1: no in-loop min-tax confirmation (H2.1).",
        ))
        points.append(_bilevel(
            cell, run_code="A5", dpid=f"exp2-A5-{cell}", variant="A5",
            note="A5: no incumbent cut (H2.2).",
        ))

    # Scalability escalation probes (2 new axis points, see module docstring).
    sub, wall = time_limits("STD_I25_M8_T6")  # hard-tier caps (every escalation base is past M8/I25)
    for run_code, cell in ESCALATION_CELLS.items():
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID, design_point_id=f"exp2-scale-{cell}",
            run_code=run_code, base_instance_id=cell, execution_mode="bilevel",
            per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
            notes=f"Scalability escalation probe ({run_code}) (H2.3).",
        ))

    # Exhaustive-enumeration benchmark.
    for cell in BENCHMARK_CELLS:
        if cell in MEDIUM_CELLS:
            sub, wall = (BENCHMARK_MEDIUM_SUBPROBLEM_TIME_LIMIT_SECONDS,
                         BENCHMARK_MEDIUM_WALL_CLOCK_CAP_SECONDS)
        else:
            sub, wall = time_limits(cell)
        points.append(DesignPoint(
            experiment_id=EXPERIMENT_ID, design_point_id=f"exp2-enum-{cell}",
            run_code="enumeration", base_instance_id=cell, execution_mode="enumeration",
            per_subproblem_time_limit_seconds=sub, per_run_wall_clock_cap_seconds=wall,
            notes="Exhaustive fine-grid enumeration baseline (H2.4).",
        ))

    return points
