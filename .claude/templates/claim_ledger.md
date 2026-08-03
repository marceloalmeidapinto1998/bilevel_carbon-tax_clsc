# Claim Ledger — campaign_01

> **Template.** Copy to `results/analysis/campaign_01/reports/claim_ledger.md` on first use.
> This is a **living document**, edited in place, with a changelog at the bottom.
> It is the single register of every claim this project intends to make. The Scientific Writer
> writes **only** from this file. The Editor resolves every numeric disagreement **against** it.

Owner: project-manager · Last updated: `<ISO date>` · Code version: `<commit>`

---

## How to use

One row per claim. A claim enters as `OPEN`, is promoted by evidence, and may only be written into
the paper at tier **E0–E2** with status `CERTIFIED`, `SUPPORTED`, `PARTIAL`, or `NOT SUPPORTED`.

- **ID**: `C-<exp>-<n>`, e.g. `C-05-01`. Stable forever; never reuse.
- **Tier**: E0 certified · E1 measured · E2 derived · E3 reported · E4 inferred.
- **Status**: CERTIFIED · SUPPORTED · PARTIAL · INDICATIVE · NOT SUPPORTED · CONTRADICTED ·
  CONTESTED · UNTRACEABLE · OPEN.
- **Locator**: must be sufficient for another agent to reproduce the number without asking.
- **Scope**: n, cells, seeds, censoring. Non-negotiable.

---

## Ledger

| ID | Claim | Value | Tier | Status | Scope (n / cells / seeds / censored) | Locator | Owner | Paper? |
|---|---|---|---|---|---|---|---|---|
| C-05-01 | Emissions at the grid ceiling equal E\* to within 0.01 % | ≤0.01 % | E3 | OPEN | 12 cells, seed 0, 0 censored | *needs promotion from Plan §6* | statistical-analyst | headline |
| C-05-02 | Median burden ratio at ceiling vs τ\* | 4.4× | E3 | OPEN | 12 cells | *needs promotion* | statistical-analyst | headline |
| C-05-03 | Max burden ratio (I25-M8-T12) | 18.6× | E3 | OPEN | 1 cell | *needs promotion* | statistical-analyst | headline |
| C-05-04 | Cold fixed-tax solve does not reproduce E\* at τ\* on 2 hardest cells | +0.035 %, +0.113 % | E3 | OPEN | 2 of 12 cells | *needs promotion* | optimization-expert | **disclosure** |
| C-03-01 | A1 (no Phase-2) loses τ\*-minimality | 6/6 cells | E3 | OPEN | 6 cells | *needs promotion* | statistical-analyst | yes |
| C-03-02 | A4 (coarse grid) biases τ\* upward via aliasing | 6/6 cells | E3 | OPEN | 6 cells | *needs promotion* | statistical-analyst | yes |
| C-08-01 | DBP vs enumeration agree exactly on exhausted cells | 2/2 exhausted; 3/4 overall | E3 | OPEN | 4 cells, 2 censored | *needs promotion* | optimization-expert | yes + **disclosure** |
| C-08-02 | Follower-solve reduction vs enumeration | ~180×, ~130× | E3 | OPEN | 2 exhausted cells | *needs promotion* | optimization-expert | yes |
| C-06-01 | demand:capacity is the strongest/near-strongest 2FI | mean rank 2.7/28 | E3 | OPEN | 6 series (3 responses × 2 seeds) | *no committed code — see P7* | statistical-analyst | yes |
| C-06-02 | demand & capacity in top-3 for every series | 6/6 | E3 | OPEN | 6 series | *no committed code* | statistical-analyst | yes |
| C-06-03 | Top-3 stability across seeds | emissions 3/3; cost 2/3; τ\* 2/3 | E3 | OPEN | 2 seeds | *no committed code* | statistical-analyst | **disclosure** |
| C-06-04 | Lenth PSE collapses on seed 1 (emissions, cost) | PSE ≈302, ≈14 | E3 | OPEN | seed 1 | *no committed code* | statistical-analyst | **disclosure** |
| C-07-01 | τ\*(ρ) is non-monotone, all runs certified | 7 values, gaps ≤1e-4 | E3 | OPEN | 1 cell, 7 ρ levels | *needs promotion* | statistical-analyst | **disclosure** |
| C-07-02 | Regime split: ρ≥10 lands τ\* in the 20–200 band | 5/7 levels | E3 | OPEN | 1 anchor cell | *needs promotion* | domain-expert | yes, conditional |
| C-07-03 | AUGMECON instrument gap vs physical minimum | ~0.5 % | E3 | OPEN | **n = 1 cell** | *needs promotion* | domain-expert | yes, scoped |
| C-04-01 | Growth in T is non-monotone | I17-M8-T6 2.6 h > both T12 cells | E3 | OPEN | 12 cells, seed 0 | *needs promotion* | optimization-expert | yes |
| C-04-02 | M12 probe censored at 0.96 % gap, real incumbent | 0.96 % | E3 | OPEN | 1 probe | *needs promotion* | optimization-expert | **disclosure** |
| C-03-03 | τ\* range and median across the 12 base cells | 1.4–167.3, median 22.6 USD/t | E3 | OPEN | 12 cells, seed 0 | *needs promotion; Plan §3 previously published a wrong median* | data-auditor | yes |
| C-07-04 | Only 6 of 12 cells have τ\* inside 20–200 USD/t at ρ=1 | 6/12 | E3 | OPEN | 12 cells | *needs promotion* | domain-expert | yes, **must accompany any band claim** |
| C-01-01 | All 12 cells terminate on relative_gap; worst gap 8.7e-5 | 38/38 runs | E3 | OPEN | 38 runs | *needs promotion* | data-auditor | appendix |
| C-02-01 | MIPFocus=2 decisive; threads 4 vs 6 unresolved | 3/3 vs 5/6 censored | E3 | OPEN | 11 runs, 1 hard cell | *needs promotion* | optimization-expert | appendix |

> Every row above starts at **E3 / OPEN by design** — these are the values currently asserted in
> `docs/Experimental_Plan.md` without locators. Promoting them is the first substantive job of this
> system. Rows marked *no committed code* additionally require the statistical layer to exist (P7).

---

## Contested claims

| ID | Claim | Position A (agent) | Position B (agent) | How it could be settled | Blocks |
|---|---|---|---|---|---|
| — | — | — | — | — | — |

## Retired / withdrawn claims

| ID | Claim | Why retired | Date | Superseded by |
|---|---|---|---|---|
| — | τ\* median ≈50 USD/t, "already inside the 20–200 band" | Recomputed: median is 22.6 and only 6/12 cells are in the band | 2026-08-03 | C-03-03, C-07-04 |
| — | P4 (plateau right edge) as a design point | Measured to coincide with P1 within 0.01 % on all 12 cells | Plan §14 | C-05-01 |

---

## Changelog

| Date | Change | By |
|---|---|---|
| `<ISO>` | Ledger created from `Experimental_Plan.md` §0–§14; all claims entered at E3/OPEN | project-manager |
