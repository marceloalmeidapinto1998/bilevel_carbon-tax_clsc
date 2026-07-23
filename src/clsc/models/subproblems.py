from __future__ import annotations


from collections import defaultdict
from dataclasses import dataclass, field, replace
import math
from typing import Iterable

import gurobipy as gp
from gurobipy import GRB

from clsc.config.gap_tol import DEFAULT
from .instance import InstanceData


EMISSIONS_SCALE = 1_000_000.0  # kg to kilotonnes
BOUND_SNAP_TOL = max(DEFAULT.eps, 1e-6)
INTEGER_SNAP_TOL = max(DEFAULT.eps, 1e-5)


@dataclass(frozen=True, slots=True)
class DbpFollowerCut:
    tax_index: int
    cost: float
    emissions: float
    iteration: int


@dataclass(slots=True)
class ModelArtifacts:
    model: gp.Model
    cost_expr: gp.LinExpr
    emissions_expr: gp.LinExpr
    follower_expr: gp.LinExpr
    tax_index_var: gp.Var | None = None
    emissions_total_var: gp.Var | None = None
    elastic_slack_var: gp.Var | None = None
    # Continuous variable tied to tax_index_var by the single linear equality
    # ``tax_rate_var == scale_factor * tax_index_var`` (added in
    # build_dbp_relaxation_master). The spatial master multiplies it by
    # emissions_total_var for the one bilinear tau*E term, and cut RHSs read as
    # ``cost_v + emissions_v * tax_rate_var`` (constant times variable, linear).
    tax_rate_var: gp.Var | None = None


@dataclass(frozen=True, slots=True)
class SolveResult:
    status_code: int
    status_name: str
    has_solution: bool
    objective_value: float | None
    cost: float | None
    emissions: float | None
    follower_objective: float | None
    tax_index: int | None
    mip_gap: float | None
    runtime: float
    variable_values: dict[str, float] | None = None
    objective_bound: float | None = None
    status_history: tuple[str, ...] = ()
    iis_constraints: tuple[str, ...] = ()
    iis_variable_bounds: tuple[str, ...] = ()
    slack_value: float | None = None
    # Populated only by two-stage lexicographic solves. Each field carries the
    # MIP gap reported by Gurobi at the corresponding stage; `mip_gap` (above)
    # carries the worst (largest) of the two for compatibility with single-
    # objective callers.
    lex_primary_mip_gap: float | None = None
    lex_secondary_mip_gap: float | None = None


@dataclass(slots=True)
class _CommonModel:
    model: gp.Model
    cost_expr: gp.LinExpr
    emissions_expr: gp.LinExpr


@dataclass(slots=True)
class FixedTaxFollowerMaster:
    instance: InstanceData
    artifacts: ModelArtifacts


@dataclass(slots=True)
class DbpRelaxationMaster:
    artifacts: ModelArtifacts
    epsilon_prime: float = 0.0
    lower_tax_index: int = 0
    upper_tax_index: int = 0
    emissions_big_m: float = 0.0
    applied_cut_iterations: set[int] = field(default_factory=set)
    objective_upper_bound_constraint: gp.Constr | None = None
    objective_upper_bound: float | None = None
    elastic: bool = False


def solve_fixed_tax_follower(
    instance: InstanceData,
    tax_index: int,
    *,
    output_flag: bool = False,
    time_limit: float | None = None,
    capture_solution: bool = False,
    mip_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
) -> SolveResult:
    artifacts = build_fixed_tax_model(instance, tax_index=tax_index)
    return optimize_model(
        artifacts,
        fixed_tax_index=tax_index,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=capture_solution,
        mip_gap=mip_gap,
        threads=threads,
        mip_focus=mip_focus,
    )


