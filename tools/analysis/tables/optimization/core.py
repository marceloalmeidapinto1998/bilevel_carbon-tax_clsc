"""Loaders, LaTeX renderer, and writer for the aggregate optimization-result table."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

INSTANCE_RE = re.compile(r"^STD_I(?P<I>\d+)_M(?P<M>\d+)_T(?P<T>\d+)$")

METHOD_LABELS = {
    "certified": "Certified",
    "enum_lf_lex_exact": "Enum | LF-Lex",
    "exact": "Exact",
    "f_lex_exact": "F-Lex Exact",
    "lf_lex_exact": "LF-Lex Exact",
}

METHOD_ORDER = {
    "exact": 0,
    "certified": 1,
    "f_lex_exact": 2,
    "lf_lex_exact": 3,
    "enum_lf_lex_exact": 4,
}


@dataclass(frozen=True)
class ResultRow:
    instance: str
    I: int | None
    M: int | None
    T: int | None
    method: str
    tau_star: float | None
    cost_star: float | None
    emissions_star: float | None
    follower_objective: float | None
    solve_seconds: float | None


def parse_instance_code(instance: str) -> tuple[int | None, int | None, int | None]:
    match = INSTANCE_RE.match(instance)
    if not match:
        return None, None, None
    return int(match.group("I")), int(match.group("M")), int(match.group("T"))


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_rows(results_base: Path) -> list[ResultRow]:
    rows: list[ResultRow] = []
    for summary_path in sorted(results_base.glob("*/*/summary.json")):
        method = summary_path.parent.name
        with summary_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        records = payload if isinstance(payload, list) else [payload]
        for record in records:
            if not isinstance(record, dict):
                continue
            instance = str(record.get("instance") or summary_path.parent.parent.name)
            I, M, T = parse_instance_code(instance)
            rows.append(
                ResultRow(
                    instance=instance,
                    I=I,
                    M=M,
                    T=T,
                    method=method,
                    tau_star=_to_float(record.get("effective_tax")),
                    cost_star=_to_float(record.get("cost")),
                    emissions_star=_to_float(record.get("emissions")),
                    follower_objective=_to_float(record.get("follower_objective")),
                    solve_seconds=_to_float(record.get("solve_seconds")),
                )
            )
    return rows


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


def fmt_int(value: int | None) -> str:
    return "--" if value is None else str(value)


def fmt_float(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "--"
    return f"{value:.{digits}f}"


def fmt_scientific_reader(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:.2e}".replace("e+0", "e").replace("e+", "e").replace("e-0", "e-")


def latex_num(value: str) -> str:
    return "--" if value == "--" else rf"\num{{{value}}}"


def method_label(method: str) -> str:
    return METHOD_LABELS.get(method, method.replace("_", " ").title())


def render_all_methods_table(rows: list[ResultRow]) -> str:
    columns = (
        r"\textbf{Instance}",
        r"\textbf{Facility}",
        r"\textbf{Product}",
        r"\textbf{Period}",
        r"\textbf{Solution Method}",
        r"\textbf{\mbox{Tax (USD/kg CO$_2$e)}}",
        r"\textbf{\mbox{Emissions (kg CO$_2$e)}}",
        r"\textbf{\mbox{Total Cost (USD)}}",
        r"\textbf{\mbox{CPU Time (s)}}",
    )
    column_spec = (
        r">{\raggedright\arraybackslash}p{2.55cm}" "\n"
        r">{\centering\arraybackslash}p{1.45cm}" "\n"
        r">{\centering\arraybackslash}p{1.45cm}" "\n"
        r">{\centering\arraybackslash}p{1.35cm}" "\n"
        r">{\raggedright\arraybackslash}p{3.00cm}" "\n"
        r">{\centering\arraybackslash}p{3.05cm}" "\n"
        r">{\centering\arraybackslash}p{3.55cm}" "\n"
        r">{\centering\arraybackslash}p{2.80cm}" "\n"
        r">{\centering\arraybackslash}p{2.30cm}"
    )
    header = " & ".join(columns) + r" \\"
    body_lines = []
    previous_dims: tuple[int | None, int | None, int | None] | None = None
    for row in sorted(
        rows,
        key=lambda r: (
            r.I if r.I is not None else 999_999,
            r.M if r.M is not None else 999_999,
            r.T if r.T is not None else 999_999,
            r.instance,
            METHOD_ORDER.get(r.method, 999),
            r.method,
        ),
    ):
        dims = (row.I, row.M, row.T)
        if previous_dims is not None and dims != previous_dims:
            body_lines.append(r"\addlinespace[0.45em]")
        previous_dims = dims
        values = (
            latex_escape(row.instance),
            fmt_int(row.I),
            fmt_int(row.M),
            fmt_int(row.T),
            latex_escape(method_label(row.method)),
            latex_num(fmt_float(row.tau_star, digits=2)),
            latex_num(fmt_scientific_reader(row.emissions_star)),
            latex_num(fmt_scientific_reader(row.follower_objective)),
            latex_num(fmt_float(row.solve_seconds, digits=2)),
        )
        body_lines.append(" & ".join(values) + r" \\")
    body = "\n".join(body_lines)
    return rf"""\documentclass[11pt]{{article}}
\usepackage[landscape,margin=0.25in]{{geometry}}
\usepackage{{array}}
\usepackage{{booktabs}}
\usepackage{{longtable}}
\usepackage{{siunitx}}
\usepackage{{caption}}
\usepackage{{ragged2e}}
\pagestyle{{empty}}
\setlength{{\tabcolsep}}{{1.35pt}}
\renewcommand{{\arraystretch}}{{1.06}}
\captionsetup{{font=scriptsize}}

\sisetup{{
    round-mode          = places,
    round-precision     = 2,
    table-number-alignment = center
}}

\begin{{document}}

\scriptsize

\begin{{longtable}}{{@{{}}{column_spec}@{{}}}}
\caption{{Summary of optimization results across all problem instances and solution methods.}}\\
\toprule
{header}
\midrule
\endfirsthead
\toprule
{header}
\midrule
\endhead
{body}
\bottomrule
\end{{longtable}}
\end{{document}}
"""


def run_pdflatex(tex_path: Path, *, keep_latex_build_files: bool) -> None:
    command = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        tex_path.name,
    ]
    subprocess.run(
        command,
        cwd=tex_path.parent,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if keep_latex_build_files:
        return
    for suffix in (".aux", ".log"):
        aux_path = tex_path.with_suffix(suffix)
        if aux_path.exists():
            try:
                aux_path.unlink()
            except PermissionError:
                pass


def write_all_methods_outputs(
    rows: list[ResultRow],
    analysis_root: Path,
    *,
    compile_pdf: bool,
    keep_latex_build_files: bool,
) -> tuple[Path, Path | None]:
    output_dir = analysis_root / "summary"
    output_dir.mkdir(parents=True, exist_ok=True)
    tex_path = output_dir / "tbl_opt_res.tex"
    pdf_path = output_dir / "tbl_opt_res.pdf"
    tex_path.write_text(render_all_methods_table(rows), encoding="utf-8")

    if compile_pdf:
        run_pdflatex(tex_path, keep_latex_build_files=keep_latex_build_files)
        return tex_path, pdf_path if pdf_path.exists() else None
    return tex_path, None
