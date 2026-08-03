# Claim Ledger — campaign_01

**Living document.** Edited in place; changelog at the bottom. This is the single register of every
claim this project intends to make.

- The **scientific-writer** writes *only* from this file.
- The **editor** resolves every numeric disagreement *against* this file.
- Only tier **E0–E2** with status `CERTIFIED` / `SUPPORTED` / `PARTIAL` / `NOT SUPPORTED` may enter
  the paper.

Owner: `project-manager` · Created: 2026-08-03 · Last updated: 2026-08-03
Code version: `cde0a97`, branch `campaign-01-remap`, dirty: **yes** (42 modified, 11 untracked)

---

## Conventions

- **ID**: `C-<exp>-<n>`. Stable forever; never reused.
- **Tier**: E0 certified · E1 measured · E2 derived · E3 reported · E4 inferred
  (`.claude/standards/evidence_and_claims.md`).
- **Status**: CERTIFIED · SUPPORTED · PARTIAL · INDICATIVE · NOT SUPPORTED · CONTRADICTED ·
  CONTESTED · UNTRACEABLE · OPEN.
- **Locator**: must be sufficient for another agent to reproduce the number without asking.
- **Scope**: n / cells / seeds / censored. Non-negotiable.

> **Why every row below starts at E3/OPEN.** These are the values currently asserted in
> `docs/Experimental_Plan.md`. None carries a locator, so none is reproducible as written — that is
> true of the correct ones too. Promoting them to E1/E2 is the first substantive job of this
> system (`/wf5-review-analysis`, then `/wf2-analyze-full-campaign`).

---

## Ledger

### Headline — plateau and the value of the bilevel leader (exp5)

| ID | Claim | Value | Tier | Status | Scope | Locator | Owner | Paper |
|---|---|---|---|---|---|---|---|---|
| C-05-01 | Emissions at the grid ceiling equal E\* to within 0.01 % | ≤0.01 % | E3 | OPEN | 12 cells / seed 0 / 0 censored | *needs promotion — Plan §6 H5.1* | statistical-analyst | headline |
| C-05-02 | Median burden ratio, ceiling vs τ\* | 4.4× | E3 | OPEN | 12 cells | *needs promotion — Plan §6 H5.2* | statistical-analyst | headline |
| C-05-03 | Max burden ratio (I25-M8-T12) | 18.6× | E3 | OPEN | 1 cell | *needs promotion* | statistical-analyst | headline |
| C-05-04 | Cold fixed-tax solve does not reproduce E\* at τ\* on the 2 hardest cells | +0.035 %, +0.113 % | E3 | OPEN | 2 of 12 cells | *needs promotion — Plan §6 H5.3* | optimization-expert | **disclosure** |
| C-05-05 | Refinement places the plateau's left edge within one step of DBP's τ\* | 10 of 12 cells | E3 | OPEN | 12 cells / 84 solves | *needs promotion* | statistical-analyst | yes |

### Algorithm — benchmark (exp8) and ablation (exp3)

| ID | Claim | Value | Tier | Status | Scope | Locator | Owner | Paper |
|---|---|---|---|---|---|---|---|---|
| C-08-01 | DBP and enumeration agree exactly on the exhausted cells | 2/2 exhausted; 3/4 overall | E3 | OPEN | 4 cells / 2 censored | *needs promotion — Plan §7 H8.1* | optimization-expert | yes + **disclosure** |
| C-08-02 | Follower-solve reduction vs enumeration | ≈180×, ≈130× | E3 | OPEN | 2 exhausted cells | *needs promotion — Plan §7 H8.2* | optimization-expert | yes |
| C-08-03 | Enumeration is fragile to noise accumulation at tight tolerance; DBP's O(log n) search is not | 51 % tax inflation pre-fix | E3 | OPEN | 1 cell (I17-M4-T6) | *trace replay; see `_correction` field* | optimization-expert | yes |
| C-03-01 | A1 (no Phase-2) loses τ\*-minimality; emissions unchanged | 6/6 cells, E ratio 1.0 | E3 | OPEN | 6 cells | *needs promotion — Plan §8.1 H3.1* | statistical-analyst | yes |
| C-03-02 | A4 (coarse grid) biases τ\* upward through aliasing | 6/6 cells | E3 | OPEN | 6 cells | *needs promotion — Plan §8.1 H3.2* | statistical-analyst | yes |
| C-03-03 | A2/A3/A5 leave (E\*, τ\*) unchanged; A5 is 11–13 % slower | — | E3 | OPEN | 2 cells each | *needs promotion* | statistical-analyst | yes |
| C-03-04 | τ\* range and median across the 12 base cells | 1.4–167.3, median 22.6 USD/t | E3 | OPEN | 12 cells / seed 0 | *needs promotion; Plan §3 previously published a **wrong** median* | data-auditor | yes |

### Scalability (exp4)

| ID | Claim | Value | Tier | Status | Scope | Locator | Owner | Paper |
|---|---|---|---|---|---|---|---|---|
| C-04-01 | Growth in T is non-monotone | I17-M8-T6 2.6 h > both T12 cells (0.69, 1.36 h) | E3 | OPEN | 12 cells / seed 0 | *needs promotion — Plan §8.2 H4.1* | optimization-expert | yes |
| C-04-02 | M12 probe censored at 0.96 % gap with a real incumbent | 0.96 % | E3 | OPEN | 1 probe | *needs promotion — Plan §8.2 H4.2* | optimization-expert | **disclosure** |