def solve_fixed_tax_lexicographic(
    instance_or_master: InstanceData | FixedTaxFollowerMaster,
    tax_index: int,
    *,
    output_flag: bool = False,
    time_limit: float | None = None,
    capture_solution: bool = False,
    warm_start_values: dict[str, float] | None = None,
    mip_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
    seed: int | None = None,
) -> SolveResult:
    """Explicit two-stage lexicographic solve over the fixed-tax follower.

    Stage 1 minimises ``cost + tau * emissions``. Stage 2 minimises
    ``emissions`` over solutions whose primary objective stays within
    ``primary_optimum + freeze_tolerance``, where ``freeze_tolerance`` is
    computed by :func:`_lex_freeze_tolerance` as a fraction of
    ``|primary_optimum|`` (rather than a fixed absolute amount) and is
    widened to cover the actual Stage-1 MIP gap whenever that gap is the
    looser of the two. This keeps the freeze consistent with Stage 1's
    precision: a loose Stage-1 gap means ``primary_optimum`` may sit up to
    ``gap * |primary_optimum|`` above the true optimum, and Stage 2 must
    keep that whole band in play, not just a small fixed-size slice of it.

    The optional ``mip_gap`` lets lexicographic callers use a looser stopping
    tolerance than the global DBP relaxation. This keeps large follower MIPs
    from spending disproportionate time chasing tiny residual gaps while the
    outer algorithm already records those stage gaps in the result.

    The returned :class:`SolveResult` carries both per-stage MIP gaps. The
    ``mip_gap`` field reports the worst (largest) of the two so existing
    single-objective consumers see a conservative bound.
    """
    master = _coerce_fixed_tax_follower_master(instance_or_master)
    _set_fixed_tax_follower_expression(master, tax_index)
    artifacts = master.artifacts
    model = artifacts.model
    model.ModelSense = GRB.MINIMIZE
    _apply_mip_start(model, warm_start_values)

    # Stage 1: minimise follower objective (cost + tau * emissions).
    model.setObjective(artifacts.follower_expr, GRB.MINIMIZE)
    stage1 = optimize_model(
        artifacts,
        fixed_tax_index=tax_index,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=False,
        mip_gap=mip_gap,
        threads=threads,
        mip_focus=mip_focus,
        seed=seed,
    )
    if not stage1.has_solution or stage1.status_name != "OPTIMAL":
        return replace(
            stage1,
            tax_index=tax_index,
            lex_primary_mip_gap=stage1.mip_gap,
            lex_secondary_mip_gap=None,
        )

    primary_optimum = float(stage1.follower_objective)
    freeze_tolerance = lex_freeze_tolerance(primary_optimum, stage1.mip_gap)
    freeze = model.addConstr(
        artifacts.follower_expr <= primary_optimum + freeze_tolerance,
        name="lex_primary_freeze",
    )
    model.update()

    # Stage 2: minimise emissions subject to the freeze.
    model.setObjective(artifacts.emissions_expr, GRB.MINIMIZE)
    stage2 = optimize_model(
        artifacts,
        fixed_tax_index=tax_index,
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

    primary_gap = stage1.mip_gap
    secondary_gap = stage2.mip_gap
    merged_mip_gap: float | None
    if primary_gap is None and secondary_gap is None:
        merged_mip_gap = None
    else:
        merged_mip_gap = max(g for g in (primary_gap, secondary_gap) if g is not None)

    return replace(
        stage2,
        tax_index=tax_index,
        mip_gap=merged_mip_gap,
        runtime=stage1.runtime + stage2.runtime,
        status_history=stage1.status_history + stage2.status_history,
        lex_primary_mip_gap=primary_gap,
        lex_secondary_mip_gap=secondary_gap,
    )


def solve_fixed_rate_lexicographic(
    master: FixedTaxFollowerMaster,
    tax_rate: float,
    *,
    output_flag: bool = False,
    time_limit: float | None = None,
    capture_solution: bool = False,
    warm_start_values: dict[str, float] | None = None,
    mip_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
) -> SolveResult:
    """Follower two-stage lexicographic solve at a CONTINUOUS tax rate (USD/kg).

    Rate-based analogue of :func:`solve_fixed_tax_lexicographic` (which takes an
    integer index): identical follower MILP, only the emissions coefficient is a
    continuous rate rather than ``scale_factor * index``. Used by the breakpoint
    tracer (``clsc.solvers.tax_breakpoints``), which probes the follower at
    off-grid tax rates.
    """
    artifacts = master.artifacts
    model = artifacts.model
    artifacts.follower_expr = artifacts.cost_expr + tax_rate * artifacts.emissions_expr
    model.ModelSense = GRB.MINIMIZE
    _apply_mip_start(model, warm_start_values)

    model.setObjective(artifacts.follower_expr, GRB.MINIMIZE)
    stage1 = optimize_model(
        artifacts,
        fixed_tax_index=None,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=False,
        mip_gap=mip_gap,
        threads=threads,
        mip_focus=mip_focus,
    )
    if not stage1.has_solution or stage1.status_name != "OPTIMAL":
        return replace(stage1, tax_index=None)

    primary_optimum = float(stage1.follower_objective)
    freeze_tolerance = lex_freeze_tolerance(primary_optimum, stage1.mip_gap)
    freeze = model.addConstr(
        artifacts.follower_expr <= primary_optimum + freeze_tolerance,
        name="lex_primary_freeze",
    )
    model.update()

    model.setObjective(artifacts.emissions_expr, GRB.MINIMIZE)
    stage2 = optimize_model(
        artifacts,
        fixed_tax_index=None,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=capture_solution,
        mip_gap=mip_gap,
        threads=threads,
        mip_focus=mip_focus,
    )
    try:
        model.remove(freeze)
        model.update()
    except gp.GurobiError:
        pass

    primary_gap = stage1.mip_gap
    secondary_gap = stage2.mip_gap
    merged_gap = (
        None
        if primary_gap is None and secondary_gap is None
        else max(g for g in (primary_gap, secondary_gap) if g is not None)
    )
    return replace(
        stage2,
        tax_index=None,
        mip_gap=merged_gap,
        runtime=stage1.runtime + stage2.runtime,
        status_history=stage1.status_history + stage2.status_history,
    )



def lex_freeze_tolerance(primary_optimum: float, primary_mip_gap: float | None) -> float:
    """Tolerance for freezing a follower-objective value before an
    optimistic-tie-break re-optimization (used by both
    :func:`solve_fixed_tax_lexicographic`'s Stage-1/Stage-2 split and the
    equivalent two-call pattern in the DBP solvers, see
    ``dbp_exact.follower_objective_cap``).

    ``DEFAULT.lex_epsilon_prime`` is a *relative* fraction of
    ``|primary_optimum|``, not a fixed absolute amount: an absolute
    constant sized for one instance's objective scale is meaningless (too
    loose or too tight) for an instance whose objective is orders of
    magnitude larger or smaller. The tolerance is then widened to at least
    ``primary_mip_gap * |primary_optimum|`` so the freeze never excludes
    solutions that are merely within the primary solve's own reported
    optimality gap of ``primary_optimum`` -- otherwise a loose stopping gap
    could silently exclude the true cost-optimum from the tie-break search.
    ``DEFAULT.eps`` is an absolute floor guarding against a degenerate
    near-zero objective.
    """
    magnitude = abs(primary_optimum)
    gap = primary_mip_gap if primary_mip_gap is not None and primary_mip_gap > 0.0 else 0.0
    return max(
        DEFAULT.eps,
        DEFAULT.lex_epsilon_prime * magnitude,
        gap * magnitude,
    )


def solve_dbp_relaxation(
    instance_or_master: InstanceData | DbpRelaxationMaster,
    cuts: list[DbpFollowerCut] | None = None,
    *,
    output_flag: bool = False,
    time_limit: float | None = None,
    capture_solution: bool = False,
    compute_iis: bool = False,
) -> SolveResult:
    if isinstance(instance_or_master, DbpRelaxationMaster):
        master = instance_or_master
    else:
        master = build_dbp_relaxation_master(instance_or_master)
    if cuts:
        _synchronize_dbp_relaxation_master(master, cuts)
    # Infeasible DBP relaxations are handled by the certified elastic fallback.
    # IIS extraction is expensive here and is only useful for final-model diagnostics.
    return optimize_model(
        master.artifacts,
        fixed_tax_index=None,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=capture_solution,
        compute_iis=compute_iis,
    )


def solve_dbp_relaxation_lexicographic(
    instance_or_master: InstanceData | DbpRelaxationMaster,
    cuts: list[DbpFollowerCut] | None = None,
    *,
    output_flag: bool = False,
    time_limit: float | None = None,
    capture_solution: bool = False,
    mip_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
    seed: int | None = None,
    lex_stage2: bool = True,
) -> SolveResult:
    """Two-stage lexicographic solve of the DBP relaxation master: minimise
    total emissions (Stage 1, identical to :func:`solve_dbp_relaxation`),
    then minimise ``tax_index`` itself (Stage 2) among master points tied at
    that emissions value.

    ``lex_stage2=False`` runs Stage 1 only (the DBP-ablation variant A2, no
    lexicographic Stage-2 in the master): the returned ``tax_index`` is then an
    arbitrary emissions-minimiser, not the smallest tied index, so the surrounding
    loop must rely on its Phase-2 bisection for tax-minimality.

    This replaces a post-hoc tax-tiebreak search (e.g. bisection) over the
    leader's tax grid. Every cut added to the master is valid for *every*
    ``tax_index`` (the follower's feasible region does not depend on the tax,
    see ``lem:lb_validity``), so the true optimistic-optimal point at any
    tax index that genuinely ties the global emissions optimum is itself
    feasible for every accumulated cut -- it can never be excluded from the
    master. Consequently, the smallest ``tax_index`` the master finds among
    its own Stage-1 emissions-minimisers is, once the surrounding DBP loop's
    gap has closed, provably the smallest tax index in the *entire* finite
    grid achieving the leader's optimal emissions -- not just among the tax
    indices visited so far -- with no monotonicity assumption required.

    Mirrors the Stage-1/Stage-2 freeze pattern already used by
    :func:`solve_fixed_tax_lexicographic` for the fixed-tax follower, applied
    here to the relaxation master's own ``emissions_total_var``/``tax_index_var``.
    """
    if isinstance(instance_or_master, DbpRelaxationMaster):
        master = instance_or_master
    else:
        master = build_dbp_relaxation_master(instance_or_master)
    if cuts:
        _synchronize_dbp_relaxation_master(master, cuts)

    artifacts = master.artifacts
    model = artifacts.model
    emissions_total_var = artifacts.emissions_total_var
    tax_index_var = artifacts.tax_index_var
    if emissions_total_var is None or tax_index_var is None:
        raise RuntimeError(
            "DBP relaxation master is missing the emissions/tax_index variables "
            "required for the lexicographic relaxation solve"
        )

    # Stage 1: minimise total (scaled) emissions -- identical to the master's
    # ordinary single-stage objective. When lex_stage2 is requested (default),
    # Stage 1 must not capture the solution yet (Stage 2 does); the A2 ablation
    # (lex_stage2=False) captures here and returns Stage 1 directly.
    model.setObjective(emissions_total_var, GRB.MINIMIZE)
    stage1 = optimize_model(
        artifacts,
        fixed_tax_index=None,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=capture_solution and not lex_stage2,
        mip_gap=mip_gap,
        threads=threads,
        mip_focus=mip_focus,
        seed=seed,
    )
    if not stage1.has_solution or stage1.status_name != "OPTIMAL":
        model.setObjective(emissions_total_var, GRB.MINIMIZE)
        return stage1

    if not lex_stage2:
        # A2 ablation: no lexicographic Stage-2 tax minimisation in the master.
        return replace(
            stage1,
            emissions=float(emissions_total_var.X) * EMISSIONS_SCALE,
            lex_primary_mip_gap=stage1.mip_gap,
            lex_secondary_mip_gap=None,
        )

    # Freeze Stage 1's optimum (in scaled, kilotonne-ish units, so the
    # absolute eps floor of lex_freeze_tolerance is already a much smaller
    # fraction of a kilogram than it would be against raw kg-scale values).
    primary_optimum_scaled = float(emissions_total_var.X)
    freeze_tolerance_scaled = lex_freeze_tolerance(primary_optimum_scaled, stage1.mip_gap)
    freeze = model.addConstr(
        emissions_total_var <= primary_optimum_scaled + freeze_tolerance_scaled,
        name="dbp_relaxation_lex_primary_freeze",
    )
    model.update()

    # Stage 2: minimise tax_index subject to the freeze.
    model.setObjective(tax_index_var, GRB.MINIMIZE)
    stage2 = optimize_model(
        artifacts,
        fixed_tax_index=None,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=capture_solution,
        mip_gap=mip_gap,
        threads=threads,
        mip_focus=mip_focus,
        seed=seed,
    )
    try:
        model.remove(freeze)
    finally:
        # Restore the master's ordinary objective so a caller that re-solves
        # this same model via solve_dbp_relaxation later sees the expected
        # single-stage emissions objective.
        model.setObjective(emissions_total_var, GRB.MINIMIZE)
        model.update()

    primary_gap = stage1.mip_gap
    secondary_gap = stage2.mip_gap
    merged_mip_gap = (
        None
        if primary_gap is None and secondary_gap is None
        else max(value for value in (primary_gap, secondary_gap) if value is not None)
    )
    return replace(
        stage2,
        # Stage 2 is only constrained by emissions <= primary_optimum + freeze
        # tolerance, not equality, so its own recomputed emissions can drift
        # above the Stage-1 optimum by up to that tolerance whenever several
        # tax indices tie the minimum and a slightly higher emissions value
        # unlocks a smaller tax_index. lem:lb_validity only certifies the exact
        # Stage-1 value as a valid lower bound, so that -- not Stage 2's
        # point -- is what callers must use as LB^(k).
        emissions=primary_optimum_scaled * EMISSIONS_SCALE,
        mip_gap=merged_mip_gap,
        runtime=stage1.runtime + stage2.runtime,
        status_history=stage1.status_history + stage2.status_history,
        lex_primary_mip_gap=primary_gap,
        lex_secondary_mip_gap=secondary_gap,
    )


def build_fixed_tax_model(
    instance: InstanceData,
    *,
    tax_index: int,
    tie_break: bool = False,
) -> ModelArtifacts:
    if tax_index not in instance.iter_tax_index():
        raise ValueError(f"tax_index={tax_index} is outside the instance bounds")

    common = _build_common_model(instance, model_name=f"fixed_tau_{tax_index}")
    follower_expr = (
        common.cost_expr
        + instance.scale_factor * tax_index * common.emissions_expr
    )

    common.model.setObjective(common.emissions_expr if tie_break else follower_expr, GRB.MINIMIZE)
    return ModelArtifacts(
        model=common.model,
        cost_expr=common.cost_expr,
        emissions_expr=common.emissions_expr,
        follower_expr=follower_expr,
    )


def build_epsilon_constraint_model(
    instance: InstanceData,
    *,
    emissions_upper_bound: float,
) -> ModelArtifacts:
    """Follower MILP minimising cost subject to a hard emissions cap (no tax term).

    Used by Family B's AUGMECON-style epsilon-constraint sweep (Mavrotas, 2009): the emissions
    objective is turned into a constraint while cost remains the objective, tracing non-dominated
    cost-emissions points that a tax-indexed (weighted-sum) sweep cannot reach on a non-convex
    frontier.
    """
    common = _build_common_model(instance, model_name=f"epsilon_constraint_{emissions_upper_bound:.4f}")
    common.model.addConstr(common.emissions_expr <= emissions_upper_bound, name="epsilon_constraint")
    common.model.setObjective(common.cost_expr, GRB.MINIMIZE)
    return ModelArtifacts(
        model=common.model,
        cost_expr=common.cost_expr,
        emissions_expr=common.emissions_expr,
        follower_expr=common.cost_expr,
    )


def solve_epsilon_constraint_follower(
    instance: InstanceData,
    emissions_upper_bound: float,
    *,
    output_flag: bool = False,
    time_limit: float | None = None,
    capture_solution: bool = False,
    mip_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
) -> SolveResult:
    artifacts = build_epsilon_constraint_model(instance, emissions_upper_bound=emissions_upper_bound)
    return optimize_model(
        artifacts,
        fixed_tax_index=0,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=capture_solution,
        mip_gap=mip_gap,
        threads=threads,
        mip_focus=mip_focus,
    )


def solve_fixed_tax_min_emissions(
    instance: InstanceData,
    *,
    output_flag: bool = False,
    time_limit: float | None = None,
    capture_solution: bool = False,
    mip_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
) -> SolveResult:
    """Unconstrained minimum-emissions anchor for Family B's epsilon-constraint payoff table.

    Equivalent to `build_fixed_tax_model(instance, tax_index=0, tie_break=True)`: no tax term
    (tax_index=0) and the objective is emissions directly, ignoring cost.
    """
    artifacts = build_fixed_tax_model(instance, tax_index=0, tie_break=True)
    return optimize_model(
        artifacts,
        fixed_tax_index=0,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=capture_solution,
        mip_gap=mip_gap,
        threads=threads,
        mip_focus=mip_focus,
    )


def build_fixed_tax_follower_master(instance: InstanceData) -> FixedTaxFollowerMaster:
    common = _build_common_model(instance, model_name="fixed_tax_follower_master")
    artifacts = ModelArtifacts(
        model=common.model,
        cost_expr=common.cost_expr,
        emissions_expr=common.emissions_expr,
        follower_expr=common.cost_expr,
    )
    master = FixedTaxFollowerMaster(instance=instance, artifacts=artifacts)
    _set_fixed_tax_follower_expression(master, instance.lower_tax_index)
    return master


def _coerce_fixed_tax_follower_master(
    instance_or_master: InstanceData | FixedTaxFollowerMaster,
) -> FixedTaxFollowerMaster:
    if isinstance(instance_or_master, FixedTaxFollowerMaster):
        return instance_or_master
    return build_fixed_tax_follower_master(instance_or_master)


def _set_fixed_tax_follower_expression(master: FixedTaxFollowerMaster, tax_index: int) -> None:
    if tax_index not in master.instance.iter_tax_index():
        raise ValueError(f"tax_index={tax_index} is outside the instance bounds")
    master.artifacts.follower_expr = (
        master.artifacts.cost_expr
        + master.instance.scale_factor * tax_index * master.artifacts.emissions_expr
    )


def _apply_mip_start(model: gp.Model, variable_values: dict[str, float] | None) -> None:
    model.NumStart = 1
    model.Params.StartNumber = 0
    for variable in model.getVars():
        variable.Start = GRB.UNDEFINED
        if not variable_values:
            continue
        value = variable_values.get(variable.VarName)
        if value is not None:
            variable.Start = float(value)


def build_dbp_relaxation_master(
    instance: InstanceData,
    *,
    elastic: bool = False,
) -> DbpRelaxationMaster:
    epsilon_prime = DEFAULT.dbp_cut_epsilon
    elastic_slack_penalty_multiplier = DEFAULT.elastic_penalty_mult

    common = _build_common_model(instance, model_name="dbp_relaxation_master")
    model = common.model

    lower_tax_index = instance.lower_tax_index
    upper_tax_index = instance.upper_tax_index
    scale_factor = instance.scale_factor  # derived from the instance's own grid
    tax_index = model.addVar(vtype=GRB.INTEGER, lb=lower_tax_index, ub=upper_tax_index, name="tax_index")

    emissions_big_m = total_emissions_upper_bound(instance)
    emissions_upper_bound_scaled = emissions_big_m / EMISSIONS_SCALE
    emissions_total_scaled = model.addVar(
        lb=0.0,
        ub=emissions_upper_bound_scaled,
        name="total_emissions_kt",
    )
    model.addConstr(
        emissions_total_scaled == common.emissions_expr / EMISSIONS_SCALE,
        name="total_emissions_kt_def",
    )

    # tax_rate == SCALE_FACTOR * tax_index -- the continuous rate pinned to the
    # grid. Defined before the tau*emissions product so the spatial mode can
    # multiply by it directly. A single linear equality (constant coefficient),
    # so it never needs a linearization of its own.
    tax_rate = model.addVar(
        lb=scale_factor * lower_tax_index,
        ub=scale_factor * upper_tax_index,
        name="tax_rate",
    )
    model.addConstr(tax_rate == scale_factor * tax_index, name="tax_rate_def")

    # tau*emissions linearised by McCormick + spatial branch-and-bound. Exact
    # because tax_index is integer: once branching pins it, the McCormick box
    # degenerates to a single point and w = tax_rate * E exactly (Gupte, Ahmed,
    # Cheon & Dey 2013, Prop. 2.1 -- the extreme points of the McCormick
    # relaxation have the integer factor at its bounds; integrality makes the
    # spatial tree finite). ONE bilinear term for the whole model, so every
    # value-function cut added later stays LINEAR.
    model.Params.NonConvex = 2
    tau_emissions_product = model.addVar(
        lb=0.0,
        ub=(scale_factor * upper_tax_index) * emissions_upper_bound_scaled,
        name="tau_emissions_scaled_product",
    )
    model.addQConstr(
        tau_emissions_product == tax_rate * emissions_total_scaled,
        name="tau_emissions_scaled_def",
    )
    # tax_rate * E_scaled * EMISSIONS_SCALE == tax_rate * E_raw.
    follower_expr = common.cost_expr + EMISSIONS_SCALE * tau_emissions_product

    elastic_slack_var: gp.Var | None = None
    if elastic:
        elastic_slack_var = model.addVar(lb=0.0, name="dbp_elastic_slack")
        slack_penalty = max(1.0, emissions_big_m) * elastic_slack_penalty_multiplier
        model.setObjective(common.emissions_expr + slack_penalty * elastic_slack_var, GRB.MINIMIZE)
    else:
        model.setObjective(emissions_total_scaled, GRB.MINIMIZE)
    return DbpRelaxationMaster(
        artifacts=ModelArtifacts(
            model=model,
            cost_expr=common.cost_expr,
            emissions_expr=common.emissions_expr,
            follower_expr=follower_expr,
            tax_index_var=tax_index,
            emissions_total_var=emissions_total_scaled,
            elastic_slack_var=elastic_slack_var,
            tax_rate_var=tax_rate,
        ),
        epsilon_prime=epsilon_prime,
        lower_tax_index=lower_tax_index,
        upper_tax_index=upper_tax_index,
        emissions_big_m=emissions_big_m,
        elastic=elastic,
    )


def add_dbp_relaxation_cut(master: DbpRelaxationMaster, cut: DbpFollowerCut) -> None:
    if cut.iteration in master.applied_cut_iterations:
        return

    tax_rate = master.artifacts.tax_rate_var
    if tax_rate is None:
        raise RuntimeError("DBP relaxation master is missing the leader tax-rate variable")

    # cut.emissions is a constant (from an already-solved point), so
    # cut.emissions * tax_rate is constant-times-variable -- always linear,
    # regardless of tax_rate's own domain. follower_expr <= cost_v +
    # emissions_v * tax_rate is exactly cost_v + emissions_v * (scale_factor
    # * tax_index), just spelled without the scale factor inline.
    right_hand_side = (
        cut.cost
        + cut.emissions * tax_rate
        + _dbp_cut_epsilon(master, cut)
    )
    if master.artifacts.elastic_slack_var is not None:
        right_hand_side += master.artifacts.elastic_slack_var

    master.artifacts.model.addConstr(
        master.artifacts.follower_expr <= right_hand_side,
        name=f"dbp_cut_{cut.iteration}",
    )
    master.applied_cut_iterations.add(cut.iteration)


def _dbp_cut_epsilon(master: DbpRelaxationMaster, cut: DbpFollowerCut) -> float:
    # master.epsilon_prime is a fixed absolute floor (DEFAULT.dbp_cut_epsilon
    # at master-build time); scale it by the cut's own cost magnitude so the
    # guard stays round-off-scale regardless of an instance's cost scale,
    # rather than becoming a large fraction of cost differences on a small
    # instance. See DEFAULT.dbp_cut_epsilon_relative's docstring.
    return max(master.epsilon_prime, DEFAULT.dbp_cut_epsilon_relative * abs(cut.cost))


def set_dbp_relaxation_objective_upper_bound(
    master: DbpRelaxationMaster,
    upper_bound: float | None,
) -> None:
    emissions_total_var = master.artifacts.emissions_total_var
    if emissions_total_var is None:
        raise RuntimeError("DBP relaxation master is missing the scaled emissions objective variable")

    if upper_bound is None:
        if master.objective_upper_bound_constraint is not None:
            master.artifacts.model.remove(master.objective_upper_bound_constraint)
            master.objective_upper_bound_constraint = None
            master.objective_upper_bound = None
            master.artifacts.model.update()
        return

    if upper_bound < 0:
        raise ValueError("upper_bound must be nonnegative")

    # Widen the cutoff by a tiny relative tolerance: `upper_bound` is the
    # emissions value reported by a *different*, independently built Gurobi
    # model (the optimistic follower solve), so floating-point reconstruction
    # of the same physical point inside this relaxation master's own
    # LinExpr can land a hair above it. An exact (non-widened) cutoff can
    # then spuriously exclude the true incumbent point from its own
    # relaxation, making the master falsely INFEASIBLE. Mirrors the same
    # relative-tolerance pattern as `lex_freeze_tolerance`.
    tolerant_upper_bound = upper_bound + lex_freeze_tolerance(upper_bound, None)

    if master.objective_upper_bound is not None and math.isclose(
        tolerant_upper_bound,
        master.objective_upper_bound,
        abs_tol=DEFAULT.eps,
    ):
        return

    scaled_upper_bound = tolerant_upper_bound / EMISSIONS_SCALE
    if master.objective_upper_bound_constraint is None:
        master.objective_upper_bound_constraint = master.artifacts.model.addConstr(
            emissions_total_var <= scaled_upper_bound,
            name="dbp_objective_upper_bound",
        )
        master.artifacts.model.update()
    else:
        master.objective_upper_bound_constraint.RHS = scaled_upper_bound
    master.objective_upper_bound = tolerant_upper_bound


def _synchronize_dbp_relaxation_master(master: DbpRelaxationMaster, cuts: Iterable[DbpFollowerCut]) -> None:
    added_cut = False
    for cut in cuts:
        if cut.iteration in master.applied_cut_iterations:
            continue
        add_dbp_relaxation_cut(master, cut)
        added_cut = True
    if added_cut:
        master.artifacts.model.update()


def optimize_model(
    artifacts: ModelArtifacts,
    *,
    fixed_tax_index: int | None,
    output_flag: bool,
    time_limit: float | None,
    capture_solution: bool,
    compute_iis: bool = True,
    mip_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
    seed: int | None = None,
) -> SolveResult:
    model = artifacts.model
    model.Params.OutputFlag = 1 if output_flag else 0
    if time_limit is not None:
        model.Params.TimeLimit = time_limit
    model.Params.MIPGap = DEFAULT.mip_gap if mip_gap is None else mip_gap
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
            tax_index=fixed_tax_index,
            mip_gap=mip_gap_value,
            runtime=runtime,
            variable_values=None,
            objective_bound=objective_bound,
            status_history=tuple(status_history),
            iis_constraints=iis_constraints,
            iis_variable_bounds=iis_variable_bounds,
            slack_value=None,
        )

    tax_index_value = fixed_tax_index
    if artifacts.tax_index_var is not None:
        tax_index_value = int(round(float(artifacts.tax_index_var.X)))

    return SolveResult(
        status_code=status_code,
        status_name=status_name,
        has_solution=True,
        objective_value=float(model.ObjVal),
        cost=float(artifacts.cost_expr.getValue()),
        emissions=float(artifacts.emissions_expr.getValue()),
        follower_objective=float(artifacts.follower_expr.getValue()),
        tax_index=tax_index_value,
        mip_gap=mip_gap_value,
        runtime=runtime,
        variable_values=_extract_nonzero_variable_values(model) if capture_solution else None,
        objective_bound=objective_bound,
        status_history=tuple(status_history),
        iis_constraints=iis_constraints,
        iis_variable_bounds=iis_variable_bounds,
        slack_value=float(artifacts.elastic_slack_var.X) if artifacts.elastic_slack_var is not None else None,
    )


