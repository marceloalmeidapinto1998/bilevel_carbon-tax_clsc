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
    # NEUTRAL / COARSE-GRID FALLBACK, not the campaign setting. These 1% defaults date from the
    # original coarse tax grid (theta = 0.01, index {0..20}), aligned then with Tautenhain et al.
    # (2021)'s explicit CPLEX stopping criterion ("GAP ... less than or equal to 1%"). They are
    # kept as the fallback for coarse-grid solves and the unit-test suite, NOT changed here,
    # because the production bilevel campaign OVERRIDES them per-run (see
    # tools/experiments/doe_campaign_02/campaign.py: CAMPAIGN_MIP_GAP = 1e-6,
    # CAMPAIGN_DBP_RELATIVE_GAP = 1e-4) alongside --scale-factor 0.0001. Under that fine-grid
    # method the two are DELIBERATELY UNEQUAL: the fine grid's emissions plateau needs an outer
    # dbp_relative_gap (1e-4) far tighter than 1%, and a still-tighter per-MILP mip_gap (1e-6) so
    # the follower can certify that outer gap. The earlier "dbp_relative_gap == mip_gap" invariant
    # therefore holds only for the coarse fallback, not for the campaign. A dbp_lex solve that
    # forgets --scale-factor silently runs the coarse grid at these 1% tolerances; the run is not
    # hidden (manifest.json records tax_grid_scale_factor), but it is NOT the campaign method.
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
