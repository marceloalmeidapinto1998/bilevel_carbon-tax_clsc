# Data Audit Report — `<scope>`

> **Template** for the Data Auditor.
> Save as `results/analysis/campaign_01/reports/YYYY-MM-DD_data_audit_<scope>.md`.

---

```
generated:      <ISO date>
auditor:        data-auditor
scope:          <experiments / claims audited>
master table:   <path> (sha256 <first 12>, <n> rows, mtime <ts>)
regenerated?:   <yes/no — did you re-run aggregate.py, and why>
code version:   <commit>, dirty: <yes|no>
```

---

## VERDICT

**`CLEAN` | `CLEAN WITH CAVEATS` | `BLOCKED`**

<One sentence. If BLOCKED, state exactly what would unblock it.>

---

## 1. Completeness

| Experiment | Design points | Run dirs on disk | Master rows | Δ | Missing / orphaned (named) |
|---|---|---|---|---|---|
| exp1_verification | | | | | |
| exp2_solver_config | | | | | |
| exp3_ablation | | | | | |
| exp4_scalability | | | | | |
| exp5_leader_value | | | | | |
| exp6_sensitivity | | | | | |
| exp7_policy_calibration | | | | | |
| exp8_benchmark | | | | | |
| **total** | | | | | |

Expected baseline as of 2026-08-03: **381 runs**, 382 lines in the master CSV.

## 2. Freshness

| Check | Result |
|---|---|
| newest run dir mtime | |
| master table mtime | |
| master table newer than newest run? | |
| aggregator re-run during this audit? | |

## 3. Status accounting (by `termination_reason`, never `solve_status`)

| Experiment | relative_gap | wall_clock_cap | wall_clock_cap_killed | stagnation | other |
|---|---|---|---|---|---|

Censored-but-usable runs (`wall_clock_cap`), with their certified gaps:

| Run | Gap | Incumbent usable? | Claim type it licenses |
|---|---|---|---|

## 4. Integrity checks

| Check | Result | Detail |
|---|---|---|
| Schema conformance vs `schemas.py` | | |
| Numeric columns free of NaN/inf | | |
| `code_version` homogeneous within each comparison group | | |
| `tax_grid_step_usd_per_kg` present on every run | | |
| `leader_tax_usd_per_tonne` consistent with index × step × 1000 | | |
| τ within 0–200 USD/t | | |
| emissions, cost non-negative | | |
| Orphan runs (no design row) | | |
| Orphan design rows (no run) | | |
| Documented `_correction` fields located | | |

## 5. Replication support (P4)

| Cell | Tier | Seeds present | Runs | Paired comparisons available |
|---|---|---|---|---|

## 6. Support matrix — what the data can and cannot carry

| Claim / hypothesis | n | Cells | Seeds | Censored | Paired? | Supportable? | Restriction |
|---|---|---|---|---|---|---|---|

## 7. Untraceable numbers

| Number | Cited in | Search performed | Verdict (LOCATED / UNTRACEABLE / MISMATCH) |
|---|---|---|---|

## 8. Defects

| # | Severity | Location | Observed | Expected | Consequence | Owner |
|---|---|---|---|---|---|---|

## 9. Caveats binding on downstream agents

<Numbered, imperative. These travel with the data: e.g. "exp6 seed-1 cost response has 63 of 64
runs; do not report a full-design effect for it without saying so.">
