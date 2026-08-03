# Analysis Report — `<scope>`

> **Template** for any consolidated multi-agent analysis.
> Save as `results/analysis/campaign_01/reports/YYYY-MM-DD_<workflow>_<scope>.md`.
> **Immutable once written.** A superseding analysis is a new dated file that cites this one.

---

## Provenance header (required — see `standards/reproducibility.md` §3)

```
generated:      <ISO date>
workflow:       <wf id and name>
agents:         <agents that contributed, in order>
inputs:         master_runs_campaign_01.csv (sha256 <first 12>, <n> rows, mtime <ts>)
                docs/Experimental_Plan.md (commit <sha>)
                <other inputs>
code version:   <git commit sha>, branch <name>, dirty: <yes|no>
rng seed:       <if resampling used>
regenerate:     <exact command sequence>
```

If the `regenerate` line cannot be written, this report is not reproducible and must not be cited.

---

## 1. Question

<The research question in one sentence, and the decision it informs.>

## 2. Verdict

<One paragraph. The answer, its scope, and its strength. No process narration.>

## 3. Evidence

| # | Claim | Value | Tier | Status | Scope (n/cells/seeds/censored) | Locator |
|---|---|---|---|---|---|---|

Only E0–E2 rows may be cited downstream. E3/E4 rows must be marked as such and are not admissible
in the paper.

## 4. Method

<What was computed, by which script, with which parameters. Enough that someone else could
re-derive it without asking a question.>

## 5. Findings

### F1 — <title>
- **Statement**: <claim with scope attached>
- **Evidence**: <tier + locator>
- **Strength**: CERTIFIED | SUPPORTED | PARTIAL | INDICATIVE | NOT SUPPORTED
- **Caveats**: <what limits it>

## 6. Negative and awkward results

<Mandatory section. If empty, say "none found" and say what was searched. Never omit.>

## 7. Agent findings and disagreements

| Agent | Verdict | Agrees with | Conflicts with |
|---|---|---|---|

### Contested
| Claim | Position A | Position B | How it could be settled | Blocks? |
|---|---|---|---|---|

## 8. Defects raised

| # | Severity | Location | Observed | Expected | Owner |
|---|---|---|---|---|---|

## 9. Decisions taken

| # | Decision | Reason | Reversible? |
|---|---|---|---|

## 10. Ledger updates

| Claim ID | Before (tier/status) | After | Why |
|---|---|---|---|

## 11. Open items and next actions

| # | Item | Owner | Blocking? | Estimated cost |
|---|---|---|---|---|

## 12. Compute requests (if any)

```
command:
cells:
estimated cost:   <hours, with the measured basis>
buys:             <claim, tier before -> after>
alternative:      <cheapest partial answer without solving>
status:           PENDING HUMAN APPROVAL
```