def total_emissions_upper_bound(instance: InstanceData) -> float:
    params = instance.parameters
    factories = instance.sets["F"]
    warehouses = instance.sets["W"]
    periods = instance.sets["T"]
    products = instance.sets["P"]
    raw_materials = instance.sets["U"]
    suppliers = instance.sets["S"]
    production_pairs = instance.sets.get("H_prod", tuple((p, g) for p in products for g in instance.sets["G"]))
    remanufacturing_pairs = instance.sets.get("H_rem", tuple((p, l) for p in products for l in instance.sets["L"]))
    modes = instance.sets["M"]
    airports = instance.sets.get("AIR", tuple())
    seaports = instance.sets.get("PORT", tuple())

    open_bound = (
        sum(params["e_open_f"][factory] * params["A_f"][factory] for factory in factories)
        + sum(params["e_open_w"][warehouse] * params["A_w"][warehouse] for warehouse in warehouses)
    )
    production_bound = len(periods) * len(factories) * sum(
        params["e_prod_g"][technology]
        * params["omega_p"][product]
        * params["bar_p_g"][technology]
        for product, technology in production_pairs
    )
    remanufacturing_bound = len(periods) * len(factories) * sum(
        params["e_rem_l"][technology]
        * params["omega_p"][product]
        * params["bar_q_l"][technology]
        for product, technology in remanufacturing_pairs
    )
    raw_material_bound = 0.0
    if "e_raw_s_u" in params and "bar_s_s_u" in params:
        raw_material_bound = len(periods) * sum(
            params["e_raw_s_u"][supplier][raw_material]
            * params["omega_u"][raw_material]
            * params["bar_s_s_u"][supplier][raw_material]
            for supplier in suppliers
            for raw_material in raw_materials
        )

    transport_bound = 0.0
    transport_arcs = instance.sets["A"]
    distance = params["d_i_j"]
    mode_family = params.get("mode_family_m", {})
    for origin, destination in transport_arcs:
        for mode in _allowed_modes(
            origin,
            destination,
            modes,
            airports=airports,
            seaports=seaports,
            mode_family=mode_family,
        ):
            if params.get("ccamax_m", {}).get(mode, 0.0) > 0.0:
                weight_bound = params["ccamax_m"][mode]
            else:
                weight_bound = max(
                    max(params.get("ecmax_i", {}).values(), default=0.0),
                    params["bar_X_m"][mode] * _trip_big_m(params, mode, origin=origin, destination=destination),
                )
            transport_bound += (
                len(periods)
                * params["e_ship_m"][mode]
                * params.get("road_return_factor_m", {}).get(mode, 1.0)
                * distance[origin][destination]
                * weight_bound
            )

    return float(open_bound + production_bound + remanufacturing_bound + raw_material_bound + transport_bound)


