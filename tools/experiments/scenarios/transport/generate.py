from __future__ import annotations

import argparse
import copy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
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


DEFAULT_SCENARIO_NAME = "trans"
DEFAULT_SOURCE_DIR = BASE_INSTANCE_DIR
DEFAULT_OUTPUT_DIR = SCENARIO_INSTANCE_DIR / DEFAULT_SCENARIO_NAME


@dataclass(frozen=True, slots=True)
class TransportModeProfile:
    mode: str
    family: str
    set_name: str
    label: str
    description: str
    capacity_factor: float
    fixed_cost_factor: float
    variable_cost_factor: float
    handling_cost_factor: float
    emission_reference: str
    emission_factor: float


TRANSPORT_PROFILES = (
    TransportModeProfile(
        mode="mrd3",
        family="truck",
        set_name="M_RD",
        label="clean_high_capacity_road",
        description="Higher-capacity road transport with lower emissions and higher fixed and variable cost.",
        capacity_factor=1.25,
        fixed_cost_factor=1.20,
        variable_cost_factor=1.10,
        handling_cost_factor=1.00,
        emission_reference="min",
        emission_factor=0.70,
    ),
    TransportModeProfile(
        mode="mrd4",
        family="truck",
        set_name="M_RD",
        label="low_cost_conventional_road",
        description="Lower-cost road transport with higher emissions and slightly lower capacity.",
        capacity_factor=0.95,
        fixed_cost_factor=0.80,
        variable_cost_factor=0.80,
        handling_cost_factor=1.00,
        emission_reference="max",
        emission_factor=1.20,
    ),
    TransportModeProfile(
        mode="ma3",
        family="air",
        set_name="M_A",
        label="clean_air_transfer",
        description="Lower-emission air transfer with higher fixed, handling, and variable cost.",
        capacity_factor=1.00,
        fixed_cost_factor=1.20,
        variable_cost_factor=1.10,
        handling_cost_factor=1.15,
        emission_reference="min",
        emission_factor=0.65,
    ),
    TransportModeProfile(
        mode="ma4",
        family="air",
        set_name="M_A",
        label="low_cost_air_transfer",
        description="Lower-cost air transfer with higher emissions.",
        capacity_factor=1.00,
        fixed_cost_factor=0.80,
        variable_cost_factor=0.80,
        handling_cost_factor=0.90,
        emission_reference="max",
        emission_factor=1.25,
    ),
    TransportModeProfile(
        mode="ms3",
        family="sea",
        set_name="M_S",
        label="clean_sea_transfer",
        description="Lower-emission sea transfer with higher fixed, handling, and variable cost.",
        capacity_factor=1.00,
        fixed_cost_factor=1.15,
        variable_cost_factor=1.10,
        handling_cost_factor=1.10,
        emission_reference="min",
        emission_factor=0.70,
    ),
    TransportModeProfile(
        mode="ms4",
        family="sea",
        set_name="M_S",
        label="low_cost_sea_transfer",
        description="Lower-cost sea transfer with higher emissions.",
        capacity_factor=1.00,
        fixed_cost_factor=0.85,
        variable_cost_factor=0.80,
        handling_cost_factor=0.90,
        emission_reference="max",
        emission_factor=1.25,
    ),
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a transport-expansion scenario by appending mrd3-mrd4, ma3-ma4, and ms3-ms4 options.",
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


def create_transport_scenario_instance(
    payload: dict[str, Any],
    *,
    scenario_name: str = DEFAULT_SCENARIO_NAME,
    include_families: frozenset[str] | None = None,
) -> GeneratedInstance:
    """Append the expanded transport-mode profiles to `payload`.

    `include_families` (added for doe_campaign_02's per-family `road_menu`/`sea_menu`/`air_menu`
    structural-factor split, EXPERIMENTAL_PLAN.md §5.2) restricts which mode families ("truck",
    "air", "sea") get expanded. `None` (the default) expands all three, reproducing the original
    (pre-split) behaviour exactly for existing callers (doe_campaign_01's single `transport_menu`
    factor).
    """
    scenario_payload = copy.deepcopy(payload)
    source_name = str(scenario_payload["name"])
    sets = scenario_payload["sets"]
    params = scenario_payload["parameters"]
    metadata = scenario_payload["metadata"]

    source_modes_by_family = {
        "truck": list(sets["M_RD"]),
        "air": list(sets["M_A"]),
        "sea": list(sets["M_S"]),
    }
    source_all_modes = list(sets["M"])
    included_profiles = tuple(
        profile
        for profile in TRANSPORT_PROFILES
        if include_families is None or profile.family in include_families
    )

    _reject_existing_added_modes(source_all_modes, included_profiles)
    _append_transport_modes(
        sets=sets,
        params=params,
        metadata=metadata,
        source_modes_by_family=source_modes_by_family,
        profiles=included_profiles,
    )
    _update_metadata(
        metadata=metadata,
        scenario_name=scenario_name,
        source_instance_name=source_name,
        scenario_instance_name=_transport_instance_name(source_name, sets),
        source_modes_by_family=source_modes_by_family,
        included_profiles=included_profiles,
    )

    scenario = GeneratedInstance(
        name=_transport_instance_name(source_name, sets),
        metadata=metadata,
        sets=sets,
        parameters=params,
    )
    InstanceData.from_dict(scenario.to_dict())
    return scenario


def create_transport_scenario(
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
        scenario = create_transport_scenario_instance(
            payload,
            scenario_name=scenario_name,
        )
        destination = output_root / f"{scenario.name}.json"
        if destination.exists() and not overwrite:
            raise FileExistsError(f"Scenario file already exists: {destination}")
        written_paths.append(write_instance(scenario, destination))
    return written_paths


def _append_transport_modes(
    *,
    sets: dict[str, Any],
    params: dict[str, Any],
    metadata: dict[str, Any],
    source_modes_by_family: dict[str, list[str]],
    profiles: tuple[TransportModeProfile, ...] = TRANSPORT_PROFILES,
) -> None:
    capacity_map = _require_parameter_map(params, "bar_X_m")
    minimum_capacity_map = _require_parameter_map(params, "ctmin_m")
    contracted_capacity_map = _require_parameter_map(params, "ccamax_m")
    variable_cost_map = _require_parameter_map(params, "c_ship_m")
    trip_cost_map = _require_parameter_map(params, "c_trip_m")
    fixed_cost_map = _require_parameter_map(params, "f_mode_m")
    handling_cost_map = _require_parameter_map(params, "c_handle_m")
    family_map = _require_parameter_map(params, "mode_family_m")
    road_return_factor_map = _require_parameter_map(params, "road_return_factor_m")
    speed_map = _require_parameter_map(params, "speed_km_h_m")
    max_driving_hours_map = _require_parameter_map(params, "max_driving_hours_m")
    trip_big_m_map = _require_parameter_map(params, "trip_big_m_m")
    emission_map = _require_parameter_map(params, "e_ship_m")
    metadata_family_map = metadata.setdefault("transport_mode_family", {})

    for profile in profiles:
        source_modes = source_modes_by_family[profile.family]
        source_capacity = _values_for_keys(capacity_map, source_modes)
        source_variable_cost = _values_for_keys(variable_cost_map, source_modes)
        source_fixed_cost = _values_for_keys(fixed_cost_map, source_modes)
        source_handling_cost = _values_for_keys(handling_cost_map, source_modes)
        source_emissions = _values_for_keys(emission_map, source_modes)

        capacity = _capacity_for_profile(profile, source_capacity)
        variable_cost = round(_mean(source_variable_cost) * profile.variable_cost_factor, 6)
        fixed_cost = round(_mean(source_fixed_cost) * profile.fixed_cost_factor, 2)
        handling_cost = round(_mean(source_handling_cost) * profile.handling_cost_factor, 4)
        emission = round(_reference_value(source_emissions, profile.emission_reference) * profile.emission_factor, 6)

        sets[profile.set_name].append(profile.mode)
        family_map[profile.mode] = profile.family
        metadata_family_map[profile.mode] = profile.family
        capacity_map[profile.mode] = capacity
        minimum_capacity_map[profile.mode] = taut.TRANSPORT_MIN_CAPACITY_KG
        contracted_capacity_map[profile.mode] = 0.0 if profile.family == "truck" else taut.CONTRACTED_CAPACITY_KG
        variable_cost_map[profile.mode] = variable_cost
        trip_cost_map[profile.mode] = round(variable_cost * capacity, 6) if profile.family == "truck" else 0.0
        fixed_cost_map[profile.mode] = fixed_cost
        handling_cost_map[profile.mode] = 0.0 if profile.family == "truck" else handling_cost
        road_return_factor_map[profile.mode] = taut.TRUCK_RETURN_DISTANCE_FACTOR if profile.family == "truck" else 1.0
        speed_map[profile.mode] = taut.TRUCK_SPEED_KM_H if profile.family == "truck" else 0.0
        max_driving_hours_map[profile.mode] = taut.MAX_DRIVING_HOURS_PER_PERIOD if profile.family == "truck" else 0.0
        trip_big_m_map[profile.mode] = max(1, math.ceil(taut.MAX_ENTITY_FLOW_KG / capacity) + 1)
        emission_map[profile.mode] = emission

    sets["M"] = [*sets["M_RD"], *sets["M_A"], *sets["M_S"]]


def _update_metadata(
    *,
    metadata: dict[str, Any],
    scenario_name: str,
    source_instance_name: str,
    scenario_instance_name: str,
    source_modes_by_family: dict[str, list[str]],
    included_profiles: tuple[TransportModeProfile, ...] = TRANSPORT_PROFILES,
) -> None:
    added_modes_by_family = {
        "truck": [profile.mode for profile in included_profiles if profile.family == "truck"],
        "air": [profile.mode for profile in included_profiles if profile.family == "air"],
        "sea": [profile.mode for profile in included_profiles if profile.family == "sea"],
    }

    config = metadata.setdefault("config", {})
    config["instance_name"] = scenario_instance_name
    config["trucks"] = len(source_modes_by_family["truck"]) + len(added_modes_by_family["truck"])
    config["airplanes"] = len(source_modes_by_family["air"]) + len(added_modes_by_family["air"])
    config["boats"] = len(source_modes_by_family["sea"]) + len(added_modes_by_family["sea"])

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
        "source_transport_modes": {
            "road": source_modes_by_family["truck"],
            "air": source_modes_by_family["air"],
            "sea": source_modes_by_family["sea"],
        },
        "added_transport_modes": {
            "road": added_modes_by_family["truck"],
            "air": added_modes_by_family["air"],
            "sea": added_modes_by_family["sea"],
        },
        "mode_rule": "Each added mode belongs to its family-specific transport set and is available on arcs requiring that family.",
        "transport_profiles": [asdict(profile) for profile in included_profiles],
    }


def _transport_instance_name(source_name: str, sets: dict[str, Any]) -> str:
    return f"{source_name}_TM{len(sets['M'])}"


def _reject_existing_added_modes(
    source_modes: list[str],
    profiles: tuple[TransportModeProfile, ...] = TRANSPORT_PROFILES,
) -> None:
    # Only the profiles being added in THIS call are checked -- not the whole TRANSPORT_PROFILES set.
    # Under doe_campaign_02's per-family split, road/sea/air menus are expanded via separate
    # sequential calls (apply_structural_levels_v2); after the road call the instance already
    # contains mrd3/mrd4, so a full-set check would wrongly reject the subsequent sea/air calls.
    # Scoping to `profiles` (defaulting to the full set for doe_campaign_01's single all-families
    # call) still catches a genuine double-add of the same family.
    existing_modes = set(source_modes)
    duplicate_modes = [profile.mode for profile in profiles if profile.mode in existing_modes]
    if duplicate_modes:
        raise ValueError(f"Source instance already contains scenario transport modes: {duplicate_modes}")


def _capacity_for_profile(profile: TransportModeProfile, source_capacity: list[float]) -> float:
    if profile.family == "truck":
        reference_capacity = max(source_capacity) if profile.capacity_factor >= 1.0 else _mean(source_capacity)
    else:
        reference_capacity = _mean(source_capacity)
    return round(reference_capacity * profile.capacity_factor, 2)


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
        raise ValueError("Expected at least one source transport mode")
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
    written_paths = create_transport_scenario(
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
