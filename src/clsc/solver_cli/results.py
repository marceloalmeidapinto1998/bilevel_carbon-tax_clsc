"""The files a solve writes: summary records, the per-instance result payload, the DBP trace,
the solution payload, failure records, and the JSON/CSV writers.
"""
from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from clsc.models.instance_data import InstanceData, InstanceValidationError
from clsc.solvers.dbp import BilevelSolveError, SubproblemStatusError, relative_optimality_gap
from .validation import OutputValidationError


RESULT_SCHEMA_VERSION = 4


SUMMARY_FIELDNAMES = [
    "instance",
    "input_path",
    "success",
    "exact",
    "result_class",
    "termination_reason",
    "iterations",
    "tax_index",
    "leader_tax_weight",
    "tax_rate",
    "cost",
    "emissions",
    "follower_objective",
    "leader_objective_lb",
    "leader_objective_ub",
    "relative_gap",
    "validation_status",
    "failure_stage",
    "error_type",
    "error_message",
    "gurobi_status",
    "objective_bound",
    "iis_constraints",
    "solve_seconds",
]


TRACE_FIELDNAMES = [
    "iteration",
    "relaxation_tax_index",
    "relaxation_lower_bound",
    "follower_seconds",
    "follower_objective",
    "leader_objective_ub",
    "relaxation_seconds",
    "next_relaxation_tax_index",
    "next_relaxation_lower_bound",
    "relaxation_mip_gap",
    "relaxation_partial",
    "relaxation_elastic_slack",
    "follower_mip_gap",
    "follower_time_limited",
    "follower_improved",
    "follower_stage2_fallback",
]


def classify_result(result) -> str:
    """How strong a claim the result supports, in Soares et al. (2021)'s terms.

    ``certified``        gap <= dbp_relative_gap with every certificate in hand (``exact``).
    ``epsilon_optimal``  gap <= dbp_relative_gap, but the tax or a bound is not certified.
    ``bounded``          the gap did not close: the result is the interval [LB, UB] and the
                         incumbent that attains UB -- "optimal or nearly optimal" at best, with
                         convergence not guaranteed under positive subproblem gaps.
    """
    if result.exact:
        return "certified"
    if result.termination_reason.startswith(("optimal", "epsilon_optimal")):
        return "epsilon_optimal"
    return "bounded"


def build_summary_record(
    *,
    instance: InstanceData,
    instance_path: Path,
    result,
    solve_seconds: float,
    solution_validation: dict[str, object],
) -> dict[str, object]:
    return {
        "instance": instance.name,
        "input_path": to_posix(instance_path),
        "success": True,
        "exact": result.exact,
        "result_class": classify_result(result),
        "termination_reason": result.termination_reason,
        "iterations": result.iterations,
        "tax_index": result.incumbent.tax_index,
        # kg CO2e per USD/t in the leader's objective F = E + w*tau. The bounds below
        # (leader_objective_lb / leader_objective_ub) are bounds on F, not on emissions alone.
        "leader_tax_weight": getattr(result, "leader_tax_weight", 0.0),
        "tax_rate": result.incumbent.tax_rate,
        "cost": result.incumbent.cost,
        "emissions": result.incumbent.emissions,
        "follower_objective": result.incumbent.follower_objective,
        "leader_objective_lb": result.leader_objective_lb,
        "leader_objective_ub": result.leader_objective_ub,
        "relative_gap": relative_optimality_gap(
            leader_objective_ub=result.leader_objective_ub,
            leader_objective_lb=result.leader_objective_lb,
        ),
        "validation_status": solution_validation["status"],
        "failure_stage": None,
        "error_type": None,
        "error_message": None,
        "gurobi_status": None,
        "objective_bound": None,
        "iis_constraints": 0,
        "solve_seconds": solve_seconds,
    }


