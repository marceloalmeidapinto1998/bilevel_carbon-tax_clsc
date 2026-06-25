"""Generate OAT sensitivity instances (one perturbed parameter each) + a design_matrix.csv."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from src.models.instance_loader import InstanceData

from .. import io
from .specs import MUTATION_FUNCTIONS, SENSITIVITY_SPECS, SensitivitySpec

DEFAULT_SCENARIO_NAME = "sensitivity"
DEFAULT_OUTPUT_DIR = io.DATA_INSTANCES / "experiments" / "sensitivity" / "oat"


def _fmt(value: float | None) -> str:
    return "" if value is None else repr(round(value, 6))


def create_sensitivity_scenarios(
    source_path: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    specs: Sequence[SensitivitySpec] = SENSITIVITY_SPECS,
    scenario_name: str = DEFAULT_SCENARIO_NAME,
    overwrite: bool = False,
) -> list[Path]:
    source_path = Path(source_path)
    InstanceData.from_file(source_path)  # validate the base instance up front
    base_payload = io.load_base_payload(source_path)
    source_name = str(base_payload["name"])
    base_params = base_payload["parameters"]

    instance_subdir = Path(output_dir) / source_name
    instance_subdir.mkdir(parents=True, exist_ok=True)

    written_paths: list[Path] = []
    design_rows: list[dict[str, Any]] = []
    for spec in specs:
        name = spec.code
        dest = instance_subdir / f"{name}.json"
        written_paths.append(io.materialize_instance(
            base_payload, name, MUTATION_FUNCTIONS[spec.code], dest,
            scenario_name=scenario_name,
            scenario_meta={"sensitivity_spec": asdict(spec)},
            overwrite=overwrite,
        ))
        design_rows.append({
            "source_instance": source_name,
            "code": spec.code,
            "factor": spec.factor,
            "kind": spec.kind,
            "priority": spec.priority,
            "dimension": spec.dimension,
            "multiplier": "" if spec.multiplier is None else spec.multiplier,
            "perturbed_value": "" if spec.perturbed_value is None else spec.perturbed_value,
            "rel_input_change": _fmt(spec.rel_input_change(base_params)),
            "parameters_changed": ";".join(spec.parameters_changed),
            "path": str(dest),
        })

    io.write_design_matrix(design_rows, instance_subdir / "design_matrix.csv")
    return written_paths
