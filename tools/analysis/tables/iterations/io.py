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
            # Old instance files (pre tax_index rename) only carry the
            # underline_hat_tau/overline_hat_tau keys -- fall back to those.
            lower = to_int(params.get("underline_tax_index", params.get("underline_hat_tau")))
            upper = to_int(params.get("overline_tax_index", params.get("overline_hat_tau")))
            if lower is not None and upper is not None:
                return lower, upper

    dbp_rows = load_csv(instance_dir / "f_lex_exact" / "dbp_trace.csv")
    candidates = [to_int(row.get("relaxation_tax_index", row.get("relaxation_hat_tau"))) for row in dbp_rows]
    candidates += [to_int(row.get("next_relaxation_tax_index", row.get("next_relaxation_hat_tau"))) for row in dbp_rows]
    clean = [value for value in candidates if value is not None]
    return (min(clean), max(clean)) if clean else (0, 0)