def build_instance_result_payload(
    *,
    run_id: str,
    instance: InstanceData,
    instance_path: Path,
    relative_instance_dir: Path,
    result,
    solve_seconds: float,
    dbp_solve_seconds: float,
    validation_seconds: float,
    solution_validation: dict[str, object],
    oracle_validation: dict[str, object] | None = None,
) -> dict[str, object]:
    relative_result_dir = "." if not relative_instance_dir.parts else to_posix(relative_instance_dir)
    dbp_trace_rows = build_dbp_trace_rows(result)
    dbp_overhead_seconds = round(
        max(0.0, dbp_solve_seconds - result.dbp_timing.total_subproblem_seconds),
        6,
    )
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "run_id": run_id,
        "instance": {
            "name": instance.name,
            "input_path": to_posix(instance_path),
            "relative_result_dir": relative_result_dir,
        },
        "solve_status": {
            "method": result.method,
            "mode": result.mode,
            "success": True,
            "exact": result.exact,
            "termination_reason": result.termination_reason,
            "iterations": result.iterations,
        },
        "phase_summary": build_phase_summary(result),
        "leader": {
            "tax_index": result.incumbent.tax_index,
            "tax_rate": result.incumbent.tax_rate,
        },
        "follower": {
            "cost": result.incumbent.cost,
            "emissions": result.incumbent.emissions,
            "objective": result.incumbent.follower_objective,
            "lex_primary_mip_gap": getattr(result.incumbent_solution, "lex_primary_mip_gap", None),
            "lex_secondary_mip_gap": getattr(result.incumbent_solution, "lex_secondary_mip_gap", None),
        },
        "bounds": {
            "leader_objective_lb": result.leader_objective_lb,
            "leader_objective_ub": result.leader_objective_ub,
            "relative_gap": relative_optimality_gap(
                leader_objective_ub=result.leader_objective_ub,
                leader_objective_lb=result.leader_objective_lb,
            ),
            "certificates": {
                "lower": asdict(result.leader_objective_lb_certificate),
                "upper": asdict(result.leader_objective_ub_certificate),
            },
        },
        "runtime": {
            "solve_seconds": solve_seconds,
            "dbp_seconds": dbp_solve_seconds,
            "validation_seconds": validation_seconds,
            "dbp_overhead_seconds": dbp_overhead_seconds,
            "phase_seconds": {
                "dbp_subproblems": result.dbp_timing.total_subproblem_seconds,
                "dbp_overhead": dbp_overhead_seconds,
                "validation": validation_seconds,
            },
            "subproblem_seconds": {
                "initial_relaxation": result.dbp_timing.initial_relaxation_seconds,
                "follower_total": result.dbp_timing.follower_total_seconds,
                "optimistic_total": result.dbp_timing.optimistic_total_seconds,
                "iterative_relaxation_total": result.dbp_timing.iterative_relaxation_total_seconds,
                "relaxation_total": result.dbp_timing.relaxation_total_seconds,
                "total": result.dbp_timing.total_subproblem_seconds,
            },
        },
        "validation": solution_validation,
        "oracle_validation": oracle_validation,
        "dbp": {
            "trace_file": "dbp_trace.csv",
            "trace_rows": len(dbp_trace_rows),
            "timings": {
                "initial_relaxation_seconds": result.dbp_timing.initial_relaxation_seconds,
                "iterations": [
                    {
                        "iteration": timing.iteration,
                        "follower_seconds": timing.follower_seconds,
                        "optimistic_seconds": timing.optimistic_seconds,
                        "relaxation_seconds": timing.relaxation_seconds,
                    }
                    for timing in result.dbp_timing.iteration_timings
                ],
            },
        },
        "files": {
            "solution_file": "solution.json",
            "diagnostics_file": None,
        },
    }


def build_phase_summary(result) -> dict[str, object]:
    # The leader's single objective F = E + w*tax_index is resolved inside the DBP loop itself,
    # so there is only one phase.
    return {
        "dbp_iterations": len(result.iteration_records),
        "final_tax_index": result.incumbent.tax_index,
    }


def build_dbp_trace_rows(result) -> list[dict[str, object]]:
    return [build_dbp_trace_row(record) for record in result.iteration_records]


def build_dbp_trace_row(record) -> dict[str, object]:
    return {
        "iteration": record.iteration,
        "relaxation_tax_index": record.relaxation_tax_index,
        "relaxation_lower_bound": record.relaxation_lower_bound,
        "follower_seconds": record.follower_seconds,
        "follower_objective": record.follower_objective,
        "leader_objective_ub": record.leader_objective_ub,
        "relaxation_seconds": record.relaxation_seconds,
        "next_relaxation_tax_index": record.next_relaxation_tax_index,
        "next_relaxation_lower_bound": record.next_relaxation_lower_bound,
        "relaxation_mip_gap": getattr(record, "relaxation_mip_gap", None),
        "relaxation_partial": getattr(record, "relaxation_partial", False),
        "relaxation_elastic_slack": getattr(record, "relaxation_elastic_slack", None),
        "follower_mip_gap": getattr(record, "follower_mip_gap", None),
        "follower_time_limited": getattr(record, "follower_time_limited", False),
        "follower_improved": getattr(record, "follower_improved", None),
        "follower_stage2_fallback": getattr(record, "follower_stage2_fallback", False),
    }


