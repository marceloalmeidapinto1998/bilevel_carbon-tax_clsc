"""The follower: its fixed-tax MILP and the two-stage optimistic solve (minimise cost plus tax,
then emissions among the cost-optimal responses), with Soares et al. (2021)'s P6 and P4-D
treatment of a follower that stops on its time limit.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import gurobipy as gp
from gurobipy import GRB

from clsc.config.defaults import DEFAULT
from .instance_data import InstanceData
from .gurobi_utils import ModelArtifacts, SolveResult, apply_mip_start, normalize_solution_value, optimize_model, tax_base_of
from .supply_chain import build_supply_chain_model


@dataclass(slots=True)
class FollowerModel:
    instance: InstanceData
    artifacts: ModelArtifacts


def solve_follower_lexicographic(
    instance_or_model: InstanceData | FollowerModel,
    tax: float,
    *,
    output_flag: bool = False,
    time_limit: float | None = None,
    capture_solution: bool = False,
    warm_start_values: dict[str, float] | None = None,
    mip_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
    seed: int | None = None,
    use_follower_improvement: bool = True,
) -> SolveResult:
    """Explicit two-stage lexicographic solve over the fixed-tax follower -- Soares et al.
    (2021)'s Steps 2-3, (P3) then (P4-eps'), with their Section 7 treatment of a follower that
    cannot be solved to optimality inside its budget.

    Stage 1 (P3) minimises ``cost + tau * emissions``. Stage 2 (P4-eps') minimises
    ``emissions`` over the responses with ``f <= f* + eps'`` (see :func:`epsilon_prime_tolerance`).

    When Stage 1 stops on its time limit with a positive gap, subproblem (P6) is solved:
    ``min D  s.t.  f <= f* (1 - gap) + D,  D >= 0`` -- a search for a response better than the
    incumbent, adopted as f* if it finds one (``use_follower_improvement``). When Stage 2 finds
    no point within its budget, the Stage-1 (or P6) response is kept, as Soares et al. keep the
    Step-2 solution when (P4-D) yields nothing acceptable. Either way the run continues: a
    follower that stops on its time limit returns status ``TIME_LIMIT`` WITH a solution, and only
    a follower with no solution at all is a failure.

    The returned :class:`SolveResult` carries both per-stage MIP gaps. The ``mip_gap`` field
    reports the worst (largest) of the two so single-objective consumers see a conservative bound.
    """
    follower_model = _coerce_follower_model(instance_or_model)
    _set_fixed_tax_follower_expression(follower_model, tax)
    artifacts = follower_model.artifacts
    model = artifacts.model
    model.ModelSense = GRB.MINIMIZE
    apply_mip_start(model, warm_start_values)

    # Stage 1 (P3): minimise follower objective (cost + tau * emissions). Its solution is always
    # captured: it is the MIP start for (P6) and Stage 2, and the fallback response if Stage 2
    # finds nothing.
    model.setObjective(artifacts.follower_objective_expr, GRB.MINIMIZE)
    stage1 = optimize_model(
        artifacts,
        tax=tax,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=True,
        mip_gap=mip_gap,
        threads=threads,
        mip_focus=mip_focus,
        seed=seed,
    )
    if not stage1.has_solution or stage1.status_name not in ("OPTIMAL", "TIME_LIMIT"):
        return replace(
            stage1,
            tax=tax,
            variable_values=stage1.variable_values if capture_solution else None,
            lex_primary_mip_gap=stage1.mip_gap,
            lex_secondary_mip_gap=None,
        )

    reference = stage1
    improvement_seconds: float | None = None
    improved: bool | None = None
    if stage1.status_name == "TIME_LIMIT" and use_follower_improvement and (stage1.mip_gap or 0.0) > 0.0:
        improvement = _improve_follower_value(
            artifacts,
            stage1,
            tax=tax,
            output_flag=output_flag,
            time_limit=time_limit,
            mip_gap=mip_gap,
            threads=threads,
            mip_focus=mip_focus,
            seed=seed,
        )
        improvement_seconds = improvement.runtime
        incumbent_value = float(stage1.follower_objective)
        improved = (
            improvement.has_solution
            and improvement.follower_objective is not None
            and improvement.follower_objective < incumbent_value - epsilon_prime_tolerance(incumbent_value)
        )
        if improved:
            reference = improvement

    primary_optimum = float(reference.follower_objective)
    freeze = model.addConstr(
        artifacts.follower_objective_expr <= primary_optimum + epsilon_prime_tolerance(primary_optimum),
        name="lex_primary_freeze",
    )
    model.update()
    # The reference response satisfies the freeze by construction, so Stage 2 always has a start.
    apply_mip_start(model, reference.variable_values)

    # Stage 2 (P4-eps'): minimise emissions subject to the freeze.
    model.setObjective(artifacts.emissions_expr, GRB.MINIMIZE)
    stage2 = optimize_model(
        artifacts,
        tax=tax,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=capture_solution,
        mip_gap=mip_gap,
        threads=threads,
        mip_focus=mip_focus,
        seed=seed,
    )
    # Remove the freeze constraint so the artifacts can be safely re-used if
    # callers retain a reference to the model.
    try:
        model.remove(freeze)
        model.update()
    except gp.GurobiError:
        pass

    stage2_fallback = not stage2.has_solution
    chosen = reference if stage2_fallback else stage2
    if stage2_fallback and not capture_solution:
        chosen = replace(chosen, variable_values=None)

    primary_gap = reference.mip_gap
    secondary_gap = None if stage2_fallback else stage2.mip_gap
    merged_mip_gap: float | None
    if primary_gap is None and secondary_gap is None:
        merged_mip_gap = None
    else:
        merged_mip_gap = max(g for g in (primary_gap, secondary_gap) if g is not None)

    # The response is "solved" only if both stages reached their targets; otherwise it is the
    # best response found inside the budget, which the caller must treat as such.
    solved = stage1.status_name == "OPTIMAL" and stage2.status_name == "OPTIMAL"
    return replace(
        chosen,
        status_code=chosen.status_code if solved else GRB.TIME_LIMIT,
        status_name="OPTIMAL" if solved else "TIME_LIMIT",
        tax=tax,
        mip_gap=merged_mip_gap,
        runtime=stage1.runtime + (improvement_seconds or 0.0) + stage2.runtime,
        status_history=stage1.status_history + stage2.status_history,
        lex_primary_mip_gap=primary_gap,
        lex_secondary_mip_gap=secondary_gap,
        follower_improvement_seconds=improvement_seconds,
        follower_improved=improved,
        follower_stage2_fallback=stage2_fallback,
    )


def _improve_follower_value(
    artifacts: ModelArtifacts,
    stage1: SolveResult,
    *,
    tax: float,
    output_flag: bool,
    time_limit: float | None,
    mip_gap: float | None,
    threads: int | None,
    mip_focus: int | None,
    seed: int | None,
) -> SolveResult:
    """Soares et al. (2021)'s subproblem (P6): ``min D  s.t.  f(x, y) <= f* (1 - gap_LL) + D``.

    ``f* (1 - gap_LL)`` is the solver's own dual bound on the follower optimum, so D measures how
    far a response sits above that bound; driving it down searches for a response better than
    the timed-out incumbent. Started from the Stage-1 incumbent, so it never returns worse.
    """
    model = artifacts.model
    gap = stage1.mip_gap or 0.0
    target = float(stage1.follower_objective) * (1.0 - gap)
    shortfall = model.addVar(lb=0.0, name="p6_shortfall")
    target_row = model.addConstr(
        artifacts.follower_objective_expr <= target + shortfall,
        name="p6_target",
    )
    model.setObjective(shortfall, GRB.MINIMIZE)
    model.update()
    apply_mip_start(model, stage1.variable_values)
    try:
        return optimize_model(
            artifacts,
            tax=tax,
            output_flag=output_flag,
            time_limit=time_limit,
            capture_solution=True,
            mip_gap=mip_gap,
            threads=threads,
            mip_focus=mip_focus,
            seed=seed,
        )
    finally:
        model.remove(target_row)
        model.remove(shortfall)
        model.update()


def epsilon_prime_tolerance(value: float) -> float:
    """eps': the single tolerance added to a follower objective value, in the tie-break freeze
    ``f <= f* + eps'`` -- Soares et al. (2021)'s (P4-eps'). The HPR's cuts add no eps' of their
    own (see ``DEFAULT.cut_slack``).

    Relative (``DEFAULT.epsilon_prime * |value|``) rather than absolute, so it means the same
    thing at every instance scale, with ``DEFAULT.eps`` as an absolute floor near zero. Soares et
    al.'s eps' = 1e-5 sits on objectives of a few euros, i.e. ~1e-6 relative.

    NOT widened by the primary solve's MIP gap, as it was until 2026-10-08. That widening rested
    on the claim that a loose stopping gap could exclude the true optimum from the tie-break; it
    cannot -- the true optimum lies at or BELOW the incumbent f*, so ``f <= f* + eps'`` already
    contains it and every other optimal point. What the widening added was points WORSE than the
    incumbent by up to the gap: at a 1% gap, responses 1% off the follower's optimum admitted
    into the optimistic tie-break. Soares et al. freeze at ``f* + eps'`` and attack the gap itself
    with subproblem (P6) instead (see solve_follower_lexicographic).
    """
    return max(DEFAULT.eps, DEFAULT.epsilon_prime * abs(value))


def _require_tax_in_bounds(instance: InstanceData, tax: float) -> None:
    # A little slack: the HPR returns the tax to within the solver's feasibility tolerance.
    slack = 1e-6 * max(1.0, abs(instance.upper_tax))
    if not instance.lower_tax - slack <= tax <= instance.upper_tax + slack:
        raise ValueError(f"tax={tax} EUR/t is outside the instance bounds")


def build_fixed_tax_model(
    instance: InstanceData,
    *,
    tax: float,
    tie_break: bool = False,
) -> ModelArtifacts:
    _require_tax_in_bounds(instance, tax)

    common = build_supply_chain_model(instance, model_name=f"fixed_tau_{tax}")
    follower_objective_expr = (
        common.cost_expr
        + instance.tax_rate(tax) * common.tax_base_expr
    )

    # tie_break minimises PHYSICAL emissions: that is the leader's criterion,
    # not the operator's tax bill.
    common.model.setObjective(common.emissions_expr if tie_break else follower_objective_expr, GRB.MINIMIZE)
    return ModelArtifacts(
        model=common.model,
        cost_expr=common.cost_expr,
        emissions_expr=common.emissions_expr,
        tax_base_expr=common.tax_base_expr,
        follower_objective_expr=follower_objective_expr,
    )


def build_follower_model(instance: InstanceData) -> FollowerModel:
    common = build_supply_chain_model(instance, model_name="fixed_tax_follower_model")
    artifacts = ModelArtifacts(
        model=common.model,
        cost_expr=common.cost_expr,
        emissions_expr=common.emissions_expr,
        tax_base_expr=common.tax_base_expr,
        follower_objective_expr=common.cost_expr,
    )
    follower_model = FollowerModel(instance=instance, artifacts=artifacts)
    _set_fixed_tax_follower_expression(follower_model, instance.lower_tax)
    return follower_model


def _coerce_follower_model(
    instance_or_model: InstanceData | FollowerModel,
) -> FollowerModel:
    if isinstance(instance_or_model, FollowerModel):
        return instance_or_model
    return build_follower_model(instance_or_model)


def _set_fixed_tax_follower_expression(follower_model: FollowerModel, tax: float) -> None:
    _require_tax_in_bounds(follower_model.instance, tax)
    follower_model.artifacts.follower_objective_expr = (
        follower_model.artifacts.cost_expr
        + follower_model.instance.tax_rate(tax) * tax_base_of(follower_model.artifacts)
    )


def validate_fixed_tax_solution(
    instance: InstanceData,
    *,
    tax: float,
    variable_values: dict[str, float],
) -> SolveResult:
    artifacts = build_fixed_tax_model(instance, tax=tax)
    model = artifacts.model
    model.update()
    for variable in model.getVars():
        target_value = float(variable_values.get(variable.VarName, 0.0))
        variable_lb = float(variable.LB)
        variable_ub = float(variable.UB)
        target_value = normalize_solution_value(
            variable,
            target_value,
            lower_bound=variable_lb,
            upper_bound=variable_ub,
        )
        if (
            target_value < variable_lb - DEFAULT.eps
            or target_value > variable_ub + DEFAULT.eps
        ):
            raise ValueError(
                f"Saved solution value {target_value} for {variable.VarName} violates [{variable_lb}, {variable_ub}]",
            )
        if variable.VType == GRB.CONTINUOUS:
            # Warm-start continuous variables rather than pinning LB=UB.
            # Fixing all continuous variables to saved float values simultaneously
            # can make the LP infeasible due to accumulated floating-point residuals
            # in mass-balance/BOM constraints even when the solution is numerically
            # correct. Integer variables are still pinned exactly; Gurobi then
            # re-solves the LP, which is always feasible for a valid integer structure.
            variable.Start = target_value
        else:
            variable.LB = target_value
            variable.UB = target_value
    return optimize_model(
        artifacts,
        tax=tax,
        output_flag=False,
        time_limit=None,
        capture_solution=False,
    )