def validate_fixed_tax_solution(
    instance: InstanceData,
    *,
    tax_index: int,
    variable_values: dict[str, float],
) -> SolveResult:
    artifacts = build_fixed_tax_model(instance, tax_index=tax_index)
    model = artifacts.model
    model.update()
    for variable in model.getVars():
        target_value = float(variable_values.get(variable.VarName, 0.0))
        lower_bound = float(variable.LB)
        upper_bound = float(variable.UB)
        target_value = _normalize_solution_value(
            variable,
            target_value,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        )
        if (
            target_value < lower_bound - DEFAULT.eps
            or target_value > upper_bound + DEFAULT.eps
        ):
            raise ValueError(
                f"Saved solution value {target_value} for {variable.VarName} violates [{lower_bound}, {upper_bound}]",
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
        fixed_tax_index=tax_index,
        output_flag=False,
        time_limit=None,
        capture_solution=False,
    )


def _build_common_model(instance: InstanceData, *, model_name: str) -> _CommonModel:
    model = gp.Model(model_name)
    params = instance.parameters

    suppliers = instance.sets["S"]
    factories = instance.sets["F"]
    warehouses = instance.sets["W"]
    retailers = instance.sets["R"]
    airports = instance.sets.get("AIR", tuple())
    seaports = instance.sets.get("PORT", tuple())
    hubs = (*airports, *seaports)
    products = instance.sets["P"]
    recovered_products = instance.sets.get("K", instance.sets.get("RP", tuple(params.get("bom_rem_r_p", {}).keys())))
    raw_materials = instance.sets["U"]
    modes = instance.sets["M"]
    production_technologies = instance.sets["G"]
    remanufacturing_technologies = instance.sets["L"]
    periods = instance.sets["T"]

    flow_raw, flow_fp, flow_rp = _flow_sets(instance)
    flow_tuples = tuple(dict.fromkeys((*flow_raw, *flow_fp, *flow_rp)))
    transport_arcs = tuple(instance.sets.get("A", tuple(dict.fromkeys((o, d) for _, o, d in flow_tuples))))
    mode_family = params.get("mode_family_m", {})
    allowed_modes = {
        (o, d): _allowed_modes(o, d, modes, airports=airports, seaports=seaports, mode_family=mode_family)
        for o, d in transport_arcs
    }
    flow_by_arc: dict[tuple[str, str], list[str]] = defaultdict(list)
    for item, origin, destination in flow_tuples:
        flow_by_arc[(origin, destination)].append(item)

    raw_in, raw_out = _flow_indices(flow_raw)
    fp_in, fp_out = _flow_indices(flow_fp)
    rp_in, rp_out = _flow_indices(flow_rp)
    weights = _item_weights(params, raw_materials, products, recovered_products)
    distances = params["d_i_j"]
    return_yield = params["ret_yield_rp_p"]

    production_pairs = set(instance.sets.get("H_prod", tuple((p, g) for p in products for g in production_technologies)))
    remanufacturing_pairs = set(instance.sets.get("H_rem", tuple((p, l) for p in products for l in remanufacturing_technologies)))
    production_products_by_technology = _products_by_technology(production_pairs, production_technologies)
    remanufacturing_products_by_technology = _products_by_technology(remanufacturing_pairs, remanufacturing_technologies)
    production_technologies_by_product = _technologies_by_product(production_pairs, products)
    remanufacturing_technologies_by_product = _technologies_by_product(remanufacturing_pairs, products)
    vehicle_pairs = tuple(
        sorted(
            {
                (origin, mode)
                for origin, destination in transport_arcs
                for mode in allowed_modes[(origin, destination)]
                if _mode_family(mode, mode_family) == "truck"
            }
        )
    )
    outsourced_modes = tuple(
        sorted(
            {
                mode
                for origin, destination in transport_arcs
                for mode in allowed_modes[(origin, destination)]
                if _mode_family(mode, mode_family) in {"air", "sea"}
                and params.get("ccamax_m", {}).get(mode, 0.0) > 0.0
            }
        )
    )
    transport_mode_keys = tuple(
        (o, d, m, t)
        for o, d in transport_arcs
        for m in allowed_modes[(o, d)]
        for t in periods
    )
    truck_transport_keys = tuple(
        (o, d, m, t)
        for o, d in transport_arcs
        for m in allowed_modes[(o, d)]
        if _mode_family(m, mode_family) == "truck"
        for t in periods
    )

    y_s = model.addVars(suppliers, vtype=GRB.BINARY, name="y_s")
    y_f = model.addVars(factories, vtype=GRB.BINARY, name="y_f")
    y_w = model.addVars(warehouses, vtype=GRB.BINARY, name="y_w")
    y_h = model.addVars(hubs, vtype=GRB.BINARY, name="y_h")
    u_prod = model.addVars(((f, g) for f in factories for g in production_technologies), vtype=GRB.BINARY, name="u_prod")
    u_rem = model.addVars(((f, l) for f in factories for l in remanufacturing_technologies), vtype=GRB.BINARY, name="u_rem")
    installed_area = model.addVars((*factories, *warehouses), lb=0.0, name="YC")
    use_rem = model.addVars(
        ((f, l, t) for f in factories for l in remanufacturing_technologies for t in periods),
        vtype=GRB.BINARY,
        name="use_rem",
    )
    zt = model.addVars(transport_mode_keys, vtype=GRB.BINARY, name="zt")
    trip = model.addVars(truck_transport_keys, vtype=GRB.INTEGER, lb=0.0, name="trip")
    vehicle = model.addVars(vehicle_pairs, vtype=GRB.INTEGER, lb=0.0, name="vehicle")
    contract = model.addVars(((m, t) for m in outsourced_modes for t in periods), vtype=GRB.BINARY, name="contract")
    order_su = model.addVars(((u, s, t) for u in raw_materials for s in suppliers for t in periods), vtype=GRB.BINARY, name="order_su")
    q = model.addVars(
        ((p, f, g, t) for p, g in sorted(production_pairs) for f in factories for t in periods),
        lb=0.0,
        name="q",
    )
    rem = model.addVars(
        ((p, f, l, t) for p, l in sorted(remanufacturing_pairs) for f in factories for t in periods),
        lb=0.0,
        name="rem",
    )
    inv_w = model.addVars(((p, w, t) for p in products for w in warehouses for t in periods), lb=0.0, name="inv_w")
    x = model.addVars(
        ((item, o, d, m, t) for item, o, d in flow_tuples for m in allowed_modes[(o, d)] for t in periods),
        lb=0.0,
        name="x",
    )

    inventory_cost = _inventory_cost(
        params,
        products,
        warehouses,
        periods,
        inv_w,
    )
    cost_expr = (
        gp.quicksum(params["f_s"].get(s, 0.0) * y_s[s] for s in suppliers)
        + gp.quicksum(params.get("c_area_f", {}).get(f, 0.0) * installed_area[f] for f in factories)
        + gp.quicksum(params.get("c_area_w", {}).get(w, 0.0) * installed_area[w] for w in warehouses)
        + len(periods) * gp.quicksum(params["f_h"][h] * y_h[h] for h in hubs)
        + _transport_fixed_cost(params, vehicle)
        + gp.quicksum(params["i_prod_g"][g] * u_prod[f, g] for f in factories for g in production_technologies)
        + gp.quicksum(params["i_rem_l"][l] * u_rem[f, l] for f in factories for l in remanufacturing_technologies)
        + gp.quicksum(params["c_prod_g"][g] * q[p, f, g, t] for p, f, g, t in q.keys())
        + gp.quicksum(params["c_rem_l"][l] * rem[p, f, l, t] for p, f, l, t in rem.keys())
        + inventory_cost
        + gp.quicksum(params["rmc_s_u"][s][u] * x[u, s, d, m, t] for u, s, d in flow_raw if s in suppliers for m in allowed_modes[(s, d)] for t in periods)
        + gp.quicksum(params["rpc_rp"][rp] * x[rp, r, d, m, t] for rp, r, d in flow_rp if r in retailers for m in allowed_modes[(r, d)] for t in periods)
        + _transport_variable_cost(params, flow_tuples, allowed_modes, weights, distances, periods, mode_family, x, trip)
        + gp.quicksum(
            params["c_handle_m"][m]
            * ((1 if o in hubs else 0) + (1 if d in hubs else 0))
            * weights[item]
            * x[item, o, d, m, t]
            for item, o, d in flow_tuples
            if o in hubs or d in hubs
            for m in allowed_modes[(o, d)]
            for t in periods
        )
    )
    emissions_expr = (
        gp.quicksum(params["e_open_f"][f] * installed_area[f] for f in factories)
        + gp.quicksum(params["e_open_w"][w] * installed_area[w] for w in warehouses)
        + gp.quicksum(
            params["e_prod_g"][g] * params["omega_p"][p] * q[p, f, g, t]
            for p, f, g, t in q.keys()
        )
        + gp.quicksum(
            params["e_rem_l"][l] * params["omega_p"][p] * rem[p, f, l, t]
            for p, f, l, t in rem.keys()
        )
        + gp.quicksum(params["e_raw_s_u"][s][u] * params["omega_u"][u] * x[u, s, d, m, t] for u, s, d in flow_raw if s in suppliers for m in allowed_modes[(s, d)] for t in periods)
        + gp.quicksum(
            params["e_ship_m"][m]
            * params.get("road_return_factor_m", {}).get(m, 1.0)
            * weights[item] * distances[o][d] * x[item, o, d, m, t]
            for item, o, d in flow_tuples for m in allowed_modes[(o, d)] for t in periods
        )
    )

    def fs(index: dict[tuple[str, str], list[tuple[str, str]]], item: str, node: str, period: str) -> gp.LinExpr:
        return gp.quicksum(x[item, o, d, m, period] for o, d in index.get((item, node), ()) for m in allowed_modes[(o, d)])

    _add_inventory_and_flow_constraints(
        model, params, products, raw_materials, recovered_products, factories, warehouses, retailers, hubs,
        periods, production_technologies, remanufacturing_technologies, production_pairs,
        remanufacturing_pairs, production_products_by_technology, remanufacturing_products_by_technology,
        production_technologies_by_product, remanufacturing_technologies_by_product,
        return_yield, raw_in, raw_out, fp_in, fp_out, rp_in, rp_out, fs, y_s, y_f, y_w, u_prod, u_rem,
        use_rem, order_su, q, rem, inv_w, installed_area,
    )
    _add_transport_constraints(
        model, params, transport_arcs, allowed_modes, flow_by_arc, weights, periods,
        suppliers, factories, warehouses, airports, seaports, hubs, y_s, y_f, y_w, y_h, zt, trip, vehicle, contract, x,
    )
    _add_valid_inequalities(
        model,
        factories,
        production_technologies,
        remanufacturing_technologies,
        y_f,
        u_prod,
        u_rem,
    )
    return _CommonModel(model=model, cost_expr=cost_expr, emissions_expr=emissions_expr)


