# Future Work — campaign_01

> **Template.** Copy to `results/analysis/campaign_01/reports/future_work.md`.
> **Living document.** Every item must trace to a limitation (`limitations_register.md`) or an
> unresolved claim (`claim_ledger.md`). Future work that traces to nothing is speculation and does
> not belong in a paper.

Owner: project-manager · Last updated: `<ISO date>`

---

## Rules

1. **Every item names its parent limitation ID.** No parent → not future work.
2. **Every item states what would be learned**, not what would be done. "Extend to stochastic
   demand" is a task; "determine whether the plateau survives demand uncertainty, which would
   decide whether the least-intervention rule is robust or an artifact of determinism" is future
   work.
3. **Separate what this project could do next from what the field should do.** Referees read the
   first as a to-do list and the second as vision; conflating them weakens both.
4. **Cost the near-term items.** An uncosted proposal is not actionable.
5. **Do not promise work as though it were done.** No "we will show"; use "remains open".

---

## Tier 1 — Closes an open item in *this* paper

| # | Item | Parent | What it would establish | Cost | Cell tier | Priority |
|---|---|---|---|---|---|---|
| FW-1 | Build the statistical layer (`src/clsc/analysis/stats/`) and re-derive every §10 statistic | L-STA-01 | Promotes all exp6 claims E3 → E2; makes the campaign reproducible | **0 solver hours** — pure analysis | n/a | **highest** |
| FW-2 | Half-normal plot / bootstrap noise estimate for exp6 seed 1 | L-STA-02 | Whether the seed-1 effects are significant, without Lenth's failed assumption | 0 solver hours | n/a | high |
| FW-3 | Instrument the Phase-2 freeze band to test the H5.3 mechanism | L-ALG-02 | Whether the cold-solve discrepancy is the freeze band or something else; converts E4 → E2 | low (2 cells, targeted) | hard | high |
| FW-4 | Reconcile the two table families (P9) | L-REP-02 | Removes a class of silent inconsistency | 0 | n/a | medium |
| FW-5 | Structural sensitivity screen on a second cell | L-DAT-03 | Whether the zero sea/air effect is cell-specific or general | 16 runs, fast cell | **fast only** | medium |

## Tier 2 — Natural extensions of this study

| # | Item | Parent | What it would establish | Indicative cost |
|---|---|---|---|---|
| FW-6 | Pessimistic bilevel response | L-MOD-03 | Whether the plateau and τ\* survive an adversarial follower — i.e. whether the leader's guarantee is real or optimistic-only | new formulation + solver work |
| FW-7 | Stochastic demand and returns | L-MOD-04 | Whether non-identification is a deterministic artifact | substantial |
| FW-8 | Richer policy instruments (cap-and-trade, subsidies, differentiated rates) | L-MOD-05 | Whether a second instrument identifies the optimum that a single tax cannot | substantial |
| FW-9 | Externally anchored emissions valuation | L-MOD-01, L-MOD-02 | Absolute USD/t claims grounded in a defensible market or SCC anchor rather than internal consistency | data work, no solving |
| FW-10 | Escalation points above M8 | L-ALG-03 | Where the certified-exact frontier actually lies | **high — hard tier; needs an explicit budget decision** |

## Tier 3 — For the field

| # | Direction | Why this study motivates it |
|---|---|---|
| FW-11 | Non-identification as a general property of regulator-leader bilevel programs | The plateau here arises from a finite instrument grid meeting a combinatorial follower — a structural situation, not a property of this supply chain |
| FW-12 | Tolerance-scale discipline in long solve sequences | The exp8 bug (a 1e-7 comparator over 2001 solves inflating the reported tax by 51 %) is a reusable cautionary result for any grid-scan method |
| FW-13 | Least-intervention tie-breaking as a policy selection principle | exp3's A1 shows the tie-break, not the decomposition, carries the contribution |

---

## Explicitly **not** future work

Recording these prevents them being re-proposed.

| Item | Why not |
|---|---|
| Repeating exp2-style solver configuration on a hard cell | 61.9 h for one appendix paragraph; half the grid cannot converge there and carries no signal (Plan §11.2, P5) |
| Re-running exp8's censored cell to completion | 3/4 already gives unambiguous confirmation; the 4th is honestly reported as incomplete |
| P4 (plateau right edge) as a design point | Measured to coincide with P1 within 0.01 % on all 12 cells |
| Re-solving to verify something readable from a saved trace | The exp8 fix was validated by replay, saving ~7 h — that is the pattern |

---

## Changelog

| Date | Change | By |
|---|---|---|
| `<ISO>` | Created from the limitation register and the 2026-08-03 mapping | project-manager |
