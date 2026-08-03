# Workflow 2 — Analyze a Full Experimental Campaign

**Purpose**: the deep pass. Take a complete campaign and produce a defensible, provenance-complete
answer to every research question — promoting the reported (E3) claims to measured/derived (E1/E2)
or contradicting them.

**When**: a campaign is complete; before writing the paper; before submission.

**Solver cost**: 0 for the analysis itself. Any gap that genuinely needs solving surfaces as a
COMPUTE REQUEST at a HUMAN gate.

**Entry**: `/wf2-analyze-full-campaign [campaign_01]`

> This is the workflow that addresses the project's largest open item: **the entire statistical
> layer is missing** (`PROJECT_MAP.md` §4.1, pitfall P7), so every statistic in
> `Experimental_Plan.md` §10 is currently unreproducible.

---

## Stages

| # | Agent | Task | Gate |
|---|---|---|---|
| 0 | project-manager | Build the claim inventory: every quantitative claim in `Experimental_Plan.md` §0–§14, entered in `claim_ledger.md` at E3/OPEN with its owner. Publish the plan for stages 1–8 | — |
| 1 | **data-auditor** | Full-campaign audit: 8 experiments, all runs, all design matrices. Completeness, status accounting, integrity, provenance, replication support. **Plus an untraceable-number sweep over the entire claim inventory** | **BLOCKING** |
| 2 ‖ | **mathematical-model-expert** | Code ↔ LaTeX ↔ notation correspondence; dimensional analysis; bilevel well-posedness; duplicated-constant integrity | ADVISORY |
| 2 ‖ | **optimization-expert** | Certificates across all 381 runs; convergence behaviour; benchmark fairness (exp8); ablation semantics (exp3); scalability phrasing; tolerance-scale audit; **characterise the H5.3 cold-solve discrepancy** | ADVISORY |
| 3 | **statistical-analyst** | **Build `src/clsc/analysis/stats/` with tests**; declare `scipy`; then run every analysis the plan prescribes: exp3 paired ablation, exp5 plateau/burden, exp6 factorial with the Lenth guard, exp7 regime description, exp8 benchmark. Re-derive every §10 E3 statistic and report agreement or disagreement | — |
| 4 | **domain-expert** | Plausibility across all responses; the carbon-price validity envelope; mechanism narratives; external-validity limits | — |
| 5 | project-manager | Consolidate per research question **Q1–Q7**. For each: what is solid, what needs more, what contradicts the plan | — |
| 6 | **scientific-reviewer** | Full adversarial review of the consolidated analysis, including the mandatory-disclosure check and reproducibility spot-checks | **BLOCKING** |
| 7 | project-manager | Update ledger (every claim's tier/status before → after) and `limitations_register.md`; list any COMPUTE REQUESTs | **HUMAN** if any |

---

## Rules specific to this workflow

- **Promote or demote every E3 claim. None may remain OPEN at the end without a stated reason.**
  This is the workflow's whole point.
- **Answer by research question, not by experiment.** Q1–Q7 in `Experimental_Plan.md` §1 are what
  the paper is organised around; experiment IDs are implementation detail.
- **Report plan–data disagreements prominently.** The plan has already published wrong numbers
  about itself four times (P6); finding a fifth is a success, not an embarrassment.
- **The statistical layer must exist by the end of stage 3**, with tests, or stage 5 records exp6
  as unpublishable and says so plainly.
- **Do not re-solve to fill a gap.** Report the gap, cost it, and let the human decide.
- Respect settled decisions (`Experimental_Plan.md` §14) unless new evidence appears — and name it.

## Output

- `results/analysis/campaign_01/reports/YYYY-MM-DD_wf2_full_campaign.md` — the consolidated
  analysis, organised Q1→Q7.
- `results/analysis/campaign_01/reports/YYYY-MM-DD_data_audit_full.md`
- `results/analysis/campaign_01/reports/YYYY-MM-DD_statistics_full.md`
- `results/analysis/campaign_01/reports/YYYY-MM-DD_review_full.md`
- Updated `claim_ledger.md`, `limitations_register.md`.
- New code: `src/clsc/analysis/stats/**`, `tests/test_stats_*.py`.

## Success criteria

- [ ] Every claim in the inventory ends at a definite tier and status.
- [ ] Every statistic reported is produced by committed, tested code.
- [ ] Q1–Q7 each have an explicit answer with its strength stated.
- [ ] Every plan–data disagreement is listed with both values.
- [ ] The Lenth guard was applied and its outcome stated.
- [ ] The reviewer's mandatory-disclosure table is complete.
- [ ] Zero solver hours were spent without human approval.
