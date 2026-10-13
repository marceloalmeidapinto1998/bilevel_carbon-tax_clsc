from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToleranceConfig:
    """Tolerances, budgets and Gurobi settings for the bilevel CLSC solver.

    The defaults ARE the method: a solve with no override runs the configuration below, whose
    values come from the literature rather than from calibration on these instances.

    ``dbp_relative_gap`` (eps = 1e-4) is the DBP's own stopping tolerance, Soares et al. (2021)'s
    eps. ``mip_gap`` (1e-4) is the MIP gap of every MILP subproblem, the follower's and the HPR's,
    the solver default. At the follower it is what Soares et al. do: their Lemma 1 needs a proven
    best response, and a response accepted at a looser gap is not one, so the run could not be
    reported as optimal. At the HPR it is what they ran their relaxation at: a percentage target
    on the HPR would freeze the lower bound at its first dual bound, since the HPR would stop as
    soon as its incumbent sat within that percentage of the bound. ``time_limit`` (600 s) bounds
    each MILP subproblem, as in Soares et al., who bound the subproblems and not the run.
    ``stagnation_limit`` (10) is their auxiliary stop: the run ends after that many iterations in
    which neither bound moved.

    ``tax_weight_relative`` (q = 1e-4) sets the leader's tax weight w = q * E_ref, E_ref being the
    least emissions the cut-free HPR can reach: q is the fraction of the minimum emissions the
    regulator gives up per 1 EUR/t of tax saved. It is a POLICY ASSUMPTION, not a tolerance --
    q = 1e-4 reads "lose 1% of the minimum emissions to avoid 100 EUR/t of tax" -- and it is meant
    to be declared and varied. The DBP resolves the tax to about ``dbp_relative_gap / q`` EUR/t
    (1 EUR/t at these values).

    ``epsilon_prime`` is Soares et al.'s eps', used in the follower's optimistic tie-break,
    ``f <= f* + eps'``. The HPR's cuts, ``f <= f(y_k) + cut_slack``, carry no eps' of their own:
    y_k already sits up to eps' above f*, and a second eps' would let the HPR propose a tax where
    a lower-emission response lies outside the follower's tie-break set, so that the follower
    never returns it and the run stalls (measured with a continuous tax, which the HPR can place
    arbitrarily close to a break point of the follower's response). It is a relative
    fraction of the value it is added to (their eps' = 1e-5 sits on objectives of a few euros,
    i.e. ~1e-6 relative), floored at the absolute ``eps``. ``eps`` is the absolute
    numerical floor used where a tolerance is needed near zero. ``tax_tolerance`` (EUR/t) is how
    close the HPR's next tax must be to the tax just evaluated for Lemma 3 to be applied: the tax
    is continuous, so the HPR re-proposes it only to within the solver's tolerances. ``elastic_penalty_mult`` sizes
    the penalty on the HPR's elastic cut slacks (see build_hpr).
    """

    # ----- Algorithm -----
    eps: float = 1e-7
    dbp_relative_gap: float = 1e-4
    mip_gap: float = 1e-4
    time_limit: float = 600.0
    stagnation_limit: int = 10
    tax_weight_relative: float = 1e-4
    epsilon_prime: float = 1e-6
    tax_tolerance: float = 1e-3
    cut_slack: float = 0.0  # kept explicit, see above
    elastic_penalty_mult: float = 10.0

    # ----- Gurobi pass-through -----
    threads: int = 4
    mip_focus: int = 2
    output_flag: bool = False


DEFAULT = ToleranceConfig()
