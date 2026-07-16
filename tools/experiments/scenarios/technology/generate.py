from __future__ import annotations

import argparse
import copy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.generator import tautenhain_data as taut
from data.generator import GeneratedInstance, write_instance
from src.models.instance import InstanceData
from tools.experiments.scenarios.common.paths import BASE_INSTANCE_DIR, SCENARIO_INSTANCE_DIR


DEFAULT_SCENARIO_NAME = "tech"
DEFAULT_SOURCE_DIR = BASE_INSTANCE_DIR
DEFAULT_OUTPUT_DIR = SCENARIO_INSTANCE_DIR / DEFAULT_SCENARIO_NAME


@dataclass(frozen=True, slots=True)
class ProductionTechnologyProfile:
    technology: str
    label: str
    description: str
    capacity_factor: float
    install_rate_factor: float
    operating_cost_factor: float
    emission_reference: str
    emission_factor: float
    input_requirement_factor: float


@dataclass(frozen=True, slots=True)
class RemanufacturingTechnologyProfile:
    technology: str
    label: str
    description: str
    capacity_factor: float
    install_rate_factor: float
    operating_cost_factor: float
    emission_reference: str
    emission_factor: float


PRODUCTION_PROFILES = (
    ProductionTechnologyProfile(
        technology="g4",
        label="clean_efficient_production",
        description="Lower material intensity and lower emissions, with higher operating and installation cost.",
        capacity_factor=0.90,
        install_rate_factor=1.35,
        operating_cost_factor=1.25,
        emission_reference="min",
        emission_factor=0.65,
        input_requirement_factor=0.85,
    ),
    ProductionTechnologyProfile(
        technology="g5",
        label="low_cost_conventional_production",
        description="Lower operating and installation cost, with higher material intensity and emissions.",
        capacity_factor=1.20,
        install_rate_factor=0.85,
        operating_cost_factor=0.75,
        emission_reference="max",
        emission_factor=1.20,
        input_requirement_factor=1.10,
    ),
    ProductionTechnologyProfile(
        technology="g6",
        label="high_capacity_balanced_production",
        description="Higher capacity with moderate cost premium and lower-than-average emissions.",
        capacity_factor=1.60,
        install_rate_factor=1.50,
        operating_cost_factor=1.05,
        emission_reference="mean",
        emission_factor=0.85,
        input_requirement_factor=0.95,
    ),
)

REMANUFACTURING_PROFILES = (
    RemanufacturingTechnologyProfile(
        technology="l4",
        label="clean_remanufacturing",
        description="Lower remanufacturing emissions, with higher operating and installation cost.",
        capacity_factor=0.90,
        install_rate_factor=1.30,
        operating_cost_factor=1.20,
        emission_reference="min",
        emission_factor=0.60,
    ),
    RemanufacturingTechnologyProfile(
        technology="l5",
        label="low_cost_remanufacturing",
        description="Lower remanufacturing cost, with higher emissions.",
        capacity_factor=1.20,
        install_rate_factor=0.85,
        operating_cost_factor=0.75,
        emission_reference="max",
        emission_factor=1.20,
    ),
    RemanufacturingTechnologyProfile(
        technology="l6",
        label="high_capacity_remanufacturing",
        description="Higher remanufacturing capacity with moderate cost premium and lower-than-average emissions.",
        capacity_factor=1.60,
        install_rate_factor=1.45,
        operating_cost_factor=1.05,
        emission_reference="mean",
        emission_factor=0.80,
    ),
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a technology-expansion scenario by appending g4-g6 and l4-l6 options to base instances.",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Directory containing source base instance JSON files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where scenario instance JSON files are written.",
    )
    parser.add_argument(
        "--pattern",
        default="*.json",
        help="Glob pattern for source instance files.",
    )
    parser.add_argument(
        "--scenario-name",
        default=DEFAULT_SCENARIO_NAME,
        help="Scenario name recorded in metadata.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing scenario files.",
    )
    return parser.parse_args(argv)


