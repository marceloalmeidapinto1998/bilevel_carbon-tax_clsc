# Skeleton — "Results and Discussion"

> **Template** for the Scientific Writer. Ordered by **contribution**, not by experiment number.
> Every `<...>` is a claim that must exist in the ledger at tier E0–E2 before it is written.
> Target files: `paper/sections/06_computational_experiments.tex`, `07_discussion.tex`.

---

## RESULTS

### R0 — Testbed and verification gate  *(exp1; T1)*

One paragraph. Establishes that the numbers can be trusted before any of them are used.

- 12 structural cells, I ∈ {17,25} × M ∈ {4,8} × T ∈ {3,6,12}; tiers fast/standard/hard.
- Campaign configuration: fine tax grid (step `1e-4` USD/kg, indices 0…2000 = 0–200 USD/t),
  `dbp_relative_gap = 1e-4`, follower `mip_gap = 1e-6`, Phase-2 ON, `threads = 4`, `MIPFocus = 2`.
- Verification: `<n>` runs, all terminating on `relative_gap`, worst gap `<value>`; toy instances
  agree with manual derivation; Gurobi-seed probes return identical (E\*, τ\*).
- **Report all quantities as rates, never grid indices** (P1).

### R1 — Non-identification of the optimal tax  ★ headline  *(exp5; T2, Fig 1)*

- Define plateau P = {τ : E(τ) ≤ E\*(1+δ)}, δ = `dbp_relative_gap` = 1e-4; τ\* = min P; τ̄ = max P.
- **H5.1**: emissions at the grid ceiling equal E\* to within `<value>` on `<n>` of 12 cells.
  The plateau extends essentially to the top of the grid on every cell tested.
- τ\* across the 12 cells: `<range>`, median `<value>` USD/t.
- **Disclosure (H5.3)**: on the two hardest cells an independent *cold* fixed-tax solve does not
  reproduce E\* at τ\* (+`<v1>` %, +`<v2>` %, both above the 1e-4 tolerance). This bounds the
  precision of τ\* on hard cells. The mechanism (lexicographic freeze band) is **hypothesised**.

### R2 — Value of the bilevel leader  ★ headline  *(exp5; T3, Fig 2)*

- **H5.2**: τ\* attains E\* at strictly lower follower burden than the ceiling on `<n>`/12 cells.
- Median burden ratio `<value>×`, range `<lo>–<hi>×`; maximum on `<cell>`.
- The sentence the paper leads with: *identical certified emissions, up to `<max>×` the cost,
  depending only on which point of an unidentified plateau the regulator picks.*

### R3 — Benchmark against exhaustive enumeration  *(exp8; T5, Fig 5)*

- Why enumeration is the right baseline: the leader controls one integer on a finite grid, so
  scanning it is exact by construction and uses the *same* per-point follower solve.
- **Report coverage for every cell** (`2001/2001` exhausted vs `<k>/2001` censored).
- **H8.1**: exact agreement on `<n>`/4 cells. **Disclosure**: the fourth is censored, not
  disagreeing — at ≈37 s/point, reaching the left edge needed ≈3.5 h against a 2 h cap.
- **H8.2**: follower-solve reduction ≈`<a>×` and ≈`<b>×` on the two exhausted cells.
  Lead with solve counts; wall-clock corroborates.
- **Second, independent advantage — numerical robustness.** A 2001-point linear scan under a
  1e-7 comparator accumulated ~1e-8-relative solve noise into a false chain of improvements,
  inflating the reported tax by 51 %; DBP's O(log n) Phase-2 bisection is structurally immune.
  Fixed by adopting the plateau tolerance; validated by **replaying saved traces**, not re-solving.

### R4 — Ablation  *(exp3; T4)*

- Variants: M0 full; A1 no Phase-2; A2 no lexicographic Stage-2; A3 no warm start; A4 coarse grid;
  A5 no incumbent cut.
- **H3.1**: A1 loses τ\*-minimality on `<n>`/6 cells; emissions unchanged (ratio 1.0). This is the
  algorithm-side confirmation of R1.
- **H3.2**: A4 biases τ\* upward through aliasing on `<n>`/6 cells.
- **H3.3/H3.4**: A2/A3/A5 leave (E\*, τ\*) unchanged — the correct outcome for efficiency
  components. A5 is `<v>` % slower than M0: the cut is doing its job.
