"""Figure 1 of the manuscript: the staircase of emission reductions the tax induces on two calibrated
instances, from the enumeration of their switching prices (experiment C2). Run from the repository root:

    python paper/tools/make_figure.py

Each candidate of the enumeration (the lower end of the range and every switching price) holds the
optimistic response from its tax up to the next switching price, so the reduction is a step function of
the tax. The regulator's optimal tax and the fixed tax of 74 EUR/t are marked.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path("results/experiments/C2/seed0")
OUT = Path("paper/figures/staircase.pdf")
INSTANCES = ("CAL_I25_M4_T6_r0", "CAL_I17_M4_T3_r0")
REFERENCE_TAX = 74.0
TAX_MAX = 200.0


def staircase(name: str) -> tuple[list[float], list[float], float]:
    directory = ROOT / name
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    with (directory / "evaluations.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    e0 = next(float(r["emissions"]) for r in rows if float(r["tax"]) == 0.0)
    candidates = sorted((float(r["tax"]), float(r["emissions"])) for r in rows if r["candidate"] == "True")
    taxes = [tax for tax, _ in candidates] + [TAX_MAX]
    reductions = [100.0 * (1.0 - emissions / e0) for _, emissions in candidates]
    return taxes, reductions, float(summary["tax"])


def main() -> None:
    plt.rcParams.update({"font.size": 9, "font.family": "serif", "axes.linewidth": 0.6})
    figure, axes = plt.subplots(1, 2, figsize=(6.6, 2.6), sharey=False)
    for axis, name in zip(axes, INSTANCES):
        taxes, reductions, optimum = staircase(name)
        axis.step(taxes, reductions + [reductions[-1]], where="post", color="black", linewidth=1.0)
        at_optimum = next(r for t, r in zip(taxes, reductions) if abs(t - optimum) < 1e-6)
        index_74 = max(i for i, t in enumerate(taxes[:-1]) if t <= REFERENCE_TAX)
        axis.axvline(REFERENCE_TAX, color="0.45", linestyle="--", linewidth=0.8)
        axis.plot([optimum], [at_optimum], marker="o", color="black", markersize=5, linestyle="none",
                  label=r"optimal tax $\tau^*$")
        axis.plot([REFERENCE_TAX], [reductions[index_74]], marker="s", markerfacecolor="white",
                  markeredgecolor="black", markersize=5, linestyle="none", label="fixed tax, €74/t")
        axis.set_xlim(0.0, TAX_MAX)
        axis.set_xlabel("Tax (€ per tonne CO$_2$e)")
        axis.set_title(name, fontsize=9, family="monospace")
        axis.grid(axis="y", color="0.85", linewidth=0.5)
        for side in ("top", "right"):
            axis.spines[side].set_visible(False)
    axes[0].set_ylabel("Emission reduction (%)")
    axes[0].legend(frameon=False, fontsize=8, loc="lower right")
    figure.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(OUT)
    figure.savefig(OUT.with_suffix(".png"), dpi=200)
    print(OUT)


if __name__ == "__main__":
    main()