def create_technology_scenario_instance(
    payload: dict[str, Any],
    *,
    scenario_name: str = DEFAULT_SCENARIO_NAME,
    include_production: bool = True,
    include_remanufacturing: bool = True,
) -> GeneratedInstance:
    """Append the expanded technology profiles to `payload`.

    `include_production`/`include_remanufacturing` (added for doe_campaign_02's
    `production_technology_menu`/`remanufacturing_technology_menu` structural-factor split,
    EXPERIMENTAL_PLAN.md §5.2) let a caller expand only one technology type at a time. Both
    default to True, reproducing the original (pre-split) behaviour exactly for existing callers
    (doe_campaign_01's single `technology_menu` factor).
    """
    scenario_payload = copy.deepcopy(payload)
    source_name = str(scenario_payload["name"])
    sets = scenario_payload["sets"]
    params = scenario_payload["parameters"]
    metadata = scenario_payload["metadata"]

    products = list(sets["P"])
    raw_materials = list(sets["U"])
    production_technologies = list(sets["G"])
    remanufacturing_technologies = list(sets["L"])

    _reject_existing_added_technologies(
        production_technologies,
        remanufacturing_technologies,
        check_production=include_production,
        check_remanufacturing=include_remanufacturing,
    )

    if include_production:
        _append_production_technologies(
            sets=sets,
            params=params,
            products=products,
            raw_materials=raw_materials,
            existing_technologies=production_technologies,
        )
    if include_remanufacturing:
        _append_remanufacturing_technologies(
            sets=sets,
            params=params,
            products=products,
            existing_technologies=remanufacturing_technologies,
        )
    _update_metadata(
        metadata=metadata,
        scenario_name=scenario_name,
        source_instance_name=source_name,
        scenario_instance_name=_technology_instance_name(source_name, sets),
        source_production_technologies=production_technologies,
        source_remanufacturing_technologies=remanufacturing_technologies,
        added_production_profiles=PRODUCTION_PROFILES if include_production else (),
        added_remanufacturing_profiles=REMANUFACTURING_PROFILES if include_remanufacturing else (),
    )

    scenario = GeneratedInstance(
        name=_technology_instance_name(source_name, sets),
        metadata=metadata,
        sets=sets,
        parameters=params,
    )
    InstanceData.from_dict(scenario.to_dict())
    return scenario


def create_technology_scenario(
    source_dir: str | Path = DEFAULT_SOURCE_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    pattern: str = "*.json",
    scenario_name: str = DEFAULT_SCENARIO_NAME,
    overwrite: bool = False,
) -> list[Path]:
    source_root = Path(source_dir)
    output_root = Path(output_dir)
    if not source_root.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source_root}")

    source_paths = sorted(path for path in source_root.glob(pattern) if path.is_file())
    if not source_paths:
        raise FileNotFoundError(f"No source instance files matching {pattern!r} under {source_root}")

    written_paths: list[Path] = []
    for source_path in source_paths:
        InstanceData.from_file(source_path)
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        scenario = create_technology_scenario_instance(
            payload,
            scenario_name=scenario_name,
        )
        destination = output_root / f"{scenario.name}.json"
        if destination.exists() and not overwrite:
            raise FileExistsError(f"Scenario file already exists: {destination}")
        written_paths.append(write_instance(scenario, destination))
    return written_paths


