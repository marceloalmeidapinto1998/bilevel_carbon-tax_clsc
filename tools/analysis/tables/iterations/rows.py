from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .units import to_float, to_int


@dataclass(frozen=True, slots=True)
class IterationRow:
    step_label: str
    hat_tau: int | None
    tax_bounds_lo: int | None
    tax_bounds_hi: int | None
    lb_emissions: float | None
    ub_emissions: float | None
    follower_objective: float | None


@dataclass(frozen=True, slots=True)
class FinalRow:
    hat_tau: int | None
    lb_emissions: float | None
    ub_emissions: float | None
    follower_objective: float | None
    relative_gap: float | None


def build_phase1_rows(
    *,
    dbp_rows: list[dict[str, str]],
    lower_hat_tau: int,
    upper_hat_tau: int,
) -> list[IterationRow]:
    rows: list[IterationRow] = []
    for index, raw in enumerate(dbp_rows):
        rows.append(
            IterationRow(
                step_label=f"I.{index + 1}",
                hat_tau=to_int(raw.get("relaxation_hat_tau")),
                tax_bounds_lo=lower_hat_tau,
                tax_bounds_hi=upper_hat_tau,
                lb_emissions=to_float(raw.get("next_relaxation_lower_bound")),
                ub_emissions=to_float(raw.get("incumbent_emissions")),
                follower_objective=to_float(raw.get("follower_objective")),
            )
        )
    return rows


def build_phase2_rows(
    *,
    lex_rows: list[dict[str, str]],
    lower_hat_tau: int,
    phase_1_hat_tau: int,
    phase_1_final_lb: float | None,
) -> list[IterationRow]:
    rows: list[IterationRow] = []
    lo = lower_hat_tau - 1
    hi = phase_1_hat_tau
    for index, raw in enumerate(lex_rows):
        hat_tau = to_int(raw.get("tested_hat_tau"))
        matched = str(raw.get("matched_incumbent_emissions", "")).lower() == "true"
        rows.append(
            IterationRow(
                step_label=f"II.{index + 1}",
                hat_tau=hat_tau,
                tax_bounds_lo=lo + 1,
                tax_bounds_hi=hi,
                lb_emissions=phase_1_final_lb,
                ub_emissions=to_float(raw.get("emissions")),
                follower_objective=to_float(raw.get("follower_objective")),
            )
        )
        if hat_tau is None:
            continue
        if matched:
            hi = hat_tau
        else:
            lo = hat_tau
    return rows


def build_final_row(
    *,
    detailed: dict[str, Any],
    summary: dict[str, Any],
) -> FinalRow:
    summary = summary if isinstance(summary, dict) else {}
    bounds = detailed.get("bounds", {}) if isinstance(detailed, dict) else {}
    return FinalRow(
        hat_tau=to_int(summary.get("hat_tau")),
        lb_emissions=to_float(summary.get("lower_bound") or bounds.get("lower_bound")),
        ub_emissions=to_float(summary.get("upper_bound") or bounds.get("upper_bound")),
        follower_objective=to_float(summary.get("follower_objective")),
        relative_gap=to_float(summary.get("relative_gap") or bounds.get("relative_gap")),
    )


def phase1_final_lb(rows: list[IterationRow]) -> float | None:
    for row in reversed(rows):
        if row.lb_emissions is not None:
            return row.lb_emissions
    return None
