# STANDARD — Evidence tiers and claim discipline

The spine of this system. Every agent, every workflow, every report obeys it.

---

## 1. The tiers

| Tier | Name | Definition | Admissible in the paper? |
|---|---|---|---|
| **E0** | Certified | A solver certificate: `termination_reason="relative_gap"` with `relative_gap ≤ dbp_relative_gap` (1e-4), or exhaustive enumeration that exhausted its grid (`coverage = 2001/2001`) | Yes — the strongest claim available |
| **E1** | Measured | A value read directly out of `master_runs_campaign_01.csv` or a run's `campaign_manifest.json` / `result.json` / `summary.json`, with the filter that selects it stated | Yes |
| **E2** | Derived | Computed from E0/E1 inputs by a **committed, named** script under `scripts/` or `src/clsc/analysis/`, reproducible by re-running that script | Yes |
| **E3** | Reported | Asserted in `docs/Experimental_Plan.md`, `paper/`, or a prior chat, with no locator into the evidence base | **No** — must be promoted or dropped |
| **E4** | Inferred | An agent's reasoning, a plausibility argument, an expectation from the literature | **Never a claim.** May appear as an explicitly labelled hypothesis |

**Promotion** is the act of turning an E3 into an E1/E2 by finding the rows that produce it and
recomputing. **Demotion** happens when a recomputation contradicts the reported value — the claim
becomes `CONTRADICTED` and the discrepancy is itself a finding.

## 2. Locator format

A locator must be sufficient for another agent to reproduce the number without asking a question.

**From the master table** — state the file and the exact filter:
```
master_runs_campaign_01.csv :: experiment_id=exp5_leader_value
                             ∧ base_instance_id=STD_I25_M8_T12
                             ∧ design_point_id=P1
                             → follower_objective
```

**From a run directory** — state the path and the JSON key path:
```
results/runs/campaign_01/exp3_ablation/STD_I17_M4_T3/M0_s0/result.json :: .leader.tax_index
```

**From a script** — state the script, the function, and the inputs it consumed:
```
scripts/make_campaign_01_tables.py :: _t2_plateau()  ← master_runs_campaign_01.csv (381 rows)
```

**From code** — `file:line`, e.g. `src/clsc/models/subproblems.py:1204`.

## 3. Claim status vocabulary

Used in the claim ledger and in every report. Do not invent alternatives.

| Status | Meaning | Requirement |
|---|---|---|
| `CERTIFIED` | E0 evidence, hypothesis supported | solver certificate on every cell cited |
| `SUPPORTED` | E1/E2 evidence, consistent, adequate n | n stated; test named if a test was used |
| `PARTIAL` | Supported for some responses/cells, not all | the split must be stated exactly (e.g. "emissions 3/3, cost 2/3") |
| `INDICATIVE` | Directionally consistent but n too small, or single-seed | may not carry a headline claim |
| `NOT SUPPORTED` | The evidence exists and does not support the hypothesis | reported as a finding, never suppressed |
| `CONTRADICTED` | Recomputation disagrees with a reported value | the discrepancy is a DEFECT |
| `CONTESTED` | Two agents disagree, unresolved | blocks paper entry |
| `UNTRACEABLE` | Cited value has no locator anywhere | blocks paper entry |
| `OPEN` | Not yet examined | — |

## 4. The four rules

**R1 — No orphan numbers.** A number in a report, table, figure caption, or paper sentence without
a locator is a defect regardless of whether it is correct.

**R2 — n and censoring travel with the claim.** Every aggregate states its denominator and how
many of its members were censored. "Confirmed 12/12" and "confirmed 3/4, 4th censored" are
different claims; collapsing the second into the first is misconduct, not simplification.

**R3 — The plan does not certify itself.** `docs/Experimental_Plan.md` is E3 by construction, even
where it is right, because it has no locators. Its §3 correction of 2026-08-03 (a wrong median and
a wrong policy-band conclusion, both previously published in that same document) is the standing
demonstration of why.

**R4 — Recomputation beats authority.** If a junior-stage agent recomputes a value and it
disagrees with a senior-stage agent's assertion, the recomputation wins pending a third check. Seniority in a workflow orders the *work*, not the *truth*.

## 5. Worked example

> **Bad** (E4 posing as fact):
> "The plateau is wide on all cells, so the tax is clearly unidentified."

> **Also bad** (E3 laundered into the paper):
> "Median burden ratio ≈ 4× (Experimental_Plan.md §6)."

> **Good**:
> "Median burden ratio across the 12 structural cells is 4.4×
> [E2: scripts/make_campaign_01_tables.py :: _t3_policy_rules() ← master_runs_campaign_01.csv,
> experiment_id=exp5_leader_value, design_point_id ∈ {P1,P3}, n=12, 0 censored].
> Range 1.2×–18.6×; the maximum is I25-M8-T12 [E1: same table, row STD_I25_M8_T12].
> Status: SUPPORTED."

Note what the good version supplies that the plan's §6 table does not: the script that computed
it, the row count, the censoring count, and a status.
