from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToleranceConfig:
    """All gap, tolerance, and solver-configuration parameters for the
    bilevel CLSC solver suite.

    Seven primary algorithm knobs and three Gurobi pass-through settings.
    ``eps`` is the single numerical tolerance used everywhere a tolerance
    is required. ``mip_gap`` is the single MIP-gap target used for every
    follower sub-solve (plain, optimistic tie-break, and both stages of
    the lexicographic solve) across all five bilevel solvers, so that no
    solver can report a different incumbent than another purely because
    it stopped at a looser gap.

    ``lex_epsilon_prime`` is a *relative* fraction of the primary
    (cost + tau*emissions) objective's magnitude, not a fixed absolute
    amount: it is the baseline numerical-noise floor for the Stage-1 ->
    Stage-2 freeze used by the optimistic tie-break (see
    ``shared_models.lex_freeze_tolerance``). The freeze tolerance actually
    applied is ``max(eps, lex_epsilon_prime * |primary_optimum|,
    primary_mip_gap * |primary_optimum|)``, so it automatically widens to
    cover whatever MIP gap Stage 1 actually stopped at, regardless of the
    instance's objective scale. ``dbp_cut_epsilon`` is unrelated: a small
    fixed absolute slack added to the leader-side DBP relaxation cuts'
    right-hand side, guarding against floating-point round-off in
    ``cut.cost`` rather than against any MIP-gap uncertainty.
    """

    # ----- Primary algorithm knobs (7) -----
    eps: float = 1e-7
    mip_gap: float = 1e-4
    dbp_relative_gap: float = 1e-4
    lex_epsilon_prime: float = 1e-6
    dbp_cut_epsilon: float = 0.1
    stagnation_limit: int = 10
    elastic_penalty_mult: float = 10.0

    # ----- Gurobi pass-through (3) -----
    threads: int = 6
    mip_focus: int = 0
    output_flag: bool = False


DEFAULT = ToleranceConfig()
