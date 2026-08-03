# Limitation Register — campaign_01

**Living document.** Edited in place; changelog at the bottom.

Every limitation here must be either (a) written into the paper's Limitations section, or (b)
explicitly closed with evidence at tier E0–E2. Silently dropping one is the failure mode this file
exists to prevent.

Owner: `project-manager` · Created: 2026-08-03 · Last updated: 2026-08-03
Code version: `cde0a97`, branch `campaign-01-remap`

> **Provenance of this initial fill.** Entries below are derived from `docs/Experimental_Plan.md`
> (tier E3 — reported, not independently verified) and from the 2026-08-03 repository mapping
> (tier E1 — directly observed in the repo). The tier column says which. Run
> `/wf7-identify-limitations` for the systematic sweep, whose stage 7 exists to find what this
> initial fill missed.

---

## Classification

| Class | Meaning |
|---|---|
| **L-MOD** | model scope — what the formulation does not represent |
| **L-DAT** | testbed / instance scope — what the data does not cover |
| **L-ALG** | algorithmic — precision, convergence, tractability boundaries |
| **L-STA** | statistical — power, assumptions, multiplicity, unreplicated design |
| **L-REP** | reproducibility — provenance gaps in the evidence chain |
| **L-EXT** | external validity — what real systems this does not speak to |

Severity: **fundamental** (bounds the contribution) · **material** (bounds a specific claim) ·
**minor** (worth stating, changes nothing).

---

## Register

### Fundamental

| ID | Class | Limitation | Tier | Bounds | Disclosed? | Status |
|---|---|---|---|---|---|---|
| L-STA-01 | L-STA | **No committed code implements any statistic the plan prescribes or reports.** `scipy` importable but undeclared; `statsmodels` absent | E1 (repo mapping) | every claim C-06-01…C-06-06; all §2.4/§10 statistics | no | **OPEN — blocks exp6 publication** |
| L-MOD-01 | L-MOD | The emissions-valuation scale is **inherited** from sources that never priced emissions in money. ρ\*=1 is internal consistency, not external anchoring | E3 (Plan §9) | every absolute USD/t claim (C-07-02, C-07-03, C-03-04) | no | OPEN |
| L-MOD-03 | L-MOD | Optimistic bilevel response assumed throughout; the pessimistic case is **not studied** | E1 (formulation) | the leader's guarantee | no | OPEN |
| L-MOD-04 | L-MOD | Demand and returns are deterministic; no uncertainty representation | E1 (formulation) | policy robustness of τ\* | no | OPEN |
| L-MOD-05 | L-MOD | The leader has a single instrument — a uniform carbon tax on a discrete grid | E1 (formulation) | generality of "the optimal policy" | no | OPEN |
| L-EXT-01 | L-EXT | One generator family (Tautenhain/Mota), one geography, 17–25 nodes, 3–12 periods, 3+3 technologies | E1 (testbed) | generalisation to real supply chains | no | OPEN |

### Material

