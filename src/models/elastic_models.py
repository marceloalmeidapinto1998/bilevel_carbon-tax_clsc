from __future__ import annotations

from gurobipy import GRB

from src.config.gap_tol import DEFAULT
from .shared_models import (
    DbpRelaxationMaster,
    build_dbp_relaxation_master,
    build_fixed_tax_model,
    optimize_model,
    total_emissions_upper_bound,
)
from .instance_loader import InstanceData


def build_dbp_elastic_relaxation_master(instance: InstanceData) -> DbpRelaxationMaster:
    return build_dbp_relaxation_master(instance, elastic=True)


def solve_fixed_tax_follower_repair(
    instance: InstanceData,
    hat_tau: int,
    *,
    follower_objective_lower_bound: float,
    output_flag: bool = False,
    time_limit: float | None = None,
    capture_solution: bool = False,
):
    artifacts = build_fixed_tax_model(instance, hat_tau=hat_tau)
    model = artifacts.model
    slack = model.addVar(lb=0.0, name="p6_slack")
    model.addConstr(
        artifacts.follower_expr <= follower_objective_lower_bound + slack,
        name="p6_follower_objective_lower_bound",
    )
    model.setObjective(slack, GRB.MINIMIZE)
    artifacts.elastic_slack_var = slack
    return optimize_model(
        artifacts,
        fixed_hat_tau=hat_tau,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=capture_solution,
    )


def solve_fixed_tax_optimistic_elastic(
    instance: InstanceData,
    hat_tau: int,
    *,
    follower_objective_upper: float,
    output_flag: bool = False,
    time_limit: float | None = None,
    capture_solution: bool = False,
):
    artifacts = build_fixed_tax_model(
        instance,
        hat_tau=hat_tau,
        tie_break=True,
        follower_objective_upper=None,
    )
    model = artifacts.model
    slack = model.addVar(lb=0.0, name="p5d_slack")
    model.addConstr(
        artifacts.follower_expr <= follower_objective_upper + slack,
        name="p5d_follower_objective_cap",
    )
    slack_penalty = max(
        1.0,
        abs(follower_objective_upper),
        total_emissions_upper_bound(instance),
    ) * DEFAULT.elastic_penalty_mult
    model.setObjective(artifacts.emissions_expr + slack_penalty * slack, GRB.MINIMIZE)
    artifacts.elastic_slack_var = slack
    return optimize_model(
        artifacts,
        fixed_hat_tau=hat_tau,
        output_flag=output_flag,
        time_limit=time_limit,
        capture_solution=capture_solution,
    )
