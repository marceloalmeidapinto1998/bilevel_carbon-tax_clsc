# Experiment Card — `<expN_name>`

> **Template** for proposing a new experiment. One card per proposal.
> A card is a **pre-registration**: it is written before running, and it is not edited afterwards.
> Results go in a dated analysis report that cites the card.
> Rejected cards are kept — a recorded rejection prevents the idea from being re-proposed blind.

---

## 1. Identity

| Field | Value |
|---|---|
| ID | `expN_<slug>` |
| Proposed by | `<agent>` |
| Date | `<ISO>` |
| Status | PROPOSED / APPROVED / REJECTED / RUNNING / COMPLETE |
| Research question | Q1–Q7, or "new" |
| Paper section it serves | |

## 2. Objective

<One paragraph. What is currently unknown, and what this would establish.>

## 3. Hypotheses

| ID | Hypothesis | Falsifiable prediction | What would refute it |
|---|---|---|---|
| HN.1 | | | |

A hypothesis with no stated refutation condition is not a hypothesis. Reject the card.

## 4. Design

| Field | Value |
|---|---|
| Independent variables | |
| Levels | |
| Dependent variables | |
| Controlled parameters | |
| Design type | full factorial / fractional (resolution) / sweep / one-factor probe |
| Cells | **must be fast/standard tier for any sweep or factorial (P5)** |
| Seeds | instance seeds and/or Gurobi seeds, with reason |
| Design points | n = |
| Execution mode | bilevel / fixed_tax / min_emissions / epsilon_constraint / enumeration |

## 5. Statistical plan (pre-specified)

| Field | Value |
|---|---|
| Test(s) | |
| Pairing | within seed and cell? |
| n and power | including the p-value floor if n ≤ 6 |
| Multiplicity | Holm within family / BH across responses |
| Intervals | BCa, 10 000 resamples, seed recorded |
| Assumption guards | e.g. Lenth PSE plausibility check |
| Code that will compute it | `src/clsc/analysis/stats/...` |

Deviating from this plan later is permitted **and must be disclosed** in the report.

## 6. Cost

| Field | Value |
|---|---|
| Design points | |
| Measured per-point cost | **with its basis** — a comparable measured cell, cited |
| Estimated total | h |
| Tier of the cells used | |
| Budget context | campaign total to date: 119.6 h / 381 runs |

## 7. Value

| Field | Value |
|---|---|
| Claim(s) it promotes | ledger IDs |
| Tier before → after | |
| Contribution per hour | <the number that decides whether this runs> |
| What is lost if it is not run | |

## 8. Cheaper alternatives considered

| Alternative | What it would answer | Cost | Why rejected |
|---|---|---|---|

A card with this section empty is incomplete. There is almost always a cheaper partial answer, and
`Experimental_Plan.md` §11.2 is what happens when nobody looks for it.

## 9. Rejection checks (Project Manager)

| Check | Pass? |
|---|---|
| Sweep/factorial confined to fast or standard tier (P5) | |
| Not re-solving something already on disk | |
| Cost estimate has a measured basis | |
| States a claim promotion, not curiosity | |
| Hypotheses have refutation conditions | |
| Statistical plan pre-specified with committed code named | |
| Does not relitigate a settled decision without new evidence | |

## 10. Decision

| Field | Value |
|---|---|
| Decision | |
| Decided by | human (compute is never agent-authorized) |
| Date | |
| Reason | |
