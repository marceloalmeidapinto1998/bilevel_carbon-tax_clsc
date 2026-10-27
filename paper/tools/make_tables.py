"""Write the LaTeX bodies of the manuscript's results tables from the experiments' files, so that every number
in them comes from results/experiments. Run from the repository root:

    python paper/tools/make_tables.py

It writes paper/tables/methods_small.tex and paper/tables/calibrated.tex, and prints the aggregate figures the
text quotes.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import statistics

ROOT = Path("results/experiments")
OUT = Path("paper/tables")
SMALL = ("STD_I17_M4_T3", "STD_I17_M4_T6", "STD_I17_M8_T3", "STD_I25_M4_T3")
SIZES = ("I17_M4_T3", "I17_M4_T6", "I17_M4_T12", "I17_M8_T3", "I17_M8_T6", "I17_M8_T12",
         "I25_M4_T3", "I25_M4_T6", "I25_M4_T12", "I25_M8_T3", "I25_M8_T6", "I25_M8_T12")
REPLICATES = (0, 1)
CLASS = {"optimal": "Optimal", "epsilon_optimal": "$\\varepsilon$-optimal", "bounds": "Bounds"}


def load(path: Path):
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload[0] if isinstance(payload, list) else payload


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def tt(name: str) -> str:
    return "\\inst{" + name + "}"


def num(value, digits=1) -> str:
    return "--" if value is None else f"{value:,.{digits}f}"


def methods_small() -> list[str]:
    lines = []
    for name in SMALL:
        dbp = load(ROOT / "P1" / "seed0" / name / "summary.json")
        enum = load(ROOT / "E1" / "seed0" / name / "summary.json")
        grid = load(ROOT / "E2" / "seed0" / name / "summary.json")
        lines.append(" & ".join([
            tt(name), CLASS[dbp["result_class"]], num(dbp["tax"], 2), str(dbp["iterations"]), num(dbp["solve_seconds"], 0),
            num(enum["tax"], 2), str(enum["follower_solves"]), str(len(enum["break_points"])),
            num(enum["seconds"] + enum["scale_seconds"], 0),
            num(grid["tax"], 0), num(grid["seconds"] + grid["scale_seconds"], 0),
        ]) + " \\\\")
    return lines


def calibrated() -> tuple[list[str], dict]:
    lines, stats = [], {"exact": [], "uncertified": [], "incomplete": []}
    for k in REPLICATES:
        for size in SIZES:
            name = f"CAL_{size}_r{k}"
            directory = ROOT / "C2" / "seed0" / name
            summary = load(directory / "summary.json")
            if summary is None:
                continue
            evaluations = rows(directory / "evaluations.csv")
            zero = next(e for e in evaluations if float(e["tax"]) == 0.0)
            e0, c0 = float(zero["emissions"]), float(zero["cost"])
            follower = ROOT / "C3" / "seed0" / name / "follower.csv"
            fixed = {float(r["tax"]): r for r in rows(follower)} if follower.exists() else {}
            status = ("exact" if summary["certified"] else "uncertified") if summary["complete"] else "incomplete"
            seconds = summary["seconds"] + summary["scale_seconds"]
            record = {"name": name, "solves": summary["follower_solves"], "points": len(summary["break_points"]),
                      "seconds": seconds, "intensity": e0 / c0}
            if status == "exact":
                tax = summary["tax"]
                bill = tax / 1000.0 * summary["tax_base"] / summary["cost"]
                reduction = 100.0 * (1.0 - summary["emissions"] / e0)
                at74 = fixed.get(74.0)
                reduction74 = None if at74 is None else 100.0 * (1.0 - float(at74["emissions"]) / e0)
                bill74 = None if at74 is None else float(at74["tax_paid"]) / float(at74["cost"])
                reman0 = None if 0.0 not in fixed else 100.0 * float(fixed[0.0]["remanufacturing_share"])
                reman = 100.0 * (summary.get("profile") or {}).get("remanufacturing_share", 0.0)
                least = 100.0 * (1.0 - summary["reference_emissions"] / e0)
                record.update(tax=tax, bill=bill, reduction=reduction, reduction74=reduction74, bill74=bill74,
                              reman0=reman0, reman=reman, least=least, cost=100.0 * (summary["cost"] / c0 - 1.0))
                cells = [num(tax, 1), num(reduction), num(reduction74), num(least), num(bill, 2),
                         num(reman0), num(reman)]
            else:
                cells = ["--"] * 7
            label = {"exact": "Exact", "uncertified": "Complete\\tr{a}", "incomplete": "Budget\\tr{b}"}[status]
            lines.append(" & ".join([tt(name), label, str(record["solves"]), str(record["points"]), num(seconds, 0), *cells]) + " \\\\")
            stats[status].append(record)
        if k != REPLICATES[-1]:
            lines.append("\\midrule")
    return lines, stats


def inline(path: Path, tables: dict[str, list[str]]) -> None:
    r"""Put each table's rows into the manuscript between its markers ``%% BEGIN table <name>`` and
    ``%% END table <name>`` (an \input inside tabularx breaks booktabs' rules)."""
    text = path.read_text(encoding="utf-8")
    for name, body in tables.items():
        begin, end = f"%% BEGIN table {name}", f"%% END table {name}"
        placeholder = "\\input{tables/" + name + ".tex}"
        if placeholder in text:
            text = text.replace(placeholder, begin + "\n" + end)
        i, j = text.index(begin), text.index(end)
        text = text[: i + len(begin)] + "\n" + "\n".join(body) + "\n" + text[j:]
    path.write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "methods_small.tex").write_text("\n".join(methods_small()) + "\n", encoding="utf-8")
    lines, stats = calibrated()
    (OUT / "calibrated.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    exact = stats["exact"]
    inline(Path("paper/main.tex"), {"methods_small": methods_small(), "calibrated": lines})
    print({key: len(value) for key, value in stats.items()})
    taxes = sorted(r["tax"] for r in exact)
    print("taxes", [round(t, 1) for t in taxes])
    above = [r for r in exact if r["tax"] > 74.0]
    below = [r for r in exact if r["tax"] <= 74.0]
    print("above 74:", len(above), "below:", len(below))
    for r in exact:
        print(r["name"], "points", r["points"], "tax", round(r["tax"], 1), "red", round(r["reduction"], 1),
              "red74", r["reduction74"] and round(r["reduction74"], 1), "least", round(r["least"], 1),
              "bill", round(r["bill"], 2), "bill74", r["bill74"] and round(r["bill74"], 2),
              "reman", r["reman0"] and round(r["reman0"], 1), round(r["reman"], 1), "cost", round(r["cost"], 1),
              "kg/EUR", round(r["intensity"], 1))
    print("points median", statistics.median(r["points"] for r in exact + stats["uncertified"]))
    print("seconds exact", [round(r["seconds"]) for r in exact])


if __name__ == "__main__":
    main()
