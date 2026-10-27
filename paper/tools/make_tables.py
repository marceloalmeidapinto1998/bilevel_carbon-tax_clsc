"""Write the rows of the manuscript's and the supplement's results tables from the experiments' files, so
that every number in them comes from results/experiments. Run from the repository root:

    python paper/tools/make_tables.py

Rows go between the markers ``%% BEGIN table <name>`` and ``%% END table <name>`` of main.tex and
supplementary.tex (an \\input inside tabularx breaks booktabs' rules). The script also prints the aggregates
the text quotes.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import statistics

ROOT = Path("results/experiments")
MAIN = Path("paper/main.tex")
SUPPLEMENT = Path("paper/supplementary.tex")
ORIGINAL_SMALL = ("STD_I17_M4_T3", "STD_I17_M4_T6", "STD_I17_M8_T3", "STD_I25_M4_T3")
CALIBRATED_SMALL = ("CAL_I17_M4_T3_r0", "CAL_I17_M4_T6_r0", "CAL_I17_M8_T3_r0", "CAL_I25_M4_T3_r0",
                    "CAL_I17_M4_T3_r1", "CAL_I17_M4_T6_r1", "CAL_I17_M8_T3_r1", "CAL_I25_M4_T3_r1")
ORIGINAL_ALL = ("STD_I17_M4_T3", "STD_I17_M4_T6", "STD_I17_M4_T12", "STD_I17_M8_T3", "STD_I17_M8_T6",
                "STD_I17_M8_T12", "STD_I25_M4_T3", "STD_I25_M4_T6", "STD_I25_M4_T12", "STD_I25_M8_T3",
                "STD_I25_M8_T6", "STD_I25_M8_T12", "STD_I25_M12_T6", "STD_I25_M16_T6", "STD_I33_M8_T6", "MOTA2018")
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
    return "Case study" if name == "MOTA2018" else "\\inst{" + name + "}"


def num(value, digits=1) -> str:
    return "--" if value is None else f"{value:,.{digits}f}"


def bold_if(text: str, condition: bool) -> str:
    return f"\\textbf{{{text}}}" if condition else text


# ------------------------------------------------------------------ the DBP on the original instances

def dbp_original() -> list[str]:
    main = {r["instance"]: r for r in rows(ROOT / "tables" / "main.csv")}
    lines = []
    for name in ORIGINAL_ALL:
        r = main[name]
        closed = r["result_class"] in ("optimal", "epsilon_optimal")
        certified = r["upper_bound_certified"] == "True"
        result = CLASS[r["result_class"]] + ("" if certified else "\\tr{a}")
        share = 100.0 * float(r["hpr_seconds"]) / float(r["seconds"])
        lines.append(" & ".join([
            tt(name), result, r["iterations"], num(float(r["tax"]), 1) if closed else "--",
            num(max(100.0 * float(r["relative_gap"]), 0.0), 3), num(float(r["seconds"]), 0), num(share, 0),
        ]) + " \\\\")
    return lines


# ------------------------------------------------------------------ the two methods on the small instances

def enumeration_summary(key: str, name: str) -> dict:
    return load(ROOT / key / "seed0" / name / "summary.json")


def methods() -> tuple[list[str], list[dict]]:
    lines, records = [], []
    for group, names, dbp_key, enum_key in (("original", ORIGINAL_SMALL, "P1", "E1"),
                                            ("calibrated", CALIBRATED_SMALL, "C1", "C2")):
        for name in names:
            dbp = load(ROOT / dbp_key / "seed0" / name / "summary.json")
            enum = enumeration_summary(enum_key, name)
            dbp_seconds, enum_seconds = dbp["solve_seconds"], enum["seconds"] + enum["scale_seconds"]
            records.append({"group": group, "name": name, "points": len(enum["break_points"]),
                            "dbp_tax": dbp["tax"], "enum_tax": enum["tax"], "dbp_seconds": dbp_seconds,
                            "enum_seconds": enum_seconds, "dbp_value": dbp["leader_objective_ub"],
                            "enum_value": enum["leader_objective"], "solves": enum["follower_solves"],
                            "iterations": dbp["iterations"], "class": dbp["result_class"]})
            lines.append(" & ".join([
                tt(name), str(len(enum["break_points"])),
                CLASS[dbp["result_class"]], num(dbp["tax"], 2), str(dbp["iterations"]),
                bold_if(num(dbp_seconds, 0), dbp_seconds < enum_seconds),
                num(enum["tax"], 2), str(enum["follower_solves"]),
                bold_if(num(enum_seconds, 0), enum_seconds < dbp_seconds),
            ]) + " \\\\")
        if group == "original":
            lines.append("\\midrule")
    return lines, records


# ------------------------------------------------------------------ the calibrated instances

def calibrated() -> tuple[list[str], list[str], dict]:
    policy_lines, status_lines = [], []
    stats = {"exact": [], "uncertified": [], "incomplete": []}
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
            label = {"exact": "Exact", "uncertified": "Complete, not certified", "incomplete": "Budget spent"}[status]
            status_lines.append(" & ".join([tt(name), label, str(record["solves"]), str(record["points"]),
                                            num(seconds, 0), num(e0 / c0, 1)]) + " \\\\")
            if status == "exact":
                tax = summary["tax"]
                bill = tax / 1000.0 * summary["tax_base"] / summary["cost"]
                reduction = 100.0 * (1.0 - summary["emissions"] / e0)
                at74 = fixed[74.0]
                reduction74 = 100.0 * (1.0 - float(at74["emissions"]) / e0)
                bill74 = float(at74["tax_paid"]) / float(at74["cost"])
                reman0 = 100.0 * float(fixed[0.0]["remanufacturing_share"])
                reman = 100.0 * (summary.get("profile") or {}).get("remanufacturing_share", 0.0)
                least = 100.0 * (1.0 - summary["reference_emissions"] / e0)
                record.update(tax=tax, bill=bill, reduction=reduction, reduction74=reduction74, bill74=bill74,
                              reman0=reman0, reman=reman, least=least, cost=100.0 * (summary["cost"] / c0 - 1.0))
                policy_lines.append(" & ".join([
                    tt(name), str(record["points"]), num(tax, 1),
                    bold_if(num(reduction), reduction > reduction74 + 0.05), num(reduction74), num(least),
                    num(bill, 2), num(bill74, 2), num(reman0), num(reman),
                ]) + " \\\\")
            stats[status].append(record)
        if k != REPLICATES[-1]:
            status_lines.append("\\midrule")
    return policy_lines, status_lines, stats


def inline(path: Path, tables: dict[str, list[str]]) -> None:
    text = path.read_text(encoding="utf-8")
    for name, body in tables.items():
        begin, end = f"%% BEGIN table {name}", f"%% END table {name}"
        if begin not in text:
            continue
        i, j = text.index(begin), text.index(end)
        text = text[: i + len(begin)] + "\n" + "\n".join(body) + "\n" + text[j:]
    path.write_text(text, encoding="utf-8")


def main() -> None:
    method_lines, method_records = methods()
    policy_lines, status_lines, stats = calibrated()
    tables = {"dbp_original": dbp_original(), "methods": method_lines, "policy": policy_lines,
              "calibrated_status": status_lines}
    inline(MAIN, tables)
    inline(SUPPLEMENT, tables)

    print({key: len(value) for key, value in stats.items()})
    exact = stats["exact"]
    above = [r for r in exact if r["tax"] > 74.0]
    below = [r for r in exact if r["tax"] <= 74.0]
    print("taxes", min(r["tax"] for r in exact), max(r["tax"] for r in exact), "above 74:", len(above))
    print("below: reduction gap", max(abs(r["reduction"] - r["reduction74"]) for r in below),
          "bill ratio", [round(r["bill74"] / r["bill"], 2) for r in below if r["bill"] > 0])
    print("above: shortfall", sorted(round(r["reduction"] - r["reduction74"], 1) for r in above))
    print("points median", statistics.median(r["points"] for r in exact), "range", min(r["points"] for r in exact), max(r["points"] for r in exact))
    print("bill share", min(r["bill"] for r in exact if r["tax"] > 0), max(r["bill"] for r in exact))
    print("gap to least", sorted(round(r["least"] - r["reduction"], 2) for r in exact))
    print("intensity all 24", min(r["intensity"] for s in stats.values() for r in s), max(r["intensity"] for s in stats.values() for r in s))
    for group in ("original", "calibrated"):
        g = [r for r in method_records if r["group"] == group]
        print(group, "dbp s", min(r["dbp_seconds"] for r in g), max(r["dbp_seconds"] for r in g),
              "enum s", min(r["enum_seconds"] for r in g), max(r["enum_seconds"] for r in g),
              "dbp faster", sum(r["dbp_seconds"] < r["enum_seconds"] for r in g),
              "tax diff", max(abs(r["dbp_tax"] - r["enum_tax"]) for r in g),
              "points", min(r["points"] for r in g), max(r["points"] for r in g))


if __name__ == "__main__":
    main()
