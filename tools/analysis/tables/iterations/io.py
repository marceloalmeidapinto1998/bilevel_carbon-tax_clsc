from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .units import to_float, to_int


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def first_record(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return payload[0] if payload else {}
    return payload if isinstance(payload, dict) else {}


def load_dbp_trace(method_dir: Path) -> list[dict[str, str]]:
    return load_csv(method_dir / "dbp_trace.csv")


def load_lex_trace(method_dir: Path) -> list[dict[str, str]]:
    path = method_dir / "lex_trace.csv"
    return load_csv(path) if path.exists() else []


def load_result(method_dir: Path) -> dict[str, Any]:
    return first_record(load_json(method_dir / "result.json"))


def load_summary(method_dir: Path) -> dict[str, Any]:
    return first_record(load_json(method_dir / "summary.json"))


def load_instance_bounds(
    instance_dir: Path,
    detailed: dict[str, Any],
    summary: dict[str, Any],
) -> tuple[int, int]:
    input_path = None
    instance_block = detailed.get("instance")
    if isinstance(instance_block, dict):
        input_path = instance_block.get("input_path")
    input_path = input_path or summary.get("input_path")
    if input_path:
        payload_path = Path(input_path)
        if not payload_path.is_absolute():
            payload_path = Path.cwd() / payload_path
        if payload_path.exists():
            payload = load_json(payload_path)
            params = payload.get("parameters", {})
            lower = to_int(params.get("underline_hat_tau"))
            upper = to_int(params.get("overline_hat_tau"))
            if lower is not None and upper is not None:
                return lower, upper

    lex_block = detailed.get("lexicographic_tiebreak", {})
    lower = to_int(lex_block.get("lower_hat_tau"))
    upper = to_int(detailed.get("phase_summary", {}).get("phase_1_selected_hat_tau"))
    if lower is not None and upper is not None:
        return lower, upper

    dbp_rows = load_csv(instance_dir / "lf_lex_exact" / "dbp_trace.csv")
    candidates = [to_int(row.get("relaxation_hat_tau")) for row in dbp_rows]
    candidates += [to_int(row.get("next_relaxation_hat_tau")) for row in dbp_rows]
    clean = [value for value in candidates if value is not None]
    return (min(clean), max(clean)) if clean else (0, 0)


def load_enumeration_emissions(instance_dir: Path) -> dict[int, float]:
    enum_path = instance_dir / "enum_lf_lex_exact" / "enumeration_solutions.json"
    if not enum_path.exists():
        return {}
    payload = load_json(enum_path)
    emissions_by_tau: dict[int, float] = {}
    for record in payload.get("tax_solutions", []):
        leader = record.get("leader", {})
        objectives = record.get("objectives", {})
        hat_tau = to_int(leader.get("hat_tau"))
        emissions = to_float(objectives.get("emissions"))
        if hat_tau is not None and emissions is not None:
            emissions_by_tau[hat_tau] = emissions
    return emissions_by_tau