def _flow_sets(instance: InstanceData):
    return (
        tuple(instance.sets["FLOW_RAW"]),
        tuple(instance.sets["FLOW_FP"]),
        tuple(instance.sets["FLOW_RP"]),
    )


def _transport_fixed_cost(params, vehicle) -> gp.LinExpr:
    # Outsourced (air/sea) contracts carry no separate fixed cost here: that
    # payment is represented once, by the hub access fee f_h, matching Mota
    # et al.'s single bundled cfp_i (see sample_transport_fixed_cost).
    return gp.quicksum(params["f_mode_m"][mode] * vehicle[origin, mode] for origin, mode in vehicle.keys())


def _transport_variable_cost(
    params, flow_tuples, allowed_modes, weights, distances, periods, mode_family, x, trip,
) -> gp.LinExpr:
    truck_trip_cost = params.get("c_trip_m", {})
    road_return_factor = params.get("road_return_factor_m", {})
    flow_cost = gp.quicksum(
        params["c_ship_m"][mode] * weights[item] * distances[origin][destination] * x[item, origin, destination, mode, period]
        for item, origin, destination in flow_tuples
        for mode in allowed_modes[(origin, destination)]
        if _mode_family(mode, mode_family) != "truck"
        for period in periods
    )
    trip_cost = gp.quicksum(
        truck_trip_cost.get(mode, params["c_ship_m"][mode] * params["bar_X_m"][mode])
        * road_return_factor.get(mode, 2.0)
        * distances[origin][destination]
        * trip[origin, destination, mode, period]
        for origin, destination, mode, period in trip.keys()
        if _mode_family(mode, mode_family) == "truck"
    )
    return flow_cost + trip_cost


