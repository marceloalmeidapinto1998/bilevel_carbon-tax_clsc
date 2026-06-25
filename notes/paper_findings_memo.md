# Paper findings memo — single source of truth for rewritten numbers

Generated from `results/analysis/` after `python -m tools.experiments.sensitivity analyze-all`
(2026-06-11). All raw values below are in base units (kg CO₂e for emissions, monetary units for
cost). The paper reports E\* in 10³ kg CO₂e and C\* in 10³ monetary units, so divide by 1000 when
typesetting. **Use these numbers, not anything from older drafts or memory.**

Source files: `results/analysis/tables/{master_runs,scenario_2x2,sensitivity_matrix,solver_robustness}.csv`,
`results/analysis/reports/SENSITIVITY_REPORT.md`.

---

## 1. Base bilevel runs (8 instances; method `lf_lex_exact`)

T12 instances are **not present** (deliberately dropped as intractable). All runs `validated`;
`exact=false` with `termination_reason=relative_gap` → describe as "validated, gap ≤ 10⁻⁴", **not
"exact"**.

| Instance | τ̂\* | τ\* | Cost | Emissions | Rel. gap | Time (s) |
|---|---|---|---|---|---|---|
| STD_I17_M4_T3 | 4  | 0.04 | 632,438   | 32,231,206  | 8.68e-9  | 36.7  |
| STD_I17_M4_T6 | 3  | 0.03 | 1,544,190 | 99,044,110  | 7.56e-10 | 51.8  |
| STD_I17_M8_T3 | 20 | 0.20 | 634,719   | 119,257,318 | 1.05e-6  | 127.0 |
| STD_I17_M8_T6 | 20 | 0.20 | 2,236,730 | 224,361,910 | 8.31e-10 | 1936.0 |
| STD_I25_M4_T3 | 15 | 0.15 | 430,707   | 15,898,097  | 8.85e-12 | 37.6  |
| STD_I25_M4_T6 | 2  | 0.02 | 910,086   | 31,533,254  | 1.61e-9  | 138.0 |
| STD_I25_M8_T3 | 2  | 0.02 | 982,039   | 130,002,141 | 8.0e-16  | 152.6 |
| STD_I25_M8_T6 | 7  | 0.07 | 2,117,591 | 144,753,884 | 7.17e-10 | 2367.0 |

- **τ\* range:** 0.02–0.20 USD/kg CO₂e, highly instance-specific. No single "right" tax.
- **Two instances hit the base ceiling τ̂=20** (I17_M8_T3, I17_M8_T6) → optimum is censored at the
  base range (see §4).
- **Follower-objective identity** Cost + τ·Emis = follower_objective holds (max residual 5.96e-8).

## 2. Solver behaviour & validation (supporting, not headline)

From `solver_robustness.csv` / report §4 — **all 95 runs validated (frac=1.0), 0 over target gap.**

| group | n | frac_validated | max_rel_gap | mean_iters | max_solve_s |
|---|---|---|---|---|---|
| all | 95 | 1.0 | 1.92e-5 | 2.45 | 18,578 |
| base | 8 | 1.0 | 1.05e-6 | 2.25 | 2,367 |
| scenario | 12 | 1.0 | 4.53e-6 | 2.50 | 18,578 |
| sensitivity | 75 | 1.0 | 1.92e-5 | 2.47 | 2,226 |

- DBP converges in ~2–3 iterations everywhere.
- **Largest runtime is 18,578 s** (≈5.2 h), the `STD_I25_M8_T3` *combined* scenario — **not** the
  289,795 s T12 anecdote in the old draft (that run no longer exists).

## 3. Sensitivity / drivers (OAT elasticities; report §1–2)

Mean |elasticity| across the 4 screened bases (I17/I25 × M4/M8, all T3):

| factor | cost elast. | emissions elast. |
|---|---|---|
| production_capacity | **0.58** | 0.04 |
| demand | **0.57** | **0.98** |
| production_emissions | 0.12 | **0.56** |
| return_availability | 0.09 | 0.002 |
| return_processing_cost | 0.05 | 0.001 |
| scope3_emissions | 0.04 | **0.42** |
| (bom_ratio, warehouse_cost, truck_capacity, tax_range, air_sea_cost) | ≤0.03 | ≤0.006 |

- **Cost** is driven by **production capacity (0.58) and demand (0.57)**; per-instance top factor is
  demand in 3/4 bases (production_emissions in I17_M8_T3).
- **Emissions** are driven by **demand (≈unit, 0.98)** and the **production + scope-3 emission
  intensities (0.56, 0.42)** — i.e. *what you make and what you buy*, not how you ship it.
- 31 perturbations fall below the 0.05% solver-noise floor; 8 structural perturbations have no
  scalar elasticity.