- State that A1/A4 are *faster by construction* and that speed is not evidence of merit.

### R5 — Scalability  *(exp4)*

- **Growth in T is non-monotone** — report it, do not smooth it.
- **Disclosure**: the M12 escalation probe censored at the hard-tier cap with a `<v>` % gap,
  reporting a real incumbent. Correct phrasing: *exact up to M8 within hard-tier limits; M12 is
  `<v>` %-gap censored, not exact, at the same limits.*
- No growth exponent is extrapolated from a 2×2×3 grid.

### R6 — Sensitivity  *(exp6; T6, Fig 3)*

- Design: 2^(8−2) resolution-V, 64 runs × 2 seeds; plus 2^(5−1) structural half-fraction, 16 runs.
- Report the empirical design-rank check (main+2FI, 37/37) before any effect.
- **H6.1**: `demand:capacity` strongest/near-strongest 2FI across `<n>` series.
- **H6.2**: `demand` and `capacity` in top-3 in 6/6 series. **Disclosure**: full top-3 stability is
  `<3/3>` for emissions but `<2/3>` for cost and τ\* — **partial**, not confirmed.
- **Disclosure**: Lenth's PSE collapsed on seed 1 (emissions, cost), violating sparsity-of-effects.
  Rank-based conclusions stand; those p-values are not published.
- Structural screen: `production_technology_menu` dominates emissions;
  `remanufacturing_technology_menu` dominates τ\* (expanding it *raises* the required tax);
  `sea_menu`/`air_menu` had exactly zero effect **on this one fast cell** — scoped, not generalised.

### R7 — Policy calibration and validity envelope  *(exp7; T7, Fig 4)*

- **Disclosure (H7.1 not supported)**: τ\*(ρ) is non-monotone across ρ ∈ {1,5,10,20,50,100,200},
  all seven certified at gaps ≤ 1e-4. This is a finding about the combinatorial mechanism, not a
  convergence artifact. **No log-linear fit is reported** — the premise is rejected by the data.
- **H7.2 by regime split**: ρ ∈ {1,5} give τ\* far below the band; ρ ≥ 10 all land inside
  20–200 USD/t across a 20× range of ρ.
- **Must accompany any band claim**: at the native valuation (ρ=1) only **6 of 12** cells have τ\*
  inside 20–200 USD/t.
- ρ\* = 1 was chosen for **internal consistency, not external anchoring** — stated as a weakness.
- The AUGMECON anchor's ~0.5 % tax-instrument gap is observed on **one cell**; scope it.

---

## DISCUSSION

*Interprets. Introduces no new numbers.*

1. **What non-identification means for a regulator.** A flat leader objective means the tax is not
   pinned down by the emissions target; some selection rule is unavoidable, and choosing badly
   costs the regulated firms up to `<max>×` at identical certified emissions.
2. **The contribution is the tie-break, not the decomposition.** exp3's A1 shows that removing
   Phase-2 still certifies the right E\* and returns an arbitrary plateau point — the
   least-intervention rule is the load-bearing component.
3. **Two independent arguments for DBP**: two orders of magnitude fewer follower solves, *and*
   structural immunity to the noise-accumulation failure that a long linear scan suffers.
4. **The boundary of the monetary claims.** Conditional form only: *if* the emissions valuation is
   at least an order of magnitude above the generator's native scale, τ\* lands in the plausible
   band and stays there across a 20× range of ρ.
5. **Limitations** — from `limitation_register.md`, not invented here.
6. **Future work** — from `future_work.md`, each item tied to a limitation.

---

## Writer's checklist

- [ ] Every number traces to a ledger claim at E0–E2.
- [ ] Every claim sentence carries n, cells, and certification status.
- [ ] All seven disclosures above appear in the main text.
- [ ] Results contains no interpretation; Discussion contains no new numbers.
- [ ] Tax reported in USD/t everywhere; emissions in kt CO₂e; money in 10⁶ USD.
- [ ] Tables `\input` from `results/analysis/campaign_01/tables/`; figures from `.../figures/`.
- [ ] Decimal marks converted from the plan's `,` to `.`.
- [ ] No promotional adjectives; no "significant" without a test; no "optimal" for a censored run.
