"""Assemble results/analysis/SENSITIVITY_REPORT.md from the analysis CSVs.

Consolidates the normalized OAT elasticities, the Morris global screening (if solved), the
solver-robustness summary, and the tax-range censoring flags into a single paper-ready markdown
report, prefixed with the uncertainty-vs-sensitivity framing and a reproducibility statement.
Optional sections degrade to a "pending" note with the command to produce them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import io

OUT = io.TABLES                              # read the aggregated CSV tables from here
REPORT = io.REPORTS / "SENSITIVITY_REPORT.md"  # write the report under reports/


def _read(name: str) -> pd.DataFrame | None:
    path = OUT / name
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception:  # noqa: BLE001
        return None


def _md_table(df: pd.DataFrame, cols: list[str], sig: int = 4) -> str:
    head = "| " + " | ".join(cols) + " |\n| " + " | ".join("---" for _ in cols) + " |"
    lines = [head]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r.get(c)
            cells.append(f"{v:.{sig}g}" if isinstance(v, (int, float, np.floating)) and not pd.isna(v)
                         else ("" if pd.isna(v) else str(v)))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _section_elasticities(sens: pd.DataFrame) -> str:
    e = sens.dropna(subset=["elasticity_cost"]).copy()
    if e.empty:
        return "_No finite elasticities available._\n"
    e["abs_cost"] = e.elasticity_cost.abs()
    e["abs_emis"] = e.elasticity_emissions.abs()
    agg = (e.groupby("factor")
           .agg(mean_abs_cost_elasticity=("abs_cost", "mean"),
                mean_abs_emissions_elasticity=("abs_emis", "mean"),
                n_instances=("base_instance", "nunique"))
           .reset_index()
           .sort_values("mean_abs_cost_elasticity", ascending=False))
    n_struct = int(sens.elasticity_cost.isna().sum())
    n_noise = int(sens.below_noise.sum()) if "below_noise" in sens else 0
    body = [
        "Elasticities normalize each output change by the relative input change, so magnitudes "
        "are comparable across factors (a local, baseline-dependent screen — see Morris below for "
        "the global ranking). Factors ranked by mean |cost elasticity| across instances:",
        "",
        _md_table(agg, ["factor", "mean_abs_cost_elasticity",
                        "mean_abs_emissions_elasticity", "n_instances"]),
        "",
        f"_Structural perturbations without a scalar input change (no elasticity): "
        f"{n_struct} run(s). Perturbations within the {io.NOISE_PCT}% solver-noise floor: {n_noise}._",
    ]
    return "\n".join(body) + "\n"


def _section_stability(sens: pd.DataFrame) -> str:
    e = sens.dropna(subset=["elasticity_cost"]).copy()
    if e.empty:
        return "_No finite elasticities available._\n"
    e["abs_cost"] = e.elasticity_cost.abs()
    rows = []
    for inst, g in e.groupby("base_instance"):
        per_factor = g.groupby("factor")["abs_cost"].max().sort_values(ascending=False)
        top = list(per_factor.index)
        rows.append({"base_instance": inst,
                     "top1": top[0] if len(top) > 0 else "",
                     "top2": top[1] if len(top) > 1 else "",
                     "top3": top[2] if len(top) > 2 else ""})
    tbl = pd.DataFrame(rows).sort_values("base_instance")
    return ("Most cost-influential factors per instance (meta-sensitivity — stable rankings "
            "across sizes strengthen the generality claim):\n\n"
            + _md_table(tbl, ["base_instance", "top1", "top2", "top3"]) + "\n")


def _section_morris() -> str:
    files = sorted(OUT.glob("morris_*_indices.csv"))
    if not files:
        return ("_Pending._ Generate, solve, and analyze a Morris screen:\n\n"
                "```\npython -m tools.experiments.sensitivity morris design data/instances/base/STD_I17_M4_T3.json -N 10\n"
                "python -m tools.solver.solve_batch data/instances/experiments/sensitivity/morris/STD_I17_M4_T3 "
                "--method dbp_lf_lex_exact\n"
                "python -m tools.experiments.sensitivity morris analyze STD_I17_M4_T3\n```\n")
    blocks = []
    for f in files:
        df = pd.read_csv(f)
        inst = f.stem.replace("morris_", "").replace("_indices", "")
        for out_name in df.output.unique():
            d = (df[df.output == out_name].dropna(subset=["mu_star"])
                 .sort_values("mu_star", ascending=False).head(8))
            blocks.append(f"**{inst} — {out_name}** (mu* = global influence, sigma = interaction):\n\n"
                          + _md_table(d, ["factor", "mu_star", "sigma", "n_effects"]) + "\n")
    return "\n".join(blocks)


def _section_solver(rob: pd.DataFrame | None, cens: pd.DataFrame | None) -> str:
    parts = []
    if rob is not None and not rob.empty:
        cat = rob[rob.grouping.isin(["all", "category"])]
        parts.append("Convergence, validation, and timing across every committed run:\n\n"
                     + _md_table(cat, ["key", "n_runs", "frac_validated", "max_relative_gap",
                                       "n_gap_above_target", "mean_iterations", "max_solve_s"]))
    if cens is not None and not cens.empty:
        n_c = int(cens.censored.sum())
        parts.append(f"\n**Tax-range censoring:** {n_c} of {len(cens)} runs have their incumbent tax "
                     f"at the top of the explored range (boundary artifact; extend the range there).")
        if n_c:
            top = cens[cens.censored].head(12)
            parts.append("\n" + _md_table(top, ["base_instance", "sa_dim", "hat_tau",
                                                "hat_tau_max_on_curve"]))
    return "\n".join(parts) + "\n" if parts else "_No solver-robustness data._\n"


def build() -> Path:
    sens = _read("sensitivity_matrix.csv")
    rob = _read("solver_robustness.csv")
    cens = _read("censoring_flags.csv")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    md = f"""# Sensitivity & Robustness Analysis — Bilevel CLSC Model