def _append_production_technologies(
    *,
    sets: dict[str, Any],
    params: dict[str, Any],
    products: list[str],
    raw_materials: list[str],
    existing_technologies: list[str],
) -> None:
    capacity_map = _require_parameter_map(params, "bar_p_g")
    install_map = _require_parameter_map(params, "i_prod_g")
    cost_map = _require_parameter_map(params, "c_prod_g")
    emission_map = _require_parameter_map(params, "e_prod_g")
    minimum_use_map = _require_parameter_map(params, "pcmin_g")
    input_requirements = _require_parameter_map(params, "a_in_u_p_g")

    max_capacity = max(_values_for_keys(capacity_map, existing_technologies))
    install_rate = _mean(
        [
            float(install_map[technology]) / float(capacity_map[technology])
            for technology in existing_technologies
            if float(capacity_map[technology]) > 0.0
        ]
    )
    mean_cost = _mean(_values_for_keys(cost_map, existing_technologies))
    emissions = _values_for_keys(emission_map, existing_technologies)

    for profile in PRODUCTION_PROFILES:
        capacity = round(max_capacity * profile.capacity_factor, 2)
        sets["G"].append(profile.technology)
        _append_all_product_pairs(sets["H_prod"], products, profile.technology)

        capacity_map[profile.technology] = capacity
        minimum_use_map[profile.technology] = round(taut.TECH_MIN_CAPACITY_FRAC * capacity, 2)
        install_map[profile.technology] = round(install_rate * capacity * profile.install_rate_factor, 2)
        cost_map[profile.technology] = round(mean_cost * profile.operating_cost_factor, 4)
        emission_map[profile.technology] = round(
            _reference_value(emissions, profile.emission_reference) * profile.emission_factor,
            4,
        )
        for material in raw_materials:
            input_requirements.setdefault(material, {})
            for product in products:
                input_requirements[material].setdefault(product, {})
                baseline = _average_compatible_input_requirement(
                    input_requirements,
                    material=material,
                    product=product,
                    existing_technologies=existing_technologies,
                )
                input_requirements[material][product][profile.technology] = round(
                    baseline * profile.input_requirement_factor,
                    4,
                )


def _append_remanufacturing_technologies(
    *,
    sets: dict[str, Any],
    params: dict[str, Any],
    products: list[str],
    existing_technologies: list[str],
) -> None:
    capacity_map = _require_parameter_map(params, "bar_q_l")
    install_map = _require_parameter_map(params, "i_rem_l")
    cost_map = _require_parameter_map(params, "c_rem_l")
    emission_map = _require_parameter_map(params, "e_rem_l")
    minimum_use_map = _require_parameter_map(params, "pcmin_l")

    max_capacity = max(_values_for_keys(capacity_map, existing_technologies))
    install_rate = _mean(
        [
            float(install_map[technology]) / float(capacity_map[technology])
            for technology in existing_technologies
            if float(capacity_map[technology]) > 0.0
        ]
    )
    mean_cost = _mean(_values_for_keys(cost_map, existing_technologies))
    emissions = _values_for_keys(emission_map, existing_technologies)

    for profile in REMANUFACTURING_PROFILES:
        capacity = round(max_capacity * profile.capacity_factor, 2)
        sets["L"].append(profile.technology)
        _append_all_product_pairs(sets["H_rem"], products, profile.technology)

        capacity_map[profile.technology] = capacity
        minimum_use_map[profile.technology] = round(taut.TECH_MIN_CAPACITY_FRAC * capacity, 2)
        install_map[profile.technology] = round(install_rate * capacity * profile.install_rate_factor, 2)
        cost_map[profile.technology] = round(mean_cost * profile.operating_cost_factor, 4)
        emission_map[profile.technology] = round(
            _reference_value(emissions, profile.emission_reference) * profile.emission_factor,
            4,
        )


def _update_metadata(
    *,
    metadata: dict[str, Any],
    scenario_name: str,
    source_instance_name: str,
    scenario_instance_name: str,
    source_production_technologies: list[str],
    source_remanufacturing_technologies: list[str],
    added_production_profiles: tuple[ProductionTechnologyProfile, ...] = PRODUCTION_PROFILES,
    added_remanufacturing_profiles: tuple[RemanufacturingTechnologyProfile, ...] = REMANUFACTURING_PROFILES,
) -> None:
    config = metadata.setdefault("config", {})
    config["instance_name"] = scenario_instance_name
    config["production_technologies"] = len(source_production_technologies) + len(added_production_profiles)
    config["remanufacturing_technologies"] = len(source_remanufacturing_technologies) + len(added_remanufacturing_profiles)

    source_benchmark = copy.deepcopy(metadata.get("benchmark", {}))
    metadata["benchmark"] = {
        "kind": "scenario",
        "scenario": scenario_name,
        "source": source_benchmark,
    }
    metadata["scenario"] = {
        "name": scenario_name,
        "source_instance": source_instance_name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_technologies": {
            "production": source_production_technologies,
            "remanufacturing": source_remanufacturing_technologies,
        },
        "added_technologies": {
            "production": [profile.technology for profile in added_production_profiles],
            "remanufacturing": [profile.technology for profile in added_remanufacturing_profiles],
        },
        "compatibility_rule": "Each added production and remanufacturing technology is compatible with all final products.",
        "production_profiles": [asdict(profile) for profile in added_production_profiles],
        "remanufacturing_profiles": [asdict(profile) for profile in added_remanufacturing_profiles],
    }


