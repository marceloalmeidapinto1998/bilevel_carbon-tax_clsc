"""Gurobi plumbing shared by every model: the model/result types, the solve wrapper, and
helpers that read a solution back.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import gurobipy as gp
from gurobipy import GRB

from clsc.config.constants import BOUND_SNAP_TOL, INTEGER_SNAP_TOL
from clsc.config.defaults import DEFAULT


@dataclass(slots=True)
class ModelArtifacts:
    model: gp.Model
    cost_expr: gp.LinExpr
    emissions_expr: gp.LinExpr
    follower_objective_expr: gp.LinExpr
    # Emission aggregate the tax is levied on (discounted). Falls back to the
    # physical emissions_expr when the instance is undiscounted.
    tax_base_expr: gp.LinExpr | None = None
    tax_var: gp.Var | None = None
    emissions_total_var: gp.Var | None = None
    elastic_slack_var: gp.Var | None = None


@dataclass(frozen=True, slots=True)
class SolveResult:
    status_code: int
    status_name: str
    has_solution: bool
    objective_value: float | None
    cost: float | None
    emissions: float | None
    follower_objective: float | None
    tax: float | None
    mip_gap: float | None
    runtime: float
    variable_values: dict[str, float] | None = None
    objective_bound: float | None = None
    # Discounted emission aggregate the tax was levied on. Equals ``emissions``
    # on an undiscounted instance.
    tax_base: float | None = None
    status_history: tuple[str, ...] = ()
    iis_constraints: tuple[str, ...] = ()
    iis_variable_bounds: tuple[str, ...] = ()
    slack_value: float | None = None
    # Populated only by the follower's two-stage solve. Each field carries the
    # MIP gap reported by Gurobi at the corresponding stage; `mip_gap` (above)
    # carries the worst (largest) of the two for compatibility with single-
    # objective callers.
    lex_primary_mip_gap: float | None = None
    lex_secondary_mip_gap: float | None = None
    # Populated only by the DBP high-point relaxation: the PROVEN dual bound on the leader's objective
    # F = E + w*tax, in kg (the HPR's ObjBound). Always a valid lower bound on the
    # bilevel optimum, whether or not the solve reached OPTIMAL -- which is what lets the DBP loop
    # keep a partially solved HPR's bound instead of discarding it. None when Gurobi reported
    # no finite bound.
    leader_lower_bound: float | None = None
    # Populated only by solve_follower_lexicographic. Soares et al. (2021, Sect. 7, Difficulty
    # 2.2): when the follower stops on its time limit, subproblem (P6) searches for a response
    # better than the incumbent; these record its time and whether it found one. And (P4-D):
    # when the optimistic tie-break finds no point within its budget, the Step-2 response is
    # kept -- `follower_stage2_fallback` says that happened.
    follower_improvement_seconds: float | None = None
    follower_improved: bool | None = None
    follower_stage2_fallback: bool = False


def apply_mip_start(model: gp.Model, variable_values: dict[str, float] | None) -> None:
    model.NumStart = 1
    model.Params.StartNumber = 0
    for variable in model.getVars():
        variable.Start = GRB.UNDEFINED
        if not variable_values:
            continue
        value = variable_values.get(variable.VarName)
        if value is not None:
            variable.Start = float(value)


def optimize_model(
    artifacts: ModelArtifacts,
    *,
    tax: float | None,
    output_flag: bool,
    time_limit: float | None,
    capture_solution: bool,
    compute_iis: bool = True,
    mip_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
    seed: int | None = None,
    mip_gap_abs: float | None = None,
) -> SolveResult:
    model = artifacts.model
    model.Params.OutputFlag = 1 if output_flag else 0
    if time_limit is not None:
        model.Params.TimeLimit = time_limit
    model.Params.MIPGap = DEFAULT.mip_gap if mip_gap is None else mip_gap
    # Always written, never merely when requested: these models are persistent and re-solved
    # many times, so a value left behind by one call would silently govern the next.
    # 1e-10 is Gurobi's own default.
    model.Params.MIPGapAbs = 1e-10 if mip_gap_abs is None else mip_gap_abs
    model.Params.Threads = DEFAULT.threads if threads is None else threads
    model.Params.MIPFocus = DEFAULT.mip_focus if mip_focus is None else mip_focus
    if seed is not None:
        model.Params.Seed = seed

    status_history: list[str] = []
    model.optimize()

    has_solution = model.SolCount > 0
    status_code = int(model.Status)
    status_name = _status_name(status_code)
    status_history.append(status_name)
    if status_code == GRB.INF_OR_UNBD:
        model.Params.DualReductions = 0
        model.reset()
        model.optimize()
        has_solution = model.SolCount > 0
        status_code = int(model.Status)
        status_name = _status_name(status_code)
        status_history.append(status_name)
    mip_gap_value = _model_float_attribute(model, "MIPGap") if has_solution else None
    runtime = float(model.Runtime)
    objective_bound = _model_float_attribute(model, "ObjBound")
    iis_constraints: tuple[str, ...] = ()
    iis_variable_bounds: tuple[str, ...] = ()
    if compute_iis and status_code == GRB.INFEASIBLE:
        iis_constraints, iis_variable_bounds = _compute_iis_summary(model)

    if not has_solution:
        return SolveResult(
            status_code=status_code,
            status_name=status_name,
            has_solution=False,
            objective_value=None,
            cost=None,
            emissions=None,
            follower_objective=None,
            tax=tax,
            mip_gap=mip_gap_value,
            runtime=runtime,
            variable_values=None,
            objective_bound=objective_bound,
            status_history=tuple(status_history),
            iis_constraints=iis_constraints,
            iis_variable_bounds=iis_variable_bounds,
            slack_value=None,
        )

    tax_value = tax
    if artifacts.tax_var is not None:
        tax_value = float(artifacts.tax_var.X)

    return SolveResult(
        status_code=status_code,
        status_name=status_name,
        has_solution=True,
        objective_value=float(model.ObjVal),
        cost=float(artifacts.cost_expr.getValue()),
        emissions=float(artifacts.emissions_expr.getValue()),
        tax_base=float(tax_base_of(artifacts).getValue()),
        follower_objective=float(artifacts.follower_objective_expr.getValue()),
        tax=tax_value,
        mip_gap=mip_gap_value,
        runtime=runtime,
        variable_values=_extract_nonzero_variable_values(model) if capture_solution else None,
        objective_bound=objective_bound,
        status_history=tuple(status_history),
        iis_constraints=iis_constraints,
        iis_variable_bounds=iis_variable_bounds,
        slack_value=float(artifacts.elastic_slack_var.X) if artifacts.elastic_slack_var is not None else None,
    )


def tax_base_of(artifacts: ModelArtifacts) -> gp.LinExpr:
    """Expression the carbon tax multiplies.

    Artifacts built before the discounted tax base existed (and any constructed
    without it in tests) fall back to the physical emissions, which is exactly
    the undiscounted semantics.
    """
    return artifacts.emissions_expr if artifacts.tax_base_expr is None else artifacts.tax_base_expr


def normalize_solution_value(
    variable: gp.Var,
    value: float,
    *,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
) -> float:
    if variable.VType != GRB.CONTINUOUS and abs(value - round(value)) <= INTEGER_SNAP_TOL:
        value = float(round(value))
    if lower_bound is not None and value < lower_bound and value >= lower_bound - BOUND_SNAP_TOL:
        return lower_bound
    if upper_bound is not None and value > upper_bound and value <= upper_bound + BOUND_SNAP_TOL:
        return upper_bound
    return value


def _extract_nonzero_variable_values(model: gp.Model, *, tolerance: float = 0.0) -> dict[str, float]:
    values: dict[str, float] = {}
    for variable in model.getVars():
        value = normalize_solution_value(variable, float(variable.X))
        if abs(value) > tolerance:
            values[variable.VarName] = value
    return values


def finite_dual_bound(bound: float | None) -> float | None:
    """Gurobi reports an absent dual bound as +/-1e100 rather than as None."""
    if bound is None or not math.isfinite(bound) or abs(bound) >= 1e50:
        return None
    return float(bound)


def _model_float_attribute(model: gp.Model, attribute: str) -> float | None:
    try:
        value = getattr(model, attribute)
    except (AttributeError, gp.GurobiError):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compute_iis_summary(model: gp.Model) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        model.computeIIS()
    except gp.GurobiError:
        return (), ()

    iis_constraints = tuple(sorted(constraint.ConstrName for constraint in model.getConstrs() if constraint.IISConstr))
    iis_variable_bounds = tuple(
        sorted(
            entry
            for variable in model.getVars()
            for entry in (
                (f"{variable.VarName}:LB" if variable.IISLB else None),
                (f"{variable.VarName}:UB" if variable.IISUB else None),
            )
            if entry is not None
        )
    )
    return iis_constraints, iis_variable_bounds


def _status_name(status_code: int) -> str:
    names = {
        GRB.LOADED: "LOADED",
        GRB.OPTIMAL: "OPTIMAL",
        GRB.INFEASIBLE: "INFEASIBLE",
        GRB.INF_OR_UNBD: "INF_OR_UNBD",
        GRB.UNBOUNDED: "UNBOUNDED",
        GRB.CUTOFF: "CUTOFF",
        GRB.ITERATION_LIMIT: "ITERATION_LIMIT",
        GRB.NODE_LIMIT: "NODE_LIMIT",
        GRB.TIME_LIMIT: "TIME_LIMIT",
        GRB.SOLUTION_LIMIT: "SOLUTION_LIMIT",
        GRB.INTERRUPTED: "INTERRUPTED",
        GRB.NUMERIC: "NUMERIC",
        GRB.SUBOPTIMAL: "SUBOPTIMAL",
        GRB.USER_OBJ_LIMIT: "USER_OBJ_LIMIT",
    }
    return names.get(status_code, f"STATUS_{status_code}")
