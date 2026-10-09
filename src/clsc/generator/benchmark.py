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

# Escalation-only bases: NOT part of the standard 12 (SIZE_SUFFIXES) and not written by
# `python -m clsc.generator benchmark`. Each pushes one axis (materials/products richness, or
# node count) past the standard testbed's range, for scalability probes.
# STD_I25_M12_T6 is the pre-existing escalation probe; STD_I25_M16_T6 and STD_I33_M8_T6 extend
# the materials/products and node-count axes by one further point each.
ESCALATION_SUFFIXES = (
    "I25_M12_T6",
    "I25_M16_T6",
    "I33_M8_T6",
)


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


def _material_split(materials_code: int) -> dict[str, int]:
    """Materials/products richness code -> (raw_materials, products).

    The standard 12 use M4 (2 raw materials, 1 product) and M8 (4/2); this is the formula those
    two fit exactly (`code // 2`, `code // 4`), generalized so escalation codes beyond M8 (M12,
    M16, ...) follow the same pattern rather than needing their own lookup entry.
    """
    if materials_code <= 0 or materials_code % 4 != 0:
        raise ValueError(f"Unsupported material code M{materials_code}: must be a positive multiple of 4")
    return {"raw_materials": materials_code // 2, "products": materials_code // 4}


def _specs_from_suffixes(suffixes: tuple[str, ...], *, seed_base: int) -> list[BenchmarkSpec]:
    specs: list[BenchmarkSpec] = []
    for prefix in PREFIXES:
        for suffix in suffixes:
            match = SIZE_PATTERN.fullmatch(suffix)
            if match is None:
                raise ValueError(f"Unsupported benchmark suffix: {suffix}")

            total_entities = int(match.group("entities"))
            materials_code = int(match.group("materials"))
            periods = int(match.group("periods"))

            specs.append(
                BenchmarkSpec(
                    prefix=prefix,
                    suffix=suffix,
                    periods=periods,
                    production_technologies=3,
                    remanufacturing_technologies=3,
                    seed=_deterministic_seed(seed_base, prefix, suffix),
                    **entity_split(total_entities),
                    **_material_split(materials_code),
                )
            )
    return specs


def build_base_benchmark_specs(seed_base: int = 0) -> list[BenchmarkSpec]:
    specs = _specs_from_suffixes(SIZE_SUFFIXES, seed_base=seed_base)
    if len(specs) != len(PREFIXES) * len(SIZE_SUFFIXES):
        raise AssertionError(f"Expected {len(PREFIXES) * len(SIZE_SUFFIXES)} base benchmark specs, got {len(specs)}")
    return specs


def build_escalation_specs(seed_base: int = 0) -> list[BenchmarkSpec]:
    """Escalation-only bases (`ESCALATION_SUFFIXES`): one point beyond the standard 12 on each of
    the materials/products and node-count axes, for scalability probes. Built the
    same deterministic way as `build_base_benchmark_specs`, just over a different suffix list --
    these are not part of the standard benchmark set and are not written by
    `python -m clsc.generator benchmark`.
    """
    specs = _specs_from_suffixes(ESCALATION_SUFFIXES, seed_base=seed_base)
    if len(specs) != len(PREFIXES) * len(ESCALATION_SUFFIXES):
        raise AssertionError(
            f"Expected {len(PREFIXES) * len(ESCALATION_SUFFIXES)} escalation specs, got {len(specs)}"
        )
    return specs


def apply_prefix_override(instance: GeneratedInstance, prefix: str) -> GeneratedInstance:
    overridden = _clone_instance(instance)

    if prefix == "STD":
        return overridden
    raise ValueError(f"Unsupported benchmark prefix: {prefix}; only STD instances are generated")


def _generate_and_write_specs(
    specs: list[BenchmarkSpec], *, output_root: Path, extension: str, ensure_feasible: bool,
) -> int:
    if ensure_feasible:
        from .feasibility import generate_feasible_instance

    written = 0
    for spec in specs:
        generated = (
            generate_feasible_instance(spec.to_config())
            if ensure_feasible
            else generate_instance(spec.to_config())
        )
        benchmark_instance = apply_prefix_override(generated, spec.prefix)
        _set_base_metadata(benchmark_instance, spec)
        _validate_prefix_override(generated, benchmark_instance, spec.prefix)
        write_instance(benchmark_instance, output_root / f"{benchmark_instance.name}{extension}")
        written += 1
    return written


def generate_benchmark(
    output_dir: str | Path,
    *,
    include_base: bool = True,
    seed_base: int = 0,
    file_format: str = "json",
    ensure_feasible: bool = True,
) -> BenchmarkSummary:
    if file_format not in {"json", "yaml"}:
        raise ValueError("file_format must be either 'json' or 'yaml'")

    extension = ".json" if file_format == "json" else ".yaml"
    output_root = Path(output_dir)
    specs = build_base_benchmark_specs(seed_base)

    base_count = 0
    if include_base:
        base_count = _generate_and_write_specs(
            specs, output_root=output_root, extension=extension, ensure_feasible=ensure_feasible,
        )

    return BenchmarkSummary(
        base_specs=len(specs),
        base_instances=base_count,
        output_dir=output_root,
        file_format=file_format,
    )


def generate_escalation_bases(
    output_dir: str | Path,
    *,
    seed_base: int = 0,
    file_format: str = "json",
    ensure_feasible: bool = True,
) -> BenchmarkSummary:
    """Write the escalation-only bases (`ESCALATION_SUFFIXES`) to `output_dir`.

    Kept separate from `generate_benchmark` because these are not part of the standard 12 and must
    never be silently produced by a routine `python -m clsc.generator benchmark` run -- call this
    explicitly to (re)generate them.
    """
    if file_format not in {"json", "yaml"}:
        raise ValueError("file_format must be either 'json' or 'yaml'")

    extension = ".json" if file_format == "json" else ".yaml"
    output_root = Path(output_dir)
    specs = build_escalation_specs(seed_base)
    written = _generate_and_write_specs(
        specs, output_root=output_root, extension=extension, ensure_feasible=ensure_feasible,
    )
    return BenchmarkSummary(
        base_specs=len(specs), base_instances=written, output_dir=output_root, file_format=file_format,
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