### Sensitivity (exp6) — *no committed code produces any of these (P7)*

| ID | Claim | Value | Tier | Status | Scope | Locator | Owner | Paper |
|---|---|---|---|---|---|---|---|---|
| C-06-01 | `demand:capacity` is the strongest / near-strongest 2FI | mean rank 2.7 of 28 | E3 | OPEN | 6 series (3 responses × 2 seeds) | **no committed code** | statistical-analyst | yes |
| C-06-02 | `demand` and `capacity` in top-3 in every series | 6/6 | E3 | OPEN | 6 series | **no committed code** | statistical-analyst | yes |
| C-06-03 | Top-3 stability across seeds | emissions 3/3; cost 2/3; τ\* 2/3 | E3 | OPEN | 2 seeds | **no committed code** | statistical-analyst | **disclosure** |
| C-06-04 | Lenth PSE collapses on seed 1 (emissions, cost) | PSE ≈302, ≈14 | E3 | OPEN | seed 1 | **no committed code** | statistical-analyst | **disclosure** |
| C-06-05 | Design is empirically resolution V (main+2FI rank 37/37) | 37/37 | E3 | OPEN | per seed | **no committed code** | statistical-analyst | yes |
| C-06-06 | Structural screen: prod-tech menu dominates emissions; reman-tech menu dominates τ\* (+17.2 USD/t); sea/air menus have exactly zero effect | — | E3 | OPEN | **1 fast cell only** | **no committed code** | statistical-analyst | yes, scoped |

### Policy calibration (exp7)

| ID | Claim | Value | Tier | Status | Scope | Locator | Owner | Paper |
|---|---|---|---|---|---|---|---|---|
| C-07-01 | τ\*(ρ) is non-monotone; all runs certified | 7 levels, gaps ≤1e-4 | E3 | OPEN | 1 cell / 7 ρ | *needs promotion — Plan §9 H7.1* | statistical-analyst | **disclosure** |
| C-07-02 | Regime split: ρ ≥ 10 lands τ\* inside 20–200 USD/t across a 20× range | 5 of 7 levels | E3 | OPEN | 1 anchor cell | *needs promotion — Plan §9 H7.2* | domain-expert | yes, conditional |
| C-07-03 | AUGMECON anchor shows a tax-instrument gap vs the physical emissions minimum | ~0.5 % | E3 | OPEN | **n = 1 cell** | *needs promotion* | domain-expert | yes, scoped |
| C-07-04 | At ρ=1 only 6 of 12 cells have τ\* inside 20–200 USD/t | 6/12 | E3 | OPEN | 12 cells | *needs promotion — Plan §3 correction* | domain-expert | yes — **must accompany any band claim** |

### Appendix — verification (exp1) and solver configuration (exp2)

| ID | Claim | Value | Tier | Status | Scope | Locator | Owner | Paper |
|---|---|---|---|---|---|---|---|---|
| C-01-01 | All 12 cells terminate on `relative_gap`; worst gap 8.7e-5 | 38/38 runs | E3 | OPEN | 38 runs | *needs promotion — Plan §11.1* | data-auditor | appendix |
| C-01-02 | All 6 toy instances agree with manual derivation; Gurobi-seed probes return identical (E\*, τ\*) | — | E3 | OPEN | 6 toys + 2 probes | *needs promotion* | data-auditor | appendix |
| C-02-01 | `MIPFocus=2` decisive; threads 4 vs 6 unresolved (within seed spread) | 3/3 converge vs 5/6 censored | E3 | OPEN | 11 runs / 1 hard cell | *needs promotion — Plan §11.2* | optimization-expert | appendix |

---

## Contested claims

| ID | Claim | Position A (agent) | Position B (agent) | How it could be settled | Blocks |
|---|---|---|---|---|---|
| — | *none yet* | | | | |

---

## Retired / withdrawn claims

| ID | Claim | Why retired | Date | Superseded by |
|---|---|---|---|---|
| — | τ\* median ≈50 USD/t; "already inside the 20–200 policy band" | Recomputed: median is 22.6 and only 6 of 12 cells fall in the band. Both the median and the conclusion were wrong | 2026-08-03 (Plan §3) | C-03-04, C-07-04 |
| — | P4 (plateau right edge) as a design point | Measured to coincide with P1 (grid ceiling) within 0.01 % on all 12 cells — not an independent point | Plan §14 | C-05-01 |
| — | Tier caps halved to 14 400 / 28 800 s | Proposed in plan v2, never applied to `_cells.py`; every completed run used 28 800 / 50 400 s | Plan §14 | — |
| — | exp6 reduced to 96 design points | Never applied; the full 128-run continuous design ran | Plan §14 | C-06-03 |

---

## Summary

| Tier | Count | Admissible in paper |
|---|---|---|
| E0–E2 | **0** | yes |
| E3 | **26** | **no — all require promotion** |
| E4 | 0 | never |

Of the 26, **6 additionally require the statistical layer to exist before they can be promoted at
all** (C-06-01…C-06-06 — see `.claude/standards/known_pitfalls.md` P7).

---

## Changelog

| Date | Change | By |
|---|---|---|
| 2026-08-03 | Ledger created from `docs/Experimental_Plan.md` §0–§14. All 26 claims entered at E3/OPEN; 4 retired claims recorded from the plan's own corrections | project-manager (framework bootstrap) |
