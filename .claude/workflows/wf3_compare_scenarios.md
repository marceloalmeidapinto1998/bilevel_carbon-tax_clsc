# Workflow 3 — Compare Scenarios

**Purpose**: compare two or more conditions rigorously — algorithm variants (M0 vs A1–A5), methods
(DBP vs enumeration), policy rules (P0/P1/P2/τ\*), valuation levels (ρ), structural cells, or seeds
— without the confounds that make most such comparisons worthless.

**Solver cost**: 0.

**Entry**: `/wf3-compare-scenarios <condition A> vs <condition B> [on <cells>]`

---

## Stages

| # | Agent | Task | Gate |
|---|---|---|---|
| 0 | project-manager | Define the comparison precisely: conditions, response(s), cells, seeds, and **what would count as a difference that matters** — before looking at the data | — |
| 1 | **data-auditor** | Verify comparability and produce the pairing table: same tolerances? same tax grid (in rates)? same `code_version`? which (cell, seed) pairs exist in **both** arms? censoring in each arm? | **BLOCKING** |
| 2 | **optimization-expert** | Fairness verdict: do both arms certify the same quantity, with the same per-point solve, under comparable budgets? Report coverage. Classify each arm's certificates | **BLOCKING** on unfair |
| 3 | **statistical-analyst** | The pre-specified paired test on the pairs stage 1 found. Effect sizes with BCa intervals. Multiplicity within the family. State the p-floor if n ≤ 6 | — |
| 4 | **domain-expert** | Is the difference *meaningful*, not merely detectable? What would a practitioner do differently? | — |
| 5 | **scientific-reviewer** | Attack the comparison: confounds, selection of cells, arm-specific censoring, multiplicity, over-general conclusion | **BLOCKING** on REJECT |
| 6 | project-manager | Consolidate; update ledger | — |

---

## Comparability checklist — stage 1 must clear all of these

| Check | Why it matters |
|---|---|
| Same tolerances (`dbp_relative_gap`, `mip_gap`) | different tolerances certify different things |
| Same tax grid, **or** both expressed in USD/t | index comparison across grids is meaningless (P1) |
| Same `code_version` | a mid-campaign code change silently splits the arms |
| Same time budgets, or budgets reported | a censored arm is not a slower arm |
| Pairs exist in both arms per (cell, seed) | unpaired comparison discards the design's main strength (P4) |
| Censoring reported per arm | asymmetric censoring biases any runtime statistic |
| Coverage reported (enumeration arms) | 310/2001 is not a completed method |

If any fails, stage 1 returns `BLOCKED` with the specific fix.

## Rules specific to this workflow

- **Pair within (cell, seed). Never pool across seeds before pairing** — cross-seed CV reaches
  40–50 % and will swamp any real effect (P4).
- **Never impute a censored value to complete a pair.** Drop the pair and say so, or report a
  bounding statement.
- **A faster arm is not a better arm.** exp3's A1 and A4 are 2–3× faster than M0 *because* they do
  less work; the finding is what they lose, not what they save.
- **An arm that leaves the optimum unchanged is not a failed arm.** A2/A3/A5 are efficiency
  components; unchanged (E\*, τ\*) is the correct result and must be reported as such.
- **Report the direction and unanimity before the p-value.** "6/6, unanimous" carries more than a
  p-value that is merely the n = 6 floor.
- **Scope the conclusion to the cells tested.** Six representative cells is six, not "all".

## Output

`results/analysis/campaign_01/reports/YYYY-MM-DD_wf3_<A>_vs_<B>.md`, containing the comparability
table, the pairing table, the test, effect sizes with intervals, the fairness verdict, and the
practical-significance judgement.

## Success criteria

- [ ] Every comparability check is explicitly passed or the workflow was blocked.
- [ ] The pairing table lists actual (cell, seed) pairs, not counts alone.
- [ ] Effect sizes accompany every p-value; intervals accompany every effect size.
- [ ] Censoring and coverage are reported per arm.
- [ ] Practical significance is judged separately from statistical detectability.
- [ ] The conclusion's scope matches the cells actually compared.
