# STANDARD — Scientific writing and notation

Binding on the Scientific Writer and the Editor. Target venue: an OR / sustainable-operations
journal (Elsevier-style; see `paper/styles/preamble.tex`).

---

## 1. Voice

- Past tense for what was done and measured; present for what the model *is* and what results
  *show*. "We solved 381 runs"; "the plateau extends to the grid ceiling".
- First person plural ("we") is acceptable and preferred over passive contortions.
- No hedging stacks: "may possibly suggest" → "suggests". One hedge or none.
- No promotional adjectives: novel, powerful, comprehensive, significant (unless statistically),
  extensive, state-of-the-art. Let the number carry it.
- No unearned causality. "τ\* rises with the remanufacturing menu" (measured) not "expanding the
  menu forces the regulator to tax more" (mechanism, unless demonstrated).

## 2. Every claim sentence has a number and a source

A Results sentence takes the shape:

> *[what was measured] [value with unit] [scope: n, cells, seeds] [certification status]*

> "Across the 12 structural cells the burden at the tax ceiling exceeds the burden at τ\* by a
> median factor of 4.4× (range 1.2–18.6×; all 12 cells certified at gap ≤ 1e-4)."

Not: "The bilevel leader delivers substantial savings."

Discussion may interpret without numbers, but must not introduce new ones. Any number in the
Discussion that does not appear in Results is a defect.

## 3. Units and notation — the canon

| Quantity | Unit in text/tables | Notes |
|---|---|---|
| Emissions | **kt CO₂e** | model works in kg; `EMISSIONS_SCALE = 1e6` |
| Money | **10⁶ USD** | state the multiplier in the column header |
| Carbon tax | **USD/t CO₂e** | **never** a grid index (P1) |
| Runtime | **s** in tables, **h** in budget prose | shifted geometric mean + median + IQR |
| Gap | **%** with the tolerance stated | e.g. "0.96 % gap against a 1e-4 threshold" |

Symbols: τ (tax rate), τ\* (least-intervention tax = plateau left edge), τ̄ (plateau right edge),
E(τ) (follower's optimistic emissions response), E\* = min_τ E(τ), plateau
P = {τ : E(τ) ≤ E\*(1+δ)} with δ = 1e-4, plateau width = τ̄ − τ\*, ρ (emissions-valuation rescale).

Symbols must match `paper/tables/tab_notation.tex`, which must match
`src/clsc/models/instance.py`. Three-way agreement, checked by the Editor.

Decimal marks: the manuscript uses `.`; note that `docs/Experimental_Plan.md` uses the Portuguese
`,` (e.g. "0,96 %"). **Convert when quoting from the plan into the paper** — this is a real and
easy-to-miss transcription hazard.

## 4. Structure of "Results and Discussion"

Results reports; Discussion interprets. Do not merge them into "here is a number and what I think
it means" paragraphs — referees read them for different things.

**Results**, ordered by contribution, not by experiment number:
1. Testbed and verification gate (one paragraph + T1) — establishes the numbers can be trusted.
2. **Non-identification of the optimal tax and the value of the leader** (exp5) — headline, T2/T3,
   Fig 1/2.
3. Algorithm: benchmark vs enumeration (exp8, T5, Fig 5) then ablation (exp3, T4).
4. Scalability (exp4) — with the non-monotonicity and the censored M12 anchor stated.
5. Sensitivity (exp6, T6, Fig 3) — with the Lenth caveat.
6. Policy calibration and validity envelope (exp7, T7, Fig 4).

**Discussion**: what the plateau means for regulator practice; why the tie-break is the
contribution rather than the decomposition; the two independent advantages of DBP (cost *and*
numerical robustness); the boundary of the monetary claims; limitations; future work.

Appendices: exp1 (verification), exp2 (solver configuration).

## 5. Reporting negative and awkward results

Mandatory, non-negotiable, and stated in the main text — not relegated to a footnote:

- **H7.1 not supported.** τ\*(ρ) is non-monotone. All seven runs certified. This is a finding about
  the combinatorial mechanism, not a convergence artifact. Report the sequence.
- **H6.2 partial.** Confirmed for emissions (3/3), partial for cost and τ\* (2/3 each). Say
  "partial", give the split.
- **exp8 3/4.** The fourth cell is censored, not disagreeing. Say which, and why (≈37 s/point ×
  index 346 needed ≈3.5 h against a 2 h cap).
- **exp5 H5.3.** Cold-solve discrepancy on the two hardest cells bounds τ\*'s precision.
- **exp6 Lenth PSE.** Assumption failure on seed 1; rank conclusions stand, p-values not published.
- **exp4 M12.** Censored at 0.96 %; frontier anchored, not resolved.

The paper is stronger for these, not weaker. A reviewer who finds an unreported one discounts
everything else.

## 6. LaTeX conventions

- Tables: `booktabs` (`\toprule/\midrule/\bottomrule`), no vertical rules. Generated tables live in
  `results/analysis/campaign_01/tables/t*.tex` and should be `\input` rather than pasted (P9).
- Figures: vector PDF from `results/analysis/campaign_01/figures/`. Captions state n, the cells,
  and the certification status.
- Every table and figure is referenced in the text before it appears.
- Macros in `paper/styles/macros.tex`. Do not hard-code a symbol that has a macro.
- Cross-references via `\ref`/`\label`; never "the table above".

## 7. Caption standard

A caption must be readable standalone:

> **Table 3.** Policy-rule comparison on the 12 structural cells. Each rule is evaluated at the
> same certified emissions floor E\*; burden is the follower objective. n = 12 cells, seed 0, all
> runs certified at relative gap ≤ 1e-4. Tax in USD/t CO₂e, burden ratio dimensionless.
> Source: `t3_policy_rules.csv`.
