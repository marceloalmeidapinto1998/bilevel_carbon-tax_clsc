"""The DBP high-point relaxation: the leader's objective F = E + w * tax_index, the value-function
cuts, the objective cap, the elastic-cut remedy, and the HPR's solve.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from typing import Iterable

import gurobipy as gp
from gurobipy import GRB

from clsc.config.defaults import DEFAULT
from .instance_data import InstanceData
from .gurobi_utils import ModelArtifacts, SolveResult, finite_dual_bound, optimize_model
from .supply_chain import build_supply_chain_model, total_emissions_upper_bound
from .follower import epsilon_prime_tolerance


# Working unit for emissions inside the models: kg -> TONNES.
#
# Was 1e6 (kilotonnes) until 2026-09-09, when that scale was shown to make Gurobi return a
# provably wrong answer on the DBP high-point relaxation. Dividing kg-scale emission factors by a
# million pushes the smallest matrix coefficients down to 1e-08, and with the value-function
# cuts at the other end the HPR spanned [1e-08, 4e+07] -- fifteen orders of magnitude, with
# Gurobi itself warning about it. Measured on STD_TOY5 carrying one cut, in a SINGLE model
# object: solved with tax_index free, Gurobi reported OPTIMAL at 38 352 186.527 kg with a
# matching ObjBound; adding the constraint tax_index == 340 -- a strict restriction of that
# same model -- then returned 38 351 450.584 kg. A restriction cannot lower a minimum, so the
# free solve's "proven" bound was false, and an invalid LOWER bound is the one error the DBP
# cannot absorb: relative_optimality_gap floors the negative gap at zero and the loop closes
# against a bound that is not one.
#
# At 1e3 the contradiction disappears and both solves agree on 38 351 450.584 kg (1.0, i.e.
# raw kg, also works; tonnes keeps the magnitudes moderate and is the natural reporting unit).
# Two companion changes went in with it: the cuts are written in tax_index rather than
# tax_rate, and the tau*emissions product is carried in EUR -- both keeping large constants out
# of the cut rows. This constant is the one that actually decides correctness.
EMISSIONS_SCALE = 1_000.0  # kg to tonnes


# Gurobi NumericFocus for the DBP high-point relaxation, and ONLY for it -- the follower and
# fixed-tax models are well behaved and pay nothing for the default.
#
# This was removed when the HPR's tau*emissions product stopped being a non-convex QCP and
# became an exact one-hot MILP, on the reasoning that the invalid bounds it had been papering
# over were the McCormick envelope's fault and were now gone. Half of that was right: the
# envelope gap IS gone. The conditioning is not. Measured on STD_TOY6 (2026-09-09), the HPR
# carrying one value-function cut reports an optimum of 38 352 186.527 kg while a point at
# 38 351 450.584 kg is feasible in that very model -- verified by fixing tax_index to 340 and
# re-solving, which returns exactly the lower value. Gurobi's presolve is making a reduction
# that does not hold at this model's coefficient scale: big-Ms near 484 in scaled units sit in
# the same constraints as costs near 1e6, and the cut couples them. Presolve=0 also restores
# the correct bound, and Cuts=0 does not, which is what identifies presolve as the culprit.
#
# An invalid LOWER bound is the one error this method cannot absorb: it silently closes the
# gap against a bound that is not one, and relative_optimality_gap floors the negative gap at
# zero so nothing downstream ever notices.
# NOT APPLIED -- kept as the record of a fix that does not work. Setting NumericFocus=3 here
# does restore the correct bound above, but breaks the loop elsewhere: on STD_TOY5 the run stops
# at stagnation_limit_gap_not_closed after 13 iterations instead of converging, and on STD_TOY6
# the HPR is reported INFEASIBLE at iteration 3 -- a model that was feasible at iteration 2
# and only gained one constraint. The same false-infeasible signature appeared earlier in the
# generator's own feasibility gate under NumericFocus=3. Presolve=0 also restores the bound and
# has not been tested past that point. The underlying problem is the HPR's coefficient range,
# and neither parameter addresses it.


@dataclass(frozen=True, slots=True)
class ValueFunctionCut:
    tax_index: int
    cost: float
    emissions: float
    iteration: int
    # Discounted emission aggregate at this point; the cut's tau-coefficient.
    # None means "undiscounted instance", where it equals ``emissions``.
    tax_base: float | None = None


@dataclass(slots=True)
class HighPointRelaxation:
    artifacts: ModelArtifacts
    lower_tax_index: int = 0
    upper_tax_index: int = 0
    emissions_big_m: float = 0.0
    # Grid step, needed to write the cuts in terms of the integer tax_index rather than the
    # continuous tax_rate. See add_value_function_cut.
    scale_factor: float = 1.0
    applied_cut_iterations: set[int] = field(default_factory=set)
    emissions_cap_constraint: gp.Constr | None = None
    emissions_cap: float | None = None
    # Soares et al. (2021)'s (P5-D): every value-function cut carries its own elastic slack D_k,
    # penalised in the objective, so the HPR always has a feasible point to return. The
    # slacks are summed into `artifacts.elastic_slack_var` by `elastic_total_constraint`.
    elastic: bool = False
    elastic_penalty: float = 0.0
    elastic_total_constraint: gp.Constr | None = None
    # Handles of the value-function cut rows, by iteration, so the cuts can be made elastic in
    # place (enable_elastic_cuts) when the HPR first fails to return a point.
    cut_constraints: dict[int, gp.Constr] = field(default_factory=dict)
    # Weight of the tax in the leader's objective F = E + w * tax_index, in tonnes of emissions per
    # grid index (the HPR works in tonnes): the single-objective leader of Soares et al. (2021),
    # whose objective already prefers the lower tax. 0.0 only before the weight is set.
    tax_weight_scaled: float = 0.0
    # F <= UB (Mitsos 2010), a two-variable row: see set_leader_objective_cap.
    objective_cap_constraint: gp.Constr | None = None
    # One-hot gadget handles, kept so the incumbent emissions cap can retighten the
    # gadget's big-M in place (see _retighten_tax_base_big_m). The build-time bound is
    # a combinatorial worst case -- every facility open, every technology at capacity,
    # every period -- and measures 35x to 500x the tax base actually attained on the
    # twelve base cells, which is the dominant weakness in this HPR's LP relaxation.
    tax_level_selected: dict[int, gp.Var] = field(default_factory=dict)
    tax_base_if_level: dict[int, gp.Var] = field(default_factory=dict)
    tax_level_cap_constraints: dict[int, gp.Constr] = field(default_factory=dict)
    tax_level_floor_constraints: dict[int, gp.Constr] = field(default_factory=dict)
    # Scaled worst-case bound from build time; the floor under any retightening.
    tax_base_big_m_scaled: float = 0.0
    # Scaled bound currently written into the gadget's rows.
    tax_base_bound_applied_scaled: float = 0.0


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
    """Solve the DBP high-point relaxation: minimise the leader's objective ``F = E + w * tax_index``
    (plus the elastic penalty once the cuts are elastic) over the follower's feasible region and
    every cut accumulated so far -- Soares et al. (2021)'s (P5), one stage.

    The returned ``emissions`` and ``leader_lower_bound`` are the HPR's DUAL bound on F, in
    kg, not the incumbent's value. Every cut is valid at every tax, so the HPR is a relaxation
    and its optimum is a valid lower bound on the bilevel optimum, and a MIP solve hands back two numbers around that
    optimum: ObjVal, the best solution found, which lies at or ABOVE it, and ObjBound, the proven
    dual bound, which lies at or BELOW it. Reading the incumbent overstates the bound by up to the
    stopping gap -- on STD_TOY6 that produced a reported LB 11.1 kg ABOVE the UB, an inversion the
    loop then swallowed silently because relative_optimality_gap floors the gap at zero. ObjBound
    is the only one of the two that is a bound in the required direction; it is weaker by exactly
    the MIP gap, which is the honest price of the claim.

    An HPR that stops on its time limit is a PARTIAL HPR: its dual bound is still valid, and
    if it found any point, that point's ``tax_index`` is a usable next proposal. This is Soares et
    al. (2021, Sect. 7)'s treatment of an unsolved relaxation -- use the solver's own bound, do
    not abandon the run. What a partial HPR cannot do is certify Lemma 3.
    """
    if isinstance(instance_or_hpr, HighPointRelaxation):
        hpr = instance_or_hpr
    else:
        hpr = build_hpr(instance_or_hpr)
    if cuts:
        _synchronize_hpr(hpr, cuts)

    artifacts = hpr.artifacts
    model = artifacts.model
    if artifacts.emissions_total_var is None or artifacts.tax_index_var is None:
        raise RuntimeError(
            "DBP high-point relaxation is missing the emissions/tax_index variables "
            "required for the relaxation solve"
        )
    objective = _hpr_objective(hpr)
    model.setObjective(objective, GRB.MINIMIZE)
    result = optimize_model(
        artifacts,
        tax_index=None,
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

    lower_tax_index = instance.lower_tax_index
    upper_tax_index = instance.upper_tax_index
    scale_factor = instance.scale_factor  # derived from the instance's own grid
    tax_index = model.addVar(vtype=GRB.INTEGER, lb=lower_tax_index, ub=upper_tax_index, name="tax_index")

    emissions_big_m = total_emissions_upper_bound(instance)
    emissions_upper_bound_scaled = emissions_big_m / EMISSIONS_SCALE
    emissions_total_scaled = model.addVar(
        lb=0.0,
        ub=emissions_upper_bound_scaled,
        name="total_emissions_tonnes",
    )
    model.addConstr(
        emissions_total_scaled == common.emissions_expr / EMISSIONS_SCALE,
        name="total_emissions_tonnes_def",
    )

    # tax_rate == TAX_SCALE_FACTOR * tax_index -- the continuous rate pinned to the
    # grid. A single linear equality (constant coefficient), so it never needs
    # a linearization of its own.
    tax_rate = model.addVar(
        lb=scale_factor * lower_tax_index,
        ub=scale_factor * upper_tax_index,
        name="tax_rate",
    )
    model.addConstr(tax_rate == scale_factor * tax_index, name="tax_rate_def")

    # The leader minimises emissions_total_scaled (PHYSICAL emissions); the
    # follower pays tax on the discounted base. On an undiscounted instance the
    # two coincide and we reuse the same variable, leaving the HPR's
    # structure byte-identical to the pre-discounting formulation.
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
        # NOT ADDED, deliberately: `tax_base_scaled <= emissions_total_scaled`.
        #
        # The inequality is true -- every term of both aggregates is per-period, including the
        # amortised construction term, and every discount weight is <= 1 (see _emissions) -- and adding it
        # looked free, since it only restates what the flow variables already imply. It is not
        # free. Measured on STD_I25_M8_T3's reconstructed iteration-2 HPR (2026-09-25),
        # Stage 1 proves optimality in 466 s WITHOUT the row and fails to find any feasible
        # point at all in 900 s WITH it. A dense row tying two aggregates that presolve would
        # otherwise substitute away costs far more than the bound it communicates.
        #
        # Nothing depends on it: B <= E holds at every feasible point whether or not the row is
        # written, so _retighten_tax_base_big_m's use of the emissions cap as a bound on the tax
        # base rests on the algebra, not on this constraint.

    # tau*emissions linearised exactly by a one-hot (Glover-style) disaggregation over the tax
    # grid, rather than by McCormick + spatial branch-and-bound on the two continuous factors
    # tax_rate and tax_base_scaled. That QCP formulation (NonConvex=2) is only exact AFTER
    # branching pins tax_index to a single value -- at every node before that the McCormick
    # envelope is a genuine relaxation, and on STD_TOY6 this measurably broke monotonicity
    # (adding a cut LOWERED the Stage-1 minimum) and reported lower bounds above a feasible
    # point. NumericFocus=3 papered over the symptom without changing the formulation; this
    # replaces the formulation itself.
    #
    # One binary tax_level[i] per grid index selects exactly one tax_index (a standard "choose
    # one of N discrete levels" gadget); for each level, tax_base_if_level[i] is tax_base_scaled
    # when that level is selected and exactly 0 otherwise -- the classic exact linearization of a
    # binary-times-continuous product (this IS the McCormick envelope specialised to a binary
    # factor, the same trick Soares et al. use, just applied once per grid level instead of once
    # to a genuinely continuous factor). Summing the selected level's tax_base_if_level, weighted
    # by that level's tax rate, reconstructs tax_rate * tax_base_scaled exactly, entirely in
    # linear constraints: no NonConvex flag, no spatial branch-and-bound, no McCormick gap ever
    # open on this model. The cost is N extra binaries, N extra continuous variables and ~3N extra
    # linear constraints (201, 201 and ~600 on the project's grid) in exchange for the
    # follower/fixed-tax models' own numerical reliability -- see build_follower_model, which
    # never needed any of this because it never faces a leader-side unknown at all.
    tax_levels = range(lower_tax_index, upper_tax_index + 1)
    tax_level_selected = model.addVars(tax_levels, vtype=GRB.BINARY, name="tax_level_selected")
    model.addConstr(tax_level_selected.sum() == 1, name="tax_level_selected_unique")
    model.addConstr(
        tax_index == gp.quicksum(index * tax_level_selected[index] for index in tax_levels),
        name="tax_index_from_level",
    )
    # Declare the selection as an ORDERED SOS1 set, weighted by the tax index itself.
    # Logically redundant beside the binaries and the unit sum, but it changes how Gurobi
    # BRANCHES: on an SOS1 set it splits the ordered index range in two and forbids one
    # half, so a 201-level selection resolves in ~log2(201) dichotomies instead of being
    # chipped away one binary at a time. The weights must be the indices for that ordering
    # to be the tax ordering.
    model.addSOS(
        GRB.SOS_TYPE1,
        [tax_level_selected[index] for index in tax_levels],
        [float(index) for index in tax_levels],
    )
    tax_base_if_level = model.addVars(
        tax_levels, lb=0.0, ub=emissions_upper_bound_scaled, name="tax_base_if_level",
    )
    tax_level_cap_constraints: dict[int, gp.Constr] = {}
    tax_level_floor_constraints: dict[int, gp.Constr] = {}
    for index in tax_levels:
        tax_level_cap_constraints[index] = model.addConstr(
            tax_base_if_level[index] <= emissions_upper_bound_scaled * tax_level_selected[index],
            name=f"tax_base_if_level_cap_{index}",
        )
        model.addConstr(tax_base_if_level[index] <= tax_base_scaled, name=f"tax_base_if_level_le_{index}")
        tax_level_floor_constraints[index] = model.addConstr(
            tax_base_if_level[index]
            >= tax_base_scaled - emissions_upper_bound_scaled * (1 - tax_level_selected[index]),
            name=f"tax_base_if_level_ge_{index}",
        )
    # The product is carried in EUR, not in scaled units later multiplied back up. Both spell
    # the same quantity -- tax_rate * E_scaled * EMISSIONS_SCALE == tax_rate * E_raw -- but the
    # scaled form leaves a bare EMISSIONS_SCALE (1e6) sitting as the coefficient of this single
    # variable in EVERY value-function cut, and the cuts are the rows where the leader and
    # follower magnitudes already meet. Folding it into the definition row instead spreads it
    # over the per-level coefficients, where it lands at EMISSIONS_SCALE * scale_factor * index
    # (at most 2e5 on the project's grid), and leaves the cuts with a coefficient of 1.
    tau_emissions_product = model.addVar(
        lb=0.0,
        ub=EMISSIONS_SCALE * (scale_factor * upper_tax_index) * emissions_upper_bound_scaled,
        name="tau_emissions_product_eur",
    )
    model.addConstr(
        tau_emissions_product
        == gp.quicksum(
            (EMISSIONS_SCALE * scale_factor * index) * tax_base_if_level[index]
            for index in tax_levels
        ),
        name="tau_emissions_eur_def",
    )
    follower_objective_expr = common.cost_expr + tau_emissions_product

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
            tax_index_var=tax_index,
            emissions_total_var=emissions_total_scaled,
            elastic_slack_var=elastic_slack_var,
            tax_rate_var=tax_rate,
        ),
        lower_tax_index=lower_tax_index,
        upper_tax_index=upper_tax_index,
        emissions_big_m=emissions_big_m,
        scale_factor=scale_factor,
        elastic=elastic,
        elastic_penalty=elastic_penalty,
        elastic_total_constraint=elastic_total_constraint,
        tax_level_selected=dict(tax_level_selected),
        tax_base_if_level=dict(tax_base_if_level),
        tax_level_cap_constraints=tax_level_cap_constraints,
        tax_level_floor_constraints=tax_level_floor_constraints,
        tax_base_big_m_scaled=emissions_upper_bound_scaled,
        tax_base_bound_applied_scaled=emissions_upper_bound_scaled,
    )


def add_value_function_cut(hpr: HighPointRelaxation, cut: ValueFunctionCut) -> None:
    if cut.iteration in hpr.applied_cut_iterations:
        return

    tax_index = hpr.artifacts.tax_index_var
    if tax_index is None:
        raise RuntimeError("DBP high-point relaxation is missing the leader tax_index variable")

    # cut.tax_base is the discounted aggregate the follower was taxed on at this point; it
    # coincides with cut.emissions on an undiscounted instance. Being a constant read off an
    # already-solved point, its product with a leader variable is linear either way.
    #
    # WRITTEN IN tax_index, NOT tax_rate, and the two are algebraically the same row:
    # tax_rate == scale_factor * tax_index is an equality of this very model, so
    # cost_v + base_v * tax_rate and cost_v + (base_v * scale_factor) * tax_index describe the
    # identical constraint. They are NOT the same numerically. base_v is an emissions aggregate
    # in kg -- tens of millions -- while tax_rate is a rate per kg confined to [0, 0.2]; the
    # product is an ordinary six-figure number of EUR reached by multiplying a huge coefficient
    # by a tiny variable. Folding the scale factor into the coefficient rescales the pair without
    # touching the product: on STD_TOY5's first cut, 3.7e7 becomes 3.7e4 against a variable that
    # runs 0..200 instead of 0..0.2.
    #
    # This is not cosmetic. With the kg-scale coefficient the HPR's matrix spanned
    # [1e-08, 4e+07] and Gurobi warned about it; its presolve then made a reduction that does
    # not hold at that range and reported an optimum of 38 352 186.527 kg for a model in which
    # 38 351 450.584 kg is feasible -- an invalid LOWER bound, which this method cannot absorb
    # because relative_optimality_gap floors the resulting negative gap at zero and closes
    # against a bound that is not one.
    cut_tax_base = cut.emissions if cut.tax_base is None else cut.tax_base
    right_hand_side = (
        cut.cost
        + (cut_tax_base * hpr.scale_factor) * tax_index
        + epsilon_prime_tolerance(cut.cost)
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
    emissions plus ``tax_weight_scaled * tax_index`` -- plus the (P5-D) elastic penalty when the
    cuts are elastic."""
    objective = gp.LinExpr(hpr.artifacts.emissions_total_var)
    if hpr.tax_weight_scaled > 0.0 and hpr.artifacts.tax_index_var is not None:
        objective += hpr.tax_weight_scaled * hpr.artifacts.tax_index_var
    if hpr.elastic and hpr.artifacts.elastic_slack_var is not None:
        objective += hpr.elastic_penalty * hpr.artifacts.elastic_slack_var
    return objective


