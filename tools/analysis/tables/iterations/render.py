from __future__ import annotations

from .rows import FinalRow, IterationRow
from .units import (
    fmt_emissions,
    fmt_gap_percent,
    fmt_tax,
    fmt_usd,
    latex_bold_num,
    latex_escape,
    latex_num,
    render_tax_bounds,
)

_PHASE_HEADING_COLS = 7


def _phase_heading(text: str) -> str:
    return rf"\multicolumn{{{_PHASE_HEADING_COLS}}}{{@{{}}l}}{{{text}}} \\"


def _render_iteration_row(row: IterationRow) -> str:
    cells = (
        row.step_label,
        latex_num(fmt_tax(row.hat_tau)),
        render_tax_bounds(row.tax_bounds_lo, row.tax_bounds_hi),
        latex_num(fmt_emissions(row.lb_emissions)),
        latex_num(fmt_emissions(row.ub_emissions)),
        latex_num(fmt_usd(row.follower_objective)),
        latex_num(fmt_gap_percent(ub=row.ub_emissions, lb=row.lb_emissions)),
    )
    return " & ".join(cells) + r" \\"


def _render_final_row(final: FinalRow) -> str:
    gap_value = None if final.relative_gap is None else 100.0 * final.relative_gap
    gap_cell = "--" if gap_value is None else latex_bold_num(f"{gap_value:.2f}")
    cells = (
        r"\textbf{Final}",
        latex_bold_num(fmt_tax(final.hat_tau)),
        "--",
        latex_bold_num(fmt_emissions(final.lb_emissions)),
        latex_bold_num(fmt_emissions(final.ub_emissions)),
        latex_bold_num(fmt_usd(final.follower_objective)),
        gap_cell,
    )
    return " & ".join(cells) + r" \\"


def _build_body(
    *,
    phase1_rows: list[IterationRow],
    phase2_rows: list[IterationRow],
    final_row: FinalRow,
) -> str:
    lines: list[str] = []
    lines.append(_phase_heading("Phase 1 --- DBP"))
    lines.append(r"\addlinespace[0.15em]")
    lines.extend(_render_iteration_row(row) for row in phase1_rows)
    if phase2_rows:
        lines.append(r"\addlinespace[0.45em]")
        lines.append(_phase_heading("Phase 2 --- Lexicographic bisection on carbon tax"))
        lines.append(r"\addlinespace[0.15em]")
        lines.extend(_render_iteration_row(row) for row in phase2_rows)
    lines.append(r"\midrule")
    lines.append(_render_final_row(final_row))
    return "\n".join(lines)


def render_instance_table(
    *,
    instance: str,
    phase1_rows: list[IterationRow],
    phase2_rows: list[IterationRow],
    final_row: FinalRow,
) -> str:
    body = _build_body(
        phase1_rows=phase1_rows,
        phase2_rows=phase2_rows,
        final_row=final_row,
    )
    escaped_instance = latex_escape(instance)
    caption = rf"LF-Lex iteration log for instance \textsc{{{escaped_instance}}}."
    label = f"tab:lflex-path-{instance.lower().replace('_', '-')}"
    return rf"""\documentclass[11pt]{{article}}
\usepackage[landscape,margin=0.35in]{{geometry}}
\usepackage{{array}}
\usepackage{{booktabs}}
\usepackage{{caption}}
\usepackage{{ragged2e}}
\usepackage{{siunitx}}
\usepackage{{threeparttable}}

\pagestyle{{empty}}
\captionsetup{{font=small,labelfont=bf}}
\setlength{{\tabcolsep}}{{4.6pt}}
\renewcommand{{\arraystretch}}{{1.20}}
\sisetup{{
    detect-all,
    group-separator = {{,}},
    group-minimum-digits = 4,
    table-number-alignment = center
}}

\begin{{document}}
\small
\begin{{table}}[htbp]
\centering
\begin{{threeparttable}}
\caption{{{caption}}}
\label{{{label}}}
\begin{{tabular}}{{@{{}}>{{\centering\arraybackslash}}p{{1.05cm}}
                  >{{\centering\arraybackslash}}p{{2.75cm}}
                  >{{\centering\arraybackslash}}p{{2.75cm}}
                  >{{\centering\arraybackslash}}p{{3.10cm}}
                  >{{\centering\arraybackslash}}p{{3.10cm}}
                  >{{\centering\arraybackslash}}p{{3.10cm}}
                  >{{\centering\arraybackslash}}p{{1.55cm}}@{{}}}}
\toprule
 & \multicolumn{{3}}{{c}}{{Leader}} & \multicolumn{{2}}{{c}}{{Follower}} & \multicolumn{{1}}{{c}}{{Convergence}} \\
\cmidrule(lr){{2-4}}\cmidrule(lr){{5-6}}\cmidrule(lr){{7-7}}
Step
 & \shortstack{{Carbon tax\\(USD/kgCO\textsubscript{{2}}e)}}
 & \shortstack{{Tax bounds\\(USD/kgCO\textsubscript{{2}}e)}}
 & \shortstack{{LB\\(kgCO\textsubscript{{2}}e)}}
 & \shortstack{{UB\\(kgCO\textsubscript{{2}}e)}}
 & \shortstack{{Objective\\(USD)}}
 & \shortstack{{Gap\\(\%)}} \\
\midrule
{body}
\bottomrule
\end{{tabular}}
\end{{threeparttable}}
\end{{table}}
\end{{document}}
"""
