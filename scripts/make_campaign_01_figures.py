"""Publication figures for campaign_01, built from the aggregated master table.

Run: python scripts/make_campaign_01_figures.py
Outputs PDF (vector, for LaTeX) + PNG (for viewing) to results/analysis/campaign_01/figures/.

Design notes (dataviz method):
- Form is chosen by the data's job, before color. Fig 1/2/4 are single-series
  (emphasis: one hue + gray); only Fig 3 and Fig 5 carry a real categorical
  distinction, and both use exactly two slots.
- The two categorical slots are the reference palette's slots 1-2 (#2a78d6 blue,
  #eb6834 orange), validated against paper white: normal-vision OKLab dE 33.6
  (floor 15), worst CVD dE 24.7 (target 8), contrast 4.42:1 / 3.20:1 (min 3.0).
- Every 2-series figure also separates by hatch/marker, so identity survives
  greyscale printing and full CVD -- never colour alone.
- Single surface (paper white): these are print figures, so there is no dark mode.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

TABLE = REPO_ROOT / "results" / "analysis" / "campaign_01" / "tables" / "master_runs_campaign_01.csv"
FIGDIR = REPO_ROOT / "results" / "analysis" / "campaign_01" / "figures"

# --- design tokens ------------------------------------------------------------
SERIES_1 = "#2a78d6"   # categorical slot 1 (blue)
SERIES_2 = "#eb6834"   # categorical slot 2 (orange)
INK = "#0b0b0b"        # text-primary
INK_2 = "#52514e"      # text-secondary
MUTED = "#8a8985"      # de-emphasis / recessive axes
PLATEAU_FILL = "#dfe9f7"   # a light tint of slot 1, for the shaded plateau region

plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 300, "savefig.bbox": "tight",
    "font.size": 9, "axes.titlesize": 9.5, "axes.labelsize": 9,
    "axes.edgecolor": MUTED, "axes.linewidth": 0.6, "axes.labelcolor": INK_2,
    "xtick.color": INK_2, "ytick.color": INK_2,
    "xtick.labelsize": 8, "ytick.labelsize": 8,
    "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": "#e6e5e1", "grid.linewidth": 0.6,
    "legend.frameon": False, "legend.fontsize": 8.5,
    "lines.linewidth": 1.4,
})


def save(fig, name: str) -> None:
    FIGDIR.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(FIGDIR / f"{name}.{ext}")
    plt.close(fig)
    print(f"  wrote {name}.pdf / .png")


def load() -> pd.DataFrame:
    return pd.read_csv(TABLE)


def cell_label(cell: str) -> str:
    return cell.replace("STD_", "").replace("_", "-")


def tau_star_table(df: pd.DataFrame) -> pd.DataFrame:
    """tau* / E* per cell, from exp3's M0 seed-0 arm (the campaign's reference solve)."""
    m0 = df[(df.experiment_id == "exp3") & (df.algorithm_variant == "M0")
            & (df.design_point_id.str.endswith("-s0"))]
    out = m0.set_index("base_instance_id")[["tax_rate_usd_per_tonne", "emissions",
                                             "cost", "follower_objective"]]
    out.columns = ["tau_star", "E_star", "cost_star", "fobj_star"]
    return out


# --- Fig 1: the plateau staircase (headline) ----------------------------------
def fig_plateau_staircase(df: pd.DataFrame) -> None:
    """Job: show that tau* is the LEFT EDGE of the region where E reaches its certified floor.

    Plotted as excess over E* on a log axis, not as raw emissions: the final step down to E*
    is ~0.1% on several cells, which is invisible on a linear emissions axis -- a raw plot
    reads as if the plateau began far below tau*, i.e. as if the tie-break were fussing over
    nothing. On a log-excess axis every step that matters to the plateau definition is legible.
    Single series per panel -> emphasis form (one hue + gray), no categorical palette.
    """
    DELTA_PCT = 100 * 1e-4        # the campaign's dbp_relative_gap, as a percentage
    FLOOR_PCT = 1e-3              # display floor: points at E* are clipped to inside the band

    ts = tau_star_table(df)
    e5 = df[df.experiment_id == "exp5"]
    cells = ts.sort_values("tau_star").index.tolist()

    fig, axes = plt.subplots(3, 4, figsize=(11.4, 7.4), sharex=True, sharey=True)
    for ax, cell in zip(axes.ravel(), cells):
        sub = e5[e5.base_instance_id == cell].sort_values("tax_rate_usd_per_tonne")
        tax = sub.tax_rate_usd_per_tonne.to_numpy(float)
        emis = sub.emissions.to_numpy(float)
        if len(tax) == 0:
            ax.axis("off")
            continue
        e_star = float(ts.loc[cell, "E_star"])
        tau = float(ts.loc[cell, "tau_star"])
        excess_raw = 100 * (emis - e_star) / e_star
        excess = np.clip(excess_raw, FLOOR_PCT, None)
        abatement = 100 * (1 - e_star / emis[tax == 0][0]) if (tax == 0).any() else np.nan

        # Independent verification of tau*: does the refinement point just ABOVE tau* already
        # sit inside the tolerance band? On 10/12 cells yes; on the two hardest (M8-T6) an
        # independent cold follower solve does not reproduce E* until a materially higher tax.
        above = np.where(tax > tau)[0]
        verified_edge = None
        if len(above) and excess_raw[above[0]] > DELTA_PCT:
            in_band = np.where(excess_raw <= DELTA_PCT)[0]
            if len(in_band):
                verified_edge = float(tax[in_band[0]])

        ax.axhspan(FLOOR_PCT * 0.5, DELTA_PCT, color=PLATEAU_FILL, lw=0, zorder=0)
        ax.step(tax, excess, where="post", color=SERIES_1, zorder=3, solid_capstyle="round")
        ax.plot(tax, excess, "o", ms=3.0, color=SERIES_1, zorder=4)
        ax.axvline(tau, color=INK_2, lw=0.9, ls=(0, (3, 2)), zorder=2)
        if verified_edge is not None:
            ax.axvline(verified_edge, color=SERIES_2, lw=1.1, ls=(0, (1, 1.6)), zorder=2)
            ax.text(verified_edge + 5, 30, f"verified\nedge {verified_edge:.0f}",
                    fontsize=6.8, color=SERIES_2, va="top", ha="left")

        ax.set_yscale("log")
        ax.set_ylim(FLOOR_PCT * 0.5, 400)
        ax.set_xlim(-6, 206)
        # Abatement rides in the title: inside the panel it collides with the tau* rule on the
        # high-tau* cells, where that rule sits far to the right.
        ax.set_title(f"{cell_label(cell)}   $\\tau^*$={tau:.1f}   ·   {abatement:.0f}% abated",
                     color=INK, pad=4, fontsize=8.8)
        ax.grid(axis="y", zorder=0)
        ax.set_axisbelow(True)

    for ax in axes[-1]:
        ax.set_xlabel("carbon tax (USD/t)")
    for ax in axes[:, 0]:
        ax.set_ylabel("excess over $E^*$  (%)")

    axes[0, 0].annotate("plateau: within the\ncertified tolerance of $E^*$",
                        xy=(150, DELTA_PCT), xytext=(60, 0.6), color=INK_2, fontsize=7.4,
                        ha="left", arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.7))

    fig.suptitle("A wide plateau: emissions reach their certified floor far below the grid ceiling "
                 "and hold there",
                 fontsize=10.5, color=INK, y=0.998)
    fig.text(0.5, -0.028,
             "Shaded band = within $10^{-4}$ of the certified floor $E^*$ (the campaign's DBP tolerance), i.e. on the plateau. "
             "Dashed grey line = $\\tau^*$ as reported by DBP; independent follower solves confirm it on 10 of 12 cells.\n"
             "On the two hardest cells (M8-T6) a cold follower solve does not reproduce $E^*$ until a higher tax — "
             "the dotted orange line marks that independently verified edge. Panels ordered by $\\tau^*$.",
             ha="center", fontsize=7.8, color=INK_2)
    fig.tight_layout()
    save(fig, "fig1_plateau_staircase")


# --- Fig 2: burden ratio (the headline number) --------------------------------
def fig_burden_ratio(df: pd.DataFrame) -> None:
    """Job: compare one magnitude across 12 cells -> sorted horizontal bar, single hue."""
    ts = tau_star_table(df)
    e5 = df[df.experiment_id == "exp5"]
    ceiling = (e5[e5.design_point_id.str.contains("P1_ceiling")]
               .set_index("base_instance_id")["follower_objective"])

    rows = []
    for cell in ts.index:
        if cell in ceiling.index:
            rows.append((cell, ceiling[cell] / ts.loc[cell, "fobj_star"],
                         ts.loc[cell, "tau_star"]))
    t = pd.DataFrame(rows, columns=["cell", "ratio", "tau_star"]).sort_values("ratio")

    fig, ax = plt.subplots(figsize=(7.4, 4.4))
    ypos = np.arange(len(t))
    ax.barh(ypos, t.ratio, height=0.62, color=SERIES_1, zorder=3)
    ax.axvline(1.0, color=MUTED, lw=0.8, zorder=2)

    for y, (r, tau) in enumerate(zip(t.ratio, t.tau_star)):
        ax.text(r + 0.28, y, f"{r:.1f}×", va="center", ha="left",
                fontsize=8.2, color=INK)

    ax.set_yticks(ypos, [f"{cell_label(c)}  ($\\tau^*$={s:.1f})" for c, s in zip(t.cell, t.tau_star)])
    ax.set_xlabel("follower burden at the 200 USD/t ceiling  ÷  burden at $\\tau^*$")
    ax.set_xlim(0, t.ratio.max() * 1.16)
    ax.grid(axis="x", zorder=0)
    ax.set_axisbelow(True)
    ax.set_title("Cost of picking the wrong point on the plateau", color=INK, pad=8)
    fig.text(0.5, -0.03,
             "Identical certified emissions in every case. Bars show what the follower pays "
             "at the ceiling relative to $\\tau^*$.",
             ha="center", fontsize=8, color=INK_2)
    fig.tight_layout()
    save(fig, "fig2_burden_ratio")


# --- Fig 3: exp6 effect sizes, by seed (H6.1 / H6.2) --------------------------
def _coded(sub: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    out = pd.DataFrame(index=sub.index)
    for f in factors:
        col = sub[f"factor__{f}"]
        lo, hi = sorted(col.unique())
        out[f] = (col - (lo + hi) / 2) / ((hi - lo) / 2)
    return out


def _effects(sub: pd.DataFrame, factors: list[str], resp: str) -> dict[str, float]:
    import itertools
    C = _coded(sub, factors)
    cols, names = [], []
    for f in factors:
        cols.append(C[f].to_numpy(float)); names.append(f)
    for a, b in itertools.combinations(factors, 2):
        cols.append(C[a].to_numpy(float) * C[b].to_numpy(float)); names.append(f"{a}×{b}")
    X = np.column_stack([np.ones(len(sub))] + cols)
    y = sub[resp].to_numpy(float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    # Report as % of the response mean so the two seeds are on a comparable scale.
    scale = abs(y.mean())
    return {n: 100 * c / scale for n, c in zip(names, coef[1:])}


def fig_exp6_effects(df: pd.DataFrame) -> None:
    """Job: which factors drive each response, and is that stable across seeds?
    Two series (seed 0 / seed 1) -> categorical slots 1-2, plus hatch for greyscale."""
    e6 = df[(df.experiment_id == "exp6") & (df.design_point_id.str.contains("cont"))]
    factors = [c.replace("factor__", "") for c in e6.columns if c.startswith("factor__")]
    responses = [("emissions", "emissions"), ("cost", "cost"),
                 ("$\\tau^*$ (USD/t)", "tax_rate_usd_per_tonne")]

    fig, axes = plt.subplots(1, 3, figsize=(12.4, 5.0))
    for ax, (label, col) in zip(axes, responses):
        per_seed = {s: _effects(e6[e6.seed_offset == s], factors, col) for s in (0, 1)}
        mean_abs = {k: (abs(per_seed[0][k]) + abs(per_seed[1][k])) / 2 for k in per_seed[0]}
        top = [k for k, _ in sorted(mean_abs.items(), key=lambda kv: -kv[1])[:9]][::-1]

        ypos = np.arange(len(top))
        h = 0.36
        ax.barh(ypos + h / 2, [abs(per_seed[0][k]) for k in top], height=h,
                color=SERIES_1, label="seed 0", zorder=3)
        ax.barh(ypos - h / 2, [abs(per_seed[1][k]) for k in top], height=h,
                color=SERIES_2, hatch="///", edgecolor="white", linewidth=0.0,
                label="seed 1", zorder=3)

        ax.set_yticks(ypos, [k.replace("_", " ") for k in top], fontsize=7.6)
        ax.set_xlabel("|effect|  (% of response mean)")
        ax.set_title(label, color=INK, pad=6)
        ax.grid(axis="x", zorder=0)
        ax.set_axisbelow(True)

    axes[0].legend(loc="lower right")
    fig.suptitle("Sensitivity screening: dominant factors and two-factor interactions",
                 fontsize=11, color=INK, y=1.0)
    fig.text(0.5, -0.035,
             "2$^{(8-2)}$ resolution-V fractional factorial, 64 runs per seed, fast cell I17-M4-T3. "
             "× denotes a two-factor interaction. Top 9 effects by mean |effect| across seeds.",
             ha="center", fontsize=8, color=INK_2)
    fig.tight_layout()
    save(fig, "fig3_exp6_effects")


# --- Fig 4: tau*(rho) -- exp7 -------------------------------------------------
def fig_tau_vs_rho(df: pd.DataFrame) -> None:
    """Job: change of tau* over rho. Single series -> one hue + a shaded reference band."""
    e7 = df[(df.experiment_id == "exp7") & (df.design_point_id.str.contains("rho-"))]
    t = e7[["valuation_ratio", "tax_rate_usd_per_tonne"]].dropna().sort_values("valuation_ratio")

    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    ax.axhspan(20, 200, color=PLATEAU_FILL, lw=0, zorder=0)
    ax.text(1.05, 205, "plausible policy band (20–200 USD/t)",
            fontsize=7.8, color=INK_2, va="bottom")
    ax.plot(t.valuation_ratio, t.tax_rate_usd_per_tonne, "-o",
            color=SERIES_1, ms=5.0, zorder=3)
    for x, y in zip(t.valuation_ratio, t.tax_rate_usd_per_tonne):
        ax.annotate(f"{y:.0f}", (x, y), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=7.6, color=INK)

    ax.set_xscale("log")
    ax.set_xticks(t.valuation_ratio, [f"{v:g}" for v in t.valuation_ratio])
    ax.set_xlabel("emissions valuation ratio  $\\rho$  (log scale)")
    ax.set_ylabel("$\\tau^*$  (USD/t)")
    ax.set_ylim(0, 245)
    ax.grid(axis="y", zorder=0)
    ax.set_axisbelow(True)
    ax.set_title("$\\tau^*$ does not scale smoothly with the valuation ratio", color=INK, pad=8)
    fig.text(0.5, -0.04,
             "All seven solves terminate with a certified gap $\\leq 10^{-4}$: the non-monotonicity is a "
             "property of the model, not of incomplete convergence. Cell I17-M4-T3.",
             ha="center", fontsize=8, color=INK_2)
    fig.tight_layout()
    save(fig, "fig4_tau_vs_rho")


# --- Fig 5: exp8 DBP vs exhaustive enumeration --------------------------------
def fig_exp8_benchmark(df: pd.DataFrame) -> None:
    """Job: compare a cost magnitude between two methods -> 2 categorical slots + hatch."""
    exhausted = {"STD_I17_M4_T3": 11, "STD_I17_M4_T6": 15}   # DBP follower solves (loop + Phase 2)
    enum_n = 2001

    fig, ax = plt.subplots(figsize=(7.6, 3.0))
    cells = list(exhausted)
    ypos = np.arange(len(cells))
    h = 0.26
    ax.barh(ypos + h * 0.62, [exhausted[c] for c in cells], height=h,
            color=SERIES_1, label="DBP (loop + Phase 2)", zorder=3)
    ax.barh(ypos - h * 0.62, [enum_n] * len(cells), height=h,
            color=SERIES_2, hatch="///", edgecolor="white", linewidth=0.0,
            label="exhaustive enumeration", zorder=3)

    for y, c in enumerate(cells):
        ax.text(exhausted[c] * 1.3, y + h * 0.62, f"{exhausted[c]}", va="center",
                fontsize=8.2, color=INK)
        ax.text(enum_n * 1.3, y - h * 0.62, f"{enum_n}", va="center", fontsize=8.2, color=INK)
        ax.text(9500, y, f"{enum_n / exhausted[c]:.0f}× fewer",
                va="center", ha="left", fontsize=8.6, color=INK)

    ax.set_xscale("log")
    ax.set_xlim(4, 33000)
    ax.set_ylim(-0.55, len(cells) - 0.45)
    ax.set_yticks(ypos, [cell_label(c) for c in cells])
    ax.set_xlabel("follower MILP solves to certify $(E^*, \\tau^*)$  (log scale)")
    ax.grid(axis="x", zorder=0)
    ax.set_axisbelow(True)
    # Legend above the plot area: inside it would sit on top of the 2001 labels.
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.02), ncol=2)
    ax.set_title("Both methods certify the same optimum; one needs two orders of magnitude fewer solves",
                 color=INK, pad=26, fontsize=9.5)
    fig.text(0.5, -0.08,
             "Only the two cells where enumeration exhausted the full 2001-point grid are shown; "
             "on those, both methods return identical $(E^*, \\tau^*)$.",
             ha="center", fontsize=8, color=INK_2)
    fig.tight_layout()
    save(fig, "fig5_exp8_benchmark")


def main() -> int:
    df = load()
    print(f"loaded {len(df)} runs")
    fig_plateau_staircase(df)
    fig_burden_ratio(df)
    fig_exp6_effects(df)
    fig_tau_vs_rho(df)
    fig_exp8_benchmark(df)
    print(f"\nfigures -> {FIGDIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
