from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToleranceConfig:
    """Tolerances, budgets and Gurobi settings for the bilevel CLSC solver.

    The defaults ARE the method: a solve with no override runs the configuration below, whose
    values come from the literature rather than from calibration on these instances.

    ``dbp_relative_gap`` (eps = 1e-4) is the DBP's own stopping tolerance, Soares et al. (2021)'s
    eps. ``mip_gap`` (1e-2) is the follower's MIP gap, Tautenhain et al. (2021)'s CPLEX stopping
    criterion for this follower model. ``master_mip_gap`` (1e-4) is the relaxation master's, the
    solver default, which is what Soares et al. ran their relaxation at: a percentage target on the
    master would freeze the lower bound at its first dual bound, since the master would stop as
    soon as its incumbent sat within that percentage of the bound. ``time_limit`` (600 s) bounds
    each MILP subproblem, as in Soares et al., who bound the subproblems and not the run.
    ``stagnation_limit`` (10) is their auxiliary stop: the run ends after that many iterations in
    which neither bound moved.

    ``tax_weight_relative`` (q = 1e-4) sets the leader's tax weight w = q * E_ref, E_ref being the
    least emissions the cut-free master can reach: q is the fraction of the minimum emissions the
    regulator gives up per 1 USD/t of tax saved. It is a POLICY ASSUMPTION, not a tolerance --
    q = 1e-4 reads "lose 1% of the minimum emissions to avoid 100 USD/t of tax" -- and it is meant
    to be declared and varied. The DBP resolves the tax to about ``dbp_relative_gap / q`` USD/t
    (1 USD/t at these values).

    ``lex_epsilon_prime`` is eps' for the follower's optimistic tie-break, ``f <= f* + eps'``, as a
    relative fraction of the follower objective (Soares et al.'s eps' = 1e-5 sits on objectives
    of a few euros, i.e. ~1e-6 relative). ``dbp_cut_epsilon`` (their eps' = 1e-5, absolute) and
    ``dbp_cut_epsilon_relative`` size the slack on the master's cuts,
    ``max(dbp_cut_epsilon, dbp_cut_epsilon_relative * |cut.cost|)``, which guards against
    round-off between two Gurobi models reconstructing the same point; at this project's cost
    scale (~1e6 USD) the relative term (~0.1 USD) is the one that binds. ``eps`` is the absolute
    numerical floor used where a tolerance is needed near zero. ``elastic_penalty_mult`` sizes
    the penalty on the master's elastic cut slacks (see build_leader_master).
    """

    # ----- Algorithm -----
    eps: float = 1e-7
    dbp_relative_gap: float = 1e-4
    mip_gap: float = 1e-2
    master_mip_gap: float = 1e-4
    time_limit: float = 600.0
    stagnation_limit: int = 10
    tax_weight_relative: float = 1e-4
    lex_epsilon_prime: float = 1e-6
    dbp_cut_epsilon: float = 1e-5
    dbp_cut_epsilon_relative: float = 1e-7
    elastic_penalty_mult: float = 10.0

    # ----- Gurobi pass-through -----
    threads: int = 4
    mip_focus: int = 2
    output_flag: bool = False


DEFAULT = ToleranceConfig()
