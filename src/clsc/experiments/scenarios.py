"""Scenarios of the sensitivity analysis: an instance with one parameter changed, one at a time.

A scenario is a name, a sequence of operations on the instance's parameters and, for the regulator's
weight, an option of the solver. Applied to an instance's JSON payload it gives a new payload, named
``<instance>__<scenario>``, which is written as an instance file of its own and solved like any other.
Each of the six parameters is set to two levels:

q (policy weight)
    The regulator's weight in w = q * E_ref, 1e-5 and 1e-3 (base 1e-4): how much emission the
    regulator accepts to lower the tax. A solver option; the data are unchanged.
production emission intensity (e_prod_g)
    x0.5 and x2, alone: the weight of production against raw materials and remanufacturing.
remanufacturing emission intensity (e_rem_l)
    x0.5 and x2: the environmental advantage of remanufacturing.
returns (rho_r_p_t and the minimum and maximum return fractions)
    x0.5 and x2, capped at 1: how much can be remanufactured.
clean-technology cost (c_prod_g and i_prod_g of each product's lowest-emission technology)
    x0.5 and x2: the price of producing cleanly.
interest rate
    x0.5 and x2 (5% and 20% on the base 10%): it discounts the tax paid but not the emissions, and
    weighs capital against operations.

Scaling every emission factor by the same k is not a scenario: it is the same follower problem at the
tax tau * k, so it only rescales the optimal tax (tau* / k, while the tax range does not bind).

Feasibility is not checked here; a variant the solver cannot solve is reported as a failed job.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from clsc.models.instance_data import InstanceData

SCENARIO_SEPARATOR = "__"
RETURN_FRACTIONS = ("rho_r_p_t", "ret_min_frac_r_p_t", "ret_max_frac_r_p_t")


def _scaled(value: Any, factor: float, cap: float | None) -> Any:
    if isinstance(value, dict):
        return {key: _scaled(inner, factor, cap) for key, inner in value.items()}
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    scaled = float(value) * factor
    return scaled if cap is None else min(scaled, cap)


@dataclass(frozen=True)
class Scale:
    """Multiply every number in the named parameters by ``factor``, capped at ``cap`` if given."""

    parameters: tuple[str, ...]
    factor: float
    cap: float | None = None

    def apply(self, parameters: dict[str, Any], sets: dict[str, Any]) -> dict[str, Any]:
        present = [name for name in self.parameters if name in parameters]
        if not present:
            raise ValueError(f"none of {self.parameters} is in the instance")
        for name in present:
            parameters[name] = _scaled(parameters[name], self.factor, self.cap)
        return {"operation": "scale", "parameters": present, "factor": self.factor, "cap": self.cap}


@dataclass(frozen=True)
class CleanTechnologyCost:
    """Scale c_prod_g and i_prod_g of each product's lowest-emission production technology."""

    factor: float

    def apply(self, parameters: dict[str, Any], sets: dict[str, Any]) -> dict[str, Any]:
        technologies = sets["G"]
        pairs = sets.get("H_prod") or [(product, technology) for product in sets["P"] for technology in technologies]
        by_product: dict[str, list[str]] = {}
        for product, technology in pairs:
            by_product.setdefault(product, []).append(technology)
        cleanest = sorted({min(options, key=lambda g: parameters["e_prod_g"][g]) for options in by_product.values()})
        # The premium of a clean technology: its cost over the cheapest other technology for the same
        # products, minus 1 (negative when it is already the cheapest), before and after the change.
        premiums = {}
        for technology in cleanest:
            others = {g for options in by_product.values() if technology in options for g in options} - {technology}
            before = self._premiums(parameters, technology, others)
            parameters["c_prod_g"][technology] = parameters["c_prod_g"][technology] * self.factor
            parameters["i_prod_g"][technology] = parameters["i_prod_g"][technology] * self.factor
            premiums[technology] = {"before": before, "after": self._premiums(parameters, technology, others)}
        return {"operation": "clean_technology_cost", "technologies": cleanest, "factor": self.factor, "premiums": premiums}

    @staticmethod
    def _premiums(parameters: dict[str, Any], technology: str, others: set[str]) -> dict[str, float | None]:
        def premium(name: str) -> float | None:
            cheapest = min((parameters[name][g] for g in others), default=None)
            return parameters[name][technology] / cheapest - 1.0 if cheapest else None

        return {"variable": premium("c_prod_g"), "investment": premium("i_prod_g")}


