"""The paper's figures, drawn from the tables of clsc.experiments.report (matplotlib, PNG and PDF).

Tornado charts of the sensitivity analysis: for each instance, the change of the optimal tax and of
the emission reduction from the base when one parameter is set to its low or its high level. One
panel per instance and measure, each with its own axis; the parameters in the same order in every
panel. Colours: slots 1 and 2 of the reference categorical palette (blue for the low level, orange
for the high level), on a light surface for print; the low level is also hatched, so the two remain
apart in grayscale.
"""
from __future__ import annotations

import csv
from pathlib import Path

PARAMETER_LABELS = {
    "q": "Regulator weight ξ",
    "e_prod": "Production emission intensity",
    "e_rem": "Remanufacturing emission intensity",
    "returns": "Return fractions",
    "clean_cost": "Clean-technology cost",
    "interest": "Interest rate",
}
LOW, HIGH = "#2a78d6", "#eb6834"
SURFACE, TEXT, TEXT_SECONDARY, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
# Instances whose optimal tax is not determined within the run's gap (see docs/experiments.md).
UNDETERMINED_TAX = {"MOTA2018": "tax not determined within the gap of 0.2-2.4%"}


def _float(value: str) -> float | None:
    return float(value) if value not in ("", None) else None


def tornado_figure(table: Path, out_dir: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = list(csv.DictReader(table.open(encoding="utf-8")))
    instances = list(dict.fromkeys(row["instance"] for row in rows))
    parameters = list(PARAMETER_LABELS)
    measures = (
        ("tax", "Change of the optimal tax (€/t)", 1.0),
        ("reduction", "Change of the emission reduction (pp)", 100.0),
    )
    plt.rcParams.update({"font.size": 8, "axes.edgecolor": GRID, "axes.labelcolor": TEXT_SECONDARY,
                         "xtick.color": TEXT_SECONDARY, "ytick.color": TEXT, "font.family": "DejaVu Sans"})
    fig, axes = plt.subplots(len(instances), 2, figsize=(7.2, 1.55 * len(instances) + 0.6), facecolor=SURFACE,
                             sharey=True, squeeze=False)
    height, gap = 0.36, 0.04
    for i, instance in enumerate(instances):
        by_parameter = {row["parameter"]: row for row in rows if row["instance"] == instance}
        for j, (measure, title, scale) in enumerate(measures):
            ax = axes[i][j]
            ax.set_facecolor(SURFACE)
            for k, parameter in enumerate(parameters):
                row = by_parameter.get(parameter)
                if row is None:
                    continue
                base = _float(row[f"{measure}_base"])
                for offset, side, colour, hatch in ((-(height + gap) / 2, "low", LOW, "////"), ((height + gap) / 2, "high", HIGH, None)):
                    value = _float(row[f"{measure}_{side}"])
                    if value is None or base is None:
                        continue
                    ax.barh(k + offset, (value - base) * scale, height=height, color=colour, edgecolor=SURFACE,
                            linewidth=0.8, hatch=hatch, zorder=2)
            ax.axvline(0, color=TEXT_SECONDARY, linewidth=0.8, zorder=3)
            ax.grid(axis="x", color=GRID, linewidth=0.6, zorder=0)
            ax.set_yticks(range(len(parameters)))
            ax.set_yticklabels([PARAMETER_LABELS[p] for p in parameters])
            # Set, not inverted: the axis is shared, and each inversion would flip it again.
            ax.set_ylim(len(parameters) - 0.5, -0.5)
            ax.tick_params(length=0)
            for spine in ("top", "right", "left"):
                ax.spines[spine].set_visible(False)
            if i == 0:
                ax.set_title(title, fontsize=8.5, color=TEXT, loc="left")
            if j == 0:
                ax.text(-0.02, 1.02, instance.replace("STD_", ""), transform=ax.transAxes, ha="right", va="bottom",
                        fontsize=8.5, fontweight="bold", color=TEXT)
            if measure == "tax" and instance in UNDETERMINED_TAX:
                ax.text(1.0, 1.02, UNDETERMINED_TAX[instance], transform=ax.transAxes, ha="right", va="bottom",
                        fontsize=7, color=TEXT_SECONDARY, style="italic")
            limit = max(abs(v) for v in ax.get_xlim())
            ax.set_xlim(-limit, limit)
    from matplotlib.patches import Patch

    fig.legend(handles=[Patch(facecolor=LOW, hatch="////", edgecolor=SURFACE, label="Low level (x0.5; q = 1e-5)"),
                        Patch(facecolor=HIGH, edgecolor=SURFACE, label="High level (x2; q = 1e-3)")],
               loc="lower center", ncol=2, frameon=False, fontsize=8, labelcolor=TEXT)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / "tornado.png", out_dir / "tornado.pdf"]
    fig.savefig(paths[0], dpi=200, facecolor=SURFACE)
    fig.savefig(paths[1], facecolor=SURFACE)
    plt.close(fig)
    return paths
