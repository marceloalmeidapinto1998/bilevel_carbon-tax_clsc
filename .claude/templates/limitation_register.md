# Limitation Register — campaign_01

> **Template.** Copy to `results/analysis/campaign_01/reports/limitations_register.md`.
> **Living document**, edited in place, changelog at the bottom.
> Every limitation here must be either (a) written into the paper's Limitations section, or
> (b) explicitly closed with evidence. Silently dropping one is the failure mode this file exists
> to prevent.

Owner: project-manager · Last updated: `<ISO date>`

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

| ID | Class | Limitation | Severity | Evidence | Bounds which claim | Disclosed in paper? | Status |
|---|---|---|---|---|---|---|---|
| L-ALG-01 | L-ALG | Cold fixed-tax solves do not reproduce E\* at DBP's τ\* on the 2 hardest cells (+0.035 %, +0.113 %, above the 1e-4 plateau tolerance) — bounds τ\*'s precision on hard cells | material | Plan §6 H5.3 (E3) | τ\* precision; not the plateau or burden ratios | | OPEN |
| L-ALG-02 | L-ALG | Mechanism for L-ALG-01 (lexicographic freeze band) is hypothesised, never instrumented | material | E4 | any causal statement about the discrepancy | | OPEN |
| L-ALG-03 | L-ALG | Tractability frontier anchored, not resolved: M12 probe censored at 0.96 % gap | material | Plan §8.2 (E3) | scalability claims above M8 | | OPEN |
| L-ALG-04 | L-ALG | exp8 coverage incomplete on 2 of 4 cells (310/2001 and 197/2001) | material | Plan §7 (E3) | the benchmark's generality | | OPEN |
| L-STA-01 | L-STA | **No committed code implements any statistic the plan prescribes or reports** (P7) | **fundamental** | repo search, 2026-08-03 | every §2.4/§10 statistic; all currently E3 | | **OPEN — blocks exp6 publication** |
| L-STA-02 | L-STA | Lenth's sparsity assumption fails on exp6 seed 1 (emissions, cost); p-values invalid | material | Plan §10 (E3) | exp6 significance claims; ranks unaffected | | OPEN |
| L-STA-03 | L-STA | n = 6 cells for ablation comparisons → minimum two-sided Wilcoxon p is 0.031 | material | design | every ablation p-value | | OPEN |
| L-STA-04 | L-STA | Factorial design is unreplicated per seed; noise estimated, not measured | material | design | all exp6 effect uncertainties | | OPEN |
| L-DAT-01 | L-DAT | Cross-seed CV reaches 40–50 %; hard cells have 1 seed (+1 spot-check) | material | Plan §2.1 (E3) | any per-cell claim on a hard cell | | OPEN |
| L-DAT-02 | L-DAT | Structural grid is 2×2×3 = 12 cells; no growth exponent is identifiable | material | design | scalability extrapolation | | OPEN |
| L-DAT-03 | L-DAT | Structural sensitivity screen ran on **one** fast cell (I17-M4-T3) only | material | Plan §10 (E3) | the zero sea/air effect; all structural effects | | OPEN |
| L-DAT-04 | L-DAT | AUGMECON instrument-gap observation has **n = 1 cell** | material | Plan §9 (E3) | the ~0.5 % gap claim | | OPEN |
| L-MOD-01 | L-MOD | Emissions valuation scale is **inherited** from sources that never priced emissions in money; ρ\*=1 is internal consistency, not external anchoring | **fundamental** | Plan §9 (E3) | every absolute USD/t claim | | OPEN |
| L-MOD-02 | L-MOD | Only 6 of 12 cells have τ\* inside the 20–200 USD/t policy band at ρ = 1 | material | Plan §3 correction (E3) | any "plausible band" statement | | OPEN |
| L-MOD-03 | L-MOD | Optimistic bilevel response assumed; pessimistic case not studied | fundamental | formulation | the leader's guarantee | | OPEN |
| L-MOD-04 | L-MOD | Deterministic demand and returns; no uncertainty representation | fundamental | formulation | policy robustness | | OPEN |
| L-MOD-05 | L-MOD | Leader has a single instrument (a uniform carbon tax) on a discrete grid | fundamental | formulation | generality of "the optimal policy" | | OPEN |
| L-REP-01 | L-REP | `scipy` is used-capable but **undeclared**; `statsmodels` absent | material | `pyproject.toml`, venv check | reproducibility of any future statistic | | OPEN |
| L-REP-02 | L-REP | Two parallel table families can disagree (P9) | material | repo structure | any number appearing in both | | OPEN |
| L-REP-03 | L-REP | Analysis findings live in a planning document that has self-corrected ≥4 times | material | Plan §3, §10, §11.1, §14 | traceability of every E3 claim | | OPEN |
| L-EXT-01 | L-EXT | One generator family (Tautenhain/Mota), one geography, 17–25 nodes, 3–12 periods | fundamental | testbed | generalisation to real supply chains | | OPEN |

---

## Closed limitations

| ID | Limitation | How it was closed | Evidence | Date |
|---|---|---|---|---|

Closing a limitation requires evidence at E0–E2, not an argument.

---

## Changelog

| Date | Change | By |
|---|---|---|
| `<ISO>` | Register created from the 2026-08-03 project mapping and `Experimental_Plan.md` | project-manager |
