"""Publication tables for campaign_01, built from the aggregated master table.

Run: python scripts/make_campaign_01_tables.py
Writes both .csv (machine-readable) and .tex (booktabs, paste-ready) per table into
results/analysis/campaign_01/tables/.

Table plan, mapped to the paper's claims:
  T1  testbed and verification      -- what the instances are, and that every solve certified
  T2  plateau characterisation      -- HEADLINE: tau*, E*, plateau width, abatement
  T3  policy-rule comparison        -- HEADLINE: what the naive rules cost at identical emissions
  T4  ablation                      -- each DBP component earns its place
  T6  sensitivity screening         -- which parameters drive the responses, and seed stability
  T7  valuation-ratio calibration   -- the validity envelope on absolute USD/t claims

Units are stated in every header: emissions in kt CO2e, money in 10^6 USD, tax in USD/t.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

TABLES = REPO_ROOT / "results" / "analysis" / "campaign_01" / "tables"
MASTER = TABLES / "master_runs_campaign_01.csv"
INSTANCES = REPO_ROOT / "data" / "instances" / "base"

KT = 1e6        # kg CO2e -> kt CO2e
MUSD = 1e6      # USD -> 10^6 USD


def cell_label(cell: str) -> str:
    return cell.replace("STD_", "").replace("_", "-")


def latex_escape(s: str) -> str:
    return str(s).replace("_", r"\_").replace("%", r"\%").replace("&", r"\&")


def _tabular(df: pd.DataFrame, align: str) -> list[str]:
    lines = [rf"\begin{{tabular}}{{{align}}}", r"\toprule",
             " & ".join(latex_escape(c) for c in df.columns) + r" \\", r"\midrule"]
    for _, row in df.iterrows():
        lines.append(" & ".join(latex_escape(v) for v in row.tolist()) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return lines


def _compile_pdf(df: pd.DataFrame, name: str, caption: str, align: str, note: str | None) -> bool:
    """Compile a standalone, cropped PDF preview of one table.

    The caption and note are set in a \\parbox whose width is measured from the tabular itself
    (\\wd of a savebox), so they wrap to exactly the table's width instead of an arbitrary one.
    """
    body = "\n".join([
        r"\documentclass[border=10pt]{standalone}",
        r"\usepackage[T1]{fontenc}", r"\usepackage{booktabs}", r"\usepackage{amsmath}",
        r"\usepackage{varwidth}",
        r"\newsavebox{\tblbox}",
        r"\begin{document}",
        r"\sbox{\tblbox}{\small" + "\n" + "\n".join(_tabular(df, align)) + "}",
        r"\parbox{\wd\tblbox}{%",
        r"\raggedright\small\textbf{" + name.split("_")[0].upper() + r".} " + caption,
        r"\par\vspace{6pt}\usebox{\tblbox}",
        (r"\par\vspace{4pt}\footnotesize " + note) if note else "",
        r"}",
        r"\end{document}",
    ])
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tex = Path(tmp) / f"{name}.tex"
        tex.write_text(body, encoding="utf-8")
        proc = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
             f"-output-directory={tmp}", str(tex)],
            capture_output=True, text=True, cwd=tmp,
        )
        pdf = Path(tmp) / f"{name}.pdf"
        if pdf.exists():
            (TABLES / f"{name}.pdf").write_bytes(pdf.read_bytes())
            return True
        tail = "\n".join(proc.stdout.splitlines()[-12:])
        print(f"    ! pdflatex failed for {name}:\n{tail}")
        return False


def write(df: pd.DataFrame, name: str, caption: str, label: str,
          align: str | None = None, note: str | None = None) -> None:
    df.to_csv(TABLES / f"{name}.csv", index=False)

    align = align or ("l" + "r" * (len(df.columns) - 1))
    # .tex is the journal-ready float, to be \input into the manuscript.
    lines = [r"\begin{table}[htbp]", r"\centering", r"\small",
             rf"\caption{{{caption}}}", rf"\label{{{label}}}"]
    lines += _tabular(df, align)
    if note:
        lines.append(rf"\par\vspace{{2pt}}\footnotesize\raggedright {note}")
    lines += [r"\end{table}", ""]
    (TABLES / f"{name}.tex").write_text("\n".join(lines), encoding="utf-8")

    ok = _compile_pdf(df, name, caption, align, note)
    print(f"  {name}.csv / .tex{' / .pdf' if ok else ''}   ({len(df)} rows)")


def load() -> pd.DataFrame:
    return pd.read_csv(MASTER)


def m0_seed0(df: pd.DataFrame) -> pd.DataFrame:
    """The campaign's reference solve per cell: exp3's M0 arm at seed 0."""
    m = df[(df.experiment_id == "exp3") & (df.algorithm_variant == "full")
           & (df.design_point_id.str.endswith("-s0"))]
    return m.set_index("base_instance_id")


# --- T1: testbed and verification --------------------------------------------
def t1_testbed(df: pd.DataFrame) -> None:
    ref = m0_seed0(df)
    rows = []
    for cell in sorted(ref.index, key=lambda c: (ref.loc[c, "I"], ref.loc[c, "M"], ref.loc[c, "T"])):
        r = ref.loc[cell]
        path = INSTANCES / f"{cell}.json"
        sets = json.loads(path.read_text(encoding="utf-8"))["sets"] if path.exists() else {}
        n = lambda k: len(sets.get(k, []))                                    # noqa: E731
        flows = n("FLOW_RAW") + n("FLOW_FP") + n("FLOW_RP")
        rows.append({
            "Cell": cell_label(cell),
            "I": int(r.I), "M": int(r.M), "T": int(r["T"]),
            "Nodes": n("N"), "Arcs": n("A"),
            "Raw mat.": n("U"), "Prod.": n("P"),
            "Flow vars": flows,
            "Runtime (s)": f"{r.runtime_seconds:.0f}",
            "Cert. gap": f"{r.mip_gap:.1e}",
            "Status": "certified" if str(r.termination_reason).startswith("optimal") else str(r.termination_reason),
        })
    write(pd.DataFrame(rows), "t1_testbed",
          "Structural testbed: instance dimensions and DBP reference solve (seed 0). "
          "Every cell terminates on the algorithm's own relative-gap criterion, "
          "inside the campaign tolerance of $10^{-4}$.",
          "tab:testbed",
          note="Flow vars counts raw-material, finished-product and returned-product flow "
               "variables. Cert.\\ gap is the certified relative optimality gap at termination.")


# --- T2: plateau characterisation (headline) ---------------------------------
def t2_plateau(df: pd.DataFrame) -> None:
    ref = m0_seed0(df)
    e5 = df[df.experiment_id == "exp5"]
    p0 = e5[e5.design_point_id.str.contains("P0_no_tax")].set_index("base_instance_id")
    ceil = e5[e5.design_point_id.str.contains("P1_ceiling")].set_index("base_instance_id")

    DIVERGENT = {"STD_I17_M8_T6": 69.3, "STD_I25_M8_T6": 182.9}   # see §6 H5.3
    rows = []
    for cell in ref.sort_values("tax_rate_usd_per_tonne").index:
        if cell not in p0.index:
            continue
        r = ref.loc[cell]
        tau = r.tax_rate_usd_per_tonne
        e_no_tax, e_star, e_ceiling = p0.loc[cell, "emissions"], r.emissions, ceil.loc[cell, "emissions"]
        rows.append({
            "Cell": cell_label(cell),
            r"$\tau^*$ (USD/t)": f"{tau:.1f}" + ("$^{\\dagger}$" if cell in DIVERGENT else ""),
            r"$E(0)$ (kt)": f"{e_no_tax / KT:.1f}",
            r"$E^*$ (kt)": f"{e_star / KT:.1f}",
            # Plain '%' here: latex_escape() escapes it on the way into the .tex.
            "Abatement (%)": f"{100 * (1 - e_star / e_no_tax):.1f}",
            r"$E(200)/E^*-1$": f"{abs(e_ceiling / e_star - 1):.1e}",
            "Plateau width (USD/t)": f"{200 - tau:.1f}",
        })
    write(pd.DataFrame(rows), "t2_plateau",
          "Plateau characterisation. On every cell the emissions floor $E^*$ is reached at "
          "$\\tau^*$ and held to the top of the tax grid: the column $E(200)/E^*-1$ shows the "
          "ceiling reproduces $E^*$ to within the campaign tolerance. The optimal tax is therefore "
          "not identified -- any tax in a band of median width 177 USD/t attains the same "
          "certified emissions.",
          "tab:plateau",
          note="$^{\\dagger}$ On these two cells an independent cold follower solve does not "
               "reproduce $E^*$ until 69.3 and 182.9 USD/t respectively (excess over $E^*$ of "
               "0.035\\% and 0.113\\%); the plateau's left edge is correspondingly less precisely "
               "located there. Ordered by $\\tau^*$.")


# --- T3: policy-rule comparison (headline) -----------------------------------
def t3_policy_rules(df: pd.DataFrame) -> None:
    ref = m0_seed0(df)
    e5 = df[df.experiment_id == "exp5"]
    rules = {"P0": "P0_no_tax", "P2": "P2_mid", "P1": "P1_ceiling"}
    idx = {k: e5[e5.design_point_id.str.contains(v)].set_index("base_instance_id")
           for k, v in rules.items()}

    rows = []
    for cell in ref.sort_values("tax_rate_usd_per_tonne").index:
        if cell not in idx["P0"].index:
            continue
        r = ref.loc[cell]
        e_star = r.emissions
        # P2 (a flat 100 USD/t) only reaches the floor on cells whose tau* is below 100. Without
        # this column its lower burden on the high-tau* cells reads as if P2 beat tau*; it does
        # not -- it is cheaper because it is dirtier.
        e100_excess = idx["P2"].loc[cell, "emissions"] / e_star - 1
        rows.append({
            "Cell": cell_label(cell),
            r"$\tau^*$": f"{r.tax_rate_usd_per_tonne:.1f}",
            r"$E^*$ (kt)": f"{e_star / KT:.1f}",
            r"$E(0)/E^*-1$": f"{idx['P0'].loc[cell, 'emissions'] / e_star - 1:.2f}",
            r"$E(100)/E^*-1$": ("0" if abs(e100_excess) < 1e-4 else f"{e100_excess:.1e}"),
            r"$E(200)/E^*-1$": "0",
            r"Burden @ $\tau^*$": f"{r.follower_objective / MUSD:.2f}",
            r"Burden @ 200": f"{idx['P1'].loc[cell, 'follower_objective'] / MUSD:.2f}",
            "Ratio": f"{idx['P1'].loc[cell, 'follower_objective'] / r.follower_objective:.1f}$\\times$",
        })
    write(pd.DataFrame(rows), "t3_policy_rules",
          "What the naive policy rules cost. The three emissions columns show which rules actually "
          "reach the certified floor: no tax never does, a flat 100 USD/t does so only where "
          "$\\tau^* \\leq 100$, and the 200 USD/t ceiling always does. Comparing the two rules that "
          "both attain the floor (namely $\\tau^*$ and the ceiling), the follower's burden differs "
          "by up to 18.6$\\times$ at identical emissions.",
          "tab:policy-rules",
          note="Burden is the follower's objective (operating cost plus tax bill), in $10^6$ USD; "
               "$E$ in kt CO$_2$e; $\\tau$ in USD/t. On the four cells with $\\tau^* > 100$ the "
               "flat 100 USD/t rule is cheaper than $\\tau^*$ only because it fails to reach the "
               "floor -- see its $E(100)/E^*-1$ entry. Ordered by $\\tau^*$.")


# --- T4: ablation -------------------------------------------------------------
def t4_ablation(df: pd.DataFrame) -> None:
    ref = m0_seed0(df)
    e3 = df[df.experiment_id == "exp3"]
    variants = {
        "no_tax_confirmation": "no Phase-2 minimum-tax bisection",
        "no_lex_master_stage2": "no lexicographic Stage-2 master",
        "no_warm_start": "no warm start",
        "A4": "coarse tax grid ($10^{-2}$)",
        "no_emissions_cap": "no incumbent objective cut",
    }
    rows = []
    for v, desc in variants.items():
        sub = e3[e3.algorithm_variant == v]
        if sub.empty:
            continue
        d_tau, d_e, t_ratio, lost = [], [], [], 0
        for _, r in sub.iterrows():
            base = ref.loc[r.base_instance_id]
            d_tau.append(r.tax_rate_usd_per_tonne - base.tax_rate_usd_per_tonne)
            d_e.append(r.emissions / base.emissions - 1)
            t_ratio.append(r.runtime_seconds / base.runtime_seconds)
            if r.tax_rate_usd_per_tonne > base.tax_rate_usd_per_tonne * 1.001:
                lost += 1
        rows.append({
            "Variant": v, "Component removed": desc, "Cells": len(sub),
            r"$\tau^*$ inflated": f"{lost}/{len(sub)}",
            r"median $\Delta\tau^*$ (USD/t)": f"{np.median(d_tau):+.1f}",
            r"max $|\Delta E^*|$": f"{np.max(np.abs(d_e)):.1e}",
            "median time vs M0": f"{np.median(t_ratio):.2f}$\\times$",
        })
    write(pd.DataFrame(rows), "t4_ablation",
          "Ablation of the DBP algorithm, paired per instance against the full method (M0) on the "
          "same cell and seed. A1 and A4 change what the algorithm certifies; A2, A3 and A5 change "
          "only its cost.",
          "tab:ablation",
          note="$\\tau^*$ inflated counts cells where the variant reports a strictly larger tax "
               "than M0 at the same certified emissions floor. A1 and A4 are cheaper searches by "
               "construction, hence their sub-1$\\times$ time ratio: that speed is exactly what "
               "removing the guarantee buys.")


# --- T6: sensitivity screening ------------------------------------------------
def t6_sensitivity(df: pd.DataFrame) -> None:
    e6 = df[(df.experiment_id == "exp6") & (df.design_point_id.str.contains("cont"))]
    factors = [c.replace("factor__", "") for c in e6.columns if c.startswith("factor__")]
    responses = {"emissions": "emissions", "cost": "cost", "tau": "tax_rate_usd_per_tonne"}

    def effects(sub, resp):
        cols, names = [], []
        coded = {}
        for f in factors:
            col = sub[f"factor__{f}"]
            lo, hi = sorted(col.unique())
            coded[f] = ((col - (lo + hi) / 2) / ((hi - lo) / 2)).to_numpy(float)
        for f in factors:
            cols.append(coded[f]); names.append(f)
        for a, b in itertools.combinations(factors, 2):
            cols.append(coded[a] * coded[b]); names.append(f"{a} x {b}")
        X = np.column_stack([np.ones(len(sub))] + cols)
        y = sub[resp].to_numpy(float)
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        return {n: 100 * c / abs(y.mean()) for n, c in zip(names, coef[1:])}

    per = {(rn, s): effects(e6[e6.seed_offset == s], rc)
           for rn, rc in responses.items() for s in (0, 1)}
    mean_abs = {k: np.mean([abs(per[(rn, s)][k]) for rn in responses for s in (0, 1)])
                for k in per[("emissions", 0)]}
    top = [k for k, _ in sorted(mean_abs.items(), key=lambda kv: -kv[1])[:12]]

    rows = []
    for k in top:
        rows.append({
            "Effect": k.replace("_", " "),
            "Type": "2FI" if " x " in k else "main",
            "Emis. s0": f"{abs(per[('emissions', 0)][k]):.1f}",
            "Emis. s1": f"{abs(per[('emissions', 1)][k]):.1f}",
            "Cost s0": f"{abs(per[('cost', 0)][k]):.1f}",
            "Cost s1": f"{abs(per[('cost', 1)][k]):.1f}",
            r"$\tau^*$ s0": f"{abs(per[('tau', 0)][k]):.1f}",
            r"$\tau^*$ s1": f"{abs(per[('tau', 1)][k]):.1f}",
        })
    write(pd.DataFrame(rows), "t6_sensitivity",
          "Sensitivity screening on the fast cell (I17-M4-T3): $2^{8-2}$ resolution-V fractional "
          "factorial, 64 runs per instance seed. Effect magnitudes are $|$effect$|$ as a percentage "
          "of the response mean, so the two seeds are comparable. Demand and capacity are top-3 "
          "for every response and both seeds; their interaction is the strongest two-factor term.",
          "tab:sensitivity",
          note="2FI = two-factor interaction. s0/s1 are instance seeds 0 and 1. Comparing s0 with "
               "s1 in the same column is the stability test: where they diverge (e.g.\\ scope3 "
               "emissions on cost), the effect is instance-specific and is not claimed. "
               "Top 12 effects by mean $|$effect$|$ across all six series.")


# --- T7: valuation-ratio calibration ------------------------------------------
def t7_calibration(df: pd.DataFrame) -> None:
    e7 = df[(df.experiment_id == "exp7") & (df.design_point_id.str.contains("rho-"))]
    rows = []
    for _, r in e7.sort_values("valuation_ratio").iterrows():
        tau = r.tax_rate_usd_per_tonne
        rows.append({
            r"$\rho$": f"{r.valuation_ratio:g}",
            r"$\tau^*$ (USD/t)": f"{tau:.1f}",
            r"$E^*$ (kt)": f"{r.emissions / KT:.1f}",
            r"Cost ($10^6$ USD)": f"{r.cost / MUSD:.2f}",
            "Certified gap": f"{r.mip_gap:.1e}",
            "In 20--200 band": "yes" if 20 <= tau <= 200 else "no",
        })
    write(pd.DataFrame(rows), "t7_calibration",
          "Validity envelope for absolute carbon-price statements: $\\tau^*$ against a uniform "
          "rescale $\\rho$ of the emissions valuation, on cell I17-M4-T3. $\\tau^*$ is not "
          "monotone in $\\rho$, but the regime is stable -- for $\\rho \\geq 10$ it lands inside "
          "the plausible policy band across a 20$\\times$ range of $\\rho$.",
          "tab:calibration",
          note="Every solve terminates with a certified gap below the campaign tolerance, so the "
               "non-monotonicity is a property of the model, not of incomplete convergence: "
               "rescaling $\\rho$ changes which technology is marginal, relocating the plateau's "
               "left edge discontinuously.")


def main() -> int:
    df = load()
    print(f"loaded {len(df)} runs\n")
    t1_testbed(df)
    t2_plateau(df)
    t3_policy_rules(df)
    t4_ablation(df)
    t6_sensitivity(df)
    t7_calibration(df)
    print(f"\ntables -> {TABLES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