_Auto-generated {now} by `tools/experiments/sensitivity/report.py`. Do not edit by hand._

## Uncertainty vs. sensitivity

This report separates two questions (after Saltelli et al.): **uncertainty analysis** — how much
the outputs (emissions, cost, optimal carbon tax) vary under input uncertainty — and
**sensitivity analysis** — which inputs drive that variation. The normalized elasticities and the
Morris indices below answer the *sensitivity* question; the solver-robustness layer characterizes
the DBP algorithm across the input space.

## 1. Normalized local sensitivity (OAT elasticities)

{_section_elasticities(sens) if sens is not None else "_sensitivity_matrix.csv missing._"}

## 2. Factor-ranking stability (meta-sensitivity)

{_section_stability(sens) if sens is not None else "_sensitivity_matrix.csv missing._"}

## 3. Global screening (Morris elementary effects)

{_section_morris()}

## 4. Solver robustness (DBP)

{_section_solver(rob, cens)}

## 5. Reproducibility

- **Designs (source of truth):** `data/instances/experiments/sensitivity/oat/<base>/design_matrix.csv` (OAT),
  `data/instances/experiments/sensitivity/morris/<base>/morris_design_matrix.csv` (Morris).
- **Factor definitions:** `tools/experiments/sensitivity/factors.py` (canonical names, multiplier ranges,
  rationale). Morris sampling via SALib (bundled trajectory fallback if absent); seed recorded in
  each instance's metadata.
- **Solver tolerances:** `src/config/gap_tol.py` (`ToleranceConfig`); tolerance sensitivity via
  `python -m tools.experiments.sensitivity robustness tolerance <base>`.
- **Minimum meaningful effect:** output changes below {io.NOISE_PCT}% are within the DBP
  relative-gap noise floor (~1e-4) and flagged `below_noise` in `sensitivity_matrix.csv`.
- **Regenerate everything (no solves):** `python -m tools.experiments.sensitivity analyze-all`.
"""
    io.REPORTS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(md, encoding="utf-8")
    print(f"Wrote {REPORT.relative_to(io.REPO)}")
    return REPORT


if __name__ == "__main__":
    build()