def build_solution_payload(
    *,
    instance: InstanceData,
    result,
    solution_validation: dict[str, object],
) -> dict[str, object]:
    optimistic = result.incumbent_solution
    if optimistic is None or not optimistic.has_solution:
        raise RuntimeError(f"Missing cached optimistic incumbent solution for {instance.name}")
    if optimistic.variable_values is None:
        raise RuntimeError(f"Cached optimistic incumbent solution for {instance.name} has no variable values")

    leader_variables = {
        "tax_index": result.incumbent.tax_index,
        "tax_rate": result.incumbent.tax_rate,
    }
    follower_variables = optimistic.variable_values

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "instance": instance.name,
        "leader": leader_variables,
        "objectives": {
            "cost": optimistic.cost if optimistic.cost is not None else result.incumbent.cost,
            "emissions": optimistic.emissions if optimistic.emissions is not None else result.incumbent.emissions,
            "follower_objective": optimistic.follower_objective
            if optimistic.follower_objective is not None
            else result.incumbent.follower_objective,
        },
        "validation": solution_validation,
        "decision_variables": {
            "leader": leader_variables,
            "follower": follower_variables,
        },
        "variables": follower_variables,
    }


def build_failure_summary_record(
    *,
    instance: InstanceData | None,
    instance_path: Path,
    error: Exception,
    solve_seconds: float,
) -> dict[str, object]:
    diagnostics = extract_failure_diagnostics(error)
    return {
        "instance": instance.name if instance is not None else instance_path.stem,
        "input_path": to_posix(instance_path),
        "success": False,
        "exact": False,
        "result_class": "failed",
        "termination_reason": "failed",
        "iterations": None,
        "tax_index": None,
        "tax_rate": None,
        "cost": None,
        "emissions": None,
        "follower_objective": None,
        "leader_objective_lb": None,
        "leader_objective_ub": None,
        "relative_gap": None,
        "validation_status": "failed",
        "failure_stage": diagnostics["failure_stage"],
        "error_type": type(error).__name__,
        "error_message": str(error),
        "gurobi_status": diagnostics["gurobi_status"],
        "objective_bound": diagnostics["objective_bound"],
        "iis_constraints": diagnostics["iis_constraint_count"],
        "solve_seconds": solve_seconds,
    }


def build_failure_result_payload(
    *,
    run_id: str,
    instance: InstanceData | None,
    instance_path: Path,
    relative_instance_dir: Path,
    error: Exception,
    solve_seconds: float,
    method: str,
    mode: str,
) -> dict[str, object]:
    relative_result_dir = "." if not relative_instance_dir.parts else to_posix(relative_instance_dir)
    diagnostics = extract_failure_diagnostics(error)
    trace_rows = extract_failure_trace_rows(error)
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "run_id": run_id,
        "instance": {
            "name": instance.name if instance is not None else instance_path.stem,
            "input_path": to_posix(instance_path),
            "relative_result_dir": relative_result_dir,
        },
        "solve_status": {
            "method": method,
            "mode": mode,
            "success": False,
            "exact": False,
            "termination_reason": "failed",
            "iterations": None,
        },
        "phase_summary": None,
        "runtime": {
            "solve_seconds": solve_seconds,
        },
        "error": {
            "type": type(error).__name__,
            "message": str(error),
        },
        "diagnostics": diagnostics,
        "dbp": {
            "trace_file": "dbp_trace.csv" if trace_rows else None,
            "trace_rows": len(trace_rows),
        },
        "files": {
            "solution_file": None,
            "diagnostics_file": "diagnostics.json",
        },
    }


def extract_failure_diagnostics(error: Exception) -> dict[str, object]:
    diagnostics = {
        "failure_stage": "unexpected",
        "gurobi_status": None,
        "objective_bound": None,
        "iis_constraint_count": 0,
        "iis_constraints": [],
        "iis_variable_bounds": [],
    }

    if isinstance(error, InstanceValidationError):
        diagnostics["failure_stage"] = "instance_validation"
        return diagnostics
    if isinstance(error, OutputValidationError):
        diagnostics["failure_stage"] = "output_validation"
        return diagnostics
    if isinstance(error, SubproblemStatusError):
        diagnostics["failure_stage"] = error.label
        result = error.result
        diagnostics["gurobi_status"] = result.status_name
        diagnostics["objective_bound"] = result.objective_bound
        diagnostics["iis_constraints"] = list(result.iis_constraints)
        diagnostics["iis_variable_bounds"] = list(result.iis_variable_bounds)
        diagnostics["iis_constraint_count"] = len(result.iis_constraints)
        diagnostics["status_history"] = list(result.status_history or (result.status_name,))
        diagnostics["has_solution"] = result.has_solution
        diagnostics["mip_gap"] = result.mip_gap
        diagnostics["runtime"] = result.runtime
        return diagnostics
    if isinstance(error, BilevelSolveError):
        diagnostics["failure_stage"] = "solve"
        return diagnostics
    return diagnostics


def extract_failure_trace_rows(error: Exception) -> list[dict[str, object]]:
    trace_rows = getattr(error, "trace_rows", ())
    if not trace_rows:
        return []
    return [dict(row) for row in trace_rows]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_posix(path: Path) -> str:
    return path.as_posix()