def _add_inventory_and_flow_constraints(
    model, params, products, raw_materials, recovered_products, factories, warehouses, retailers, hubs,
    periods, production_technologies, remanufacturing_technologies, production_pairs,
    remanufacturing_pairs, production_products_by_technology, remanufacturing_products_by_technology,
    production_technologies_by_product, remanufacturing_technologies_by_product,
    return_yield, raw_in, raw_out, fp_in, fp_out, rp_in, rp_out, fs, y_s, y_f, y_w, u_prod, u_rem,
    use_rem, order_su, q, rem, inv_w, installed_area,
) -> None:
    initial_inventory = params["i_p_n_0"]
    for product in products:
        for factory in factories:
            for period in periods:
                model.addConstr(
                    fs(fp_in, product, factory, period)
                    + gp.quicksum(q[product, factory, g, period] for g in production_technologies_by_product.get(product, ()))
                    + gp.quicksum(rem[product, factory, l, period] for l in remanufacturing_technologies_by_product.get(product, ()))
                    == fs(fp_out, product, factory, period)
                )
        for warehouse in warehouses:
            for period_index, period in enumerate(periods):
                previous = initial_inventory[product][warehouse] if period_index == 0 else inv_w[product, warehouse, periods[period_index - 1]]
                model.addConstr(inv_w[product, warehouse, period] == previous + fs(fp_in, product, warehouse, period) - fs(fp_out, product, warehouse, period))
        for retailer in retailers:
            for period in periods:
                model.addConstr(fs(fp_in, product, retailer, period) == params["d_r_p_t"][retailer][product][period])
        for hub in hubs:
            for period in periods:
                model.addConstr(fs(fp_in, product, hub, period) == fs(fp_out, product, hub, period))

    for supplier in params.get("bar_s_s_u", {}):
        for raw_material in raw_materials:
            for period in periods:
                shipped = fs(raw_out, raw_material, supplier, period)
                model.addConstr(shipped <= params["bar_s_s_u"][supplier][raw_material] * order_su[raw_material, supplier, period])
                model.addConstr(shipped >= params["scmin_s_u"][supplier][raw_material] * order_su[raw_material, supplier, period])
                model.addConstr(order_su[raw_material, supplier, period] <= y_s[supplier])
    for raw_material in raw_materials:
        for factory in factories:
            for period in periods:
                model.addConstr(
                    gp.quicksum(
                        _input_requirement(params, raw_material, product, g) * q[product, factory, g, period]
                        for product, g in production_pairs
                    )
                    == fs(raw_in, raw_material, factory, period)
                )
        for hub in hubs:
            for period in periods:
                model.addConstr(fs(raw_in, raw_material, hub, period) == fs(raw_out, raw_material, hub, period))

    _add_technology_constraints(
        model, params, products, factories, periods, production_technologies, remanufacturing_technologies,
        production_pairs, remanufacturing_pairs, production_products_by_technology, remanufacturing_products_by_technology,
        production_technologies_by_product,
        remanufacturing_technologies_by_product, y_f, u_prod, u_rem, use_rem, q, rem,
    )
    return_lag = _return_lags(params, products)
    for retailer in retailers:
        for recovered_product in recovered_products:
            for period_index, period in enumerate(periods):
                collected = fs(rp_out, recovered_product, retailer, period)
                minimum_return = gp.quicksum(
                    return_yield[recovered_product][product]
                    * _return_fraction(params, "ret_min_frac_r_p_t", retailer, product, period)
                    * _lagged_demand(params, retailer, product, periods, period_index, return_lag[product])
                    for product in products
                )
                maximum_return = gp.quicksum(
                    return_yield[recovered_product][product]
                    * _return_fraction(params, "ret_max_frac_r_p_t", retailer, product, period)
                    * _lagged_demand(params, retailer, product, periods, period_index, return_lag[product])
                    for product in products
                )
                model.addConstr(collected >= minimum_return)
                model.addConstr(
                    collected <= maximum_return
                )
    for recovered_product in recovered_products:
        for warehouse in warehouses:
            for period in periods:
                model.addConstr(fs(rp_in, recovered_product, warehouse, period) == fs(rp_out, recovered_product, warehouse, period))
        for hub in hubs:
            for period in periods:
                model.addConstr(fs(rp_in, recovered_product, hub, period) == fs(rp_out, recovered_product, hub, period))
        for factory in factories:
            for period in periods:
                model.addConstr(
                    gp.quicksum(
                        params["bom_rem_r_p"][recovered_product][product] * rem[product, factory, l, period]
                        for product, l in remanufacturing_pairs
                    )
                    == fs(rp_in, recovered_product, factory, period)
                )
    _add_inventory_capacity_constraints(
        model,
        params,
        products,
        warehouses,
        periods,
        y_w,
        inv_w,
    )

    # Floor-area requirement YCT_it (eq:YCT): a flow-based handling term at
    # both factories and warehouses, plus a stock-based storage term at
    # warehouses only -- mirrors Mota et al. (2018)'s general facility-area
    # expression (their Eq. 16), adapted to this model's flow-direction
    # convention (see rem:floor_area_flow_direction). Factories use X^out
    # (the only nonzero flow direction for finished products under the
    # greenfield convention of rem:valid_ineq, equal to q^p+q^r there);
    # warehouses use X^in, mirroring Mota's own indexing, alongside their
    # existing stock term. fs/fp_in/fp_out are already in scope here.
    item_area = _item_area_map(params, products, recovered_products=())
    item_flow_area = _item_flow_area_map(params, products)
    min_area_f = params.get("Amin_f", {factory: 0.0 for factory in factories})
    min_area_w = params.get("Amin_w", {warehouse: 0.0 for warehouse in warehouses})

    for factory in factories:
        model.addConstr(installed_area[factory] >= min_area_f.get(factory, 0.0) * y_f[factory])
        model.addConstr(installed_area[factory] <= params["A_f"][factory] * y_f[factory])
        for period in periods:
            used_area = gp.quicksum(
                item_flow_area.get(product, 0.0) * fs(fp_out, product, factory, period)
                for product in products
            )
            model.addConstr(used_area <= installed_area[factory])

    for warehouse in warehouses:
        model.addConstr(installed_area[warehouse] >= min_area_w.get(warehouse, 0.0) * y_w[warehouse])
        model.addConstr(installed_area[warehouse] <= params["A_w"][warehouse] * y_w[warehouse])
        for period in periods:
            used_area = gp.quicksum(
                item_flow_area.get(product, 0.0) * fs(fp_in, product, warehouse, period)
                + item_area.get(product, 0.0) * inv_w[product, warehouse, period]
                for product in products
            )
            model.addConstr(used_area <= installed_area[warehouse])


def _add_technology_constraints(
    model, params, products, factories, periods, production_technologies, remanufacturing_technologies,
    production_pairs, remanufacturing_pairs, production_products_by_technology, remanufacturing_products_by_technology,
    production_technologies_by_product,
    remanufacturing_technologies_by_product, y_f, u_prod, u_rem, use_rem, q, rem,
) -> None:
    production_pairs = tuple(production_pairs)
    remanufacturing_pairs = tuple(remanufacturing_pairs)
    for factory in factories:
        for technology in production_technologies:
            model.addConstr(u_prod[factory, technology] <= y_f[factory])
        for technology in remanufacturing_technologies:
            model.addConstr(u_rem[factory, technology] <= y_f[factory])
            for period in periods:
                model.addConstr(use_rem[factory, technology, period] <= u_rem[factory, technology])

        for technology in production_technologies:
            for period in periods:
                compatible_products = production_products_by_technology.get(technology, ())
                throughput = gp.quicksum(q[product, factory, technology, period] for product in compatible_products)
                model.addConstr(throughput <= params["bar_p_g"][technology] * u_prod[factory, technology])
                if compatible_products:
                    model.addConstr(throughput >= params["pcmin_g"][technology] * u_prod[factory, technology])
        for technology in remanufacturing_technologies:
            for period in periods:
                compatible_products = remanufacturing_products_by_technology.get(technology, ())
                throughput = gp.quicksum(rem[product, factory, technology, period] for product in compatible_products)
                model.addConstr(throughput <= params["bar_q_l"][technology] * use_rem[factory, technology, period])
                if compatible_products:
                    model.addConstr(throughput >= params["pcmin_l"][technology] * use_rem[factory, technology, period])

        for product in products:
            model.addConstr(
                gp.quicksum(u_prod[factory, technology] for technology in production_technologies_by_product.get(product, ()))
                <= 1
            )
            model.addConstr(
                gp.quicksum(u_rem[factory, technology] for technology in remanufacturing_technologies_by_product.get(product, ()))
                <= 1
            )