Operation = Scale | CleanTechnologyCost


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    # The parameter the scenario varies (for the tornado chart) and its level, as shown.
    parameter: str = ""
    level: str = ""
    operations: tuple[Operation, ...] = ()
    # Options passed to the solver, e.g. the regulator's weight.
    solver_options: dict = field(default_factory=dict)

    @property
    def is_base(self) -> bool:
        return self.name == "base"


def _pair(parameter: str, label: str, low: tuple, high: tuple) -> tuple[Scenario, Scenario]:
    """The two levels of one parameter: (name suffix, level label, operations, solver options)."""
    return tuple(
        Scenario(f"{parameter}_{suffix}", f"{label} {level}", parameter, level, operations, options)
        for suffix, level, operations, options in (low, high)
    )


SCENARIOS: dict[str, Scenario] = {
    scenario.name: scenario
    for scenario in (
        Scenario("base", "the instance as published"),
        *_pair("q", "regulator's weight q =", ("1e-5", "1e-5", (), {"leader_tax_weight_relative": 1e-5}),
               ("1e-3", "1e-3", (), {"leader_tax_weight_relative": 1e-3})),
        *_pair("e_prod", "production emission intensity", ("x0.5", "x0.5", (Scale(("e_prod_g",), 0.5),), {}),
               ("x2", "x2", (Scale(("e_prod_g",), 2.0),), {})),
        *_pair("e_rem", "remanufacturing emission intensity", ("x0.5", "x0.5", (Scale(("e_rem_l",), 0.5),), {}),
               ("x2", "x2", (Scale(("e_rem_l",), 2.0),), {})),
        *_pair("returns", "return fractions", ("x0.5", "x0.5", (Scale(RETURN_FRACTIONS, 0.5, cap=1.0),), {}),
               ("x2", "x2", (Scale(RETURN_FRACTIONS, 2.0, cap=1.0),), {})),
        *_pair("clean_cost", "cost of the cleanest production technology", ("x0.5", "x0.5", (CleanTechnologyCost(0.5),), {}),
               ("x2", "x2", (CleanTechnologyCost(2.0),), {})),
        *_pair("interest", "interest rate", ("x0.5", "x0.5", (Scale(("interest_rate",), 0.5),), {}),
               ("x2", "x2", (Scale(("interest_rate",), 2.0),), {})),
    )
}
SENSITIVITY_SCENARIOS = tuple(name for name in SCENARIOS if name != "base")


def variant_name(instance_name: str, scenario: Scenario) -> str:
    return instance_name if scenario.is_base else f"{instance_name}{SCENARIO_SEPARATOR}{scenario.name}"


def apply_scenario(payload: dict[str, Any], scenario: Scenario) -> dict[str, Any]:
    """A copy of the instance payload with the scenario applied, renamed and with the scenario in its metadata."""
    variant = copy.deepcopy(payload)
    if scenario.is_base:
        return variant
    effects = [operation.apply(variant["parameters"], variant["sets"]) for operation in scenario.operations]
    variant["metadata"]["scenario"] = {
        "name": scenario.name,
        "description": scenario.description,
        "base_instance": payload["name"],
        "operations": effects,
        "solver_options": scenario.solver_options,
    }
    variant["name"] = variant_name(payload["name"], scenario)
    return variant


def write_variant(instance_path: Path, scenario: Scenario, directory: Path) -> Path:
    """The instance file of the scenario: the instance itself for the base scenario, otherwise a new file
    in ``directory`` (a renamed copy when only solver options change), validated by loading it."""
    if scenario.is_base:
        return instance_path
    payload = json.loads(instance_path.read_text(encoding="utf-8"))
    variant = apply_scenario(payload, scenario)
    # Named after the file, as clsc-solve names its results folder.
    variant["name"] = variant_name(instance_path.stem, scenario)
    InstanceData.from_dict(copy.deepcopy(variant))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{variant['name']}.json"
    path.write_text(json.dumps(variant, indent=2), encoding="utf-8")
    return path
