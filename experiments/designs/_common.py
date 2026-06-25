"""Shared row schema for all family design-matrix builders.

Field set is the design-time subset of the full run-metadata schema (plan §8); the remaining
fields (objective values, runtime, censored, ...) are filled in by the orchestrator after a run
completes, and live in the per-run `campaign_manifest.json`, not the design matrix.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class DesignPoint:
    family_id: str
    design_point_id: str
    run_code: str
    base_instance_id: str
    execution_mode: str                              # "bilevel" or "fixed_tax"
    per_subproblem_time_limit_seconds: float
    per_run_wall_clock_cap_seconds: float
    factor_levels: dict[str, float] = field(default_factory=dict)
    technology_menu: str = "base"
    transport_menu: str = "base"
    seed_offset: int = 0                              # 0 = base instance's own seed
    fixed_hat_tau: int | None = None                  # Family B only
    mip_gap: float | None = None                      # None = solver default
    dbp_relative_gap: float | None = None
    threads: int | None = None
    mip_focus: int | None = None
    notes: str = ""

    def to_row(self) -> dict[str, Any]:
        row = {
            "family_id": self.family_id,
            "design_point_id": self.design_point_id,
            "run_code": self.run_code,
            "base_instance_id": self.base_instance_id,
            "execution_mode": self.execution_mode,
            "per_subproblem_time_limit_seconds": self.per_subproblem_time_limit_seconds,
            "per_run_wall_clock_cap_seconds": self.per_run_wall_clock_cap_seconds,
            "technology_menu": self.technology_menu,
            "transport_menu": self.transport_menu,
            "seed_offset": self.seed_offset,
            "fixed_hat_tau": self.fixed_hat_tau,
            "mip_gap": self.mip_gap,
            "dbp_relative_gap": self.dbp_relative_gap,
            "threads": self.threads,
            "mip_focus": self.mip_focus,
            "notes": self.notes,
        }
        for factor_name, level in sorted(self.factor_levels.items()):
            row[f"factor__{factor_name}"] = level
        return row


def rows_to_csv_dicts(points: list[DesignPoint]) -> list[dict[str, Any]]:
    """Flatten to a uniform column set (union of all rows' keys) for `io.write_design_matrix`."""
    rows = [point.to_row() for point in points]
    all_keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                all_keys.append(key)
    return [{key: row.get(key, "") for key in all_keys} for row in rows]
