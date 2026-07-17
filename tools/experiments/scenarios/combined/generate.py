from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.generator import GeneratedInstance, write_instance
from clsc.models.instance import InstanceData
from tools.experiments.scenarios.common.paths import BASE_INSTANCE_DIR, SCENARIO_INSTANCE_DIR
from tools.experiments.scenarios.technology.generate import (
    _append_production_technologies,
    _append_remanufacturing_technologies,
    _update_metadata as _update_tech_metadata,
    _reject_existing_added_technologies,
    PRODUCTION_PROFILES,
    REMANUFACTURING_PROFILES,
)
from tools.experiments.scenarios.transport.generate import (
    _append_transport_modes,
    _update_metadata as _update_trans_metadata,
    _reject_existing_added_modes,
    TRANSPORT_PROFILES,
)


DEFAULT_SCENARIO_NAME = "tech_trans"
DEFAULT_SOURCE_DIR = BASE_INSTANCE_DIR
DEFAULT_OUTPUT_DIR = SCENARIO_INSTANCE_DIR / DEFAULT_SCENARIO_NAME


def _tech_trans_instance_name(source_name: str, sets: dict[str, Any]) -> str:
    return (
        f"{source_name}"
        f"_G{len(sets['G'])}"
        f"_L{len(sets['L'])}"
        f"_TM{len(sets['M'])}"
    )


def create_tech_trans_scenario_instance(
    payload: dict[str, Any],
    *,
    scenario_name: str = DEFAULT_SCENARIO_NAME,
) -> GeneratedInstance:
    """Apply both technology expansion and transport expansion to a base instance.

    The two expansions target disjoint parameter sets so they compose without conflict:
    - Tech expansion modifies G, L, bar_p_g, c_prod_g, e_prod_g, a_in_u_p_g,
      bar_q_l, c_rem_l, e_rem_l, i_prod_g, i_rem_l, pcmin_g, pcmin_l.
    - Transport expansion modifies M, M_RD, M_A, M_S, bar_X_m, c_ship_m, f_mode_m,
      c_handle_m, e_ship_m, road_return_factor_m, speed_km_h_m, trip_big_m_m, ctmin_m,
      ccamax_m, c_trip_m.
    """
    import copy
    scenario_payload = copy.deepcopy(payload)
    source_name = str(scenario_payload["name"])
    sets = scenario_payload["sets"]
    params = scenario_payload["parameters"]
    metadata = scenario_payload["metadata"]

    products = list(sets["P"])
    raw_materials = list(sets["U"])
    source_production_technologies = list(sets["G"])
    source_remanufacturing_technologies = list(sets["L"])
    source_modes_by_family = {
        "truck": list(sets["M_RD"]),
        "air":   list(sets["M_A"]),
        "sea":   list(sets["M_S"]),
    }
    source_all_modes = list(sets["M"])

    # Guard: reject if either expansion's added entities already present
    _reject_existing_added_technologies(
        source_production_technologies, source_remanufacturing_technologies
    )
    _reject_existing_added_modes(source_all_modes)

    # --- Step 1: apply technology expansion ---
    _append_production_technologies(
        sets=sets,
        params=params,
        products=products,
        raw_materials=raw_materials,
        existing_technologies=source_production_technologies,
    )
    _append_remanufacturing_technologies(
        sets=sets,
        params=params,
        products=products,
        existing_technologies=source_remanufacturing_technologies,
    )

    # --- Step 2: apply transport expansion ---
    _append_transport_modes(
        sets=sets,
        params=params,
        metadata=metadata,
        source_modes_by_family=source_modes_by_family,
    )

    # --- Update metadata (joint technology + transport record) ---
    instance_name = _tech_trans_instance_name(source_name, sets)
    from datetime import datetime, timezone
    import copy as _copy
    source_benchmark = _copy.deepcopy(metadata.get("benchmark", {}))
    metadata["benchmark"] = {
        "kind": "scenario",
        "scenario": scenario_name,
        "source": source_benchmark,
    }
    metadata.setdefault("config", {})["instance_name"] = instance_name
    metadata.setdefault("config", {})["production_technologies"] = len(sets["G"])
    metadata.setdefault("config", {})["remanufacturing_technologies"] = len(sets["L"])
    metadata.setdefault("config", {})["trucks"] = len(sets["M_RD"])
    metadata.setdefault("config", {})["airplanes"] = len(sets["M_A"])
    metadata.setdefault("config", {})["boats"] = len(sets["M_S"])
    metadata["scenario"] = {
        "name": scenario_name,
        "source_instance": source_name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "description": (
            "Technology + transport scenario: technology expansion (G6/L6) "
            "plus transport mode expansion (TM12) applied jointly."
        ),
        "added_technologies": {
            "production": [p.technology for p in PRODUCTION_PROFILES],
            "remanufacturing": [p.technology for p in REMANUFACTURING_PROFILES],
        },
        "added_transport_modes": {
            "road": [p.mode for p in TRANSPORT_PROFILES if p.family == "truck"],
            "air":  [p.mode for p in TRANSPORT_PROFILES if p.family == "air"],
            "sea":  [p.mode for p in TRANSPORT_PROFILES if p.family == "sea"],
        },
    }

    result = GeneratedInstance(
        name=instance_name,
        metadata=metadata,
        sets=sets,
        parameters=params,
    )
    InstanceData.from_dict(result.to_dict())
    return result


def create_tech_trans_scenario(
    source_dir: str | Path = DEFAULT_SOURCE_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    pattern: str = "*.json",
    scenario_name: str = DEFAULT_SCENARIO_NAME,
    overwrite: bool = False,
) -> list[Path]:
    source_root = Path(source_dir)
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    if not source_root.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source_root}")

    source_paths = sorted(p for p in source_root.glob(pattern) if p.is_file())
    if not source_paths:
        raise FileNotFoundError(f"No source instance files matching {pattern!r} under {source_root}")

    written_paths: list[Path] = []
    for source_path in source_paths:
        InstanceData.from_file(source_path)
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        scenario = create_tech_trans_scenario_instance(payload, scenario_name=scenario_name)
        destination = output_root / f"{scenario.name}.json"
        if destination.exists() and not overwrite:
            raise FileExistsError(f"Technology + transport scenario file already exists: {destination}")
        written_paths.append(write_instance(scenario, destination))
    return written_paths


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create technology + transport scenario instances by applying both technology expansion "
            "(G6/L6) and transport mode expansion (TM12) to base instances. "
            "Completes the 2x2 factorial design: base / tech / trans / tech_trans."
        ),
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
        help="Directory where technology + transport scenario JSON files are written.",
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    written_paths = create_tech_trans_scenario(
        args.source_dir,
        args.output_dir,
        pattern=args.pattern,
        scenario_name=args.scenario_name,
        overwrite=args.overwrite,
    )
    print(f"Wrote {len(written_paths)} technology + transport scenario instance(s) under {Path(args.output_dir)}")
    for p in written_paths:
        print(f"  {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
