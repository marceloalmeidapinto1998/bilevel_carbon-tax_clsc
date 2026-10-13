"""The DBP high-point relaxation (HPR): the leader's objective F = E + w * tax, the value-function
cuts, the objective cap, the elastic-cut remedy, and the HPR's solve.

The leader's tax is a continuous variable, in EUR per tonne of CO2e. The follower's objective
contains the product of the tax and the discounted emissions (tax * beta), a bilinear term in two
continuous variables. The HPR carries it as a non-convex quadratic equality, which Gurobi solves by
spatial branch-and-bound (``NonConvex=2``), so the relaxation stays exact.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from typing import Iterable

import gurobipy as gp
from gurobipy import GRB

from clsc.config.constants import KG_PER_TONNE
from clsc.config.defaults import DEFAULT
from .instance_data import InstanceData
from .gurobi_utils import ModelArtifacts, SolveResult, finite_dual_bound, optimize_model
from .supply_chain import build_supply_chain_model, total_emissions_upper_bound
from .follower import epsilon_prime_tolerance


# The HPR works in tonnes of CO2e (kg / EMISSIONS_SCALE), which keeps its coefficients moderate.
EMISSIONS_SCALE = KG_PER_TONNE


@dataclass(frozen=True, slots=True)
class ValueFunctionCut:
    tax: float
    cost: float
    emissions: float
    iteration: int
    # Discounted emission aggregate at this point (kg); the cut's tax coefficient.
    # None means "undiscounted instance", where it equals ``emissions``.
    tax_base: float | None = None


@dataclass(slots=True)
class HighPointRelaxation:
    artifacts: ModelArtifacts
    lower_tax: float = 0.0
    upper_tax: float = 0.0
    # Build-time bound on the total emissions, kg: every facility open, every technology at
    # capacity, in every period.
    emissions_upper_bound: float = 0.0
    applied_cut_iterations: set[int] = field(default_factory=set)
    # Slack added to the right-hand side of every cut: f(tax, y) <= f(tax, y_k) + cut_slack, in EUR.
    # Set by the DBP from its parameter (DEFAULT.cut_slack).
    cut_slack: float = 0.0
    emissions_cap_constraint: gp.Constr | None = None
    emissions_cap: float | None = None
    # (P5-D): every value-function cut carries its own elastic slack D_k, penalised in the
    # objective, so the HPR always has a feasible point to return. The slacks are summed into
    # `artifacts.elastic_slack_var` by `elastic_total_constraint`.
    elastic: bool = False
    elastic_penalty: float = 0.0
    elastic_total_constraint: gp.Constr | None = None
    # Handles of the value-function cut rows, by iteration, so the cuts can be made elastic in
    # place (enable_elastic_cuts) when the HPR first fails to return a point.
    cut_constraints: dict[int, gp.Constr] = field(default_factory=dict)
    # Weight of the tax in the leader's objective F = E + w * tax, in tonnes of emissions per
    # EUR/t (the HPR works in tonnes). 0.0 only before the weight is set.
    tax_weight_scaled: float = 0.0
    # F <= UB (Mitsos 2010), a two-variable row: see set_leader_objective_cap.
    objective_cap_constraint: gp.Constr | None = None
    # The bilinear product's operands and result, kept so the emissions cap can tighten their
    # bounds, which tightens the spatial branching: tax_base_var is the discounted emissions
    # (tonnes), tax_payment_var is tax * tax_base (EUR).
    tax_base_var: gp.Var | None = None
    tax_payment_var: gp.Var | None = None
    tax_base_upper_bound_scaled: float = 0.0


def solve_hpr(
    instance_or_hpr: InstanceData | HighPointRelaxation,
    cuts: list[ValueFunctionCut] | None = None,
    *,
    output_flag: bool = False,
    time_limit: float | None = None,
    capture_solution: bool = False,
    mip_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
    seed: int | None = None,
) -> SolveResult:
    """Solve the DBP high-point relaxation: minimise the leader's objective ``F = E + w * tax``
    (plus the elastic penalty once the cuts are elastic) over the follower's feasible region and
    every cut accumulated so far -- Soares et al. (2021)'s (P5), one stage.

    The returned ``emissions`` and ``leader_lower_bound`` are the HPR's DUAL bound on F, in
    kg, not the incumbent's value. Every cut is valid at every tax, so the HPR is a relaxation
    and its optimum is a valid lower bound on the bilevel optimum. A MIP solve hands back two
    numbers around that optimum: ObjVal, the best solution found, which lies at or ABOVE it, and
    ObjBound, the proven dual bound, which lies at or BELOW it. Only ObjBound is a bound in the
    required direction.

    An HPR that stops on its time limit is a PARTIAL HPR: its dual bound is still valid, and
    if it found any point, that point's ``tax`` is a usable next proposal (Soares et al., Sect. 7).
    What a partial HPR cannot do is certify Lemma 3.
    """
    if isinstance(instance_or_hpr, HighPointRelaxation):
        hpr = instance_or_hpr
    else:
        hpr = build_hpr(instance_or_hpr)
    if cuts:
        _synchronize_hpr(hpr, cuts)

    artifacts = hpr.artifacts
    model = artifacts.model
    if artifacts.emissions_total_var is None or artifacts.tax_var is None:
        raise RuntimeError(
            "DBP high-point relaxation is missing the emissions/tax variables "
            "required for the relaxation solve"
        )
    objective = _hpr_objective(hpr)
    model.setObjective(objective, GRB.MINIMIZE)
    result = optimize_model(
        artifacts,
        tax=None,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=capture_solution,
        mip_gap=mip_gap,
        threads=threads,
        mip_focus=mip_focus,
        seed=seed,
    )
    if result.status_name not in ("OPTIMAL", "TIME_LIMIT"):
        return result
    bound_scaled = finite_dual_bound(result.objective_bound)
    if bound_scaled is None and result.status_name == "OPTIMAL" and result.objective_value is not None:
        # An optimal solve with no reported bound: the optimum is its own bound.
        bound_scaled = float(result.objective_value)
    bound_kg = None if bound_scaled is None else bound_scaled * EMISSIONS_SCALE
    return replace(
        result,
        emissions=bound_kg if result.has_solution else None,
        leader_lower_bound=bound_kg,
    )


def build_hpr(
    instance: InstanceData,
    *,
    elastic: bool = False,
) -> HighPointRelaxation:
    elastic_slack_penalty_multiplier = DEFAULT.elastic_penalty_mult

    common = build_supply_chain_model(instance, model_name="hpr")
    model = common.model

    lower_tax = instance.lower_tax
    upper_tax = instance.upper_tax
    tax = model.addVar(lb=lower_tax, ub=upper_tax, name="tax")

    emissions_upper_bound = total_emissions_upper_bound(instance)
    emissions_upper_bound_scaled = emissions_upper_bound / EMISSIONS_SCALE
    emissions_total_scaled = model.addVar(
        lb=0.0,
        ub=emissions_upper_bound_scaled,
        name="total_emissions_tonnes",
    )
    model.addConstr(
        emissions_total_scaled == common.emissions_expr / EMISSIONS_SCALE,
        name="total_emissions_tonnes_def",
    )

    # The leader minimises emissions_total_scaled (PHYSICAL emissions); the follower pays tax on
    # the discounted base. On an undiscounted instance the two coincide and share one variable.
    if common.tax_base_expr is common.emissions_expr:
        tax_base_scaled = emissions_total_scaled
    else:
        tax_base_scaled = model.addVar(
            lb=0.0,
            ub=emissions_upper_bound_scaled,
            name="tax_base_tonnes",
        )
        model.addConstr(
            tax_base_scaled == common.tax_base_expr / EMISSIONS_SCALE,
            name="tax_base_tonnes_def",
        )

    # The follower's tax bill, tax [EUR/t] * discounted emissions [t], in EUR: a bilinear equality
    # in two continuous variables, solved by Gurobi's spatial branch-and-bound.
    tax_payment = model.addVar(
        lb=0.0,
        ub=upper_tax * emissions_upper_bound_scaled,
        name="tax_payment_eur",
    )
    model.addConstr(tax_payment == tax * tax_base_scaled, name="tax_payment_def")
    model.Params.NonConvex = 2
    follower_objective_expr = common.cost_expr + tax_payment

    # (P5-D) of Soares et al. (2021): with `elastic`, each cut gets its own slack D_k >= 0 (added
    # by add_value_function_cut), and `dbp_elastic_slack_total` == sum(D_k) is penalised in the
    # objective. The penalty is per EUR of cut violation and in the objective's tonnes: at
    # emissions_upper_bound_scaled * multiplier, violating any cut by more than 1/multiplier EUR
    # costs more than the entire emissions range, so D > 0 is chosen only where no D = 0 point
    # exists within the solver's reach. It never weakens the lower bound: D = 0 points keep their
    # objective, so the elastic optimum -- and its dual bound -- is at most the original's.
    elastic_slack_var: gp.Var | None = None
    elastic_total_constraint: gp.Constr | None = None
    elastic_penalty = 0.0
    if elastic:
        elastic_slack_var = model.addVar(lb=0.0, name="dbp_elastic_slack_total")
        elastic_total_constraint = model.addConstr(elastic_slack_var == 0.0, name="dbp_elastic_slack_total_def")
        elastic_penalty = max(1.0, emissions_upper_bound_scaled) * elastic_slack_penalty_multiplier
        model.setObjective(emissions_total_scaled + elastic_penalty * elastic_slack_var, GRB.MINIMIZE)
    else:
        model.setObjective(emissions_total_scaled, GRB.MINIMIZE)
    return HighPointRelaxation(
        artifacts=ModelArtifacts(
            model=model,
            cost_expr=common.cost_expr,
            emissions_expr=common.emissions_expr,
            tax_base_expr=common.tax_base_expr,
            follower_objective_expr=follower_objective_expr,
            tax_var=tax,
            emissions_total_var=emissions_total_scaled,
            elastic_slack_var=elastic_slack_var,
        ),
        lower_tax=lower_tax,
        upper_tax=upper_tax,
        emissions_upper_bound=emissions_upper_bound,
        elastic=elastic,
        elastic_penalty=elastic_penalty,
        elastic_total_constraint=elastic_total_constraint,
        tax_base_var=tax_base_scaled,
        tax_payment_var=tax_payment,
        tax_base_upper_bound_scaled=emissions_upper_bound_scaled,
    )


def add_value_function_cut(hpr: HighPointRelaxation, cut: ValueFunctionCut) -> None:
    if cut.iteration in hpr.applied_cut_iterations:
        return

    tax = hpr.artifacts.tax_var
    if tax is None:
        raise RuntimeError("DBP high-point relaxation is missing the leader tax variable")

    # cut.tax_base is the discounted aggregate (kg) the follower was taxed on at this point; it
    # coincides with cut.emissions on an undiscounted instance. Being a constant read off an
    # already-solved point, its product with the leader's tax is linear. The tax is in EUR/t and
    # the aggregate in kg, so the rate per kg is tax / KG_PER_TONNE.
    cut_tax_base = cut.emissions if cut.tax_base is None else cut.tax_base
    right_hand_side = (
        cut.cost
        + (cut_tax_base / KG_PER_TONNE) * tax
        + hpr.cut_slack
    )
    if hpr.elastic and hpr.elastic_total_constraint is not None:
        # (P5-D): this cut's own slack D_k, summed into the penalised total.
        cut_slack = hpr.artifacts.model.addVar(lb=0.0, name=f"dbp_cut_slack_{cut.iteration}")
        hpr.artifacts.model.update()
        hpr.artifacts.model.chgCoeff(hpr.elastic_total_constraint, cut_slack, -1.0)
        right_hand_side += cut_slack

    hpr.cut_constraints[cut.iteration] = hpr.artifacts.model.addConstr(
        hpr.artifacts.follower_objective_expr <= right_hand_side,
        name=f"dbp_cut_{cut.iteration}",
    )
    hpr.applied_cut_iterations.add(cut.iteration)


def _hpr_objective(hpr: HighPointRelaxation) -> gp.LinExpr:
    """Stage-1 objective of the HPR: the leader's objective in tonnes -- total
    emissions plus ``tax_weight_scaled * tax`` -- plus the (P5-D) elastic penalty when the
    cuts are elastic."""
    objective = gp.LinExpr(hpr.artifacts.emissions_total_var)
    if hpr.tax_weight_scaled > 0.0 and hpr.artifacts.tax_var is not None:
        objective += hpr.tax_weight_scaled * hpr.artifacts.tax_var
    if hpr.elastic and hpr.artifacts.elastic_slack_var is not None:
        objective += hpr.elastic_penalty * hpr.artifacts.elastic_slack_var
    return objective


def set_leader_tax_weight(hpr: HighPointRelaxation, weight_kg_per_eur_t: float) -> None:
    """Make the leader's objective ``F = E + w * tax`` (``w`` in kg CO2e per EUR/t).

    This is the single-objective leader of Soares et al. (2021): one criterion, so their DBP --
    one HPR stage, the UB_F - LB_F gap, Lemma 3 -- applies as written. The tax is the
    leader's own variable, so the extra term is linear; ``w`` states how much emissions the
    regulator would give up to avoid one more EUR/t of tax, which is what decides among taxes
    that abate the same.
    """
    if weight_kg_per_eur_t < 0.0:
        raise ValueError("the leader's tax weight must be non-negative")
    hpr.tax_weight_scaled = weight_kg_per_eur_t / EMISSIONS_SCALE
    hpr.artifacts.model.setObjective(_hpr_objective(hpr), GRB.MINIMIZE)
    hpr.artifacts.model.update()


def set_leader_objective_cap(hpr: HighPointRelaxation, leader_objective_ub: float | None) -> None:
    """Bound the HPR's leader objective from above by the best value any evaluated point
    attained: ``E + w * tax <= UB`` -- Soares et al. (2021, Sect. 8)'s ``F <= UB_F``
    (Mitsos 2010) in its natural form for this leader. It removes nothing the HPR could still
    return as optimal (the optimum is at most UB) and stops it exploring points already known to
    be worse than the incumbent. Only two variables appear, so the row is as cheap as the cap on
    emissions alone. A no-op while the tax weight is zero, where ``set_emissions_cap`` is it.
    """
    if leader_objective_ub is None or hpr.tax_weight_scaled <= 0.0:
        return
    artifacts = hpr.artifacts
    model = artifacts.model
    # Widened by the same relative tolerance as set_emissions_cap: the UB comes from a different
    # model, and an exact cutoff could exclude the incumbent from its own relaxation.
    ub_scaled = (leader_objective_ub + epsilon_prime_tolerance(leader_objective_ub)) / EMISSIONS_SCALE
    if hpr.objective_cap_constraint is None:
        hpr.objective_cap_constraint = model.addConstr(
            artifacts.emissions_total_var + hpr.tax_weight_scaled * artifacts.tax_var <= ub_scaled,
            name="dbp_leader_objective_cap",
        )
    elif math.isclose(hpr.objective_cap_constraint.RHS, ub_scaled, abs_tol=DEFAULT.eps):
        return
    else:
        hpr.objective_cap_constraint.RHS = ub_scaled
    model.update()


def enable_elastic_cuts(hpr: HighPointRelaxation) -> bool:
    """Make the HPR's value-function cuts elastic IN PLACE -- Soares et al. (2021)'s (P5-D),
    applied the way they introduce it: as the remedy once the plain HPR fails to return a
    point (their Difficulty 1), not from the start. Each existing cut gets its own slack
    D_k >= 0 on its right-hand side, the slacks are summed into ``elastic_slack_var`` and
    penalised in the objective (see build_hpr for the penalty's size), and every cut
    added afterwards is elastic too. Returns False if the HPR was already elastic.
    """
    if hpr.elastic:
        return False
    model = hpr.artifacts.model
    total = model.addVar(lb=0.0, name="dbp_elastic_slack_total")
    model.update()
    total_row = model.addConstr(total == 0.0, name="dbp_elastic_slack_total_def")
    model.update()
    for iteration, cut_row in hpr.cut_constraints.items():
        cut_slack = model.addVar(lb=0.0, name=f"dbp_cut_slack_{iteration}")
        model.update()
        # Cut row: f(x, y) - ... <= rhs. A slack on the right-hand side is a -1 coefficient.
        model.chgCoeff(cut_row, cut_slack, -1.0)
        model.chgCoeff(total_row, cut_slack, -1.0)
    hpr.elastic = True
    hpr.elastic_penalty = (
        max(1.0, hpr.emissions_upper_bound / EMISSIONS_SCALE) * DEFAULT.elastic_penalty_mult
    )
    hpr.elastic_total_constraint = total_row
    hpr.artifacts.elastic_slack_var = total
    model.setObjective(_hpr_objective(hpr), GRB.MINIMIZE)
    model.update()
    return True


def set_hpr_start(
    hpr: HighPointRelaxation,
    follower_values: dict[str, float],
    follower_variable_names: Iterable[str],
    tax: float,
) -> None:
    """MIP start for the HPR at an already-evaluated point (tax, y): the follower's
    variables by name (absent names are the zeros the follower snapshot omits) and the tax.
    The continuous auxiliary variables and any elastic slacks are left for Gurobi to complete.
    With elastic cuts and y the best-emissions response (so that it meets the emissions cap)
    this start is feasible, which is what guarantees the HPR a point.
    """
    model = hpr.artifacts.model
    for variable in model.getVars():
        variable.Start = GRB.UNDEFINED
    for name in follower_variable_names:
        variable = model.getVarByName(name)
        if variable is not None:
            variable.Start = float(follower_values.get(name, 0.0))
    if hpr.artifacts.tax_var is not None:
        hpr.artifacts.tax_var.Start = float(tax)
    model.update()


def _tighten_tax_base_bounds(hpr: HighPointRelaxation, cap_scaled: float | None) -> None:
    """Bound the tax base, and so the tax payment, by the emissions cap, in tonnes.

    ``E <= cap`` holds in the HPR once an incumbent exists, and the tax base never exceeds the
    emissions (every per-period weight is at most 1), so the cap bounds the tax base, usually
    far below the build-time bound. Tighter bounds on the operands of the bilinear product
    tighten Gurobi's spatial branching. The bound is recomputed from the build-time value on
    every call, so removing or raising the cap restores a valid, looser one.
    """
    if hpr.tax_base_var is None or hpr.tax_payment_var is None:
        return
    target = hpr.tax_base_upper_bound_scaled
    if cap_scaled is not None:
        target = min(target, cap_scaled)
    hpr.tax_base_var.UB = target
    hpr.tax_payment_var.UB = hpr.upper_tax * target
    hpr.artifacts.model.update()


def set_emissions_cap(
    hpr: HighPointRelaxation,
    upper_bound: float | None,
) -> None:
    emissions_total_var = hpr.artifacts.emissions_total_var
    if emissions_total_var is None:
        raise RuntimeError("DBP high-point relaxation is missing the scaled emissions objective variable")

    if upper_bound is None:
        if hpr.emissions_cap_constraint is not None:
            hpr.artifacts.model.remove(hpr.emissions_cap_constraint)
            hpr.emissions_cap_constraint = None
            hpr.emissions_cap = None
            hpr.artifacts.model.update()
            _tighten_tax_base_bounds(hpr, None)
        return

    if upper_bound < 0:
        raise ValueError("upper_bound must be nonnegative")

    # Widen the cutoff by a tiny relative tolerance: `upper_bound` is the value reported by a
    # *different*, independently built Gurobi model (the optimistic follower solve), so
    # floating-point reconstruction of the same physical point inside this HPR's own LinExpr can
    # land a hair above it. An exact (non-widened) cutoff can then spuriously exclude the true
    # incumbent point from its own relaxation, making the HPR falsely INFEASIBLE. Mirrors the
    # same relative-tolerance pattern as `epsilon_prime_tolerance`.
    tolerant_upper_bound = upper_bound + epsilon_prime_tolerance(upper_bound)

    if hpr.emissions_cap is not None and math.isclose(
        tolerant_upper_bound,
        hpr.emissions_cap,
        abs_tol=DEFAULT.eps,
    ):
        return

    scaled_upper_bound = tolerant_upper_bound / EMISSIONS_SCALE
    if hpr.emissions_cap_constraint is None:
        hpr.emissions_cap_constraint = hpr.artifacts.model.addConstr(
            emissions_total_var <= scaled_upper_bound,
            name="dbp_emissions_cap",
        )
        hpr.artifacts.model.update()
    else:
        hpr.emissions_cap_constraint.RHS = scaled_upper_bound
    hpr.emissions_cap = tolerant_upper_bound
    _tighten_tax_base_bounds(hpr, scaled_upper_bound)


def _synchronize_hpr(hpr: HighPointRelaxation, cuts: Iterable[ValueFunctionCut]) -> None:
    added_cut = False
    for cut in cuts:
        if cut.iteration in hpr.applied_cut_iterations:
            continue
        add_value_function_cut(hpr, cut)
        added_cut = True
    if added_cut:
        hpr.artifacts.model.update()
