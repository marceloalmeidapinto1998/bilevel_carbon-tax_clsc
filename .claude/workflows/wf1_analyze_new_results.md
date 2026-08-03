# Workflow 1 — Analyze New Results

**Purpose**: triage a fresh batch of completed runs. Answer, fast: are they valid, what do they
say, do they change anything we believed, and does anything need attention?

**When**: after any solve completes. This is the routine, high-frequency workflow.

**Solver cost**: 0. Reads only.

**Entry**: `/wf1-analyze-new-results <experiment or run path>`

---

## Stages

| # | Agent | Task | Input | Output | Gate |
|---|---|---|---|---|---|
| 0 | project-manager | Identify the batch: which runs are new since the last dated report; state the comparison baseline | `reports/`, `results/runs/` mtimes | scope statement | — |
| 1 | **data-auditor** | Re-run `aggregate.py`; audit completeness, status by `termination_reason`, schema, grid/rate consistency, provenance; produce the support matrix | new runs, master table, design matrix | data audit report | **BLOCKING** |
| 2 ‖ | **optimization-expert** | Classify every run's certificate; diagnose convergence from `dbp_trace.csv`; flag numerical hazards | run artifacts, traces | run classification + diagnosis | ADVISORY |
| 2 ‖ | **domain-expert** | Magnitude plausibility of the new values against literature ranges | master table rows, `solution.json` | plausibility verdict | ADVISORY |
| 3 | **statistical-analyst** | Only if the batch completes a designed comparison: run the pre-specified test with correct pairing and multiplicity. Otherwise: descriptive summary only, explicitly labelled as such | audited rows + support matrix | statistics or descriptive summary | — |
| 4 | project-manager | Consolidate; compare against `claim_ledger.md` and `Experimental_Plan.md`; identify claims changed, confirmed, or contradicted | all above | analysis report + ledger update | — |
| 5 | **scientific-reviewer** | Short-form review: is any conclusion stronger than the batch supports? | consolidated report | verdict | **BLOCKING** on REJECT |

---

## Rules specific to this workflow

- **Do not run a hypothesis test on a partial batch.** If the design point set is incomplete,
  report descriptives and say the test is pending. Testing as data arrives inflates false positives.
- **Compare against the baseline, not against expectation.** The baseline is the previous dated
  report or the ledger — not what the plan predicted.
- **A contradiction is the most valuable output this workflow can produce.** If a new run disagrees
  with a ledger claim, raise it to `CONTRADICTED` immediately and stop treating the old value as
  usable.
- **Censored runs are triaged, not discarded** (P2). Report the incumbent and the certified gap;
  state which claim types they license.
- Do not update `docs/Experimental_Plan.md`. Findings go to the dated report and the ledger.

## Output

`results/analysis/campaign_01/reports/YYYY-MM-DD_wf1_<experiment>.md`
(template: `analysis_report.md`), plus ledger updates.

## Success criteria

- [ ] Every new run is classified by `termination_reason`.
- [ ] The batch's completeness is stated as a fraction of its design.
- [ ] Every claim the batch touches is marked confirmed / refined / contradicted in the ledger.
- [ ] No test was run on an incomplete comparison.
- [ ] Anything anomalous is either explained or raised as a DEFECT with an owner.
