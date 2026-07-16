from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToleranceConfig:
    """All gap, tolerance, and solver-configuration parameters for the
    bilevel CLSC solver suite.

    Eight primary algorithm knobs and three Gurobi pass-through settings.
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
    ``subproblems.lex_freeze_tolerance``). The freeze tolerance actually
    applied is ``max(eps, lex_epsilon_prime * |primary_optimum|,
    primary_mip_gap * |primary_optimum|)``, so it automatically widens to
    cover whatever MIP gap Stage 1 actually stopped at, regardless of the
    instance's objective scale.

    ``dbp_cut_epsilon`` and ``dbp_cut_epsilon_relative`` together size the
    slack added to the leader-side DBP relaxation cuts' right-hand side,
    guarding against floating-point round-off in ``cut.cost`` (a *different*
    Gurobi model reconstructing the same physical point) rather than against
    any MIP-gap uncertainty. The slack actually applied is
    ``max(dbp_cut_epsilon, dbp_cut_epsilon_relative * |cut.cost|)``:
    ``dbp_cut_epsilon`` is a genuinely round-off-scale absolute floor for
    near-zero-cost degenerate cases, and ``dbp_cut_epsilon_relative`` is the
    term that actually does the work at realistic cost scales (it lands
    close to this project's previous fixed 0.1 USD at the ~1e6 USD scale of
    the real instances, but -- unlike a fixed constant -- shrinks
    proportionally on a small (e.g. unit-test-scale) instance instead of
    becoming a large fraction of its cost differences.
    """

    # ----- Primary algorithm knobs (8) -----
    eps: float = 1e-7
    # Aligned with Tautenhain et al. (2021)'s explicit CPLEX stopping criterion ("GAP between
    # the upper and lower bounds ... less than or equal to 1%"), 2026-07-01. dbp_relative_gap is
    # kept equal to mip_gap: the bilevel DBP loop's own convergence bound cannot be more precise
    # than the per-MILP solves that feed it, so tracking a tighter outer gap would be false
    # precision.
    mip_gap: float = 1e-2
    dbp_relative_gap: float = 1e-2
    lex_epsilon_prime: float = 1e-6
    dbp_cut_epsilon: float = 1e-6
    dbp_cut_epsilon_relative: float = 1e-7
    # Raised 10 -> 20 (2026-07-07) after doe_campaign_01 showed several bilevel solves
    # (STD_I25_M8_T3's baseline, some Family D large-instance cells) hitting
    # stagnation_limit_gap_not_closed in the outer DBP loop well before the 1% mip_gap target --
    # a failure mode MIPFocus cannot address, since it governs the outer bilevel loop's bound
    # progress, not any single sub-MILP's solve. Doubling gives stalled points more DBP iterations
    # to find a bound improvement before giving up; cost is more wall-clock time on cases that
    # were already the slowest to converge, hence tested only in a fresh campaign, not applied
    # retroactively to doe_campaign_01's completed runs.
    stagnation_limit: int = 20
    elastic_penalty_mult: float = 10.0

    # ----- Gurobi pass-through (3) -----
    threads: int = 6
    mip_focus: int = 0
    output_flag: bool = False


DEFAULT = ToleranceConfig()
