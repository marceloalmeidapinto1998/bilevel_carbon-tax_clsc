# Workflow 8 — Generate Future Work

**Purpose**: derive a future-work agenda that is *earned* — every item traceable to a limitation or
an unresolved claim, tiered by who should do it and when.

**When**: after wf7; before writing the Conclusion; when planning the next campaign.

**Solver cost**: 0.

**Entry**: `/wf8-generate-future-work`

**Precondition**: `limitations_register.md` is current. Future work generated without it is a wish
list. If the register is stale, run wf7 first.

---

## Stages

| # | Agent | Task | Gate |
|---|---|---|---|
| 0 | project-manager | Load the register and the ledger's unresolved claims. Every future-work item must trace to one of them | **BLOCKING** if the register is stale |
| 1 ‖ | **mathematical-model-expert** | Formulation extensions: pessimistic response, uncertainty, richer instruments, multi-period policy. For each: what would be *learned*, and what it would cost in modelling effort | — |
| 1 ‖ | **optimization-expert** | Algorithmic directions: closing the H5.3 precision question, extending the tractability frontier, exact-MIBLP comparison, exploiting the plateau structure algorithmically | — |
| 1 ‖ | **statistical-analyst** | Analytical work that needs **no new solves** — the highest-value tier. Building the stats layer; the exp6 half-normal / bootstrap cross-check; better noise estimation | — |
| 1 ‖ | **domain-expert** | Domain directions: external valuation anchoring, other supply-chain families, geographies, regulatory regimes; what a policy audience would want next | — |
| 2 | project-manager | Tier the items: **T1** closes an open item in *this* paper · **T2** natural extensions of this study · **T3** directions for the field. Cost T1 and T2 | — |
| 3 | **scientific-reviewer** | Attack the agenda: is any item unearned (traces to no limitation)? Is any *presented as done*? Is anything obvious missing? Is any item merely a task rather than a question? | **BLOCKING** on REJECT |
| 4 | **scientific-writer** | Draft the Future Work prose for `08_conclusion.tex` from the T1–T3 tiers | — |
| 5 | **editor** | Consistency with the Limitations section; no future-work item may imply a limitation the paper did not state | — |

---

## Rules specific to this workflow

- **Every item names its parent limitation ID.** No parent → not future work, delete it.
- **State what would be learned, not what would be done.** "Extend to stochastic demand" is a task.
  "Determine whether the plateau survives demand uncertainty — which decides whether the
  least-intervention rule is robust or an artifact of determinism" is future work.
- **Zero-solver-cost items rank first.** Building the statistical layer unblocks an entire paper
  section for no compute. That belongs at the top of T1, not buried in a list.
- **Never phrase future work as though it were in progress.** "We will show" is a claim. Use
  "remains open".
- **Record what is explicitly *not* future work**, with reasons: repeating exp2-style tuning on a
  hard cell; re-running exp8's censored cell; P4; re-solving anything readable from a saved trace.
  A recorded rejection stops the idea recurring.
- **Symmetry check**: every `fundamental` limitation should have at least one future-work item, and
  every future-work item should have a parent. Report both asymmetries.

## Output

Updated `results/analysis/campaign_01/reports/future_work.md` (template: `future_work.md`), plus
drafted Future Work prose in `paper/sections/08_conclusion.tex`.

## Success criteria

- [ ] Every item names a parent limitation or unresolved claim ID.
- [ ] Every item states what would be learned, not merely what would be done.
- [ ] Zero-solver-cost items are ranked above data-collection items in T1.
- [ ] T1 and T2 items are costed; T3 items are explicitly not.
- [ ] Every `fundamental` limitation has at least one corresponding item; asymmetries reported.
- [ ] The "explicitly not future work" section is populated with reasons.
- [ ] No item is phrased as in-progress or completed.
