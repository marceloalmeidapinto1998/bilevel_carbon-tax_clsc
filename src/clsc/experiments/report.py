"""The paper's tables, computed from the experiments' files; no solver is called.

Each table is written to <root>/tables/<name>.csv with whatever runs exist so far; a run whose files
are missing, or that failed, is left out.

The response without the tax is the DBP's first iteration: the first HPR proposes tax 0, so the first
row of dbp_trace.csv holds the follower's cost at tax 0 (``follower_objective``, the tax term being
zero) and its emissions (``leader_objective_ub``, F = E there). It is used only when that row's tax
is 0.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from clsc.config.defaults import DEFAULT
from clsc.models.instance_data import InstanceData

from .plan import ALL_INSTANCES, EXPERIMENTS
from .profile import response_profile
from .scenarios import SCENARIOS, variant_name

Row = dict[str, object]
PROFILE_COLUMNS = (
    "remanufacturing_share", "emissions_production", "emissions_raw_material", "emissions_remanufacturing",
    "emissions_transport", "factories", "warehouses", "production_technologies", "remanufacturing_technologies",
)


def _number(value: str) -> object:
    if value in ("", "None"):
        return None
    if value in ("True", "False"):
        return value == "True"
    try:
        return float(value)
    except ValueError:
        return value


def read_rows(path: Path) -> list[Row]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [{key: _number(value) for key, value in row.items()} for row in csv.DictReader(handle)]


def _json(path: Path) -> dict | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload[0] if isinstance(payload, list) else payload


def _job(root: Path, key: str, name: str, seed: int = 0) -> Path:
    return root / key / f"seed{seed}" / name


def _relative(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None:
        return None
    return (value - reference) / max(1.0, abs(reference))


def run_record(directory: Path, instance_path: Path) -> Row | None:
    """One DBP run: its result, the response without the tax and the profile of its solution."""
    summary = _json(directory / "summary.json")
    if summary is None or not summary.get("success"):
        return None
    trace = read_rows(directory / "dbp_trace.csv")
    first = trace[0] if trace else {}
    at_zero = first.get("relaxation_tax") == 0.0
    emissions_no_tax = first.get("leader_objective_ub") if at_zero else None
    cost_no_tax = first.get("follower_objective") if at_zero else None
    record: Row = {
        "result_class": summary["result_class"], "termination_reason": summary["termination_reason"],
        "relative_gap": summary["relative_gap"], "iterations": summary["iterations"], "seconds": summary["solve_seconds"],
        "leader_tax_weight": summary["leader_tax_weight"], "tax": summary["tax"],
        "emissions": summary["emissions"], "cost": summary["cost"],
        "tax_paid": summary["follower_objective"] - summary["cost"],
        "emissions_no_tax": emissions_no_tax, "cost_no_tax": cost_no_tax,
        "emission_reduction": None if emissions_no_tax is None else -_relative(summary["emissions"], emissions_no_tax),
        "cost_increase": _relative(summary["cost"], cost_no_tax),
    }
    solution = _json(directory / "solution.json")
    if solution is not None and instance_path.exists():
        profile = response_profile(InstanceData.from_file(instance_path), solution["variables"])
        record.update({column: profile[column] for column in PROFILE_COLUMNS})
    return record


def _variant_path(root: Path, path: str, scenario_name: str) -> Path:
    scenario = SCENARIOS[scenario_name]
    return Path(path) if scenario.is_base else root / "instances" / f"{variant_name(Path(path).stem, scenario)}.json"


# ----- tables -----

def main_table(root: Path) -> list[Row]:
    """P1: the DBP on every instance, with the time split between the HPR and the follower."""
    rows = []
    for path in ALL_INSTANCES:
        name = Path(path).stem
        directory = _job(root, "P1", name)
        summary = _json(directory / "summary.json")
        if summary is None:
            continue
        result = _json(directory / "result.json") or {}
        subproblems = (result.get("runtime") or {}).get("subproblem_seconds") or {}
        rows.append({
            "instance": name, "result_class": summary.get("result_class"), "termination_reason": summary.get("termination_reason"),
            "iterations": summary.get("iterations"), "tax": summary.get("tax"),
            "lower_bound": summary.get("leader_objective_lb"), "upper_bound": summary.get("leader_objective_ub"),
            "relative_gap": summary.get("relative_gap"), "upper_bound_certified": summary.get("upper_bound_certified"),
            "seconds": summary.get("solve_seconds"), "hpr_seconds": subproblems.get("relaxation_total"),
            "follower_seconds": subproblems.get("follower_total"), "validation_status": summary.get("validation_status"),
        })
    return rows


def sensitivity_table(root: Path) -> list[Row]:
    """P2a and P2b: every instance under the base (from P1) and each scenario."""
    rows = []
    for key in ("P2a", "P2b"):
        experiment = EXPERIMENTS[key]
        for path in experiment.instances:
            name = Path(path).stem
            for scenario_name in ("base", *experiment.scenarios):
                scenario = SCENARIOS[scenario_name]
                directory = _job(root, "P1", name) if scenario.is_base else _job(root, key, variant_name(name, scenario))
                record = run_record(directory, _variant_path(root, path, scenario_name))
                if record is not None:
                    rows.append({"instance": name, "scenario": scenario_name, "parameter": scenario.parameter or "base",
                                 "level": scenario.level or "base", **record})
    return rows


def policy_table(root: Path) -> list[Row]:
    """P3 and P3b: the response without the tax, at the fixed reference tax and at the regulator's
    optimal tax, and the least emissions of any network, E_ref = w / q.

    The no_tax row's emissions and cost are the DBP's first iteration; its network profile is that of
    the follower solved at tax 0 in P3/P3b (the same problem, solved again), when that run exists."""
    rows = []
    for key in ("P3", "P3b"):
        for path in EXPERIMENTS[key].instances:
            name = Path(path).stem
            record = run_record(_job(root, "P1", name), Path(path))
            if record is None:
                continue
            e0, c0 = record["emissions_no_tax"], record["cost_no_tax"]

            def point(label: str, tax, emissions, cost, tax_paid, profile: Row | None = None) -> Row:
                return {
                    "instance": name, "point": label, "tax": tax, "emissions": emissions, "cost": cost, "tax_paid": tax_paid,
                    "emission_reduction": None if e0 is None else -_relative(emissions, e0),
                    "cost_increase": _relative(cost, c0),
                    **{column: (profile or {}).get(column) for column in PROFILE_COLUMNS},
                }

            follower = _job(root, key, name) / "follower.csv"
            fixed_rows = read_rows(follower) if follower.exists() else []
            at_zero = next((fixed for fixed in fixed_rows if fixed["tax"] == 0.0), None)
            rows.append(point("no_tax", 0.0, e0, c0, 0.0, at_zero))
            for fixed in fixed_rows:
                if fixed["tax"] == 0.0:
                    continue  # the response without a tax is the no_tax row, from the DBP's first iteration
                rows.append(point("reference_tax", fixed["tax"], fixed["emissions"], fixed["cost"], fixed["tax_paid"], fixed))
            rows.append(point("regulator_optimum", record["tax"], record["emissions"], record["cost"], record["tax_paid"], record))
            least = record["leader_tax_weight"] / DEFAULT.tax_weight_relative
            rows.append({"instance": name, "point": "least_emissions", "emissions": least,
                         "emission_reduction": None if e0 is None else -_relative(least, e0)})
    return rows


def seeds_table(root: Path) -> list[Row]:
    """R3 with P1: each small instance under seeds 0-4 (seed 0 is P1's run)."""
    rows = []
    for path in EXPERIMENTS["R3"].instances:
        name = Path(path).stem
        for seed in (0, *EXPERIMENTS["R3"].seeds):
            directory = _job(root, "P1", name) if seed == 0 else _job(root, "R3", name, seed)
            record = run_record(directory, Path(path))
            if record is None:
                continue
            rows.append({
                "instance": name, "seed": seed, "result_class": record["result_class"], "iterations": record["iterations"],
                "tax": record["tax"], "emissions": record["emissions"], "emission_reduction": record["emission_reduction"],
                "relative_gap": record["relative_gap"], "seconds": record["seconds"],
            })
    return rows


def robustness_table(root: Path) -> list[Row]:
    """R1 against P2a (and P1 for the base): the optimal tax and the emission reduction of each small
    instance and scenario at the MIP gap of 1e-4 and of 1e-6."""
    rows = []
    for path in EXPERIMENTS["R1"].instances:
        name = Path(path).stem
        for scenario_name in EXPERIMENTS["R1"].scenarios:
            scenario = SCENARIOS[scenario_name]
            variant = variant_name(name, scenario)
            instance_path = _variant_path(root, path, scenario_name)
            coarse = run_record(_job(root, "P1" if scenario.is_base else "P2a", variant), instance_path)
            fine = run_record(_job(root, "R1", variant), instance_path)
            if coarse is None or fine is None:
                continue
            rows.append({
                "instance": name, "scenario": scenario_name,
                "tax_gap_1e-4": coarse["tax"], "tax_gap_1e-6": fine["tax"], "tax_difference": fine["tax"] - coarse["tax"],
                "reduction_gap_1e-4": coarse["emission_reduction"], "reduction_gap_1e-6": fine["emission_reduction"],
                "class_gap_1e-6": fine["result_class"], "seconds_gap_1e-6": fine["seconds"],
            })
    return rows


def _enumeration_record(directory: Path) -> Row | None:
    summary = _json(directory / "summary.json")
    if summary is None or (_json(directory / "job.json") or {}).get("status") != "ok":
        return None
    return summary


def _evaluations(directory: Path) -> list[Row]:
    path = directory / "evaluations.csv"
    return read_rows(path) if path.exists() else []


def methods_table(root: Path) -> list[Row]:
    """The DBP against the enumeration of the break points and the grid, instance by instance: on the
    original instances (P1, E1, E2) and on the calibrated ones (C1, C2, C5). ``value_difference`` is the
    enumeration's leader value minus the DBP's upper bound, relative to the latter."""
    rows = []
    for dbp_key, enum_key, grid_key, instances in (("P1", "E1", "E2", ALL_INSTANCES),
                                                     ("C1", "C2", "C5", EXPERIMENTS["C1"].instances)):
        for path in instances:
            name = Path(path).stem
            dbp = _json(_job(root, dbp_key, name) / "summary.json")
            enum = _enumeration_record(_job(root, enum_key, name))
            grid = _enumeration_record(_job(root, grid_key, name))
            if dbp is None and enum is None:
                continue
            row: Row = {"set": "original" if dbp_key == "P1" else "calibrated", "instance": name}
            if dbp is not None:
                row.update({
                    "dbp_class": dbp.get("result_class"), "dbp_tax": dbp.get("tax"), "dbp_lb": dbp.get("leader_objective_lb"),
                    "dbp_ub": dbp.get("leader_objective_ub"), "dbp_gap": dbp.get("relative_gap"),
                    "dbp_iterations": dbp.get("iterations"), "dbp_seconds": dbp.get("solve_seconds"),
                })
            if enum is not None:
                row.update({
                    "enum_complete": enum["complete"], "enum_certified": enum["certified"], "enum_tax": enum["tax"],
                    "enum_value": enum["leader_objective"], "enum_solves": enum["follower_solves"],
                    "enum_break_points": len(enum["break_points"]), "enum_seconds": enum["seconds"] + enum["scale_seconds"],
                })
                if dbp is not None and dbp.get("leader_objective_ub") is not None:
                    row["value_difference"] = _relative(enum["leader_objective"], dbp["leader_objective_ub"])
                    row["tax_difference"] = enum["tax"] - dbp["tax"] if dbp.get("tax") is not None else None
            if grid is not None:
                row.update({
                    "grid_complete": grid["complete"], "grid_tax": grid["tax"], "grid_value": grid["leader_objective"],
                    "grid_solves": grid["follower_solves"], "grid_seconds": grid["seconds"] + grid["scale_seconds"],
                })
            rows.append(row)
    return rows


def staircase_table(root: Path) -> list[Row]:
    """The candidate taxes of each enumeration -- the lower end of the range and every break point -- with
    the optimistic emissions there and the leader's value: the staircase of emissions the tax can induce."""
    rows = []
    for key in ("E1", "C2"):
        for path in EXPERIMENTS[key].instances:
            name = Path(path).stem
            directory = _job(root, key, name)
            summary = _enumeration_record(directory)
            if summary is None:
                continue
            evaluations = _evaluations(directory)
            no_tax = next((e for e in evaluations if e["tax"] == 0.0), None)
            for evaluation in evaluations:
                if not evaluation["candidate"]:
                    continue
                rows.append({
                    "set": "original" if key == "E1" else "calibrated", "instance": name, "tax": evaluation["tax"],
                    "emissions": evaluation["emissions"], "cost": evaluation["cost"],
                    "leader_objective": evaluation["leader_objective"],
                    "emission_reduction": None if no_tax is None else -_relative(evaluation["emissions"], no_tax["emissions"]),
                    "cost_increase": None if no_tax is None else _relative(evaluation["cost"], no_tax["cost"]),
                    "optimal": evaluation["tax"] == summary["tax"],
                })
    return rows


def _enumeration_point(directory: Path) -> Row | None:
    """The best tax of a complete enumeration, with the response without a tax (its evaluation at 0)."""
    summary = _enumeration_record(directory)
    if summary is None or not summary["complete"]:
        return None
    no_tax = next((e for e in _evaluations(directory) if e["tax"] == 0.0), None)
    e0 = None if no_tax is None else no_tax["emissions"]
    c0 = None if no_tax is None else no_tax["cost"]
    tax_paid = None if summary.get("tax_base") is None else summary["tax"] / 1000.0 * summary["tax_base"]
    return {
        "certified": summary["certified"], "tax": summary["tax"], "emissions": summary["emissions"],
        "cost": summary.get("cost"), "tax_paid": tax_paid, "emissions_no_tax": e0, "cost_no_tax": c0,
        "emission_reduction": None if e0 is None else -_relative(summary["emissions"], e0),
        "cost_increase": _relative(summary.get("cost"), c0),
        "bill_share": None if tax_paid is None or not summary.get("cost") else tax_paid / summary["cost"],
        "reference_emissions": summary["reference_emissions"], "break_points": len(summary["break_points"]),
        **{column: (summary.get("profile") or {}).get(column) for column in PROFILE_COLUMNS},
    }


def calibrated_policy_table(root: Path) -> list[Row]:
    """The calibrated instances: the response without a tax and at the fixed reference tax (C3), at the
    regulator's optimal tax (C2, complete enumerations only) and the least emissions of any network."""
    rows = []
    for path in EXPERIMENTS["C2"].instances:
        name = Path(path).stem
        optimum = _enumeration_point(_job(root, "C2", name))
        if optimum is None:
            continue
        follower = _job(root, "C3", name) / "follower.csv"
        fixed = {row["tax"]: row for row in read_rows(follower)} if follower.exists() else {}
        zero = fixed.get(0.0)
        e0 = zero["emissions"] if zero else optimum["emissions_no_tax"]
        c0 = zero["cost"] if zero else optimum["cost_no_tax"]

        def point(label: str, tax, emissions, cost, tax_paid, profile: Row | None) -> Row:
            return {"instance": name, "point": label, "tax": tax, "emissions": emissions, "cost": cost, "tax_paid": tax_paid,
                    "emission_reduction": -_relative(emissions, e0), "cost_increase": _relative(cost, c0),
                    "bill_share": None if tax_paid is None or not cost else tax_paid / cost,
                    "intensity_kg_per_eur": None if not cost else emissions / cost,
                    **{column: (profile or {}).get(column) for column in PROFILE_COLUMNS}}

        rows.append(point("no_tax", 0.0, e0, c0, 0.0, zero))
        for tax, row in fixed.items():
            if tax != 0.0:
                rows.append(point("reference_tax", tax, row["emissions"], row["cost"], row["tax_paid"], row))
        rows.append(point("regulator_optimum", optimum["tax"], optimum["emissions"], optimum["cost"], optimum["tax_paid"], optimum))
        rows.append({"instance": name, "point": "least_emissions", "emissions": optimum["reference_emissions"],
                     "emission_reduction": -_relative(optimum["reference_emissions"], e0)})
    return rows


def calibrated_sensitivity_table(root: Path) -> list[Row]:
    """C4 with its bases from C2: the optimal tax, the emissions there and the reduction against each
    scenario's own network without a tax, so that a change of the reduction can be told apart from a change
    of the baseline."""
    rows = []
    experiment = EXPERIMENTS["C4"]
    for path in experiment.instances:
        name = Path(path).stem
        for scenario_name in ("base", *experiment.scenarios):
            scenario = SCENARIOS[scenario_name]
            directory = _job(root, "C2", name) if scenario.is_base else _job(root, "C4", variant_name(name, scenario))
            point = _enumeration_point(directory)
            if point is not None:
                rows.append({"instance": name, "scenario": scenario_name, "parameter": scenario.parameter or "base",
                             "level": scenario.level or "base", **point})
    return rows


TABLES = {
    "main": main_table, "sensitivity": sensitivity_table, "policy": policy_table,
    "robustness": robustness_table, "seeds": seeds_table, "methods": methods_table, "staircase": staircase_table,
    "calibrated_policy": calibrated_policy_table, "calibrated_sensitivity": calibrated_sensitivity_table,
}


def write_tables(root: Path, names: list[str] | None = None) -> dict[str, int]:
    """Write the tables (all by default) to <root>/tables/; return the number of rows of each."""
    directory = root / "tables"
    directory.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name in names or TABLES:
        rows = TABLES[name](root)
        counts[name] = len(rows)
        if not rows:
            continue
        fields = list(dict.fromkeys(key for row in rows for key in row))
        with (directory / f"{name}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return counts
