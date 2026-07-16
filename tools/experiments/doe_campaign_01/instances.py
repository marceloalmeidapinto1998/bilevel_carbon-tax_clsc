"""Materialize one design point's instance JSON under data/instances/campaigns/doe_campaign_01/.

Pipeline: (optionally regenerate at a different seed) -> apply continuous factor multipliers
-> apply structural (technology/transport menu) levels -> validate -> write.
"""
from __future__ import annotations

import copy
import dataclasses
from pathlib import Path

from data.generator import GeneratedInstance, write_instance
from data.generator.benchmark import apply_prefix_override, build_base_benchmark_specs, _set_base_metadata
from data.generator.feasibility import generate_feasible_instance
from src.models.instance import InstanceData

from experiments.designs._common import DesignPoint
from tools.experiments.doe_campaign_01.design.structural import apply_structural_levels, apply_structural_levels_v2
from tools.experiments.doe_campaign_01.factors import apply_levels

BASE_DIR = Path("data/instances/campaigns/doe_campaign_01/base")

# Offset added to the spec's deterministic base seed for each extra-seed run (Family F).
# Large and prime-ish to avoid colliding with seed_base sweeps elsewhere.
SEED_OFFSET_STRIDE = 104729


def _load_base_payload(base_instance_id: str, *, seed_offset: int) -> dict:
    if seed_offset == 0:
        return _read_json(BASE_DIR / f"{base_instance_id}.json")

    suffix = base_instance_id.removeprefix("STD_")
    specs = [s for s in build_base_benchmark_specs(seed_base=0) if s.suffix == suffix]
    if not specs:
        raise ValueError(f"No benchmark spec found for base instance {base_instance_id!r}")
    spec = specs[0]
    reseeded_spec = dataclasses.replace(spec, seed=spec.seed + seed_offset * SEED_OFFSET_STRIDE)
    generated = generate_feasible_instance(reseeded_spec.to_config())
    benchmark_instance = apply_prefix_override(generated, reseeded_spec.prefix)
    _set_base_metadata(benchmark_instance, reseeded_spec)
    return benchmark_instance.to_dict()


def _read_json(path: Path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def materialize(point: DesignPoint, *, output_root: Path) -> Path:
    payload = _load_base_payload(point.base_instance_id, seed_offset=point.seed_offset)
    payload = copy.deepcopy(payload)

    params = payload["parameters"]
    if point.factor_levels:
        apply_levels(params, tuple(point.factor_levels.keys()), tuple(point.factor_levels.values()))

    if point.technology_menu != "base" or point.transport_menu != "base":
        payload = apply_structural_levels(
            payload, technology_menu=point.technology_menu, transport_menu=point.transport_menu,
        )

    if (
        point.production_technology_menu != "base"
        or point.remanufacturing_technology_menu != "base"
        or point.road_menu != "base"
        or point.sea_menu != "base"
        or point.air_menu != "base"
    ):
        payload = apply_structural_levels_v2(
            payload,
            production_technology_menu=point.production_technology_menu,
            remanufacturing_technology_menu=point.remanufacturing_technology_menu,
            road_menu=point.road_menu,
            sea_menu=point.sea_menu,
            air_menu=point.air_menu,
        )

    instance_name = f"{point.base_instance_id}__{point.family_id}_{point.run_code}"
    payload["metadata"].setdefault("config", {})["instance_name"] = instance_name
    payload["metadata"]["campaign"] = {
        "family_id": point.family_id,
        "design_point_id": point.design_point_id,
        "base_instance_id": point.base_instance_id,
    }

    instance = GeneratedInstance(
        name=instance_name,
        metadata=payload["metadata"],
        sets=payload["sets"],
        parameters=payload["parameters"],
    )
    InstanceData.from_dict(instance.to_dict())  # validate before writing

    dest = output_root / point.family_id / point.base_instance_id / f"{point.run_code}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    return write_instance(instance, dest)