def set_leader_tax_weight(hpr: HighPointRelaxation, weight_kg_per_index: float) -> None:
    """Make the leader's objective ``F = E + w * tax_index`` (``w`` in kg CO2e per grid index).

    This is the single-objective leader of Soares et al. (2021): one criterion, so their DBP --
    one HPR stage, the UB_F - LB_F gap, Lemma 3 -- applies as written. The tax is the
    leader's own variable, so the extra term is linear and the HPR is no harder to formulate;
    ``w`` states how much emissions the regulator would give up to avoid one more grid index of
    tax, which is what decides among taxes that abate the same.
    """
    if weight_kg_per_index < 0.0:
        raise ValueError("the leader's tax weight must be non-negative")
    hpr.tax_weight_scaled = weight_kg_per_index / EMISSIONS_SCALE
    hpr.artifacts.model.setObjective(_hpr_objective(hpr), GRB.MINIMIZE)
    hpr.artifacts.model.update()


def set_leader_objective_cap(hpr: HighPointRelaxation, leader_objective_ub: float | None) -> None:
    """Bound the HPR's leader objective from above by the best value any evaluated point
    attained: ``E + w * tax_index <= UB`` -- Soares et al. (2021, Sect. 8)'s ``F <= UB_F``
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
            artifacts.emissions_total_var + hpr.tax_weight_scaled * artifacts.tax_index_var <= ub_scaled,
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
        max(1.0, hpr.emissions_big_m / EMISSIONS_SCALE) * DEFAULT.elastic_penalty_mult
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
    tax_index: int,
) -> None:
    """MIP start for the HPR at an already-evaluated point (tax_index, y): the follower's
    variables by name (absent names are the zeros the follower snapshot omits), the tax, and
    the one-hot selector. The continuous gadget variables and any elastic slacks are left for
    Gurobi to complete. With elastic cuts and y the best-emissions response (so that it meets
    the emissions cap) this start is feasible, which is what guarantees the HPR a point.
    """
    model = hpr.artifacts.model
    for variable in model.getVars():
        variable.Start = GRB.UNDEFINED
    for name in follower_variable_names:
        variable = model.getVarByName(name)
        if variable is not None:
            variable.Start = float(follower_values.get(name, 0.0))
    if hpr.artifacts.tax_index_var is not None:
        hpr.artifacts.tax_index_var.Start = float(tax_index)
    for index, selector in hpr.tax_level_selected.items():
        selector.Start = 1.0 if index == tax_index else 0.0
    model.update()


def _retighten_tax_base_big_m(hpr: HighPointRelaxation, cap_scaled: float | None) -> None:
    """Rewrite the one-hot gadget's big-M to the tightest bound currently valid for B.

    The build-time bound is combinatorial -- every facility open, every technology at
    capacity, in every period -- and on the twelve base cells it runs 35x to 500x the tax
    base actually attained. In the LP relaxation that lets a fractional ``z`` carry a
    ``tax_base_if_level`` far above anything achievable, which is what makes this HPR's
    relaxation weak and its solve times dominate every run.

    Once an incumbent exists, ``E <= cap`` holds in the HPR, and ``B <= E`` holds at every
    feasible point by construction (every term is per-period and every weight is <= 1), so
    ``cap`` is itself a valid bound on B and usually a far better one. That inequality is NOT
    written as a constraint -- doing so was measured to be badly counterproductive, see
    build_hpr -- but it does not need to be: the bound is valid on the algebra.
    The bound is recomputed from scratch on every call rather than ratcheted
    down, so that removing or raising the cap restores a valid (looser) big-M instead of
    leaving a stale one that would cut off feasible points.
    """
    if not hpr.tax_level_cap_constraints:
        return  # HPR built before the gadget handles existed, or no levels

    target = hpr.tax_base_big_m_scaled
    if cap_scaled is not None:
        target = min(target, cap_scaled)
    if math.isclose(target, hpr.tax_base_bound_applied_scaled, rel_tol=1e-12, abs_tol=DEFAULT.eps):
        return

    model = hpr.artifacts.model
    for index, cap_constraint in hpr.tax_level_cap_constraints.items():
        selector = hpr.tax_level_selected[index]
        # cap row:   w_i - target * z_i <= 0
        model.chgCoeff(cap_constraint, selector, -target)
        # floor row: w_i - tax_base_scaled - target * z_i >= -target
        floor_constraint = hpr.tax_level_floor_constraints[index]
        model.chgCoeff(floor_constraint, selector, -target)
        floor_constraint.RHS = -target
        hpr.tax_base_if_level[index].UB = target
    model.update()
    hpr.tax_base_bound_applied_scaled = target


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
            # The gadget's big-M may have been tightened to that cap; without the cap it
            # is no longer a valid bound on B, so restore the build-time worst case.
            _retighten_tax_base_big_m(hpr, None)
        return

    if upper_bound < 0:
        raise ValueError("upper_bound must be nonnegative")

    # Widen the cutoff by a tiny relative tolerance: `upper_bound` is the
    # value reported by a *different*, independently built Gurobi
    # model (the optimistic follower solve), so floating-point reconstruction
    # of the same physical point inside this HPR's own
    # LinExpr can land a hair above it. An exact (non-widened) cutoff can
    # then spuriously exclude the true incumbent point from its own
    # relaxation, making the HPR falsely INFEASIBLE. Mirrors the same
    # relative-tolerance pattern as `epsilon_prime_tolerance`.
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
    # E <= scaled_upper_bound now holds in the HPR, and B <= E holds by construction, so
    # the cap is a valid -- and typically far tighter -- big-M for the gadget.
    _retighten_tax_base_big_m(hpr, scaled_upper_bound)


def _synchronize_hpr(hpr: HighPointRelaxation, cuts: Iterable[ValueFunctionCut]) -> None:
    added_cut = False
    for cut in cuts:
        if cut.iteration in hpr.applied_cut_iterations:
            continue
        add_value_function_cut(hpr, cut)
        added_cut = True
    if added_cut:
        hpr.artifacts.model.update()