def _add_inventory_capacity_constraints(
    model, params, products, warehouses, periods, y_w, inv_w,
) -> None:
    capacity = params["icmax_p_n"]
    minimum = params.get("icmin_p_n", {})
    for product in products:
        for warehouse in warehouses:
            for period in periods:
                model.addConstr(inv_w[product, warehouse, period] <= capacity[product][warehouse] * y_w[warehouse])
                if minimum:
                    model.addConstr(inv_w[product, warehouse, period] >= minimum[product][warehouse] * y_w[warehouse])


def _item_area_map(params, products, recovered_products) -> dict[str, float]:
    if "apu_q" in params:
        return {item: float(area) for item, area in params["apu_q"].items()}
    item_area = {product: float(area) for product, area in params.get("apu_p", {}).items()}
    item_area.update(
        {
            recovered_product: float(area)
            for recovered_product, area in params.get(
                "apu_rp",
                _derive_recovered_product_area(params, products, recovered_products),
            ).items()
        }
    )
    return item_area


def _item_flow_area_map(params, products) -> dict[str, float]:
    flow_area = params.get("apur_p", {})
    return {product: float(flow_area.get(product, 0.0)) for product in products}


def _derive_recovered_product_area(params, products, recovered_products) -> dict[str, float]:
    product_area = params.get("apu_p", {})
    remanufacturing_bom = params.get("bom_rem_r_p", {})
    return {
        recovered_product: sum(
            remanufacturing_bom.get(recovered_product, {}).get(product, 0.0)
            * product_area.get(product, 0.0)
            for product in products
        )
        for recovered_product in recovered_products
    }


def _add_transport_constraints(
    model, params, transport_arcs, allowed_modes, flow_by_arc, weights, periods,
    suppliers, factories, warehouses, airports, seaports, hubs, y_s, y_f, y_w, y_h, zt, trip, vehicle, contract, x,
) -> None:
    mode_family = params.get("mode_family_m", {})
    for origin, destination in transport_arcs:
        for mode in allowed_modes[(origin, destination)]:
            family = _mode_family(mode, mode_family)
            for period in periods:
                transported_weight = gp.quicksum(
                    weights[item] * x[item, origin, destination, mode, period]
                    for item in flow_by_arc.get((origin, destination), ())
                )
                contracted_cap = params.get("ccamax_m", {}).get(mode, 0.0)
                _add_transport_endpoint_activation(
                    model,
                    origin=origin,
                    destination=destination,
                    mode=mode,
                    period=period,
                    suppliers=suppliers,
                    factories=factories,
                    warehouses=warehouses,
                    hubs=hubs,
                    y_s=y_s,
                    y_f=y_f,
                    y_w=y_w,
                    y_h=y_h,
                    zt=zt,
                )
                if family == "truck":
                    model.addConstr(transported_weight <= params["bar_X_m"][mode] * trip[origin, destination, mode, period])
                    if params.get("ctmin_m", {}).get(mode, 0.0) > 0.0:
                        model.addConstr(transported_weight >= params["ctmin_m"][mode] * trip[origin, destination, mode, period])
                    model.addConstr(
                        trip[origin, destination, mode, period]
                        <= _trip_big_m(params, mode, origin=origin, destination=destination) * zt[origin, destination, mode, period]
                    )
                    model.addConstr(trip[origin, destination, mode, period] >= zt[origin, destination, mode, period])
                elif contracted_cap > 0.0:
                    model.addConstr(transported_weight <= contracted_cap * zt[origin, destination, mode, period])
                    if (mode, period) in contract:
                        model.addConstr(zt[origin, destination, mode, period] <= contract[mode, period])
                else:
                    model.addConstr(transported_weight <= params["bar_X_m"][mode] * zt[origin, destination, mode, period])
        if allowed_modes[(origin, destination)]:
            for period in periods:
                model.addConstr(
                    gp.quicksum(zt[origin, destination, mode, period] for mode in allowed_modes[(origin, destination)]) <= 1,
                )

    _add_truck_fleet_constraints(
        model,
        params,
        transport_arcs,
        allowed_modes,
        periods,
        suppliers,
        factories,
        warehouses,
        hubs,
        y_s,
        y_f,
        y_w,
        y_h,
        mode_family,
        trip,
        vehicle,
    )

    # eq:min_flow (C8): every open/selected node must carry positive flow of
    # some item in some period, ruling out degenerate open-but-unused nodes.
    openable_nodes = (*suppliers, *factories, *warehouses, *hubs)
    for entity in openable_nodes:
        incident_flow = gp.quicksum(
            x[item, origin, destination, mode, period]
            for origin, destination in transport_arcs
            if origin == entity or destination == entity
            for item in flow_by_arc.get((origin, destination), ())
            for mode in allowed_modes[(origin, destination)]
            for period in periods
        )
        model.addConstr(
            incident_flow >= _entity_activity(entity, suppliers, factories, warehouses, hubs, y_s, y_f, y_w, y_h),
            name=f"min_flow[{entity}]",
        )

    for entity, cap in params.get("ecmax_i", {}).items():
        for period in periods:
            model.addConstr(
                gp.quicksum(
                    weights[item] * x[item, origin, destination, mode, period]
                    for origin, destination in transport_arcs
                    if origin == entity or destination == entity
                    for mode in allowed_modes[(origin, destination)]
                    for item in flow_by_arc.get((origin, destination), ())
                )
                <= cap * _entity_activity(entity, suppliers, factories, warehouses, hubs, y_s, y_f, y_w, y_h)
    )
    _add_intermodal_hub_constraints(
        model,
        transport_arcs,
        allowed_modes,
        flow_by_arc,
        periods,
        airports,
        seaports,
        mode_family,
        x,
    )


def _add_transport_endpoint_activation(
    model,
    *,
    origin: str,
    destination: str,
    mode: str,
    period: str,
    suppliers,
    factories,
    warehouses,
    hubs,
    y_s,
    y_f,
    y_w,
    y_h,
    zt,
) -> None:
    if origin in suppliers:
        model.addConstr(zt[origin, destination, mode, period] <= y_s[origin])
    if destination in suppliers:
        model.addConstr(zt[origin, destination, mode, period] <= y_s[destination])
    if origin in factories:
        model.addConstr(zt[origin, destination, mode, period] <= y_f[origin])
    if destination in factories:
        model.addConstr(zt[origin, destination, mode, period] <= y_f[destination])
    if origin in warehouses:
        model.addConstr(zt[origin, destination, mode, period] <= y_w[origin])
    if destination in warehouses:
        model.addConstr(zt[origin, destination, mode, period] <= y_w[destination])
    if origin in hubs:
        model.addConstr(zt[origin, destination, mode, period] <= y_h[origin])
    if destination in hubs:
        model.addConstr(zt[origin, destination, mode, period] <= y_h[destination])


def _add_valid_inequalities(
    model,
    factories,
    production_technologies,
    remanufacturing_technologies,
    y_f,
    u_prod,
    u_rem,
) -> None:
    """(C10) Valid inequalities -- see Remark rem:valid_ineq in
    paper/sections/04c_follower.tex.

    Only eq:vi_tech_demand is implemented: every open factory installs at
    least one production OR remanufacturing technology. Production alone is
    not implied by C1-C9 -- a factory engaged purely in remanufacturing can
    satisfy eq:min_flow via q^r without ever installing lambda^p. (The
    other candidate inequality from the paper, eq:vi_capacity_demand, is not
    a valid inequality in general -- inventory banking lets a network cover
    a single period's peak demand with less installed capacity than that
    inequality requires -- so it is deliberately not implemented; see the
    remark for the counterexample.)
    """
    if not production_technologies and not remanufacturing_technologies:
        return
    for factory in factories:
        model.addConstr(
            gp.quicksum(u_prod[factory, technology] for technology in production_technologies)
            + gp.quicksum(u_rem[factory, technology] for technology in remanufacturing_technologies)
            >= y_f[factory],
            name=f"vi_tech_demand[{factory}]",
        )