- **Morris screening is thin** (one trajectory / n_effects=1, single base STD_I17_M4_T3) — present
  as a preliminary confirmatory screen only, or relegate to appendix. It agrees that demand
  dominates.

## 4. Tax-range truncation / over-taxation pathology (key policy finding)

The leader is a **true lexicographic regulator: min emissions, then min τ̂** (confirmed
`src/solvers/dbp_lf_lex_exact.py:37`). Extended-range OAT runs (TAX40 → τ̂∈[0,40], TAX80 → [0,80])
show the emissions–tax response **saturates**: beyond a point, extra tax buys negligible abatement.

Examples (base vs extended, STD_I17_M4_T3 / I17_M8_T3 / I25_M4_T3 / I25_M8_T3):

| base inst. | base τ̂ (E) | TAX40 τ̂ (E) | TAX80 τ̂ (E) | interpretation |
|---|---|---|---|---|
| I25_M8_T3 | 2 (130.00M) | 36 (129.95M) | 36 (129.95M) | **18× tax for 0.04% abatement** |
| I25_M4_T3 | 15 (15.898M) | 31 (15.896M) | 31 (15.896M) | ~2× tax for 0.016% abatement |
| I17_M8_T3 | 20\* (119.257M) | 14 (119.258M) | 31 (119.257M) | emissions flat → τ\* unidentified in a wide band |
| I17_M4_T3 | 4 (32.231M) | 4 (32.231M) | 61 (32.209M) | stable until TAX80 chases 0.07% |

\* hit base ceiling. **Takeaway:** a pure emissions-minimizing leader is *ill-posed* on a saturating
frontier — it will chase vanishing abatement with unboundedly large taxes, and the optimal tax is
only weakly identified (a wide near-flat band). The min-τ̂ lexicographic tiebreak mitigates this only
up to solver tolerance. This motivates (a) reporting τ\* as a band, and (b) a cost-aware leader
objective as future work. **Do not** present base τ̂∈[0,20] τ\* as a sharp optimum for the censored
M8 instances.

## 5. Design-lever scenarios (2×2; `scenario_2x2.csv`)

Scenarios augment the 4 T3 bases: **technology** (more production/reman tech options, `G6_L6`),
**transport** (more transport modes, `TM12`), **combined** (both). Emissions vs base:

| base | base E | technology E (Δ) | transport E (Δ) | combined E (Δ) |
|---|---|---|---|---|
| I17_M4_T3 | 32.231M | 22.083M (**−31.5%**) | 32.242M (+0.03%) | 22.092M (−31.5%) |
| I17_M8_T3 | 119.257M | 80.440M (**−32.5%**) | 119.298M (+0.03%) | 80.515M (−32.5%) |
| I25_M4_T3 | 15.898M | 11.049M (**−30.5%**) | 15.920M (+0.14%) | 11.054M (−30.5%) |
| I25_M8_T3 | 130.002M | 96.661M (**−25.6%**) | 130.023M (+0.02%) | 96.725M (−25.6%) |

- **Dominant abatement lever = expanding cleaner production/remanufacturing technology
  (−26% to −33% emissions).** Expanding transport modes alone yields ≈0% (even marginally higher).
  Combined ≈ technology, i.e. technology is the binding lever; transport is inert.
- Cost effects are mixed (technology can raise cost a few %, e.g. I17 instances; but combined sharply
  cuts cost for I25, e.g. I25_M4_T3 430,707 → 248,285, −42%). Report deltas per instance; the robust
  qualitative claim is on **emissions**, where technology dominates and transport is inert.

## 6. Structural observations

- **Warehouses never open** in any incumbent (`warehouses ever open = 0`). The model permits them,
  but the cost/emission structure never makes them attractive → note as a structural finding /
  modelling caveat, not "the model has no warehouses."
- Remanufacturing share (≤~5% from prior notes) **not re-verified here** — needs network curves
  (currently absent; censoring/curve analysis was skipped). Do **not** cite a reman % until
  regenerated.

## 7. Things the old draft says that are now WRONG — fix everywhere

- "ten exact runs / 12 base instances / 2 T12 missing" → **8 base runs, no T12** (T12 intractable).
- "STD_I25_M8_T12 ≈ 289,795.8 s" → no T12 on disk; largest is **18,578 s** (I25_M8_T3 combined).
- "largest relative gap 3.54e-6" → **1.92e-5** overall, **1.05e-6** for base runs.
- Old path `results/base/*/lex_exact` → `results/runs/base/<inst>/lf_lex_exact`.
- tab_results_main numbers (τ\*=0.17, E\*=28,768k for I17_M4_T3, etc.) are from a superseded solve →
  rebuild entirely from §1.
- "exact" → "validated, gap ≤ 10⁻⁴".
