"""Family D - Scenario analysis (RQ4, RQ6).

Nine named, internally-consistent scenarios (each a coherent "world" of factor levels), evaluated
at two tax regimes -- `tax_index=0` (`execution_mode="fixed_tax"`, unregulated) and the scenario's
own bilevel-optimal tax (`execution_mode="bilevel"`, full leader-follower solve) -- so each
scenario shows both the unregulated network and what the tax changes. This is the standard
scenario-analysis convention in carbon-policy supply-chain design (Benjaafar, Li & Daskin, 2013;
Fahimnia et al., 2013). See EXPERIMENTAL_PLAN.md §4-D for the full scenario table.

A factor absent from a scenario's definition below is held at its baseline (1.0 for continuous
factors, "base" for structural factors) via each `Scenario` field's own default -- a scenario
only states the levels that actually deviate from baseline. `transport_emission_intensity` is
intentionally excluded from scenario factor levels: the transport dimension is carried
structurally here by the road_menu/sea_menu/air_menu factors, not by scaling emission intensity.
"""
from __future__ import annotations

from dataclasses import dataclass

from clsc.campaign.designs._common import DesignPoint

FAMILY_ID = "D"

FAST_INSTANCE = "STD_I17_M4_T3"
LARGE_INSTANCE = "STD_I25_M8_T6"
LARGE_INSTANCE_SCENARIOS: frozenset[str] = frozenset({"S0", "S7", "S8"})

# Two-tier time-limit scheme, see EXPERIMENTAL_PLAN.md §3.
STANDARD_SUBPROBLEM_SECONDS = 3600.0
STANDARD_WALL_CLOCK_SECONDS = 28800.0
HARD_SUBPROBLEM_SECONDS = 10800.0
HARD_WALL_CLOCK_SECONDS = 50400.0


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    name: str
    demand: float = 1.0
    return_availability: float = 1.0
    emission_intensity: float = 1.0
    scope3_emissions: float = 1.0
    capacity: float = 1.0
    return_economics: float = 1.0
    raw_material_cost: float = 1.0
    production_technology_menu: str = "base"
    remanufacturing_technology_menu: str = "base"
    road_menu: str = "base"
    sea_menu: str = "base"
    air_menu: str = "base"

    def factor_levels(self) -> dict[str, float]:
        return {
            "demand": self.demand,
            "return_availability": self.return_availability,
            "emission_intensity": self.emission_intensity,
            "scope3_emissions": self.scope3_emissions,
            "capacity": self.capacity,
            "return_economics": self.return_economics,
            "raw_material_cost": self.raw_material_cost,
        }


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("S0", "Nominal"),
    Scenario(
        "S1", "Green transition", emission_intensity=0.5, scope3_emissions=0.5,
        production_technology_menu="expanded", road_menu="expanded", sea_menu="expanded",
    ),
    Scenario(
        "S2", "Circular economy", return_availability=1.5, return_economics=0.5,
        remanufacturing_technology_menu="expanded",
    ),
    Scenario("S3", "Demand boom", demand=1.3, capacity=1.3),
    Scenario("S4", "Returns crisis", return_availability=0.5, return_economics=1.5),
    Scenario("S5", "Dirty chain", emission_intensity=1.5, scope3_emissions=1.5),
    Scenario("S6", "Clean suppliers", scope3_emissions=0.5, raw_material_cost=0.7),
    Scenario(
        "S7", "Pessimistic", demand=0.7, return_availability=0.5, emission_intensity=1.5,
        scope3_emissions=1.5, capacity=0.7, return_economics=1.5, raw_material_cost=1.3,
    ),
    Scenario(
        "S8", "Optimistic", demand=1.3, return_availability=1.5, emission_intensity=0.5,
        scope3_emissions=0.5, capacity=1.3, return_economics=0.5, raw_material_cost=0.8,
        production_technology_menu="expanded", remanufacturing_technology_menu="expanded",
        road_menu="expanded", sea_menu="expanded", air_menu="expanded",
    ),
)


def build_design_matrix() -> list[DesignPoint]:
    points: list[DesignPoint] = []
    index = 0

    for scenario in SCENARIOS:
        instances = [FAST_INSTANCE]
        if scenario.scenario_id in LARGE_INSTANCE_SCENARIOS:
            instances.append(LARGE_INSTANCE)

        for instance_id in instances:
            is_hard = instance_id == LARGE_INSTANCE
            subproblem_cap = HARD_SUBPROBLEM_SECONDS if is_hard else STANDARD_SUBPROBLEM_SECONDS
            wall_clock_cap = HARD_WALL_CLOCK_SECONDS if is_hard else STANDARD_WALL_CLOCK_SECONDS

            index += 1
            points.append(
                DesignPoint(
                    family_id=FAMILY_ID,
                    design_point_id=f"D-{index:02d}",
                    run_code=f"{scenario.scenario_id}_tau00",
                    base_instance_id=instance_id,
                    execution_mode="fixed_tax",
                    per_subproblem_time_limit_seconds=subproblem_cap,
                    per_run_wall_clock_cap_seconds=wall_clock_cap,
                    factor_levels=scenario.factor_levels(),
                    production_technology_menu=scenario.production_technology_menu,
                    remanufacturing_technology_menu=scenario.remanufacturing_technology_menu,
                    road_menu=scenario.road_menu,
                    sea_menu=scenario.sea_menu,
                    air_menu=scenario.air_menu,
                    fixed_tax_index=0,
                    notes=f"{scenario.name} (unregulated)",
                )
            )

            index += 1
            points.append(
                DesignPoint(
                    family_id=FAMILY_ID,
                    design_point_id=f"D-{index:02d}",
                    run_code=f"{scenario.scenario_id}_bilevel",
                    base_instance_id=instance_id,
                    execution_mode="bilevel",
                    per_subproblem_time_limit_seconds=subproblem_cap,
                    per_run_wall_clock_cap_seconds=wall_clock_cap,
                    factor_levels=scenario.factor_levels(),
                    production_technology_menu=scenario.production_technology_menu,
                    remanufacturing_technology_menu=scenario.remanufacturing_technology_menu,
                    road_menu=scenario.road_menu,
                    sea_menu=scenario.sea_menu,
                    air_menu=scenario.air_menu,
                    notes=f"{scenario.name} (bilevel-optimal tax)",
                )
            )

    return points
