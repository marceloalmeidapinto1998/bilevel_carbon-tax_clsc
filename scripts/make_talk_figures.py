"""Slide figures for the CONTROLO 2026 talk, built ONLY from the numbers printed
in the submitted paper (CONTROLO_2026_paper_3877). No run data is read.

Run: python scripts/make_talk_figures.py
Outputs PDF (vector) + PNG (for slides) to paper/figures/talk/.

Provenance of every number is annotated at its literal below: Table I, or the
Section IV paragraph it comes from. Where the paper does not report a quantity
(the shape of the tax response between 0 and tau*, the per-iteration DBP bounds,
the per-instance technology-menu effects), the figure either omits it or draws it
in the muted "illustrative" register -- it is never fabricated in the data colour.

Design notes (dataviz method):
- Sized for projection, not for a two-column paper: larger type, wider canvas.
- Form before colour. Fig 1 and 3 are single-series (one hue + gray, no legend
  box -- the title names the series); Fig 2 is not a chart at all but a stat-tile
  row, because "8/8 converged" has no magnitude to plot; Fig 4 and 5 carry a real
  two-way categorical distinction and use exactly the two validated slots.
- Palette: slots 1-2 of the reference palette (#2a78d6, #eb6834) on paper white.
  Validation of this exact pair and surface is recorded in
  make_campaign_01_figures.py: normal-vision OKLab dE 33.6 (floor 15), worst CVD
  dE 24.7 (target 8), contrast 4.42:1 / 3.20:1 (min 3.0). node is unavailable in
  this environment to re-run the validator.
- Two-series figures separate by hatch as well as hue, so identity survives
  greyscale printing and full CVD.
- Single surface (light): these are projected on a light slide master.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
FIGDIR = REPO_ROOT / "paper" / "figures" / "talk"

# --- design tokens (shared with the paper figures) ----------------------------
SERIES_1 = "#2a78d6"   # categorical slot 1 (blue) -- carries "reported in the paper"
SERIES_2 = "#eb6834"   # categorical slot 2 (orange)
INK = "#0b0b0b"        # text-primary
INK_2 = "#52514e"      # text-secondary
MUTED = "#8a8985"      # de-emphasis / recessive axes / the "illustrative" register
GRID = "#e6e5e1"
TILE_FILL = "#f6f7f9"
PLATEAU_FILL = "#dfe9f7"   # light tint of slot 1

plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 240, "savefig.bbox": "tight",
    "savefig.facecolor": "white", "figure.facecolor": "white",
    "font.size": 13, "axes.titlesize": 15, "axes.labelsize": 13,
    "axes.edgecolor": MUTED, "axes.linewidth": 0.8, "axes.labelcolor": INK_2,
    "xtick.color": INK_2, "ytick.color": INK_2,
    "xtick.labelsize": 12, "ytick.labelsize": 12,
    "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": GRID, "grid.linewidth": 0.8,
    "legend.frameon": False, "legend.fontsize": 12,
    "lines.linewidth": 2.0,
})


def save(fig, name: str) -> None:
    FIGDIR.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(FIGDIR / f"{name}.{ext}")
    plt.close(fig)
    print(f"  wrote {name}.pdf / .png")


# --- the paper's numbers ------------------------------------------------------
# Table I: instance, tau* (USD/tCO2e), dE (%), dC (%)
TABLE_I = [
    ("I17-M4-T3", 200, -28.4, 14.2),
    ("I17-M4-T6", 190,  -9.3,  3.4),
    ("I17-M8-T3", 140, -23.9, 75.6),
    ("I17-M8-T6", 200,  -8.7,  5.0),
    ("I25-M4-T3", 180, -35.4, 75.9),
    ("I25-M4-T6",  20, -57.6, 20.6),
    ("I25-M8-T3", 140, -48.4, 14.9),
    ("I25-M8-T6", 100,  -8.6,  5.2),
]


def fig_plateau() -> None:
    """Section IV findings 1-2, plus Table I row I17-M8-T3: tau* = 140,
    dE = -23.9%, dC = +75.6%, and the response "stays flat across 140-310".

    The paper does NOT report the response between tau = 0 and tau*, so that
    region is drawn as an illustrative staircase in the muted register and
    labelled as such. Only the two anchors and the plateau are paper data.
    """
    fig, ax = plt.subplots(figsize=(9.6, 5.2))

    tau_star, e_star, plateau_end = 140, 100 - 23.9, 310

    # illustrative staircase between the two anchors -- NOT paper data
    steps_x = [0, 45, 45, 85, 85, 115, 115, tau_star]
    steps_y = [100, 100, 93, 93, 86, 86, e_star, e_star]
    ax.plot(steps_x, steps_y, color=MUTED, lw=2.0, ls=(0, (5, 3)), zorder=2)
    ax.text(14, 71.5, "step positions between 0 and " r"$\tau^\star$" "\nnot reported (illustrative)",
            color=MUTED, fontsize=11.5, ha="left", va="center", style="italic")

    # the plateau -- paper data
    ax.axvspan(tau_star, plateau_end, color=PLATEAU_FILL, zorder=0)
    ax.plot([tau_star, plateau_end], [e_star, e_star], color=SERIES_1, lw=2.8, zorder=3)
    ax.scatter([0, tau_star], [100, e_star], s=110, color=SERIES_1,
               edgecolor="white", linewidth=2, zorder=4)

    ax.annotate(r"$\tau^\star = 140$" "\n" r"$-23.9\%$ emissions,  $+75.6\%$ cost",
                xy=(tau_star, e_star), xytext=(tau_star + 20, e_star + 8.5),
                color=INK, fontsize=12.5,
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=1.0))
    ax.text((tau_star + plateau_end) / 2, e_star - 4.5,
            "plateau: no further abatement\nanywhere from 140 to 310",
            color=INK_2, fontsize=12.5, ha="center", va="top")
    ax.text(0, 101.4, r"baseline  $\tau = 0$", color=INK_2, fontsize=12, va="bottom")

    ax.set_xlim(-10, 340)
    ax.set_ylim(64, 108)
    ax.set_xlabel(r"carbon tax  $\tau$  (USD/tCO$_2$e, testbed scale)")
    ax.set_ylabel(r"emissions (index, $\tau = 0$ is 100)")
    ax.set_title("The regulator's optimum is a plateau, not a point   -   I17-M8-T3",
                 color=INK, loc="left", pad=14)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    save(fig, "fig1_plateau_I17_M8_T3")


def fig_convergence_tiles() -> None:
    """Section IV, opening paragraph: "All 8 instances converge with a relative
    gap no greater than <= 1.36e-5 in 2-4 DBP iterations."

    The paper reports no per-iteration bounds, so there is no convergence curve
    to draw honestly -- three headline numbers are the right form.
    """
    tiles = [
        ("8 / 8", "instances solved to\nproven optimality"),
        (r"$\leq 1.36 \times 10^{-5}$", "relative gap\n(UB - LB) / UB"),
        ("2 - 4", "DBP iterations\nper instance"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(12.4, 3.1))
    for ax, (big, small) in zip(axes, tiles):
        ax.axis("off")
        ax.add_patch(plt.Rectangle((0.02, 0.06), 0.96, 0.88, transform=ax.transAxes,
                                   facecolor=TILE_FILL, edgecolor=GRID, lw=1.0))
        ax.text(0.5, 0.64, big, transform=ax.transAxes, ha="center", va="center",
                fontsize=24, color=SERIES_1)
        ax.text(0.5, 0.27, small, transform=ax.transAxes, ha="center", va="center",
                fontsize=13, color=INK_2, linespacing=1.4)
    fig.suptitle("The bounding procedure closes the gap on every instance",
                 fontsize=15, color=INK, x=0.055, ha="left", y=1.05)
    save(fig, "fig2_convergence_tiles")


def fig_cost_vs_abatement() -> None:
    """Table I, all 8 rows, with the Section IV finding-1 annotations
    (I25-M4-T6 at 3.62 USD/t; I17-M8-T3 and I25-M4-T3 above +75% cost).
    """
    fig, ax = plt.subplots(figsize=(9.6, 5.8))
    names = [r[0] for r in TABLE_I]
    cut = np.array([-r[2] for r in TABLE_I])     # emission reduction, positive %
    cost = np.array([r[3] for r in TABLE_I])

    ax.scatter(cut, cost, s=150, color=SERIES_1, edgecolor="white",
               linewidth=2, zorder=3)

    # Direct labels: the five separated points get their own label; the three
    # near-coincident low-response instances share one, via a leader line.
    cluster = {"I17-M4-T6", "I17-M8-T6", "I25-M8-T6"}
    offsets = {
        "I17-M4-T3": (11, 4),
        "I17-M8-T3": (11, 2),
        "I25-M4-T3": (-4, 11),
        "I25-M4-T6": (-13, -4),
        "I25-M8-T3": (0, -22),
    }
    align = {"I25-M4-T6": "right", "I25-M8-T3": "center"}
    for n, x, y in zip(names, cut, cost):
        if n in cluster:
            continue
        dx, dy = offsets[n]
        ax.annotate(n, (x, y), xytext=(dx, dy), textcoords="offset points",
                    color=INK_2, fontsize=12, ha=align.get(n, "left"))
    ax.annotate("3 instances barely respond:\nabout 9% cut for about 5% cost",
                xy=(9.0, 4.6), xytext=(26, -12), textcoords="offset points",
                color=INK_2, fontsize=12, va="center",
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=1.0))
    ax.annotate("cheapest abatement\n(3.62 USD/t)", xy=(57.6, 20.6),
                xytext=(0, 34), textcoords="offset points",
                color=INK_2, fontsize=12, ha="center",
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=1.0))

    ax.set_xlim(0, 70)
    ax.set_ylim(-5, 95)
    ax.set_xlabel(r"emission reduction at $\tau^\star$ (%)")
    ax.set_ylabel(r"cost increase at $\tau^\star$ (%)")
    ax.set_title("Deeper cuts are not the expensive ones", color=INK, loc="left", pad=14)
    ax.grid(True)
    ax.set_axisbelow(True)
    save(fig, "fig3_cost_vs_abatement")


def fig_levers() -> None:
    """Section IV finding 3: the technology menu 3->6 per family cuts emissions
    in all 8 instances by 18.9-37.8%; transport modes 6->12 leave emissions
    near-unchanged (0.24%).

    Per-instance values are not reported, so technology is drawn as its reported
    RANGE, not as eight invented bars.
    """
    fig, ax = plt.subplots(figsize=(9.8, 3.3))

    ax.barh([1], [37.8 - 18.9], left=[18.9], height=0.5, color=SERIES_1,
            edgecolor="white", linewidth=2, zorder=3)
    ax.text(37.8 + 1.4, 1, "18.9 - 37.8%\nin all 8 instances", va="center",
            color=INK_2, fontsize=12.5)

    # 0.24% is far too small to render as a bar -- that IS the finding, so draw a
    # visible tick at the true value rather than exaggerating the bar.
    ax.barh([0], [0.24], height=0.5, color=SERIES_2, zorder=3)
    ax.plot([0.24, 0.24], [-0.25, 0.25], color=SERIES_2, lw=4, zorder=4,
            solid_capstyle="butt")
    ax.text(1.8, 0, "0.24%  -  effectively unchanged", va="center",
            color=INK_2, fontsize=12.5)

    ax.set_yticks([1, 0])
    ax.set_yticklabels([r"technology menu" "\n" r"3 $\rightarrow$ 6 per family",
                        r"transport modes" "\n" r"6 $\rightarrow$ 12"],
                       color=INK, fontsize=13)
    ax.set_xlim(0, 54)
    ax.set_xlabel("emission reduction (%)")
    ax.set_title("Technology is the binding lever; transport is not",
                 color=INK, loc="left", pad=14)
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    fig.text(0.125, -0.16,
             "On I25-M4-T3 the wider technology menu also cuts cost by 41.8%"
             r"  -  a Pareto gain, at any $\tau$.",
             color=INK_2, fontsize=12)
    save(fig, "fig4_levers")


def fig_recovery_elasticity() -> None:
    """Section IV finding 4: the elasticity of the required tax rate with respect
    to return availability is -0.744; that of the attained emissions level is
    -0.001.
    """
    fig, ax = plt.subplots(figsize=(8.8, 3.2))
    labels = [r"tax rate needed  $\tau^\star$", "emissions level attained"]

    ax.barh([0], [-0.744], height=0.5, color=SERIES_1, zorder=3)
    ax.text(-0.744 - 0.025, 0, "-0.744", va="center", ha="right",
            color=INK_2, fontsize=13)

    # -0.001 cannot render as a bar; the tick marks its true position.
    ax.barh([1], [-0.001], height=0.5, color=SERIES_2, zorder=3)
    ax.plot([-0.001, -0.001], [0.75, 1.25], color=SERIES_2, lw=4, zorder=4,
            solid_capstyle="butt")
    ax.text(0.025, 1, "-0.001  -  effectively zero", va="center", ha="left",
            color=INK_2, fontsize=13)

    ax.set_yticks([0, 1])
    ax.set_yticklabels(labels, color=INK, fontsize=13)
    ax.set_xlim(-0.95, 0.32)
    ax.set_xlabel("elasticity with respect to return availability")
    ax.set_title("More recovery buys the same abatement at a lower tax",
                 color=INK, loc="left", pad=14)
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    save(fig, "fig5_recovery_elasticity")


if __name__ == "__main__":
    print(f"Talk figures -> {FIGDIR}")
    fig_plateau()
    fig_convergence_tiles()
    fig_cost_vs_abatement()
    fig_levers()
    fig_recovery_elasticity()
    print("done.")
