"""Calibrated instances (prefix CAL): the generated instances with the emission factors and return fractions of
the case study of Mota et al. (2018), everything else unchanged.

The generator of Tautenhain et al. (2021) draws the climate-change intensity of production, of
remanufacturing and of every raw material from one range, [102.86, 536.29] kg CO2e per kg: the hull of the
case study's technology values, in which 102.86-134 belong to remanufacturing and 375-536 to production.
Drawn that way, remanufacturing has no environmental advantage, and raw materials that cost cents per unit
carry hundreds of kg CO2e per kg, so the instances emit 37-202 kg CO2e per euro of cost. It also caps the
maximum return fraction at 15%, while remanufacturing a unit takes four to five returned units, so that
remanufacturing stays under 1% of production. A carbon tax acting on such an instance tests the method, not
the closed loop.

A CAL instance keeps the network, the costs, the demand and the capacities of its STD instance and changes
only what the case study pins down, so that the two can be compared instance by instance:

* production intensity drawn from the case study's production technologies, [375, 536] kg CO2e/kg, and
  remanufacturing intensity from its remanufacturing technologies, [103, 134] (Tautenhain et al.'s data
  document, Table 24, the climate-change values of Mota et al.'s technologies);
* no emissions on raw materials bought from suppliers, as in the environmental objective of Mota et al.,
  which has no supplier term: the operator is taxed on its own operations -- production,
  remanufacturing, transport and construction -- as a tax on direct emissions would tax it;
* a maximum return fraction of 1, every unit sold may return, and a minimum return fraction drawn below the
  case study's 15%, as in Mota et al.'s case;
* the case study's cost of acquiring a returned unit, EUR 0.15. The generator draws it as a fraction of the
  selling price, up to tens of euros per unit, so that a remanufactured unit, which takes four to five
  returned units, costs a hundred times a new one.

The emission factors stay large relative to costs, as they are in the case study itself (13.5 kg CO2e per
euro of cost without a tax). Tax levels scale with that intensity: multiplying every emission factor by k
divides every break point of the follower's value function by k and leaves the tax bill, as a share of the
operator's cost, unchanged at each of them.
"""
from __future__ import annotations

import copy
import hashlib
import random
from typing import Any

PRODUCTION_EMISSION_RANGE = (375.0, 536.0)
REMANUFACTURING_EMISSION_RANGE = (103.0, 134.0)
RAW_MATERIAL_EMISSION = 0.0
RETURN_MAX_FRACTION = 1.0
RETURN_MIN_FRACTION_CEILING = 0.15
# EUR per returned unit acquired (Mota et al., 2018, Table 3; clsc.generator.mota2018.RECOVERY_COST).
RECOVERY_COST_PER_UNIT = 0.15

PREFIX = "CAL"


def _rng(name: str, attempt: int) -> random.Random:
    digest = hashlib.sha256(f"{PREFIX}:{name}:{attempt}".encode("utf-8")).hexdigest()
    return random.Random(int(digest[:8], 16))


