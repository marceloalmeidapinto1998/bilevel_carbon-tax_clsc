from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any

from .config import GeneratorConfig
from .models import GeneratedInstance
from .instance import generate_instance, write_instance

PREFIXES = ("STD",)


SIZE_SUFFIXES = (
    "I17_M4_T3",
    "I17_M4_T6",
    "I17_M4_T12",
    "I17_M8_T3",
    "I17_M8_T6",
    "I17_M8_T12",
    "I25_M4_T3",
    "I25_M4_T6",
    "I25_M4_T12",
    "I25_M8_T3",
    "I25_M8_T6",
    "I25_M8_T12",
)


PREFIX_OVERRIDE_DECIMALS: dict[str, dict[str, int]] = {}


SIZE_PATTERN = re.compile(r"^I(?P<entities>\d+)_M(?P<materials>\d+)_T(?P<periods>\d+)$")


@dataclass(frozen=True, slots=True)
class BenchmarkSpec:
    prefix: str
    suffix: str
    suppliers: int
    factories: int
    warehouses: int
    retailers: int
    airports: int
    seaports: int
    raw_materials: int
    products: int
    production_technologies: int
    remanufacturing_technologies: int
    periods: int
    seed: int
    tax_lower: float = 0.0
    tax_upper: float = 0.2

    @property
    def name(self) -> str:
        return f"{self.prefix}_{self.suffix}"

    def to_config(self) -> GeneratorConfig:
        return GeneratorConfig(
            suppliers=self.suppliers,
            factories=self.factories,
            warehouses=self.warehouses,
            retailers=self.retailers,
            airports=self.airports,
            seaports=self.seaports,
            products=self.products,
            raw_materials=self.raw_materials,
            production_technologies=self.production_technologies,
            remanufacturing_technologies=self.remanufacturing_technologies,
            periods=self.periods,
            seed=self.seed,
            instance_name=self.name,
            tax_lower=self.tax_lower,
            tax_upper=self.tax_upper,
        )


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    base_specs: int
    base_instances: int
    output_dir: Path
    file_format: str

    @property
    def total_files(self) -> int:
        return self.base_instances


def entity_split(total_entities: int) -> dict[str, int]:
    suppliers = 3
    factories = 3
    retailers = 4
    airports = 2 if total_entities == 17 else 4
    seaports = 2
    warehouses = total_entities - suppliers - factories - retailers - airports - seaports
    if warehouses <= 0:
        raise ValueError(f"Unsupported entity total {total_entities}: warehouses must remain positive")
    return {
        "suppliers": suppliers,
        "factories": factories,
        "warehouses": warehouses,
        "retailers": retailers,
        "airports": airports,
        "seaports": seaports,
    }


def build_base_benchmark_specs(seed_base: int = 0) -> list[BenchmarkSpec]:
    specs: list[BenchmarkSpec] = []
    material_split = {
        4: {"raw_materials": 2, "products": 1},
        8: {"raw_materials": 4, "products": 2},
    }

    for prefix in PREFIXES:
        for suffix in SIZE_SUFFIXES:
            match = SIZE_PATTERN.fullmatch(suffix)
            if match is None:
                raise ValueError(f"Unsupported benchmark suffix: {suffix}")

            total_entities = int(match.group("entities"))
            materials_code = int(match.group("materials"))
            periods = int(match.group("periods"))
            if materials_code not in material_split:
                raise ValueError(f"Unsupported material code M{materials_code}")

            specs.append(
                BenchmarkSpec(
                    prefix=prefix,
                    suffix=suffix,
                    periods=periods,
                    production_technologies=3,
                    remanufacturing_technologies=3,
                    seed=_deterministic_seed(seed_base, prefix, suffix),
                    **entity_split(total_entities),
                    **material_split[materials_code],
                )
            )

    if len(specs) != len(PREFIXES) * len(SIZE_SUFFIXES):
        raise AssertionError(f"Expected {len(PREFIXES) * len(SIZE_SUFFIXES)} base benchmark specs, got {len(specs)}")
    return specs


