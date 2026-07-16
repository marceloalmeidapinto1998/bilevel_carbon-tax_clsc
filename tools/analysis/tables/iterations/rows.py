from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .units import to_float, to_int


@dataclass(frozen=True, slots=True)
class IterationRow:
    step_label: str
    tax_index: int | None
    tax_bounds_lo: int | None
    tax_bounds_hi: int | None
    lb_emissions: float | None
    ub_emissions: float | None
    follower_objective: float | None


@dataclass(frozen=True, slots=True)
class FinalRow:
    tax_index: int | None
    lb_emissions: float | None
    ub_emissions: float | None
    follower_objective: float | None
    relative_gap: float | None


def build_phase1_rows(
    *,
    dbp_rows: list[dict[str, str]],
    lower_tax_index: int,
    upper_tax_index: int,
) -> list[IterationRow]:
    rows: list[IterationRow] = []
    for index, raw in enumerate(dbp_rows):
        rows.append(
            IterationRow(
                step_label=f"I.{index + 1}",
                tax_index=to_int(raw.get("relaxation_tax_index", raw.get("relaxation_hat_tau"))),
                tax_bounds_lo=lower_tax_index,
                tax_bounds_hi=upper_tax_index,
                lb_emissions=to_float(raw.get("next_relaxation_lower_bound")),
                ub_emissions=to_float(raw.get("incumbent_emissions")),
                follower_objective=to_float(raw.get("follower_objective")),
            )
        )
    return rows


def build_final_row(
    *,
    detailed: dict[str, Any],
    summary: dict[str, Any],
) -> FinalRow:
    summary = summary if isinstance(summary, dict) else {}
    bounds = detailed.get("bounds", {}) if isinstance(detailed, dict) else {}
    return FinalRow(
        tax_index=to_int(summary.get("tax_index", summary.get("hat_tau"))),
        lb_emissions=to_float(summary.get("lower_bound") or bounds.get("lower_bound")),
        ub_emissions=to_float(summary.get("upper_bound") or bounds.get("upper_bound")),
        follower_objective=to_float(summary.get("follower_objective")),
        relative_gap=to_float(summary.get("relative_gap") or bounds.get("relative_gap")),
    )