def calibrate(instance: dict[str, Any], *, attempt: int = 0) -> dict[str, Any]:
    """The CAL version of an STD instance (as a dict). ``attempt`` changes only the draws."""
    calibrated = copy.deepcopy(instance)
    name = instance["name"]
    rng = _rng(name, attempt)
    parameters = calibrated["parameters"]
    parameters["e_prod_g"] = {g: round(rng.uniform(*PRODUCTION_EMISSION_RANGE), 4) for g in parameters["e_prod_g"]}
    parameters["e_rem_l"] = {l: round(rng.uniform(*REMANUFACTURING_EMISSION_RANGE), 4) for l in parameters["e_rem_l"]}
    parameters["e_raw_s_u"] = {s: {u: RAW_MATERIAL_EMISSION for u in materials}
                               for s, materials in parameters["e_raw_s_u"].items()}
    for key in ("ret_max_frac_r_p_t", "rho_r_p_t"):
        parameters[key] = {r: {p: {t: RETURN_MAX_FRACTION for t in periods} for p, periods in products.items()}
                           for r, products in parameters[key].items()}
    parameters["rpc_rp"] = {k: RECOVERY_COST_PER_UNIT for k in parameters["rpc_rp"]}
    parameters["ret_min_frac_r_p_t"] = {
        r: {p: {t: round(rng.uniform(0.0, RETURN_MIN_FRACTION_CEILING), 4) for t in periods}
            for p, periods in products.items()}
        for r, products in parameters["ret_min_frac_r_p_t"].items()
    }
    calibrated["name"] = name.replace("STD_", f"{PREFIX}_", 1) if name.startswith("STD_") else f"{PREFIX}_{name}"
    metadata = calibrated.setdefault("metadata", {})
    metadata.setdefault("config", {})["instance_name"] = calibrated["name"]
    metadata["calibration"] = {
        "from": name, "attempt": attempt,
        "production_emission_range": PRODUCTION_EMISSION_RANGE,
        "remanufacturing_emission_range": REMANUFACTURING_EMISSION_RANGE,
        "raw_material_emission": RAW_MATERIAL_EMISSION,
        "return_max_fraction": RETURN_MAX_FRACTION,
        "return_min_fraction_ceiling": RETURN_MIN_FRACTION_CEILING,
        "recovery_cost_per_unit": RECOVERY_COST_PER_UNIT,
        "source": "Mota et al. (2018) case study; Tautenhain et al. (2021) data document, Table 24",
    }
    return calibrated


def _feasible(instance: dict[str, Any]) -> bool:
    from .feasibility import _is_relaxation_feasible
    from .generated_instance import GeneratedInstance

    return _is_relaxation_feasible(GeneratedInstance(**{key: instance[key] for key in ("name", "metadata", "sets", "parameters")}))


def calibrated_feasible(instance: dict[str, Any], *, max_attempts: int = 5) -> dict[str, Any]:
    """``calibrate``, redrawn until the follower's network admits the minimum returns (the check the
    generator applies to its own instances)."""
    for attempt in range(max_attempts):
        candidate = calibrate(instance, attempt=attempt)
        if _feasible(candidate):
            return candidate
    raise RuntimeError(f"no feasible calibration of {instance['name']} in {max_attempts} attempts")


def write_calibrated_set(output_dir, *, replicates: tuple[int, ...] = (0, 1, 2), escalation_replicates: tuple[int, ...] = (0,)) -> list[str]:
    """Write CAL_<size>_r<k>.json for the twelve standard sizes, replicate k drawn from the generator with
    seed base k, and for the three escalation sizes with ``escalation_replicates``. Replicate 0 is the STD
    instance of the paper's first version."""
    import json
    from pathlib import Path

    from .benchmark import _set_base_metadata, apply_prefix_override, build_base_benchmark_specs, build_escalation_specs
    from .feasibility import generate_feasible_instance

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    written = []
    jobs = [(spec, k) for k in replicates for spec in build_base_benchmark_specs(seed_base=k)]
    jobs += [(spec, k) for k in escalation_replicates for spec in build_escalation_specs(seed_base=k)]
    for spec, replicate in jobs:
        generated = generate_feasible_instance(spec.to_config())
        instance = apply_prefix_override(generated, spec.prefix)
        _set_base_metadata(instance, spec)
        base = instance.to_dict()
        calibrated = calibrated_feasible(base)
        calibrated["name"] = f"{PREFIX}_{spec.suffix}_r{replicate}"
        calibrated["metadata"]["config"]["instance_name"] = calibrated["name"]
        calibrated["metadata"]["calibration"]["replicate"] = replicate
        path = output / f"{calibrated['name']}.json"
        path.write_text(json.dumps(calibrated, indent=2), encoding="utf-8")
        written.append(path.as_posix())
    return written
