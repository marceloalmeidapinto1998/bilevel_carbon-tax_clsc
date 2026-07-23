"""Materialize one design point's instance JSON under data/instances/campaigns/campaign_01/.

Pipeline: (optionally regenerate at a different seed) -> apply continuous factor multipliers
-> apply the Experiment-7 valuation rescale -> apply structural (menu) levels -> validate -> write.
Toy instances (Experiment 1) are built by `clsc.campaign.toy`, not here.
"""
from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

from clsc.generator import GeneratedInstance, write_instance
from clsc.generator.benchmark import apply_prefix_override, build_base_benchmark_specs, _set_base_metadata
from clsc.generator.feasibility import generate_feasible_instance
from clsc.models.instance import InstanceData

from clsc.campaign.designs._common import DesignPoint
from clsc.campaign.structural import apply_structural_levels
from clsc.campaign.factors import apply_levels
from clsc.campaign.valuation import apply_valuation_ratio

# Authoritative base set.
BASE_DIR = Path("data/instances/base")

# Offset added to the spec's deterministic base seed for each extra-seed run. Large and prime-ish
# to avoid colliding with any seed_base sweep elsewhere.
SEED_OFFSET_STRIDE = 104729


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _has_structural_expansion(point: DesignPoint) -> bool:
    return any(
        getattr(point, name) != "base"
        for name in (
            "production_technology_menu",
            "remanufacturing_technology_menu",
            "road_menu",
            "sea_menu",
            "air_menu",
        )
    )


def materialize(point: DesignPoint, *, output_root: Path) -> Path:
    if point.is_toy:
        raise ValueError(
            f"{point.design_point_id}: toy instances are built by clsc.campaign.toy, not materialize()"
        )

    payload = copy.deepcopy(_load_base_payload(point.base_instance_id, seed_offset=point.seed_offset))
    params = payload["parameters"]

    if point.factor_levels:
        apply_levels(params, tuple(point.factor_levels.keys()), tuple(point.factor_levels.values()))

    if point.valuation_ratio is not None:
        apply_valuation_ratio(params, point.valuation_ratio)

    if _has_structural_expansion(point):
        payload = apply_structural_levels(
            payload,
            production_technology_menu=point.production_technology_menu,
            remanufacturing_technology_menu=point.remanufacturing_technology_menu,
            road_menu=point.road_menu,
            sea_menu=point.sea_menu,
            air_menu=point.air_menu,
        )

    instance_name = f"{point.base_instance_id}__{point.experiment_id}_{point.run_code}"
    payload["metadata"].setdefault("config", {})["instance_name"] = instance_name
    payload["metadata"]["campaign"] = {
        "campaign_id": "campaign_01",
        "experiment_id": point.experiment_id,
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

    dest = output_root / point.experiment_id / point.base_instance_id / f"{point.run_code}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    return write_instance(instance, dest)