| ID | Class | Limitation | Tier | Bounds | Disclosed? | Status |
|---|---|---|---|---|---|---|
| L-ALG-01 | L-ALG | Cold fixed-tax solves do not reproduce E\* at DBP's τ\* on the 2 hardest cells (+0.035 %, +0.113 %, both above the 1e-4 plateau tolerance) | E3 (Plan §6) | τ\* precision on hard cells (C-05-04); **not** the plateau or burden ratios | no | OPEN |
| L-ALG-02 | L-ALG | The mechanism for L-ALG-01 (lexicographic freeze band) is **hypothesised, never instrumented** | E4 | any causal statement about the discrepancy | no | OPEN |
| L-ALG-03 | L-ALG | Tractability frontier is anchored, not resolved: the M12 probe censored at 0.96 % gap | E3 (Plan §8.2) | scalability claims above M8 (C-04-02) | no | OPEN |
| L-ALG-04 | L-ALG | exp8 coverage incomplete on 2 of 4 cells (310/2001 and 197/2001) | E3 (Plan §7) | the benchmark's generality (C-08-01) | no | OPEN |
| L-STA-02 | L-STA | Lenth's sparsity-of-effects assumption fails on exp6 seed 1 (emissions, cost); p-values invalid as computed | E3 (Plan §10) | exp6 significance claims; rank conclusions unaffected (C-06-04) | no | OPEN |
| L-STA-03 | L-STA | n = 6 cells for ablation comparisons → minimum attainable two-sided Wilcoxon p is 0.031 | E1 (design) | every ablation p-value (C-03-01, C-03-02) | no | OPEN |
| L-STA-04 | L-STA | The factorial design is unreplicated per seed; noise is estimated, not measured | E1 (design) | all exp6 effect uncertainties | no | OPEN |
| L-DAT-01 | L-DAT | Cross-seed CV reaches 40–50 %; hard cells have 1 seed (+1 spot-check) | E3 (Plan §2.1) | any per-cell claim on a hard cell | no | OPEN |
| L-DAT-02 | L-DAT | Structural grid is 2×2×3 = 12 cells; no growth exponent is identifiable | E1 (design) | scalability extrapolation (C-04-01) | no | OPEN |
| L-DAT-03 | L-DAT | The structural sensitivity screen ran on **one** fast cell (I17-M4-T3) only | E3 (Plan §10) | the zero sea/air effect and all structural effects (C-06-06) | no | OPEN |
| L-DAT-04 | L-DAT | The AUGMECON instrument-gap observation has **n = 1 cell** | E3 (Plan §9) | the ~0.5 % gap claim (C-07-03) | no | OPEN |
| L-DAT-05 | L-DAT | exp3's M0 reference arm is 22/25 complete; exp3 overall 42/43 | E3 (Plan §8.1) | the ablation baseline | no | OPEN |
| L-MOD-02 | L-MOD | At ρ = 1 only 6 of 12 cells have τ\* inside the 20–200 USD/t policy band | E3 (Plan §3) | any "plausible band" statement (C-07-04) | no | OPEN |
| L-REP-01 | L-REP | `scipy` is used-capable but **undeclared** in `pyproject.toml`; `statsmodels` absent | E1 (venv check) | reproducibility of any future statistic | no | OPEN |
| L-REP-02 | L-REP | Two parallel table families (`paper/tables/tab_*.tex` hand-maintained vs generated `t{1..7}_*.tex`) can disagree | E1 (repo mapping) | any number appearing in both | no | OPEN |
| L-REP-03 | L-REP | Analysis findings live in a planning document that has self-corrected ≥4 times and carries no locators | E1 (repo mapping) | traceability of all 26 E3 claims | no | OPEN |

### Minor

| ID | Class | Limitation | Tier | Bounds | Disclosed? | Status |
|---|---|---|---|---|---|---|
| L-REP-04 | L-REP | exp1's invariance-probe directory naming predates the current design module; a regenerate would produce 16 duplicate solves alongside orphans | E3 (Plan §11.1) | nothing — rates were always correct | n/a | OPEN |

---

## Closed limitations

| ID | Limitation | How it was closed | Evidence | Date |
|---|---|---|---|---|
| — | *none yet* | | | |

Closing a limitation requires evidence at E0–E2, not an argument.

---

## Summary

| Severity | Count |
|---|---|
| fundamental | 6 |
| material | 16 |
| minor | 1 |
| **total** | **23** |

**Disclosed in the paper: 0 of 23.** Bringing that to completion is `/wf4`'s stage-4 gate.

---

## Changelog

| Date | Change | By |
|---|---|---|
| 2026-08-03 | Register created from the 2026-08-03 repository mapping (E1 entries) and `docs/Experimental_Plan.md` (E3 entries). Awaits the systematic `/wf7` sweep | project-manager (framework bootstrap) |
