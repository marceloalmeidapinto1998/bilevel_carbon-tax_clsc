"""Family B - Cost-emissions frontier: tax-indexed and epsilon-constraint sweeps (RQ1).

Two complementary sweeps of the follower's single-level MILP on the same 3 representative
instances (EXPERIMENTAL_PLAN.md §4-B):

- **Tax-indexed sweep** (`execution_mode="fixed_tax"`): `fixed_tax_index` in {0, 2, ..., 20} (11
  points). Sidesteps carbon-price non-identification -- no leader optimization, every point exact
  for its tax level.
- **Epsilon-constraint sweep** (AUGMECON-style, Mavrotas 2009): minimize cost subject to
  `emissions <= epsilon`, at `tax_index = 0`. The minimum-cost anchor is the tax sweep's own
  `tax_index=0` run -- identical model, since `follower_expr = cost_expr + scale*0*emissions_expr`
  reduces to `cost_expr` -- and is NOT re-solved here. The minimum-emissions anchor
  (`execution_mode="min_emissions"`) and the intermediate epsilon grid
  (`execution_mode="epsilon_constraint"`) are genuinely new solves.

**Two-phase design**, mirroring Family E's data-driven pattern (`family_e_response_surface.py`):
the intermediate epsilon grid's bounds are the two anchors' *observed* emissions values, which
are only known once the anchors have actually been solved.

- `build_design_matrix()` with no arguments returns only the context-free Phase-1 design (tax
  sweep + minimum-emissions anchors: 33 + 3 = 36 runs).
- Once Phase 1's manifests are available, `build_design_matrix(epsilon_anchors={instance_id:
  (min_emissions, min_cost_anchor_emissions), ...})` appends the intermediate epsilon grid (10 +
  5 + 5 = 20 more runs, 56 total), where `min_emissions` is the min-emissions-anchor run's solved
  `emissions` value and `min_cost_anchor_emissions` is the tax sweep's `tax_index=0` run's solved
  `emissions` value, both for that `instance_id`.
"""
from __future__ import annotations

from experiments.designs._common import DesignPoint
from tools.experiments.doe_campaign_01.design.epsilon_sweep import epsilon_grid
from tools.experiments.doe_campaign_01.design.frontier_sweep import tax_grid

FAMILY_ID = "B"

REPRESENTATIVE_INSTANCES: tuple[str, ...] = ("STD_I17_M4_T3", "STD_I25_M4_T6", "STD_I25_M8_T6")

OVERLINE_TAX_INDEX = 20  # all base instances share this ceiling (overline_tau=0.20)
N_TAX_POINTS = 11
TAX_STEP = 2

# Intermediate epsilon-grid points per instance (EXPERIMENTAL_PLAN.md §4-B).
N_EPSILON_INTERMEDIATE: dict[str, int] = {
    "STD_I17_M4_T3": 10,
    "STD_I25_M4_T6": 5,
    "STD_I25_M8_T6": 5,
}

# Two-tier time-limit scheme, see EXPERIMENTAL_PLAN.md §3. fixed_tax/min_emissions/
# epsilon_constraint are all single-MILP solves (no DBP outer loop), so wall-clock == per-subproblem.
STANDARD_SUBPROBLEM_SECONDS = 3600.0
HARD_SUBPROBLEM_SECONDS = 10800.0

HARD_TIER_INSTANCES: frozenset[str] = frozenset({"STD_I25_M8_T6"})


def _time_limit(instance_id: str) -> float:
    return HARD_SUBPROBLEM_SECONDS if instance_id in HARD_TIER_INSTANCES else STANDARD_SUBPROBLEM_SECONDS


# Fixed per-instance design_point_id block, wide enough for the largest possible per-instance
# count (11 tax + 1 anchor + 10 intermediate = 22 for the fast instance). Reserving a stable block
# per instance -- rather than a single running counter -- keeps already-solved runs' ids from
# shifting when Phase 2 (epsilon_anchors supplied) regenerates the design matrix: run identity for
# resumability is keyed off (instance, run_code) -> output path (see campaign.py's
# `_run_output_dir`), but design_point_id is still recorded inside each manifest and must match the
# regenerated design_matrix.csv row for `tools.analysis.doe_campaign_02.integrity_check` to pass.
IDS_PER_INSTANCE_BLOCK = 30


def build_design_matrix(
    epsilon_anchors: dict[str, tuple[float, float]] | None = None,
) -> list[DesignPoint]:
    epsilon_anchors = epsilon_anchors or {}
    grid = tax_grid(OVERLINE_TAX_INDEX, n_points=N_TAX_POINTS, step=TAX_STEP)
    points: list[DesignPoint] = []

    for instance_index, instance_id in enumerate(REPRESENTATIVE_INSTANCES):
        cap = _time_limit(instance_id)
        base_id = instance_index * IDS_PER_INSTANCE_BLOCK
        local = 0

        for tax_index in grid:
            local += 1
            points.append(
                DesignPoint(
                    family_id=FAMILY_ID,
                    design_point_id=f"B-{base_id + local:02d}",
                    run_code=f"tau{tax_index:02d}",
                    base_instance_id=instance_id,
                    execution_mode="fixed_tax",
                    per_subproblem_time_limit_seconds=cap,
                    per_run_wall_clock_cap_seconds=cap,
                    fixed_tax_index=tax_index,
                )
            )

        local += 1
        points.append(
            DesignPoint(
                family_id=FAMILY_ID,
                design_point_id=f"B-{base_id + local:02d}",
                run_code="eps_anchor_min_emissions",
                base_instance_id=instance_id,
                execution_mode="min_emissions",
                per_subproblem_time_limit_seconds=cap,
                per_run_wall_clock_cap_seconds=cap,
                fixed_tax_index=0,
                notes="AUGMECON payoff-table anchor: unconstrained minimum emissions",
            )
        )

        anchors = epsilon_anchors.get(instance_id)
        if anchors is not None:
            min_emissions, min_cost_anchor_emissions = anchors
            n_intermediate = N_EPSILON_INTERMEDIATE[instance_id]
            grid_points = epsilon_grid(min_emissions, min_cost_anchor_emissions, n_points=n_intermediate)
            for i, epsilon in enumerate(grid_points, start=1):
                local += 1
                points.append(
                    DesignPoint(
                        family_id=FAMILY_ID,
                        design_point_id=f"B-{base_id + local:02d}",
                        run_code=f"eps_{i:02d}",
                        base_instance_id=instance_id,
                        execution_mode="epsilon_constraint",
                        per_subproblem_time_limit_seconds=cap,
                        per_run_wall_clock_cap_seconds=cap,
                        fixed_tax_index=0,
                        epsilon_emissions=epsilon,
                    )
                )

    return points
