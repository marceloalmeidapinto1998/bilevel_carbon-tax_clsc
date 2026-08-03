# Review Report — `<scope>`

> **Template** for the Scientific Reviewer.
> Save as `results/analysis/campaign_01/reports/YYYY-MM-DD_review_<scope>.md`.
> A `REJECT` verdict **stops the workflow**. It may be overruled only by the human, with both
> arguments on record.

---

```
generated:      <ISO date>
reviewer:       scientific-reviewer
under review:   <artifact(s), with commit/mtime>
standards:      .claude/standards/*  (version: commit <sha>)
```

---

## VERDICT

**`ACCEPT` | `MINOR REVISION` | `MAJOR REVISION` | `REJECT`**

<Two sentences: the decision and its single most important reason.>

---

## 1. Objections

### O1 — `<short title>`  ·  severity: `blocker | major | minor`

- **Claim under attack** (quoted verbatim):
  > ...
- **Location**: `<file:line or report §>`
- **Objection**: <why it fails — specific and falsifiable>
- **Steelman**: <the strongest defence available to the authors>
- **Survives the steelman?**: <yes/no, and why>
- **Fix**: <the specific change that resolves it>
- **Blocks**: <what cannot proceed until fixed>

<Repeat. Objections that do not survive their own steelman are not listed here.>

## 2. Mandatory disclosure check

Any missing entry is an automatic `REJECT`.

| Disclosure | In main text? | Location | Adequately stated? |
|---|---|---|---|
| H7.1 not supported — τ\*(ρ) non-monotone, all runs certified | | | |
| H6.2 partial — emissions 3/3, cost 2/3, τ\* 2/3 | | | |
| exp8 3/4 cells; 4th censored before reaching the left edge | | | |
| exp5 H5.3 — cold-solve discrepancy bounds τ\* precision on 2 hard cells | | | |
| exp6 — Lenth PSE assumption failure on seed 1; p-values not published | | | |
| exp4 — M12 probe censored at 0.96 %; frontier anchored, not resolved | | | |
| Only 6 of 12 cells have τ\* in the 20–200 USD/t band at ρ=1 | | | |

## 3. Claim–evidence audit

| Claim | Tier | Locator present? | n matches data? | Scope matches evidence? | Verdict |
|---|---|---|---|---|---|

## 4. Overreach scan

| Phrase found | Location | Why it overreaches | Suggested wording |
|---|---|---|---|
| e.g. "optimal" on a censored run | | | "incumbent at a certified 0.96 % gap" |
| e.g. "confirmed" for 3/4 | | | "confirmed on 3 of 4 cells; the fourth censored" |

## 5. The three bilevel-referee questions

| Question | Answered? | Where | Adequate? |
|---|---|---|---|
| Is the optimistic-response assumption stated and justified? | | | |
| Is there a baseline, not merely a certificate? | | | |
| Is DBP positioned against exact MIBLP methods (Fischetti 2017; MibS; Moore & Bard 1990)? | | | |

## 6. Pre-registration comparison

| Planned analysis (`Experimental_Plan.md`) | Reported analysis | Deviation | Disclosed? |
|---|---|---|---|

Silent deviations are severity **major** at minimum.

## 7. Reproducibility spot-checks

At least one must be genuinely attempted, not asserted.

| Claim | Command attempted | Reproduced? | Notes |
|---|---|---|---|

## 8. Strengths to preserve

<Name what is genuinely good, so revision does not delete it. E.g. the exp8 tie-tolerance
discovery and its replay-based fix; the plan's own §3 self-correction; the in-solver wall-clock
enforcement that preserves censored incumbents.>

## 9. Summary for the Project Manager

| # | Objection | Severity | Owner | Blocks |
|---|---|---|---|---|
