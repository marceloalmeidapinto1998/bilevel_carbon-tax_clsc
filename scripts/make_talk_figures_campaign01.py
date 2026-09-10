"""Slide figures built from the LIVE campaign_01 run data (exp1 verification).

Run: python scripts/make_talk_figures_campaign01.py
Outputs PDF (vector) + PNG (for slides) to paper/figures/talk_campaign01/.

Source of truth: results/runs/campaign_01/exp1_verification/<cell>/base/
    summary.json    -- tau index, effective rate, gap, runtime, termination
    dbp_trace.csv   -- per-iteration relaxation lower bound and incumbent

Scope note. exp1 is the ONLY experiment of campaign_01 that has run. exp2, exp3
and exp4 have instances generated but zero solves, and exp1 itself has no
tau = 0 baseline runs. So nothing here can express a change relative to an
untaxed baseline, a tax sweep, a plateau, a menu scenario, or an elasticity --
those all live in experiments that have not been solved. These figures report
what exp1 actually establishes: whether, how fast, and how reliably the DBP
closes its own bounds.

Tax is reported as the campaign's dimensionless rate (effective_tax =
tax_index * 5e-4), never in USD/t: absolute currency claims are reserved for the
exp3 calibration stage on the one instance whose valuation ratio is justified.

Design notes (dataviz method):
- Ten instances is past the point where per-series hues are legitimate, so colour
  encodes the OUTCOME (proven / censored) -- two slots, fixed -- and instance
  identity is carried by direct labels and by the y-axis, never by hue.
- Palette: slots 1-2 of the reference palette (#2a78d6, #eb6834) on paper white;
  validation of this exact pair and surface is recorded in
  make_campaign_01_figures.py. node is unavailable here to re-run the validator.
- Every two-series figure separates by marker or hatch as well as hue.
- Sized for projection: larger type, wider canvas than the paper figures.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNDIR = REPO_ROOT / "results" / "runs" / "campaign_01" / "exp1_verification"
FIGDIR = REPO_ROOT / "paper" / "figures" / "talk_campaign01"

# --- design tokens (shared with the paper figures) ----------------------------
PROVEN = "#2a78d6"     # categorical slot 1 -- gap closed to tolerance
CENSORED = "#eb6834"   # categorical slot 2 -- stopped by a time or wall-clock cap
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#8a8985"
GRID = "#e6e5e1"
TILE_FILL = "#f6f7f9"

# Gaps are reconstructed from the trace and are occasionally a hair negative
# (the relaxation bound overshooting the incumbent by ~1e-7 relative, i.e. solver
# round-off). A log axis cannot show those, so they are drawn at this floor and
# the figure says so.
GAP_FLOOR = 1e-13

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


def load_cells() -> list[dict]:
    """One record per solved cell, with its reconstructed per-iteration gap."""
    cells = []
    for cell_dir in sorted(RUNDIR.iterdir()):
        if not cell_dir.is_dir():
            continue
        summary = cell_dir / "base" / "summary.json"
        trace = cell_dir / "base" / "dbp_trace.csv"
        if not summary.exists():
            continue  # started but not finished -- no result to plot
        record = json.loads(summary.read_text())[0]

        gaps = []
        if trace.exists():
            with trace.open() as handle:
                for row in csv.DictReader(handle):
                    ub = float(row["incumbent_emissions"])
                    lb = float(row["next_relaxation_lower_bound"])
                    gaps.append((ub - lb) / ub if ub else float("nan"))
        # The final, interrupted iteration of a censored run is never written to
        # the trace, so append the gap the run actually reported.
        if not gaps or abs(gaps[-1] - record["relative_gap"]) > 1e-12:
            gaps.append(record["relative_gap"])

        cells.append({
            "name": cell_dir.name.replace("STD_", "").replace("_", "-"),
            "proven": bool(record["exact"]),
            "termination": record["termination_reason"],
            "iterations": record["iterations"],
            "gap": record["relative_gap"],
            "seconds": record["solve_seconds"],
            "tax_index": record["tax_index"],
            "effective_tax": record["effective_tax"],
            "gaps": [max(g, GAP_FLOOR) for g in gaps],
        })
    return cells


def fig_status_tiles(cells: list[dict]) -> None:
    """What exp1 has actually established so far. 12 base cells were designed."""
    designed = 12
    proven = sum(c["proven"] for c in cells)
    censored = len(cells) - proven
    outstanding = designed - len(cells)
    fastest = min(c["seconds"] for c in cells)
    slowest = max(c["seconds"] for c in cells)

    tiles = [
        (f"{proven} / {designed}", "cells closed to\nproven optimality"),
        (f"{censored}", "cells censored by a\ntime or wall-clock cap"),
        (f"{fastest:.0f} s  -  {slowest / 3600:.0f} h", "solve time,\nfastest to slowest"),
    ]
    colors = [PROVEN, CENSORED, INK_2]
    fig, axes = plt.subplots(1, 3, figsize=(12.4, 3.1))
    for ax, (big, small), color in zip(axes, tiles, colors):
        ax.axis("off")
        ax.add_patch(plt.Rectangle((0.02, 0.06), 0.96, 0.88, transform=ax.transAxes,
                                   facecolor=TILE_FILL, edgecolor=GRID, lw=1.0))
        ax.text(0.5, 0.64, big, transform=ax.transAxes, ha="center", va="center",
                fontsize=24, color=color)
        ax.text(0.5, 0.27, small, transform=ax.transAxes, ha="center", va="center",
                fontsize=13, color=INK_2, linespacing=1.4)
    fig.suptitle("Where exp1 stands", fontsize=15, color=INK, x=0.055, ha="left", y=1.05)
    fig.text(0.055, -0.06,
             f"{outstanding} of the 12 designed base cells are still outstanding. "
             "exp2, exp3 and exp4 have not been solved.",
             color=INK_2, fontsize=12)
    save(fig, "c1_status_tiles")


def fig_gap_trajectories(cells: list[dict], compact: bool = False) -> None:
    """Per-iteration relative gap. Colour encodes outcome, not instance.

    `compact` drops the in-figure title and the round-off footnote and shrinks
    the canvas, for the ongoing-work slide where the deck's own frame title
    carries the message and the figure is reproduced smaller.
    """
    fig, ax = plt.subplots(figsize=(7.6, 4.8) if compact else (10.2, 5.8))

    for cell in cells:
        color = PROVEN if cell["proven"] else CENSORED
        xs = range(1, len(cell["gaps"]) + 1)
        ax.plot(xs, cell["gaps"], color=color, lw=2.0, alpha=0.85,
                marker="o" if cell["proven"] else "s", markersize=5,
                markeredgecolor="white", markeredgewidth=1.0, zorder=3)

    # Label the two cells that carry the story: the one that stalls on the
    # tolerance line for fifteen iterations, and the one that dives past it.
    for cell in cells:
        if cell["name"] == "I17-M8-T6":
            ax.annotate(cell["name"], (11, cell["gaps"][-1]), xytext=(0, 13),
                        textcoords="offset points", color=INK_2, fontsize=12,
                        ha="center")
        elif cell["name"] == "I17-M8-T3":
            ax.annotate(cell["name"], (len(cell["gaps"]), cell["gaps"][-1]),
                        xytext=(9, -4), textcoords="offset points",
                        color=INK_2, fontsize=12)

    ax.axhline(1e-4, color=MUTED, lw=1.0, ls=(0, (4, 3)), zorder=1)
    ax.text(0.7, 3.2e-5, "tolerance", color=INK_2, fontsize=11.5,
            ha="left", va="top")

    ax.set_yscale("log")
    ax.set_ylim(3e-14, 3)
    ax.set_xlim(0.4, 18.6)
    ax.set_xlabel("DBP iteration")
    ax.set_ylabel("relative gap  (UB - LB) / UB")
    if not compact:
        ax.set_title("Six instances close the gap; four are cut off before they do",
                     color=INK, loc="left", pad=14)
    ax.grid(True)
    ax.set_axisbelow(True)

    handles = [
        plt.Line2D([], [], color=PROVEN, marker="o", markersize=7,
                   markeredgecolor="white", lw=2.0, label="proven optimal"),
        plt.Line2D([], [], color=CENSORED, marker="s", markersize=7,
                   markeredgecolor="white", lw=2.0, label="censored (time / wall-clock cap)"),
    ]
    ax.legend(handles=handles, loc="lower right")
    if compact:
        save(fig, "c2_gap_trajectories_compact")
        return
    fig.text(0.125, -0.03,
             "Gaps at the floor are exact to solver round-off (reconstructed value "
             "slightly negative); a log axis cannot show those.",
             color=MUTED, fontsize=11)
    save(fig, "c2_gap_trajectories")


def fig_solve_time(cells: list[dict]) -> None:
    """Runtime per cell, log scale, ordered fastest to slowest."""
    ordered = sorted(cells, key=lambda c: c["seconds"])
    fig, ax = plt.subplots(figsize=(9.8, 5.4))
    ys = range(len(ordered))
    for y, cell in zip(ys, ordered):
        color = PROVEN if cell["proven"] else CENSORED
        ax.barh([y], [cell["seconds"]], height=0.6, color=color,
                hatch=None if cell["proven"] else "///", zorder=3)
        ax.text(cell["seconds"] * 1.15, y,
                f"{cell['seconds'] / 60:.0f} min" if cell["seconds"] < 5400
                else f"{cell['seconds'] / 3600:.1f} h",
                va="center", color=INK_2, fontsize=11.5)

    ax.set_yticks(list(ys))
    ax.set_yticklabels([c["name"] for c in ordered], color=INK, fontsize=12)
    ax.set_xscale("log")
    ax.set_xlim(20, 4e5)
    ax.set_xlabel("solve time (seconds, log scale)")
    ax.set_title("Runtime spans three orders of magnitude on the same design",
                 color=INK, loc="left", pad=14)
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)

    handles = [
        plt.Rectangle((0, 0), 1, 1, color=PROVEN, label="proven optimal"),
        plt.Rectangle((0, 0), 1, 1, color=CENSORED, hatch="///", label="censored"),
    ]
    ax.legend(handles=handles, loc="lower right")
    save(fig, "c3_solve_time")


def fig_tau_star(cells: list[dict]) -> None:
    """The leader's selected rate per cell, on the campaign's dimensionless grid.

    For a censored cell the rate is the incumbent, not a proven optimum -- the
    figure marks that rather than presenting all ten alike.
    """
    ordered = sorted(cells, key=lambda c: c["effective_tax"])
    fig, ax = plt.subplots(figsize=(9.8, 5.4))
    ys = range(len(ordered))
    for y, cell in zip(ys, ordered):
        color = PROVEN if cell["proven"] else CENSORED
        ax.barh([y], [cell["effective_tax"]], height=0.6, color=color,
                hatch=None if cell["proven"] else "///", zorder=3)
        label = f"{cell['effective_tax']:.4f}"
        if not cell["proven"]:
            label += "  (incumbent)"
        ax.text(cell["effective_tax"] + 0.004, y, label, va="center",
                color=INK_2, fontsize=11.5)

    ax.set_yticks(list(ys))
    ax.set_yticklabels([c["name"] for c in ordered], color=INK, fontsize=12)
    ax.set_xlim(0, 0.30)
    ax.set_xlabel(r"selected carbon-tax rate  $\tau^\star$  (campaign grid, dimensionless)")
    ax.set_title("The selected rate varies by two orders of magnitude across the design",
                 color=INK, loc="left", pad=14)
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)

    handles = [
        plt.Rectangle((0, 0), 1, 1, color=PROVEN, label="proven optimal"),
        plt.Rectangle((0, 0), 1, 1, color=CENSORED, hatch="///",
                      label="censored -- rate not proven"),
    ]
    ax.legend(handles=handles, loc="lower right")
    save(fig, "c4_tau_star")


if __name__ == "__main__":
    cells = load_cells()
    print(f"Campaign_01 talk figures -> {FIGDIR}")
    print(f"  {len(cells)} solved cells "
          f"({sum(c['proven'] for c in cells)} proven, "
          f"{sum(not c['proven'] for c in cells)} censored)")
    fig_status_tiles(cells)
    fig_gap_trajectories(cells)
    fig_gap_trajectories(cells, compact=True)
    fig_solve_time(cells)
    fig_tau_star(cells)
    print("done.")
