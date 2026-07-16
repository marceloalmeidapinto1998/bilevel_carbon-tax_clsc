"""Generate-and-verify: retry instance generation until the follower's network-flow relaxation
is actually feasible.

The rest of `data.generator` has no dependency on `src.models`/Gurobi by design (it is pure
sampling/geometry, unit-testable without a license). This module is the one deliberate
exception: `ret_min_frac_r_p_t` (mandatory minimum return collection) is a hard lower bound on
the recovered-product flow network, sampled independently per (retailer, product, period) with
no awareness of the random network topology's routing capacity. For some seeds, several
retailers can land near-simultaneously tight in the same period purely by chance, producing a
network-flow infeasibility that no purely-local parameter check (e.g.
`InstanceData._validate_capacity_feasibility`, which is explicitly a necessary-not-sufficient
check) can catch a priori -- confirmed via Gurobi IIS on STD_I17_M8_T6/STD_I25_M8_T3,
2026-06-26. Damping the min/max ratio (`tautenhain_data.RETURN_MIN_RATE_DAMPING`) reduces how
often this happens but cannot guarantee it never does, since the actual bottleneck is the
random hub-routing graph, not the ratio.

This reuses the exact same feasibility check the real solver performs first (the DBP
relaxation's initial follower-network solve) rather than approximating it with a separate LP,
so "feasible here" guarantees "feasible in the real solve" by construction.
"""
from __future__ import annotations

import dataclasses

from .config import GeneratorConfig
from .instance import generate_instance
from .models import GeneratedInstance

FEASIBILITY_CHECK_TIME_LIMIT_SECONDS = 60.0


def _is_relaxation_feasible(instance: GeneratedInstance) -> bool:
    from gurobipy import GRB

    from src.models.instance import InstanceData
    from src.models.subproblems import build_dbp_relaxation_master

    instance_data = InstanceData.from_dict(instance.to_dict())
    master = build_dbp_relaxation_master(instance_data)
    model = master.artifacts.model
    model.Params.OutputFlag = 0
    model.Params.TimeLimit = FEASIBILITY_CHECK_TIME_LIMIT_SECONDS
    model.optimize()
    return model.Status == GRB.OPTIMAL


def generate_feasible_instance(
    config: GeneratorConfig,
    *,
    max_attempts: int = 5,
    seed_stride: int = 1,
) -> GeneratedInstance:
    """`generate_instance`, retried with a perturbed seed until the initial DBP relaxation
    (the real solver's own first feasibility check) is satisfied.

    Raises RuntimeError after `max_attempts` if no seed in the tried range is feasible --
    at that point the issue is more likely structural (e.g. a generator/config combination that
    is infeasible for whole classes of seeds) than a one-off unlucky draw, and should be
    investigated rather than retried further.
    """
    attempt_config = config
    attempted_seeds: list[int] = []
    for attempt in range(max_attempts):
        attempted_seeds.append(attempt_config.seed)
        candidate = generate_instance(attempt_config)
        if _is_relaxation_feasible(candidate):
            return candidate
        attempt_config = dataclasses.replace(attempt_config, seed=attempt_config.seed + seed_stride)

    raise RuntimeError(
        f"No feasible instance found for {config.instance_name!r} after {max_attempts} attempts "
        f"(seeds tried: {attempted_seeds}). The initial DBP relaxation was infeasible for every "
        "seed tried; this looks structural rather than an unlucky draw -- investigate the "
        "config (entity counts, periods, return-rate range) rather than retrying further."
    )