def _add_truck_fleet_constraints(
    model,
    params,
    transport_arcs,
    allowed_modes,
    periods,
    suppliers,
    factories,
    warehouses,
    hubs,
    y_s,
    y_f,
    y_w,
    y_h,
    mode_family,
    trip,
    vehicle,
) -> None:
    if len(vehicle) == 0:
        return

    model.addConstr(
        gp.quicksum(params["f_mode_m"][mode] * vehicle[origin, mode] for origin, mode in vehicle.keys())
        <= params.get("truck_investment_budget", 1.0e12),
        name="truck_investment_budget",
    )

    max_vehicle = params.get("max_vehicle_i_m", {})
    road_return_factor = params.get("road_return_factor_m", {})
    speed = params.get("speed_km_h_m", {})
    max_hours = params.get("max_driving_hours_m", {})
    distances = params["d_i_j"]

    for origin, mode in vehicle.keys():
        activity = _entity_activity(origin, suppliers, factories, warehouses, hubs, y_s, y_f, y_w, y_h)
        configured_max = max_vehicle.get(origin, {}).get(mode)
        if configured_max is None:
            configured_max = _trip_big_m(params, mode, origin=origin)
        model.addConstr(vehicle[origin, mode] <= configured_max * activity)
        outbound_trip_vars = [
            trip[origin, destination, mode, period]
            for arc_origin, destination in transport_arcs
            if arc_origin == origin and mode in allowed_modes[(arc_origin, destination)]
            for period in periods
        ]
        if outbound_trip_vars:
            model.addConstr(vehicle[origin, mode] <= configured_max * gp.quicksum(outbound_trip_vars))
        else:
            model.addConstr(vehicle[origin, mode] == 0.0)

        if _mode_family(mode, mode_family) != "truck":
            continue
        mode_speed = float(speed.get(mode, 0.0))
        mode_hours = float(max_hours.get(mode, 0.0))
        for period in periods:
            outbound_trips = (
                (destination, trip[origin, destination, mode, period])
                for arc_origin, destination in transport_arcs
                if arc_origin == origin and mode in allowed_modes[(arc_origin, destination)]
            )
            if mode_speed > 0.0 and mode_hours > 0.0:
                model.addConstr(
                    gp.quicksum(
                        road_return_factor.get(mode, 2.0)
                        * distances[origin][destination]
                        / mode_speed
                        * trip_var
                        for destination, trip_var in outbound_trips
                    )
                    <= mode_hours * vehicle[origin, mode]
                )
            else:
                model.addConstr(
                    gp.quicksum(trip_var for _destination, trip_var in outbound_trips)
                    <= _trip_big_m(params, mode, origin=origin) * vehicle[origin, mode]
                )


def _trip_big_m(
    params,
    mode: str,
    *,
    origin: str | None = None,
    destination: str | None = None,
) -> int:
    configured = params.get("trip_big_m_m", {}).get(mode)
    capacity = max(float(params["bar_X_m"].get(mode, 1.0)), 1.0)
    candidate_bounds: list[int] = []
    if configured is not None:
        candidate_bounds.append(max(1, int(math.ceil(float(configured)))))

    endpoint_caps = [
        float(params.get("ecmax_i", {}).get(node, 0.0))
        for node in (origin, destination)
        if node is not None and params.get("ecmax_i", {}).get(node) is not None
    ]
    if endpoint_caps:
        candidate_bounds.append(max(1, int(math.ceil(min(endpoint_caps) / capacity)) + 1))

    if params.get("ccamax_m", {}).get(mode, 0.0) > 0.0:
        candidate_bounds.append(max(1, int(math.ceil(float(params["ccamax_m"][mode]) / capacity)) + 1))
    elif not candidate_bounds:
        flow_bound = max(params.get("ecmax_i", {}).values(), default=capacity)
        candidate_bounds.append(max(1, int(math.ceil(flow_bound / capacity)) + 1))

    return min(candidate_bounds)


def _add_intermodal_hub_constraints(
    model, transport_arcs, allowed_modes, flow_by_arc, periods, airports, seaports, mode_family, x,
) -> None:
    for transfer_hubs, transfer_family, name_prefix in (
        (airports, "air", "airport"),
        (seaports, "sea", "seaport"),
    ):
        hub_set = set(transfer_hubs)
        if not hub_set:
            continue

        items_by_hub: dict[str, set[str]] = {hub: set() for hub in transfer_hubs}
        for origin, destination in transport_arcs:
            items = flow_by_arc.get((origin, destination), ())
            if origin in hub_set:
                items_by_hub[origin].update(items)
            if destination in hub_set:
                items_by_hub[destination].update(items)

        for hub in transfer_hubs:
            for item in sorted(items_by_hub[hub]):
                for period in periods:
                    access_in = gp.quicksum(
                        x[item, origin, hub, mode, period]
                        for origin, destination in transport_arcs
                        if destination == hub
                        and origin not in hub_set
                        and item in flow_by_arc.get((origin, destination), ())
                        for mode in allowed_modes[(origin, destination)]
                        if _mode_family(mode, mode_family) != transfer_family
                    )
                    transfer_out = gp.quicksum(
                        x[item, hub, destination, mode, period]
                        for origin, destination in transport_arcs
                        if origin == hub
                        and destination in hub_set
                        and item in flow_by_arc.get((origin, destination), ())
                        for mode in allowed_modes[(origin, destination)]
                        if _mode_family(mode, mode_family) == transfer_family
                    )
                    transfer_in = gp.quicksum(
                        x[item, origin, hub, mode, period]
                        for origin, destination in transport_arcs
                        if destination == hub
                        and origin in hub_set
                        and item in flow_by_arc.get((origin, destination), ())
                        for mode in allowed_modes[(origin, destination)]
                        if _mode_family(mode, mode_family) == transfer_family
                    )
                    access_out = gp.quicksum(
                        x[item, hub, destination, mode, period]
                        for origin, destination in transport_arcs
                        if origin == hub
                        and destination not in hub_set
                        and item in flow_by_arc.get((origin, destination), ())
                        for mode in allowed_modes[(origin, destination)]
                        if _mode_family(mode, mode_family) != transfer_family
                    )

                    model.addConstr(
                        access_in == transfer_out,
                        name=f"{name_prefix}_access_to_transfer[{item},{hub},{period}]",
                    )
                    model.addConstr(
                        transfer_in == access_out,
                        name=f"{name_prefix}_transfer_to_access[{item},{hub},{period}]",
                    )


def _entity_activity(entity: str, suppliers, factories, warehouses, hubs, y_s, y_f, y_w, y_h):
    if entity in suppliers:
        return y_s[entity]
    if entity in factories:
        return y_f[entity]
    if entity in warehouses:
        return y_w[entity]
    if entity in hubs:
        return y_h[entity]
    return 1.0


def _inventory_cost(params, products, warehouses, periods, inv_w):
    product_holding_cost = params["h_p"]
    return gp.quicksum(product_holding_cost[p] * inv_w[p, w, t] for p in products for w in warehouses for t in periods)


def _input_requirement(params: dict[str, object], raw_material: str, product: str, technology: str) -> float:
    return params["a_in_u_p_g"][raw_material][product].get(technology, 0.0)


def _return_lags(params: dict[str, object], products: Iterable[str]) -> dict[str, int]:
    configured = params.get("theta_p", {})
    return {product: int(configured.get(product, 1)) for product in products}


def _lagged_demand(
    params: dict[str, object],
    retailer: str,
    product: str,
    periods: tuple[str, ...],
    period_index: int,
    lag: int,
) -> float:
    lagged_index = period_index - lag
    if lagged_index < 0:
        return 0.0
    return params["d_r_p_t"][retailer][product][periods[lagged_index]]


def _return_fraction(
    params: dict[str, object],
    parameter_name: str,
    retailer: str,
    product: str,
    period: str,
) -> float:
    if parameter_name in params:
        return float(params[parameter_name][retailer][product][period])
    return float(params["rho_r_p_t"][retailer][product][period])


def _products_by_technology(pairs: Iterable[tuple[str, str]], technologies: Iterable[str]) -> dict[str, tuple[str, ...]]:
    mapping: dict[str, list[str]] = {technology: [] for technology in technologies}
    for product, technology in pairs:
        mapping.setdefault(technology, []).append(product)
    return {technology: tuple(products) for technology, products in mapping.items()}


def _technologies_by_product(pairs: Iterable[tuple[str, str]], products: Iterable[str]) -> dict[str, tuple[str, ...]]:
    mapping: dict[str, list[str]] = {product: [] for product in products}
    for product, technology in pairs:
        mapping.setdefault(product, []).append(technology)
    return {product: tuple(technologies) for product, technologies in mapping.items()}


def _flow_indices(flow_tuples: Iterable[tuple[str, str, str]]):
    incoming: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    outgoing: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for item, origin, destination in flow_tuples:
        outgoing[(item, origin)].append((origin, destination))
        incoming[(item, destination)].append((origin, destination))
    return incoming, outgoing


def _item_weights(params: dict[str, object], raw_materials, products, recovered_products) -> dict[str, float]:
    weights: dict[str, float] = {}
    weights.update({raw_material: float(params["omega_u"][raw_material]) for raw_material in raw_materials})
    weights.update({product: float(params["omega_p"][product]) for product in products})
    for recovered_product in recovered_products:
        weights[recovered_product] = float(params["omega_rp"][recovered_product])
    return weights


def _allowed_modes(
    origin: str,
    destination: str,
    modes: tuple[str, ...],
    *,
    airports: tuple[str, ...],
    seaports: tuple[str, ...],
    mode_family: dict[str, str],
) -> tuple[str, ...]:
    if origin in airports and destination in airports:
        required_family = "air"
    elif origin in seaports and destination in seaports:
        required_family = "sea"
    else:
        required_family = "truck"
    allowed = tuple(mode for mode in modes if mode_family.get(mode, mode) == required_family)
    return allowed or tuple(modes)


def _mode_family(mode: str, mode_family: dict[str, str]) -> str:
    return mode_family.get(mode, mode)


def _normalize_solution_value(
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
        value = _normalize_solution_value(variable, float(variable.X))
        if abs(value) > tolerance:
            values[variable.VarName] = value
    return values


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
