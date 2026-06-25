"""Shared IO and paths for the sensitivity package.

Single home for the boilerplate every method otherwise duplicates: materializing a perturbed
instance (deep-copy base payload -> mutate params -> write benchmark/scenario metadata ->
validate -> write JSON), writing a design matrix, joining solved results back to design points,
and loading base-instance parameters for elasticity baselines. Also holds the shared paths and
analysis constants.
"""
from __future__ import annotations

import copy
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from data.generator import GeneratedInstance, write_instance
from src.models.instance_loader import InstanceData

# ---- paths (single source of truth in tools.analysis.common.paths) ---------
from tools.analysis.common.paths import (  # noqa: E402
    ANALYSIS_OUT,
    FIGURES,
    REPORTS,
    RESULTS,
    RUNS,
    TABLES,
)

DATA_INSTANCES = REPO / "data" / "instances"
BASE_DIR = DATA_INSTANCES / "base"

# ---- analysis constants ----------------------------------------------------
# Minimum meaningful effect: % output changes below this are within solver noise
# (DBP relative gap ~1e-4 == 0.01%); 0.05% is a conservative reporting floor.
NOISE_PCT = 0.05
DBP_GAP_TARGET = 1e-4  # ToleranceConfig.dbp_relative_gap


# ---- instance materialization ---------------------------------------------

def load_base_payload(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def materialize_instance(
    base_payload: dict,
    name: str,
    mutate: Callable[[dict[str, Any]], None],
    dest: Path,
    *,
    scenario_name: str | None = None,
    scenario_meta: dict | None = None,
    extra_meta: dict | None = None,
    overwrite: bool = False,
) -> Path:
    """Deep-copy a base payload, apply ``mutate`` to its parameters, set provenance metadata,
    validate, and write the instance JSON to ``dest``.

    - ``scenario_name``/``scenario_meta``: when set, writes the standard ``benchmark`` block
      (kind=scenario) and a ``scenario`` block ({name, source_instance, created_at_utc, **meta}).
    - ``extra_meta``: top-level metadata keys to merge (e.g. a ``tax_extension`` record).
    """
    payload = copy.deepcopy(base_payload)
    source_name = str(payload["name"])
    params = payload["parameters"]
    mutate(params)

    metadata = payload["metadata"]
    metadata.setdefault("config", {})["instance_name"] = name
    if scenario_name is not None:
        source_benchmark = copy.deepcopy(metadata.get("benchmark", {}))
        metadata["benchmark"] = {"kind": "scenario", "scenario": scenario_name, "source": source_benchmark}
        scenario_block = {
            "name": scenario_name,
            "source_instance": source_name,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        if scenario_meta:
            scenario_block.update(scenario_meta)
        metadata["scenario"] = scenario_block
    if extra_meta:
        metadata.update(extra_meta)

    instance = GeneratedInstance(name, metadata, payload["sets"], params)
    InstanceData.from_dict(instance.to_dict())  # validate before writing

    if dest.exists() and not overwrite:
        raise FileExistsError(f"Instance already exists: {dest}")
    return write_instance(instance, dest)


def write_design_matrix(rows: list[dict], path: Path) -> Path:
    if not rows:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


# ---- results loading -------------------------------------------------------

def load_summary_records(results_root: Path, run_ids: set[str]) -> dict[str, dict]:
    """Map run_id -> solved record by scanning run-level summary.csv files under results_root."""
    import pandas as pd

    solved: dict[str, dict] = {}
    for csv_path in results_root.glob("**/summary.csv"):
        if "analysis" in csv_path.parts or "network" in csv_path.parts:
            continue
        try:
            df = pd.read_csv(csv_path)
        except Exception:  # noqa: BLE001
            continue
        if "instance" not in df.columns or df.empty:
            continue
        for _, rec in df.iterrows():
            name = str(rec["instance"])
            if name in run_ids and name not in solved:
                solved[name] = rec.to_dict()
    return solved


# ---- base-instance parameters (elasticity baselines) -----------------------

_BASE_PARAMS_CACHE: dict[str, dict | None] = {}


def base_params(instance_name: str) -> dict | None:
    """Load (and cache) the parameters block of a base instance."""
    if instance_name not in _BASE_PARAMS_CACHE:
        path = BASE_DIR / f"{instance_name}.json"
        try:
            _BASE_PARAMS_CACHE[instance_name] = json.loads(path.read_text(encoding="utf-8"))["parameters"]
        except Exception:  # noqa: BLE001
            _BASE_PARAMS_CACHE[instance_name] = None
    return _BASE_PARAMS_CACHE[instance_name]
