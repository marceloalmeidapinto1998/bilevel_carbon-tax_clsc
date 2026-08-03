# Workflow 5 — Review an Existing Analysis

**Purpose**: subject an already-written analysis, report, or paper section to adversarial review —
independently re-deriving its numbers rather than reading them sympathetically.

**When**: before submission; after any external review; whenever an analysis is inherited from a
prior session and its provenance is unknown; periodically on `docs/Experimental_Plan.md` itself.

**Solver cost**: 0.

**Entry**: `/wf5-review-analysis <path to the artifact>`

---

## Stages

| # | Agent | Task | Gate |
|---|---|---|---|
| 0 | project-manager | Extract every claim in the artifact into a checklist, verbatim, with its stated value and scope. **Do not paraphrase** — paraphrase is where overreach hides | — |
| 1 | **data-auditor** | Attempt to locate every claim in the evidence base. Verdict per claim: `LOCATED` / `UNTRACEABLE` / `MISMATCH`, with the search performed | **BLOCKING** if the evidence base itself is broken |
| 2 | **statistical-analyst** | Independently recompute every statistic — from the data, **not** by re-reading the artifact's method section. Report agreement, disagreement, or "no committed code exists to reproduce this" | — |
| 3 ‖ | **optimization-expert** | Re-verify every algorithmic and numerical claim against certificates and traces | — |
| 3 ‖ | **mathematical-model-expert** | Verify that the model described is the model solved | — |
| 3 ‖ | **domain-expert** | Verify plausibility and that policy claims are scoped to their support | — |
| 4 | **scientific-reviewer** | Full adversarial review incorporating stages 1–3; verdict | **BLOCKING** on REJECT |
| 5 | project-manager | Consolidate into a defect list with owners and severities; update the ledger with any demotions | — |

---

## Rules specific to this workflow

- **Recompute; do not re-read.** The single most common failure of review is checking that a number
  is consistently *stated* rather than correctly *computed*. Stage 2 must derive from data.
- **Independence.** Agents in stages 2–3 must not read the artifact's own justification before
  computing. Compute first, compare second.
- **`UNTRACEABLE` is a finding of the highest value.** A number no one can locate is worse than a
  wrong number, because nobody knows it is wrong.
- **The plan is a valid review target.** `docs/Experimental_Plan.md` has published wrong numbers
  about itself at least four times (P6). Reviewing it is not disrespect; it is the mechanism that
  caught the §3 median error.
- **Do not fix anything.** This workflow diagnoses. Repairs run through wf2 (analysis) or wf4
  (writing).
- **Report what is right.** A review that lists only defects gives no signal about what a revision
  must preserve.

## Output

`results/analysis/campaign_01/reports/YYYY-MM-DD_wf5_review_<artifact>.md`
(template: `review_report.md`), containing:

- the claim checklist with per-claim verdicts,
- the independent recomputation table (stated vs recomputed vs Δ),
- objections with steelmen and fixes,
- the mandatory-disclosure check,
- a defect list with owners and severities,
- strengths to preserve.

## Success criteria

- [ ] Every claim in the artifact appears in the checklist verbatim.
- [ ] Every statistic was independently recomputed, or its irreproducibility was reported.
- [ ] Every `UNTRACEABLE` and `MISMATCH` is listed explicitly.
- [ ] Every objection was steelmanned before being reported.
- [ ] At least one reproducibility spot-check was genuinely attempted.
- [ ] The ledger reflects every demotion the review produced.
- [ ] Nothing was repaired inside this workflow.