def _technology_instance_name(source_name: str, sets: dict[str, Any]) -> str:
    return f"{source_name}_G{len(sets['G'])}_L{len(sets['L'])}"


def _reject_existing_added_technologies(
    production_technologies: list[str],
    remanufacturing_technologies: list[str],
    *,
    check_production: bool = True,
    check_remanufacturing: bool = True,
) -> None:
    # Only the technology types being added in THIS call are checked. Under doe_campaign_02's
    # per-type split, production and remanufacturing menus are expanded via separate sequential
    # calls (apply_structural_levels_v2); after the production call the instance already contains
    # g4/g5/g6, so an unconditional check would wrongly reject the subsequent remanufacturing call.
    # doe_campaign_01's single all-types call leaves both flags True, preserving its behaviour.
    existing_production = set(production_technologies)
    existing_remanufacturing = set(remanufacturing_technologies)
    duplicate_production = (
        [profile.technology for profile in PRODUCTION_PROFILES if profile.technology in existing_production]
        if check_production else []
    )
    duplicate_remanufacturing = (
        [profile.technology for profile in REMANUFACTURING_PROFILES if profile.technology in existing_remanufacturing]
        if check_remanufacturing else []
    )
    if duplicate_production or duplicate_remanufacturing:
        raise ValueError(
            "Source instance already contains scenario technologies: "
            f"production={duplicate_production}, remanufacturing={duplicate_remanufacturing}",
        )


def _append_all_product_pairs(pairs: list[list[str]], products: list[str], technology: str) -> None:
    existing_pairs = {tuple(pair) for pair in pairs}
    for product in products:
        pair = (product, technology)
        if pair not in existing_pairs:
            pairs.append([product, technology])


def _average_compatible_input_requirement(
    input_requirements: dict[str, Any],
    *,
    material: str,
    product: str,
    existing_technologies: list[str],
) -> float:
    product_requirements = input_requirements[material][product]
    positive_values = [
        float(product_requirements[technology])
        for technology in existing_technologies
        if float(product_requirements.get(technology, 0.0)) > 0.0
    ]
    if positive_values:
        return _mean(positive_values)
    return _mean([float(product_requirements.get(technology, 0.0)) for technology in existing_technologies])


def _reference_value(values: list[float], reference: str) -> float:
    if reference == "min":
        return min(values)
    if reference == "max":
        return max(values)
    if reference == "mean":
        return _mean(values)
    raise ValueError(f"Unsupported reference value: {reference}")


def _values_for_keys(mapping: dict[str, Any], keys: list[str]) -> list[float]:
    values = [float(mapping[key]) for key in keys]
    if not values:
        raise ValueError("Expected at least one source technology")
    return values


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("Cannot compute the mean of an empty list")
    return sum(values) / len(values)


def _require_parameter_map(params: dict[str, Any], parameter_name: str) -> dict[str, Any]:
    value = params.get(parameter_name)
    if not isinstance(value, dict):
        raise ValueError(f"Parameter {parameter_name!r} must be a dictionary")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    written_paths = create_technology_scenario(
        args.source_dir,
        args.output_dir,
        pattern=args.pattern,
        scenario_name=args.scenario_name,
        overwrite=args.overwrite,
    )
    print(f"Wrote {len(written_paths)} scenario instance(s) under {Path(args.output_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
