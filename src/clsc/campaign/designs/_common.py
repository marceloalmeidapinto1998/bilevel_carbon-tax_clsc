"""Shared row schema for all experiment design-matrix builders (campaign_01).

`DesignPoint` is the design-time subset of the full run-metadata schema; the remaining fields
(objective values, runtime, censored, ...) are filled in by the orchestrator after a run
completes and live in the per-run `campaign_manifest.json`, not the design matrix.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from clsc.config.tax_scale import TAX_SCALE_FACTOR

# Algorithm variants for Experiment 2 (computational performance / ablation). M0 is the full DBP
# reference; A1/A5 are claim-carrying and efficiency-only respectively (A1 changes the certified
# guarantee; A5 is the one efficiency-only variant with a measured effect in the prior campaign).
# A4 (coarse tax resolution) was dropped from the design matrix. There is no longer a second, pre-named
# grid constant for it to point to -- the project has exactly one (TAX_SCALE_FACTOR); a
# rescheduled A4 would pick its own coarser step explicitly via InstanceData.with_tax_grid_step().
# See docs/Experimental_Plan.md §2 and the orchestrator's flag mapping.
ALGORITHM_VARIANTS = ("full", "no_tax_confirmation", "no_emissions_cap")

# Execution modes understood by the orchestrator.
EXECUTION_MODES = ("bilevel", "fixed_tax", "min_emissions", "epsilon_constraint")

# --- Carbon-tax resolution -------------------------------------------------------------------------
# The project's one tax resolution: TAX_SCALE_FACTOR (clsc.config.tax_scale), imported above.
# Every base instance is generated at this resolution and every execution mode (bilevel,
# fixed_tax) solves on it -- there is no separate "native" instance grid and
# "campaign" solve grid to keep in sync. That used to be two grids spanning the same real range
# [0, TAX_CEILING_USD_PER_KG] at different resolutions, and mixing them (a tax RATE is comparable
# across grids, a tax INDEX is not) is what once made bilevel tau* and fixed-tax probes silently
# incomparable -- see docs/Experimental_Plan.md and clsc.config.tax_scale's own docstring for why
# 5e-4 (0.5 USD/t, 401 points) is the resolution, not the earlier 1e-4 (2001 points, where the DBP
# loop does not converge).
TAX_CEILING_USD_PER_KG = 0.2
TAX_CEILING_INDEX = round(TAX_CEILING_USD_PER_KG / TAX_SCALE_FACTOR)


def tax_index_for(usd_per_kg: float) -> int:
    """The leader's integer tax_index for a tax rate in USD/kg CO2e."""
    if not 0.0 <= usd_per_kg <= TAX_CEILING_USD_PER_KG:
        raise ValueError(
            f"tax rate {usd_per_kg} USD/kg outside the grid [0, {TAX_CEILING_USD_PER_KG}]"
        )
    return round(usd_per_kg / TAX_SCALE_FACTOR)


@dataclass(frozen=True, slots=True)
class DesignPoint:
    experiment_id: str                                # "exp1".."exp4"
    design_point_id: str
    run_code: str
    base_instance_id: str
    execution_mode: str                               # one of EXECUTION_MODES
    per_subproblem_time_limit_seconds: float
    # None = no cap on the whole run, as in Soares et al. (2021): a run ends on its own stopping
    # criteria (gap, tax confirmation, or 10 iterations without a bound update).
    per_run_wall_clock_cap_seconds: float | None = None
    # --- instance-variant knobs ---
    factor_levels: dict[str, float] = field(default_factory=dict)
    seed_offset: int = 0                              # 0 = base instance's own seed
    valuation_ratio: float | None = None              # Exp3 only: emissions-valuation rescale
    is_toy: bool = False                              # Exp1 only: reduced-dimension toy instance
    # structural menu expansions (5-way split; each independent)
    production_technology_menu: str = "base"
    remanufacturing_technology_menu: str = "base"
    road_menu: str = "base"
    sea_menu: str = "base"
    air_menu: str = "base"
    # --- solver knobs ---
    algorithm_variant: str = "full"                     # Exp3: selects DBP ablation flags
    tax_index: int | None = None                # fixed_tax mode
    epsilon_emissions: float | None = None            # epsilon_constraint mode
    invariant_tax_indices: tuple[int, ...] = ()       # Exp1 structural-invariant probe points
    gurobi_seed: int | None = None                    # Exp1/Exp2 seed-invariance / noise probes
    mip_gap: float | None = None                      # None = campaign default
    dbp_relative_gap: float | None = None
    scale_factor: float | None = None                 # None = campaign fine grid
    threads: int | None = None
    mip_focus: int | None = None
    notes: str = ""

    def to_row(self) -> dict[str, Any]:
        row = {
            "experiment_id": self.experiment_id,
            "design_point_id": self.design_point_id,
            "run_code": self.run_code,
            "base_instance_id": self.base_instance_id,
            "execution_mode": self.execution_mode,
            "algorithm_variant": self.algorithm_variant,
            "per_subproblem_time_limit_seconds": self.per_subproblem_time_limit_seconds,
            "per_run_wall_clock_cap_seconds": self.per_run_wall_clock_cap_seconds,
            "production_technology_menu": self.production_technology_menu,
            "remanufacturing_technology_menu": self.remanufacturing_technology_menu,
            "road_menu": self.road_menu,
            "sea_menu": self.sea_menu,
            "air_menu": self.air_menu,
            "seed_offset": self.seed_offset,
            "valuation_ratio": self.valuation_ratio,
            "is_toy": self.is_toy,
            "tax_index": self.tax_index,
            "epsilon_emissions": self.epsilon_emissions,
            "invariant_tax_indices": ";".join(str(i) for i in self.invariant_tax_indices),
            "gurobi_seed": self.gurobi_seed,
            "mip_gap": self.mip_gap,
            "dbp_relative_gap": self.dbp_relative_gap,
            "scale_factor": self.scale_factor,
            "threads": self.threads,
            "mip_focus": self.mip_focus,
            "notes": self.notes,
        }
        for factor_name, level in sorted(self.factor_levels.items()):
            row[f"factor__{factor_name}"] = level
        return row


def rows_to_csv_dicts(points: list[DesignPoint]) -> list[dict[str, Any]]:
    """Flatten to a uniform column set (union of all rows' keys)."""
    rows = [point.to_row() for point in points]
    all_keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                all_keys.append(key)
    return [{key: row.get(key, "") for key in all_keys} for row in rows]
