"""Hand-verifiable toy instances for Experiment 1 (docs/Experimental_Plan.md §11.1, H1.2).

Six deliberately tiny instances (1-2 products, 1-2 periods, one node per echelon) whose optimal
network configuration a reader can re-derive on paper. Built directly from a minimal
`BenchmarkSpec` through the same validated generator path as the base set, then written under the
campaign instance tree by `materialize_toy`.
"""
from __future__ import annotations

from pathlib import Path

from clsc.generator import BenchmarkSpec, GeneratedInstance, write_instance
from clsc.generator.benchmark import apply_prefix_override, _set_base_metadata
from clsc.generator.feasibility import generate_feasible_instance
from clsc.models.instance import InstanceData


def _toy_spec(suffix: str, *, products: int, raw_materials: int, periods: int, retailers: int,
              seed: int) -> BenchmarkSpec:
    return BenchmarkSpec(
        prefix="STD", suffix=suffix,
        suppliers=1, factories=1, warehouses=1, retailers=retailers, airports=1, seaports=1,
        raw_materials=raw_materials, products=products,
        production_technologies=1, remanufacturing_technologies=1,
        periods=periods, seed=seed,
    )


# Increasing size across the six toys, all small enough to check by hand.
TOY_SPECS: tuple[BenchmarkSpec, ...] = (
    _toy_spec("TOY1", products=1, raw_materials=1, periods=1, retailers=1, seed=0),
    _toy_spec("TOY2", products=1, raw_materials=1, periods=2, retailers=1, seed=1),
    _toy_spec("TOY3", products=1, raw_materials=2, periods=1, retailers=2, seed=2),
    _toy_spec("TOY4", products=2, raw_materials=2, periods=1, retailers=1, seed=3),
    _toy_spec("TOY5", products=2, raw_materials=2, periods=2, retailers=1, seed=4),
    _toy_spec("TOY6", products=2, raw_materials=2, periods=2, retailers=2, seed=5),
)

TOY_SPECS_BY_NAME = {spec.name: spec for spec in TOY_SPECS}


def build_toy_instance(spec: BenchmarkSpec) -> GeneratedInstance:
    generated = generate_feasible_instance(spec.to_config())
    instance = apply_prefix_override(generated, spec.prefix)
    _set_base_metadata(instance, spec)
    return instance


def materialize_toy(point, *, output_root: Path) -> Path:
    """Build the toy instance named by `point.base_instance_id` and write it under the campaign
    instance tree (mirrors clsc.campaign.instances.materialize for the non-toy path)."""
    spec = TOY_SPECS_BY_NAME.get(point.base_instance_id)
    if spec is None:
        raise ValueError(
            f"{point.design_point_id}: unknown toy instance {point.base_instance_id!r} "
            f"(known: {sorted(TOY_SPECS_BY_NAME)})"
        )
    instance = build_toy_instance(spec)
    payload = instance.to_dict()
    instance_name = f"{point.base_instance_id}__{point.experiment_id}_{point.run_code}"
    payload["metadata"].setdefault("config", {})["instance_name"] = instance_name
    payload["metadata"]["campaign"] = {
        "campaign_id": "campaign_01",
        "experiment_id": point.experiment_id,
        "design_point_id": point.design_point_id,
        "base_instance_id": point.base_instance_id,
        "toy": True,
    }
    rebuilt = GeneratedInstance(
        name=instance_name, metadata=payload["metadata"],
        sets=payload["sets"], parameters=payload["parameters"],
    )
    InstanceData.from_dict(rebuilt.to_dict())  # validate before writing

    dest = output_root / point.experiment_id / point.base_instance_id / f"{point.run_code}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    return write_instance(rebuilt, dest)