def apply_prefix_override(instance: GeneratedInstance, prefix: str) -> GeneratedInstance:
    overridden = _clone_instance(instance)

    if prefix == "STD":
        return overridden
    raise ValueError(f"Unsupported benchmark prefix: {prefix}; only STD instances are generated")


def generate_benchmark(
    output_dir: str | Path,
    *,
    include_base: bool = True,
    seed_base: int = 0,
    file_format: str = "json",
) -> BenchmarkSummary:
    if file_format not in {"json", "yaml"}:
        raise ValueError("file_format must be either 'json' or 'yaml'")

    extension = ".json" if file_format == "json" else ".yaml"
    output_root = Path(output_dir)
    specs = build_base_benchmark_specs(seed_base)

    base_count = 0
    for spec in specs:
        if not include_base:
            continue

        generated = generate_instance(spec.to_config())
        benchmark_instance = apply_prefix_override(generated, spec.prefix)
        _set_base_metadata(benchmark_instance, spec)
        _validate_prefix_override(generated, benchmark_instance, spec.prefix)

        if include_base:
            write_instance(benchmark_instance, output_root / f"{benchmark_instance.name}{extension}")
            base_count += 1

        if spec.prefix != "STD":
            continue

    return BenchmarkSummary(
        base_specs=len(specs),
        base_instances=base_count,
        output_dir=output_root,
        file_format=file_format,
    )


def _clone_instance(instance: GeneratedInstance, name: str | None = None) -> GeneratedInstance:
    cloned = GeneratedInstance(
        name=name or instance.name,
        metadata=copy.deepcopy(instance.metadata),
        sets=copy.deepcopy(instance.sets),
        parameters=copy.deepcopy(instance.parameters),
    )
    cloned.metadata.setdefault("config", {})["instance_name"] = cloned.name
    return cloned


def _deterministic_seed(seed_base: int, prefix: str, suffix: str) -> int:
    seed_material = f"{seed_base}:{prefix}:{suffix}".encode("utf-8")
    digest = hashlib.sha256(seed_material).hexdigest()
    return int(digest[:8], 16)


def _equalized_dictionary(values: dict[str, float], *, decimals: int) -> dict[str, float]:
    if not values:
        return {}
    mean_value = round(sum(values.values()) / len(values), decimals)
    return {key: mean_value for key in values}


def _require_nested_parameter(instance: GeneratedInstance, parameter_name: str) -> dict[str, Any]:
    if parameter_name not in instance.parameters:
        raise KeyError(f"Missing required parameter '{parameter_name}' in instance '{instance.name}'")
    parameter = instance.parameters[parameter_name]
    if not isinstance(parameter, dict):
        raise TypeError(f"Parameter '{parameter_name}' must be a dictionary")
    return parameter


def _set_base_metadata(instance: GeneratedInstance, spec: BenchmarkSpec) -> None:
    instance.metadata["benchmark"] = {
        "kind": "base",
        "prefix": spec.prefix,
        "suffix": spec.suffix,
        "seed": spec.seed,
    }


def _changed_parameter_keys(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    return {
        key
        for key in set(before) | set(after)
        if before.get(key) != after.get(key)
    }


def _validate_prefix_override(
    base_instance: GeneratedInstance,
    overridden_instance: GeneratedInstance,
    prefix: str,
) -> None:
    allowed = set(PREFIX_OVERRIDE_DECIMALS.get(prefix, {}))
    changed = _changed_parameter_keys(base_instance.parameters, overridden_instance.parameters)
    if not changed.issubset(allowed):
        raise AssertionError(f"{prefix} changed unexpected parameter groups: {sorted(changed - allowed)}")

    for parameter_name in allowed:
        if parameter_name not in overridden_instance.parameters:
            continue
        values = list(overridden_instance.parameters[parameter_name].values())
        if values and len(set(values)) != 1:
            raise AssertionError(f"{prefix} did not equalize '{parameter_name}'")
