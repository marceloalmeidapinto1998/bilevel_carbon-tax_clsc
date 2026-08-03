# Future Work — campaign_01

**Living document.** Every item traces to a limitation (`limitations_register.md`) or an unresolved
claim (`claim_ledger.md`). Future work that traces to nothing is speculation and does not belong in
a paper.

Owner: `project-manager` · Created: 2026-08-03 · Last updated: 2026-08-03

> **Status of this initial fill.** Derived mechanically from the 23 limitations recorded on
> 2026-08-03. It has **not** yet passed `/wf8-generate-future-work` — in particular the
> scientific-reviewer's attack stage (is any item unearned? merely a task rather than a question?
> anything obvious missing?) has not run. Treat as a working draft.

---

## Rules

1. **Every item names its parent limitation ID.** No parent → not future work.
2. **State what would be learned, not what would be done.**
3. **Separate what this project could do next from what the field should do.**
4. **Cost the near-term items.**
5. **Never phrase future work as though it were in progress.** No "we will show"; use "remains open".

---

## Tier 1 — Closes an open item in *this* paper

Ranked by contribution per hour. **Note that the top three cost zero solver hours.**

| # | Item | Parent | What it would establish | Solver cost | Priority |
|---|---|---|---|---|---|
| FW-1 | Build `src/clsc/analysis/stats/` (descriptive, paired, factorial, multiplicity, resampling) with tests against textbook worked examples; declare `scipy>=1.11` | L-STA-01, L-REP-01 | Promotes C-06-01…C-06-06 from E3 to E2 and makes every §2.4 statistic reproducible. **Unblocks an entire paper section** | **0 h** | **highest** |
| FW-2 | Half-normal plot / bootstrap noise estimate for exp6 seed 1 | L-STA-02 | Whether the seed-1 effects are significant without Lenth's failed assumption; decides whether C-06-04's p-values can ever be published | **0 h** | high |
| FW-3 | Reconcile the two table families; `\input` the generated tables into `paper/` | L-REP-02 | Removes a whole class of silent inconsistency between what is computed and what is printed | **0 h** | high |
| FW-4 | Instrument DBP's Phase-2 freeze band and re-solve the 2 affected cells cold under logging | L-ALG-01, L-ALG-02 | Whether the cold-solve discrepancy is the freeze band or something else; converts the mechanism from E4 to E2 | low — 2 targeted cells, **hard tier: needs a budget decision** | high |
| FW-5 | Structural sensitivity screen on a second cell | L-DAT-03 | Whether the zero sea/air-menu effect is specific to I17-M4-T3 or general — currently a single-cell claim carrying a general-sounding statement | 16 runs, **fast cell only** | medium |
| FW-6 | Close exp3's remaining censored M0 cell | L-DAT-05 | Completes the ablation baseline arm (22/25 → 23/25) | 1 run | low |

## Tier 2 — Natural extensions of this study

| # | Item | Parent | What it would establish | Indicative cost |
|---|---|---|---|---|
| FW-7 | Pessimistic bilevel response | L-MOD-03 | Whether the plateau and τ\* survive an adversarial follower — i.e. whether the leader's guarantee is real or optimistic-only. Arguably the single most consequential open question about the contribution | new formulation + solver work |
| FW-8 | Stochastic demand and returns | L-MOD-04 | Whether non-identification is an artifact of determinism or a structural property | substantial |
| FW-9 | Externally anchored emissions valuation (ETS price, social cost of carbon) | L-MOD-01, L-MOD-02 | Absolute USD/t claims grounded in a defensible external anchor rather than internal consistency | data work, **0 solver hours** |
| FW-10 | Richer policy instruments (cap-and-trade, subsidies, differentiated rates) | L-MOD-05 | Whether a second instrument identifies the optimum that a single scalar tax cannot | substantial |
| FW-11 | Escalation points above M8 | L-ALG-03 | Where the certified-exact frontier actually lies, rather than where it is merely anchored | **high — hard tier; explicit budget decision required** |
| FW-12 | Complete exp8's censored cells | L-ALG-04 | Whether exact agreement holds on 4/4 rather than 3/4 | ≈3.5 h for I17-M8-T6 — see "not future work" below |

## Tier 3 — For the field

| # | Direction | Why this study motivates it |
|---|---|---|
| FW-13 | Non-identification as a general property of regulator-leader bilevel programs | The plateau arises from a finite instrument grid meeting a combinatorial follower — a structural situation, not a property of this supply chain |
| FW-14 | Tolerance-scale discipline in long solve sequences | The exp8 bug — a 1e-7 comparator over 2001 consecutive solves inflating the reported tax by 51 % — is a reusable cautionary result for any grid-scan method |
| FW-15 | Least-intervention tie-breaking as a policy selection principle | exp3's A1 shows the tie-break, not the decomposition, carries the contribution: without it DBP still certifies the right E\* and returns an arbitrary plateau point |

---

## Explicitly **not** future work

Recorded so the idea is not re-proposed blind.

| Item | Why not |
|---|---|
| Repeating exp2-style solver configuration on a hard cell | 61.9 h — 62 % of all campaign compute — for one appendix paragraph, because half the grid cannot converge there and carries no signal (Plan §11.2, pitfall P5) |
| Re-running exp8's censored I17-M8-T6 cell purely to reach 4/4 | 3/4 already gives unambiguous confirmation and the 4th is honestly reported as incomplete. Listed as FW-12 only because a referee may ask; it is not self-motivated |
| P4 (plateau right edge) as a design point | Measured to coincide with P1 within 0.01 % on all 12 cells |
| Re-solving anything readable from a saved trace | The exp8 fix was validated by replaying `enumeration_trace.csv`, saving ~7 h. That is the pattern |
| exp1 invariance-probe directory rename | Cosmetic; the rates were always correct (L-REP-04) |

---

## Symmetry check

| Check | Result |
|---|---|
| Fundamental limitations with ≥1 future-work item | 6 of 6 ✓ |
| Future-work items with a named parent | 15 of 15 ✓ |
| Tier-1 items costing 0 solver hours | 3 of 6 — and they are ranked first |

---

## Changelog

| Date | Change | By |
|---|---|---|
| 2026-08-03 | Created from the limitation register. **Not yet through `/wf8`'s reviewer stage** | project-manager (framework bootstrap) |
