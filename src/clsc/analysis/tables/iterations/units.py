from __future__ import annotations

from typing import Any

from clsc.models.instance import TAX_SCALE_FACTOR

# USD/t CO2e per integer tax_index step, derived from the single-source-of-truth
# TAX_SCALE_FACTOR (USD/kg) since all reporting uses the economically meaningful
# rate -- see paper/appendix/app_data.tex Sec. "Carbon-Tax Range Justification".
# The index tax_index itself is confined to the leader's formulation and the DBP algorithm.
TAX_SCALE_USD_PER_TONNE = TAX_SCALE_FACTOR * 1000.0


def to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def to_int(value: Any) -> int | None:
    number = to_float(value)
    if number is None:
        return None
    return int(round(number))


def latex_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def _fmt(number: float, digits: int) -> str:
    return f"{number:.{digits}f}"


def latex_num(value: str) -> str:
    return "--" if value == "--" else rf"\num{{{value}}}"


def latex_bold_num(value: str) -> str:
    return "--" if value == "--" else rf"\textbf{{\num{{{value}}}}}"


def fmt_tax(tax_index: int | None) -> str:
    if tax_index is None:
        return "--"
    return _fmt(TAX_SCALE_USD_PER_TONNE * tax_index, 1)


def fmt_emissions(value: float | None) -> str:
    if value is None:
        return "--"
    return _fmt(value, 2)


def fmt_usd(value: float | None) -> str:
    if value is None:
        return "--"
    return _fmt(value, 2)


def fmt_gap_percent(*, ub: float | None, lb: float | None) -> str:
    if ub is None or lb is None or ub == 0:
        return "--"
    gap = max(0.0, (ub - lb) / abs(ub))
    return _fmt(100.0 * gap, 2)


def render_tax_bounds(lo_idx: int | None, hi_idx: int | None) -> str:
    if lo_idx is None or hi_idx is None:
        return "--"
    lo = _fmt(TAX_SCALE_USD_PER_TONNE * lo_idx, 1)
    hi = _fmt(TAX_SCALE_USD_PER_TONNE * hi_idx, 1)
    return rf"[\num{{{lo}}},\;\num{{{hi}}}]"
