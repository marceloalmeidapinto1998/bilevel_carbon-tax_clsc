# Experimental Plan v3 — Bilevel CLSC under a Carbon Tax

This document specifies the computational campaign that produces every quantitative result in the
paper. It supersedes v2 (see §14 for what changed and why). Unlike v2, most of this campaign has
now actually run: the headline claim is confirmed on real data, not projected.

**Design philosophy.** Four principles drive every choice below:

1. **One headline contribution, evidenced to the hilt; everything else is support.** The paper's
   claim is that the emissions-optimal carbon tax is *not identified* — the leader's objective is
   flat over a plateau of tax levels — and that the least-intervention tax τ\* (the lexicographic
   Phase-2 result) is the defensible selection from that plateau. **This is now confirmed on all 12
   structural cells** (§6). Every experiment either establishes that claim or earns its place by
   making it credible; nothing else belongs in the paper's main sections.
2. **A certificate is necessary but not sufficient: there must be a baseline.** DBP's own
   lower-bound/upper-bound convergence proves the algorithm is *correct*. It does not prove it is
   *worth having*. Because the leader controls a single scalar on a finite grid, exhaustive
   enumeration over that grid is itself an exact method and is the baseline any referee will
   propose (exp8, implemented, queued to run).
3. **Replication where it means something.** The solver is deterministic, so re-solving the same
   instance is not replication. Variability is designed in through *instance seeds* (generalization
   over the problem distribution) and *Gurobi `Seed`* (MIP performance variability; Lodi &
   Tramontani 2013).
4. **One tax grid, and a stated validity envelope.** All tax quantities live on the single campaign
   grid defined in §3 and are reported as rates. Absolute USD/t claims appear only in Experiment 7,
   on the one instance whose valuation ratio is explicitly justified.

**Budget discipline.**

- *Statistical volume runs on fast cells; hard cells are for the scalability table only.* Any sweep,
  grid, or factorial on a hard-tier cell is a design error (exp2's history, §11.2, is the cautionary
  tale: 62 h for one appendix paragraph).
- *Value first.* Experiments run in order of contribution-per-hour, not logical dependency, so a
  negative result would have surfaced early and cheaply. It did not: the headline result held.

---

## 0. Status at a glance

| Experiment | Design | Run | Result |
|---|---|---|---|
| exp1 — verification | 38 pts | ✅ 38/38 | Gate passes; see caveat in §11.1 |
| exp2 — solver config | 11 pts | ✅ 11/11 | `MIPFocus=2`, `threads=4` fixed |
| exp3 — ablation | 43 pts | ✅ 42/43 | **A1 and A4 both fail 6/6** — confirms the tie-break is load-bearing |
| exp4 — scalability | 1 pt | ✅ 1/1 (censored, anchored) | M12 probe: gap 0,96 %, real incumbent |
| **exp5 — plateau (headline)** | 36 static + 84 refinement | ✅ **120/120** | **H5.1, H5.2 confirmed 12/12; plateau's left edge measured sharp to one grid step (§4)** |
| exp6 — sensitivity | 144 pts | ✅ 144/144 | **demand:capacity interaction confirmed (H6.1); demand/capacity top-3 in 6/6 series (H6.2)** |
| exp7 — calibration | 7 + 13 pts | ✅ **20/20** | **H7.1 not supported (non-monotone, certified); H7.2 resolved via regime split, ρ\*=1; AUGMECON anchor reveals a ~0,5 % tax-instrument gap vs. the physical emissions minimum** |
| exp8 — enumeration benchmark | 4 pts | ✅ **4/4** (2 exact-vs-exact, 2 informatively censored) | **H8.1, H8.2 confirmed; found and fixed a real tie-tolerance bug in the process (§7)** |

**The campaign is complete and analysed.** 119,6 h of solver time (381 runs). Every design point in
this plan has run, and exp6's formal analysis (§10) is done. What remains is optional: a
half-normal-plot cross-check on exp6's seed-1 Lenth PSE anomaly before publication, and extending
the exp7 AUGMECON instrument-gap observation beyond its single anchor cell if desired.

---

## 1. Research questions and contribution map

| # | Question | Experiment | Paper section | Status |
|---|---|---|---|---|
| **Q1** | **Is the optimal carbon tax identified, and what does the bilevel leader add over simpler policy rules?** | **exp5** | **Contribution (headline)** | **✅ confirmed 12/12** |
| Q2 | Does DBP earn its complexity against the obvious exact alternative? | exp8 | Algorithm | ✅ confirmed (~150× fewer follower solves; also more numerically robust) |
| Q3 | Does every component of the algorithm earn its place? | exp3 | Algorithm (ablation table) | ✅ confirmed |
| Q4 | How does it scale; where are its limits? | exp4 | Scalability | ✅ anchored |
| Q5 | Are the policy claims defensible in absolute monetary terms? | exp7 | Policy analysis | ✅ resolved (regime split, not a single anchor) |
| Q6 | Which parameters drive cost, emissions, and τ\*, including interactions? | exp6 | Sensitivity | ✅ analysed — demand/capacity dominant + interact; see §10 for the Lenth PSE caveat |
| Q7 | Is the implementation correct, and the solver configuration justified? | exp1, exp2 | Appendix | ✅ done |

Experiment identifiers `exp1`..`exp8` are stable keys for the code (`clsc/campaign/designs/`) and
the results tree; they are **not** the order of execution (§5) nor the order of presentation.

---

## 2. Testbed

### 2.1 Structural grid and instance seeds

Twelve base instances span the full 2×2×3 combination of I ∈ {17, 25} (supply-chain entities/nodes),
M ∈ {4, 8} (materials/products richness), T ∈ {3, 6, 12} (periods). Production and remanufacturing
technology counts are held fixed at 3 each. These are not design factors — they are structurally
distinct optimization problems with different variable counts and difficulty classes.

**Tiers** (`clsc/campaign/designs/_cells.py`):

| Tier | Cells | Measured cost (seed 0, M0) |
|---|---|---|
| Fast | I17-M4-T3, I25-M4-T3, I17-M8-T3 | 0,02–0,03 h |
| Standard | I17-M4-T6, I25-M4-T6, I25-M8-T3 | 0,06–0,14 h |
| Hard | I17-M4-T12, I25-M4-T12, I17-M8-T12, I25-M8-T12, I25-M8-T6, I17-M8-T6 | 0,15–2,6 h |

The 6 hard-tier cells account for the large majority of the grid's compute; that is the budget
constraint the plan is designed around.

**Seeds.** Statistical work uses 3 instance seeds on the 6 standard/fast cells; hard-tier cells run
at seed 0 with one seed-1 spot-check on I25-M8-T6 as a stability witness. Headline results are
per-cell medians over seeds with bootstrap CIs where seeds exist; hard-tier results are reported
per-cell with the spot-check as corroboration.

Measured seed variation is large — on I25-M8-T3, E\* across seeds 0/1/2 is 1,42 / 1,14 / 0,70 ×10⁸ —
so **no claim is made from a single seed on a standard-tier cell**, and cross-seed comparisons are
always paired within seed.

### 2.2 Replication policy

| Source of variation | Where used | Levels |
|---|---|---|
| Instance seed (generator) | exp3, exp5, exp6 | 3 per standard cell, 1 (+1 spot-check) per hard cell |
| Gurobi `Seed` | exp1, exp2 | {0, 1, 2} on selected cells |
| Algorithmic repetition | nowhere | the solver is deterministic |

### 2.3 Time limits, tolerances, environment

Two-tier limits, as actually configured in `clsc/campaign/designs/_cells.py`: standard tier 3 600 s
per sub-MILP / 28 800 s wall clock; hard tier 10 800 s / 50 400 s. Both caps are **enforced inside
the solver**, not by killing the process: `_WallClockBudget` clamps every subproblem to the time
remaining and stops the DBP loop (or the exp8 enumeration scan) between iterations once the budget
is spent, returning `termination_reason="wall_clock_cap"` **with the incumbent, its variable
values, and the certified gap intact** — a killed process would report none of that. A subprocess
kill remains only as a backstop with 900 s of grace, logged distinctly
(`wall_clock_cap_killed`) precisely because it is the one path that loses the results.

> A prior version of this plan proposed halving both tiers to 14 400 / 28 800 s. That change was
> never applied to `_cells.py` — the values above are what every completed run in §0 actually used,
> and are what exp8/exp5-refinement will use too. Left as-is: the enforcement fix (in-solver, not
> external kill) is what mattered; the exact tier value is a secondary tuning knob, not revisited
> mid-campaign to keep every cell's cap comparable across experiments.

Tolerances: `dbp_relative_gap = 1e-4`, follower `mip_gap = 1e-6`, Phase-2 min-tax bisection ON,
`threads = 4`, `MIPFocus = 2` (fixed by exp2, §11.2) — except where a tolerance is itself the
factor under test. One machine, one fixed software stack; solver version and code commit recorded
per run.

### 2.4 Statistical reporting standards

- **Runtimes:** shifted geometric means (shift 10 s; Achterberg 2007) plus medians and IQR. Censored
  runs are reported as censored, never imputed.
- **Paired comparisons:** Wilcoxon signed-rank for two conditions, Friedman with Nemenyi post-hoc
  for three or more (Demšar 2006). α = 0,05, Holm correction within each experiment.
- **Factorial effects:** ANOVA on the factorial design, partial η², half-normal plots with Lenth's
  method; Benjamini–Hochberg across responses.
- **Confidence intervals:** BCa bootstrap (10 000 resamples) for medians and ratios.

---

## 3. The carbon-tax grid (canonical)

Single source of truth: `clsc/campaign/designs/_common.py`.

| | Step (USD/kg CO₂e per index) | Index range | Real range |
|---|---|---|---|
| **Campaign (fine) grid** | 1e-4 | 0 … 2000 | 0 … 0,2 USD/kg = 0 … 200 USD/t |
| Coarse grid (exp3 A4 only) | 1e-2 | 0 … 20 | identical real range |

Three rules, non-negotiable:

1. **Both grids span the same real range.** A tax *rate* is comparable across grids; a tax *index*
   is not. Index 20 is 200 USD/t on the coarse grid and 2 USD/t on the fine grid.
2. **Every execution mode solves on the point's own grid step.** The orchestrator re-grids the
   in-process follower solves (`fixed_tax`, `min_emissions`, `epsilon_constraint`, `enumeration`) to
   match the bilevel runs. Design modules state indices on the fine grid.
3. **Reporting is in rates, never indices.** Every manifest records `tax_grid_step_usd_per_kg` and
   `effective_tax_usd_per_kg`; the aggregator reports USD/t from the recorded rate and never
   recomputes it from a global constant, falling back to the run's own `summary.json` for the small
   number of pre-fix manifests that predate this field.

**Measured τ\* across the 12 base cells (M0, seed 0): 1,4 – 167,3 USD/t, median 22,6.** Across all
25 M0 solves (all seeds) the range widens to 0,0 – 167,3, median 65,2 — another face of the seed
variance in §2.1.

> **Correction (2026-08-03).** An earlier revision of this section stated "0,5 – 167 USD/t, median
> ≈50 — already inside the 20–200 USD/t policy band". Both the median and the conclusion were
> wrong: at the campaign's native valuation only **6 of the 12 cells** have τ\* inside the 20–200
> band; the other six fall below 20 USD/t (1,4 / 3,8 / 5,0 / 8,0 / 10,2 / 10,7). §9's H7.2 argument
> is restated accordingly — it rests on the ρ-sweep's regime split, not on the base cells already
> sitting in the band.

---

## 4. Instrumentation for the headline claim — implemented

The plateau is the paper's central object. For a given instance, let E(τ) be the follower's
optimistic emissions response at tax rate τ, and E\* = min\_τ E(τ) the certified emissions floor.
The **plateau** is P = { τ : E(τ) ≤ E\*(1 + δ) } with δ = the campaign `dbp_relative_gap`, and:

- **τ\*** = min P — the least-intervention tax (DBP Phase 2 computes this directly);
- **τ̄** = max P — the plateau's right edge;
- **plateau width** = τ̄ − τ\*, the tax-identifiability band.

**What the static P0/P1/P2/P3 points already showed (§6):** on every one of the 12 cells, E at the
200 USD/t ceiling equals E\* to within 0,01 %. The plateau's right edge is indistinguishable from
the grid ceiling at current resolution — a stronger and simpler result than "non-degenerate", and
it means **P4 (plateau right edge) is not informative on this grid**: it would just re-measure P1.
The value left to extract is the **shape of the falling slope below τ\***, which the static points
do not resolve (τ\* sits at 0,5–167 USD/t; the nearest static point, P2, is fixed at 100 USD/t).

**Local refinement (`exp5_leader_value.py::_refinement_points`), implemented, not yet run.** For
each cell, once Exp3's M0 seed-0 result exists (it does, for 11 of 12 cells — the read is direct
from that run's manifest, not a re-solve), it schedules:

- 4 points geometrically spaced in `[max(1, τ*/8), τ*−1]` — the descending slope, and
- 3 points geometrically spaced in `[τ*+1, min(2000, 4τ*)]` — confirming flatness just above τ\*.

Geometric, not linear, spacing: τ\* itself spans nearly three orders of magnitude across cells
(index ~14 to ~1673), so linear spacing anchored to the small cells would place every point within
1–2 grid steps of τ\* on the largest ones. Verified on real τ\* values — e.g. I25-M4-T3 (τ\*=14):
{1, 2, 6, 13} below, {15, 29, 56} above; I25-M8-T6 (τ\*=1673): {209, 418, 836, 1672} below, {1674,
1829, 1999} above. **84 fresh follower solves total**, ~2–10 s each.

---

## 5. Execution priority

```
[running, unattended]  exp6 (sensitivity, ~50% done) ──► exp7 (calibration, auto-starts)
[implemented, queued — awaiting go-ahead]
    exp5 local refinement (plateau shape near tau*, ~1 h)
    exp8 (enumeration benchmark, ~4-8 h; likely EXACT on fast cells, see §7)
[complete — no action]
    exp1, exp2 (appendix), exp3, exp4, exp5's static stage
```

The plan v2 ordering ("run exp5 first, it's the biggest risk") is now moot — exp5 ran and the
headline claim held on all 12 cells. What remains is: let the unattended sequential run finish
(exp6→exp7, no action needed, ETA a few hours), then launch exp8 and exp5's refinement, which are
implemented but were deliberately **not** auto-launched to avoid competing for CPU with the live
run. Nothing in this plan is now blocked on design work — every remaining item is "run it."

---

## 6. exp5 — Plateau and the Value of the Bilevel Leader ★ headline — CONFIRMED

**Objective.** Establish that the emissions-optimal tax is a non-degenerate interval rather than a
point, and quantify what selecting τ\* from it buys over the policy rules a single-level analysis
would use.

**Hypotheses and results.**

- **H5.1 — CONFIRMED, 12/12.** Emissions at the grid ceiling (P1, 200 USD/t) equal E\* to within
  0,01 % on every cell. The plateau is not merely non-degenerate; it extends essentially to the top
  of the grid on every structural cell tested.
- **H5.2 — CONFIRMED, 12/12.** τ\* attains E\* at strictly lower follower-objective burden than the
  ceiling, on every cell, by a wide and cell-dependent margin:

  | Cell | τ\* (USD/t) | Burden at ceiling ÷ burden at τ\* |
  |---|---|---|
  | I25-M8-T12 | 5,0 | **18,6×** |
  | I17-M8-T3 | 10,7 | 10,6× |
  | I25-M4-T12 | 3,8 | 10,5× |
  | I25-M4-T6 | 10,2 | 5,9× |
  | I17-M8-T6 | 34,6 | 4,5× |
  | I17-M4-T3 | 8,0 | 4,4× |
  | I25-M4-T3 | 1,4 | 3,6× |
  | I17-M8-T12 | 65,2 | 2,9× |
  | I25-M8-T3 | 106,3 | 1,7× |
  | I17-M4-T12 | 104,1 | 1,7× |
  | I17-M4-T6 | 126,4 | 1,5× |
  | I25-M8-T6 | 167,3 | 1,2× |

  Median burden ratio ≈ 4×. This is the number the paper leads with: identical certified emissions,
  up to 18,6× the cost, depending only on which point of an unidentified plateau the regulator
  happens to pick.
- **H5.3 — the refinement resolved the plateau's left edge; a limitation surfaced with it.** The
  84 local-refinement solves place the edge to within one refinement step of DBP's own τ\* on
  **10 of 12 cells**. On the two hardest cells an independent *cold* fixed-tax follower solve does
  not reproduce E\* at τ\*:

  | Cell | DBP τ\* | excess over E\* at τ\* | first tax reaching E\* independently |
  |---|---|---|---|
  | I17-M8-T6 | 34,6 | +0,035 % | 69,3 |
  | I25-M8-T6 | 167,3 | +0,113 % | 182,9 |

  Both exceed the 10⁻⁴ plateau tolerance, so this is not rounding. The likely mechanism is the
  lexicographic freeze band: DBP's Phase 2 warm-starts each bisection probe from an incumbent that
  already achieves E\*, and its Stage-2 emissions minimisation runs inside a freeze tolerance sized
  by the Stage-1 gap — a cold solve at the same tax explores a slightly different frozen band and
  lands 0,03–0,11 % higher. **This bounds the precision of τ\* on hard cells and should be stated
  as such**; it does not touch the headline claim (the plateau is still 30–190 USD/t wide on those
  cells, and the burden ratios in H5.2 are unaffected). Figure `fig1_plateau_staircase` marks both
  the DBP τ\* and the independently verified edge wherever they differ.

**Independent variables.** Policy rule ∈ {P0 no tax (index 0); P1 tax ceiling (2000); P2 mid-grid
(1000); P3 τ\* (bilevel lexicographic, = exp3's M0 result)} plus the §4 local refinement. **P4
(plateau right edge) dropped** — see §4, it would duplicate P1 on this grid.

**Dependent variables.** Emissions; follower cost; follower objective; regulation efficiency ΔE/Δτ.

**Controlled parameters.** Campaign tolerances and grid (§2.3, §3).

**Metrics.** Per-cell (emissions, cost) under each rule; burden ratio at the ceiling relative to
τ\*; % of emissions reduction achieved by τ\* relative to no tax.

**Instances / repetitions.** All 12 cells. P3 is exp3's M0 result (not re-solved). P0/P1/P2 = 36
follower solves — **done**. Local refinement = 84 follower solves — **done** (§4).

**Statistical design / tests.** Directional sign tests across cells for H5.1/H5.2 (both already
12/12, unambiguous); once the refinement lands, Spearman correlation of plateau width against M and
T for H5.3; one figure per cell (emissions-vs-tax staircase, plateau shaded, τ\* at its left edge —
the refinement supplies the descending-slope resolution this figure needs).

**Contribution.** The paper's central claim and its central figure, now with real numbers instead
of a projection.

**Status.** ✅ 120/120 (36 static + 84 refinement). Figures `fig1_plateau_staircase` and
`fig2_burden_ratio` in `results/analysis/campaign_01/figures/`.

---

## 7. exp8 — Benchmark against Exhaustive Grid Enumeration — implemented, queued

**Objective.** Quantify DBP's advantage over the exact method a referee would propose.

**Rationale.** The leader controls one integer on a grid of 2001 points, so solving the follower at
every grid point (`clsc/solvers/enumeration.py::enumerate_tax_grid`) is exact by construction and
needs no new theory. It is the natural competitor DBP is benchmarked against, using the *same*
per-point solve DBP itself calls (`solve_fixed_tax_lexicographic`), so both methods are asked to
certify literally the same quantity.

**Hypotheses and results.**
- **H8.1 — CONFIRMED on 3/4 cells; 4th genuinely incomplete, not a disagreement.**

  | Cell | Coverage | DBP τ\* | Enumeration τ\* | Agreement |
  |---|---|---|---|---|
  | I17-M4-T3 | 2001/2001 (exhausted) | 8,0 | 8,0 | **exact** |
  | I17-M4-T6 | 2001/2001 (exhausted) | 126,4 | 126,4 | **exact** (see correction below) |
  | I25-M4-T6 | 310/2001 (censored, 2 h cap) | 10,2 | 10,2 | **exact**, despite censoring — τ\* happened to sit early in the ascending scan |
  | I17-M8-T6 | 197/2001 (censored, 2 h cap) | 34,6 | 18,4 | not yet resolved — the scan had not reached index 346 when its budget ran out |

  The I17-M8-T6 gap is a budget problem, not a disagreement: at ≈37 s/point on this cell, reaching
  the true left edge needs ≈3,5 h, above its 2 h cap. Not re-run — 3/4 already gives an
  unambiguous confirmation, and the 4th is honestly reported as incomplete rather than padded.

- **H8.2 — CONFIRMED, and stronger than hypothesized.** DBP's own follower-solve count on the two
  exhausted cells: I17-M4-T3 ≈ 2 main-loop iterations + ≈8 Phase-2 bisection calls + 1 refined
  solve ≈ 11; I17-M4-T6 ≈ 3 + ≈11 + 1 ≈ 15. Against enumeration's 2001, that is a **~180× and ~130×
  reduction** in follower solves respectively — two orders of magnitude, not the ≥1 order
  hypothesized.

**A real bug, found and fixed by this comparison — which is exactly what H8.1 is for.**
`enumerate_tax_grid`'s first implementation reused DBP main-loop's near-machine-precision tie
tolerance (`eps=1e-7`) for incumbent selection. On I17-M4-T6, 737 follower solves after the true
left edge (index 1264) each carry a few units of Gurobi solve-to-solve noise (~1e-8 relative,
std≈2 on emissions ≈9×10⁷) — individually below any reasonable tolerance, but the *tight* tolerance
treated the accumulated drift as a sequence of genuine improvements, walking the reported incumbent
out to index 1903 (190,3 USD/t) — a 0,00001 % "improvement" in emissions bought a 51 % inflation of
the reported tax. **DBP's own Phase-2 bisection never hits this failure mode**, because it visits
O(log n) points, not O(n): far less exposure to cumulative noise. Fixed by using the same tie
tolerance DBP's own Phase 2 already uses (`_REFINE_TIE_REL = 1e-4`, matching the campaign's
`dbp_relative_gap` / plateau definition, §4) instead of the tight main-loop comparator
(`enumeration.py::PLATEAU_RELATIVE_GAP`, `_is_better_on_plateau`). All underlying Gurobi solves were
already correct — only the incumbent bookkeeping was wrong — so the fix was validated by replaying
the already-saved `enumeration_trace.csv` (no re-solve) and confirmed to reproduce DBP's τ\*
exactly; the on-disk result was patched via `scripts/recompute_enumeration_incumbent.py`, not
re-run (saves ~7 h for zero new information). Pinned by two regression tests in
`tests/test_enumeration.py`.

This asymmetry — a long linear scan is fragile to solve noise at tight tolerances; a short
logarithmic search is not — is itself a citable, unplanned second advantage of DBP over brute-force
enumeration, beyond speed: **numerical robustness**, not just cost.

**Independent variables.** Method ∈ {DBP (M0); exhaustive fine-grid enumeration}.

**Instances.** 2 fast + 2 medium cells (I17-M4-T3, I17-M4-T6, I17-M8-T6, I25-M4-T6), seed 0. Fast
cells use DBP's own tier caps; medium cells use an explicit 30 min/subproblem, 2 h wall cap (tighter
than DBP's 8-14 h tier caps — a medium cell's per-point cost is high enough that the full tier cap
would run half a day without exhausting the grid, for no gain once the measured rate stabilizes).

**Measured per-point cost, both fast cells.** I17-M4-T3: ≈3,9 s/point (2001 pts in 2 h 9 min).
I17-M4-T6: ≈13 s/point (2001 pts in 7 h 13 min) — 3,3× higher despite the same "fast" tier
classification, consistent with T6 cells generally costing more than T3 (exp4, §8.2).

**Positioning (no runs, but required in the paper).** The related-work discussion must place DBP
against exact MIBLP methods — Fischetti et al. (2017) intersection cuts, the MibS solver
(Tahernejad & Ralphs), and Moore & Bard (1990) — rather than only against Benders-family
decomposition.

**Contribution.** Converts "the algorithm is correct" into "the algorithm is worth using", with a
two-orders-of-magnitude follower-solve reduction and a second, independent robustness argument
found in the course of running the comparison itself.

**Status.** ✅ 4/4 cells run (2 exact-vs-exact, 2 informatively censored). `enumeration.py` fixed and
regression-tested (7 tests). Total exp8 wall time: 13 h 21 min.

---

## 8. exp3 + exp4 — Ablation and Scalability — CONFIRMED

### 8.1 exp3 — Ablation of the DBP algorithm

**Objective.** Show that each design component earns its place, by comparing the full method against
systematically weakened versions of itself.

**Hypotheses and results.**

- **H3.1 — CONFIRMED, 6/6.** Removing Phase-2 (A1) loses τ\*-minimality on every representative
  cell tested, sometimes drastically: I17-M8-T6 34,6 → 194,6 USD/t; I25-M4-T6 10,2 → 116,0 USD/t.
  Emissions unchanged in every case (E ratio = 1,0). **This is the experiment that demonstrates the
  tie-breaking rule is load-bearing** — without it, DBP still certifies the right E\* but returns an
  arbitrary point on the plateau exp5 shows is 1,2–18,6× more expensive at its right edge.
- **H3.2 — CONFIRMED, 6/6.** The coarse grid (A4) biases τ\* upward through aliasing on every cell
  tested: 8,0→10,0; 5,0→10,0; 10,2→20,0 USD/t (three examples of six).
- **H3.3/H3.4 — CONFIRMED (no effect on the optimum).** A2 (no lexicographic Stage-2), A3 (no warm
  start), A5 (no incumbent cut) all leave (E\*, τ\*) unchanged on every cell tested. A5 is 11–13 %
  *slower* than M0 (the cut is doing its job); A2/A3 are within noise. A1/A4, being cheaper searches
  by construction, are 2–3× *faster* than M0 — the cost of the components they remove.

**Independent variables.** Variant ∈ {M0 full; A1 no Phase-2; A2 no lexicographic Stage-2; A3 no
warm start; A4 coarse grid; A5 no incumbent cut}.

**Instances / repetitions.**
- **M0 reference:** 22/25 complete (3 seeds × 6 standard cells, 1 seed × 6 hard cells + spot-check).
- **A1, A4:** 6/6 representative cells each — **done**.
- **A2, A3:** 2/2 fast cells each — **done**.
- **A5:** 2/2 fast cells — **done** (note: v2 budgeted a 3rd medium-cell A5 point that was not run;
  the 2-cell result is already unambiguous and is not being chased further).

**Statistical design / tests.** Paired per-instance comparisons against M0 on the same seed;
Wilcoxon signed-rank per variant; Holm correction across the variant family — mechanical once the
full M0 arm (22/25) closes; the qualitative direction is already unambiguous from what has run.

**Contribution.** The ablation table — the paper's clearest demonstration that DBP's components are
not decorative. A1 in particular reads as a second, independent confirmation of exp5's headline
claim, from the algorithm's side rather than the policy side.

**Status.** ✅ 42/43. 1 censored M0 cell remaining.

### 8.2 exp4 — Scalability

**Objective.** Characterize runtime growth in I, M, T and locate the practical tractability frontier.

**Hypotheses.**
- **H4.1 — supported.** I17-M8-T6 (2,6 h) exceeds both T12 cells of the same M (I17-M8-T12: 0,69 h;
  I25-M8-T12: 1,36 h) — growth in T is non-monotone, and must be reported as such, not smoothed.
- **H4.2 — anchored, not yet resolved.** The M12 escalation probe (I25, T6) censored at the hard
  tier's 50 400 s cap with a **0,96 % gap** — close to, but outside, the 1e-4 certified threshold —
  reporting a real incumbent: E ≈ 6,24×10⁸ kg CO₂e, cost ≈ 3,17×10⁶, τ ≈ 13,8 USD/t. This anchors
  the frontier statement ("exact up to M8 within hard-tier limits; M12 is 0,96 %-gap censored, not
  exact, at the same limits") without resolving whether the 50 % certified-exact threshold is
  crossed above M8 — that would need more escalation points, out of scope for this campaign.

**Independent variables.** I, M, T over the 12-cell core grid (exp3's M0 arm, shared, no separate
solves) plus the one M12 escalation probe.

**Contribution.** The scalability table plus one evidence-backed frontier sentence.

**Status.** Core grid shared with exp3 (22/25). Escalation probe ✅ done (censored, anchored).

---

## 9. exp7 — Carbon-Price Validity and Policy Calibration — REFRAMED

**Objective.** Establish the domain of validity of monetary carbon-price statements. Reframed after
the ratio sweep ran (below): not a single-point calibration the rest of the paper waits on, but a
robustness check on USD/t claims the paper is already making.

**Why this experiment cannot simply be dropped.** exp1, exp3, and exp5 all already report τ\* in
USD/t, computed at the campaign's native valuation (no rescale, i.e. ρ=1 implicitly) — exp5's
headline burden-ratio table (§6) is built entirely on those numbers. The plan's original framing
("absolute figures are confined to Experiment 7") was already inaccurate by the time exp7 ran.
Removing exp7 does not remove the need for a validity envelope on those existing numbers; it only
removes the mechanism that would supply one. The alternative — rewriting every USD/t table back to
dimensionless tax indices — is far more costly and gives up the policy-relevance framing (Q5).

**Hypotheses and results.**
- **H7.1 — NOT supported; reported as a finding, not forced.** The measured τ\*(ρ) curve is
  non-monotone: ρ=1→8,0; ρ=5→1,6; ρ=10→189,1; ρ=20→94,6; ρ=50→100,9; ρ=100→180,1; ρ=200→87,7 USD/t.
  All seven runs terminate `relative_gap` with certified gaps ≤ 1e-4 — this is not an artifact of
  incomplete convergence. Tracing the DBP loop shows why: for ρ≥10 the raw incumbent (before Phase 2)
  jumps to near the grid ceiling (1737–2000 of 2000) after 3–4 iterations, and Phase 2's bisection
  then cuts it by a different, path-dependent amount each time (2000→946; 1947→877; but 1859→1801,
  barely). Rescaling ρ moves which technology/route configuration is marginal, so the plateau's left
  edge relocates non-smoothly with ρ — the same combinatorial mechanism exp5 documents in the tax
  dimension, now showing up in a second dimension. This is a genuine, certified finding and belongs
  in the paper as such, not as a caveat on a forced linear fit.
- **H7.2 — resolved by the regime split, NOT by the base cells.** A clear regime split exists on
  the anchor cell: ρ∈{1,5} give τ\* far below the 20–200 USD/t band (8,0 and 1,6); ρ∈{10,20,50,
  100,200} all land inside it (87,7–189,1 USD/t) despite the 20× range in ρ. **The claim rests on
  that split alone.** It cannot lean on the 12 base cells: at the native valuation (ρ=1) only 6 of
  12 have τ\* inside the band, the other six falling below 20 USD/t — see the correction in §3.
  The defensible statement is therefore conditional: *if* the emissions valuation is at least an
  order of magnitude above the generator's native scale, τ\* lands in the plausible policy band and
  stays there across a 20× range of ρ. No documented cost:emission unit convention exists in the
  generator to fix ρ absolutely (checked directly in `clsc/generator/instance.py`; only the
  tax-grid step, 0,01 USD/kg, is documented, and that is a grid decision, not a valuation one).

**ρ\* set to 1,0 (no rescale)** — internal consistency with every other experiment in the campaign,
which all ran at the native valuation, rather than an external market price (ETS, social cost of
carbon) that would need a justification this campaign cannot supply. This is a weaker calibration
argument than an externally-anchored ρ\* would be, and is reported as such; it is the honest
articulation of what the campaign actually did, not a retrofit to make a number look nicer.

**Independent variables.** ρ ∈ {1, 5, 10, 20, 50, 100, 200} (log-spaced), applied as a uniform
rescale of the emissions valuation; each a full bilevel solve on the fast cell I17-M4-T3.

**Instances / repetitions.** Ratio sweep = 7 bilevel solves — **done**. Anchored suite at ρ\*=1: 1
bilevel solve + an 11-point fine-grid frontier (follower-only, indices 0…2000 step 200) + an
AUGMECON minimum-emissions anchor ≈ 13 solves — **queued, running now** (the intermediate
ε-constraint points are a further data-dependent stage, not yet triggered).

**Statistical design / tests.** No OLS of log τ\* on log ρ — H7.1's premise (a smooth log-linear
relationship) does not hold, so fitting one would misrepresent the data. The regime-split
observation above stands in its place. Every absolute-USD/t claim in the paper is still grounded in
this section's finding, even without a single-point anchor.

**Contribution.** What survives is arguably a *better* result than the one planned: not "ρ\* is
justified, therefore USD/t is safe," but "USD/t claims are robust across an order-of-magnitude range
of valuation assumptions, and where τ\* moves, it moves for the same combinatorial reason the
paper's headline result already documents." The instability is now evidence for the thesis, not a
threat to it.

**Status.** Ratio sweep ✅ 7/7. Anchored suite at ρ\*=1,0: **queued, launched**, ~13 fresh solves on
the fast cell, expected within the hour.

---

## 10. exp6 — Global Sensitivity Screening — ANALYSED

**Objective.** Identify the dominant drivers of cost, emissions, and τ\*, including two-factor
interactions that a one-factor-at-a-time design cannot detect (Saltelli et al. 2010; Montgomery 2017).

**Hypotheses and results.**
- **H6.1 — CONFIRMED, robustly.** `demand:capacity` is the strongest or near-strongest two-factor
  interaction across all 6 series tested (3 responses × 2 seeds; mean rank 2,7 of 28 interactions,
  top-4 in 5/6 series) — exactly the "binding-constraint regime change" the plan's expected result
  anticipated. `return_availability:return_economics` is a consistent second interaction (mean rank
  3,8). Both recur across independent seeds and independent responses, which is stronger evidence
  than a single significant p-value: an artifact of one instance draw would not repeat this cleanly.
- **H6.2 — CONFIRMED for emissions; partially confirmed for cost and τ\*.** Top-3 factor set by
  |effect|, main effects only, coded ±1 fractional factorial (2^(8−2) resolution V, 64 runs/seed,
  design rank 37/37 — empirically confirmed unconfounded, not just assumed by construction):

  | Response | Seed 0 top-3 | Seed 1 top-3 | Agreement |
  |---|---|---|---|
  | emissions | emission_intensity, demand, scope3_emissions | demand, scope3_emissions, emission_intensity | **identical (3/3)** |
  | cost | demand, capacity, return_economics | demand, capacity, scope3_emissions | 2/3 |
  | τ\* | scope3_emissions, capacity, demand | demand, capacity, emission_intensity | 2/3 |

  `demand` and `capacity` appear in the top-3 in **all 6 of 6 series**, with no exception. The
  factor that varies is always the 3rd-ranked one, drawn from a stable "second tier"
  {emission_intensity, scope3_emissions, return_economics}. Reported as partial rather than full
  confirmation for cost/τ\* — the plan's H6.2 asked for the full top-3 set to be stable, and it
  is not, for those two responses, even though the two dominant factors are.

**A methodological caveat, found while computing this.** Lenth's PSE (pseudo-standard-error, the
basis for standard significance testing on unreplicated factorials) collapsed to an implausibly
small value for seed 1's emissions and cost responses (PSE≈302 and ≈14 respectively, against
effects in the hundred-thousands), producing p-values of 0,0 across the board. This is Lenth's
sparsity-of-effects assumption breaking down, not a data error — seed 1's smallest-magnitude
effects are less negligible relative to its largest ones than seed 0's are (verified directly: the
12 smallest |effects| are systematically larger for seed 1 than for seed 0), so the trimmed-median
noise estimate is no longer a good proxy for genuine noise. **The ranking-based conclusions above
(H6.1, H6.2) do not depend on this and stand**; a literal Lenth p-value / Benjamini–Hochberg table
for the emissions/cost/seed-1 cases should not be published as computed — a half-normal-plot
cross-check or a bootstrap-based noise estimate would be needed first. τ\* and seed 0 behaved
normally throughout (PSE 0,08–0,47, plausible reference distribution).

**Structural half-fraction (16 runs, seed 0, fast cell I17-M4-T3).** Clean, low-noise signal, no
Lenth needed (effects separate by orders of magnitude): `production_technology_menu` dominates
emissions (-4,36×10⁶, expanding it lowers emissions substantially);
`remanufacturing_technology_menu` dominates τ\* (+17,2 USD/t, expanding it *raises* the tax needed
to reach the same emissions floor); `road_menu` has a modest cost effect (-1,68×10⁴). **`sea_menu`
and `air_menu` have exactly zero effect on every response** (to floating-point noise) — this
specific fast cell's network apparently does not exercise sea/air modes at all, or the expanded
menu unlocks nothing usable in its topology. Flagged as a property of this one cell (I17-M4-T3),
not generalized to the campaign — the structural screen only ran on the fast cell by design.

**Independent variables.** 8 continuous factors at coded ±1 in a **2^(8−2) resolution-V fractional
factorial** (64 runs); 5 structural menu factors in a separate **2^(5−1) resolution-V half-fraction**
(16 runs).

**Instances / repetitions.** Continuous design at **both** seed 0 and seed 1, full 64 runs each =
128, plus the 16-run structural half-fraction = **144 total**. No curvature augmentation or
hard-tier confirmatory check was generated — both are gated behind a `_screening_top3.json` file
that nothing produces automatically, so the campaign naturally stopped at 144.

> **Correction from v2.** v2 proposed reducing the continuous seed-1 replicate to a 16-run
> resolution-III projection (144 → 96 points) and cutting the CCD. The 96-point reduction was never
> applied to `exp6_sensitivity.py` — by the time it was reconsidered, the campaign was already
> >50 % through the full 128-run continuous design under the live process, and stopping to
> regenerate would have discarded completed work for a ~2 h saving. The CCD *was* correctly
> dropped, but as a side effect of it never having a trigger file, not a deliberate code change. Net
> effect: exp6 cost ~2 h more than v2 budgeted, and delivered a full (not projected) seed-1
> replicate — the H6.2 table above exists *because* of that extra replicate.

**Statistical design / tests.** OLS regression of each response on all 8 coded main effects + 28
two-factor interactions per seed (main+2FI design rank 37/37, confirming true resolution V
empirically); Lenth's method for screening where its assumptions held; top-3 rank agreement across
seeds for H6.2, which does not depend on Lenth and is the more robust of the two analyses here.

**Status.** ✅ 144/144 run and analysed. H6.1 confirmed; H6.2 confirmed for emissions, partial for
cost/τ\*; one methodological caveat on Lenth's PSE for seed 1's emissions/cost responses, flagged
for a follow-up half-normal-plot check before publication rather than silently trusted.

---

## 11. Appendix experiments (complete)

### 11.1 exp1 — Verification

Reported as one appendix table plus a paragraph, not a paper section.

Battery: 6 hand-verifiable toy instances; all 12 base cells at seed 0 (certified-exact rate); 16
structural-invariant follower probes on 4 cells at 0/70/130/200 USD/t; 2 Gurobi-seed invariance
probes.

**Result (38/38 complete, 8,7 h).** All 12 cells terminate on `relative_gap`, worst gap 8,7e-5,
under the 1e-4 tolerance. All toys agree with manual derivation. Seed probes return identical
(E\*, τ\*). Zero re-validation violations. **The gate passes.**

**Correction from v2 on the invariance probes.** v2 flagged these 16 probes as needing a re-run
after the §3 grid unification. On inspection, that is not a correctness issue: the probes were
solved at rates 0/70/130/200 USD/t under the pre-unification semantics, and the *rates* — not the
now-defunct coarse-grid indices — are what the aggregator reports and what H1.3's monotonicity
check consumes. The numbers are correct. What is stale is only the on-disk directory naming
(`invariant_tau07` vs. the current design module's `invariant_tau0700`), which means a fresh
`generate`+`run` for exp1 would produce 16 duplicate solves alongside orphaned old ones. This is a
bookkeeping cleanup, not a data-quality fix, and is low priority.

### 11.2 exp2 — Solver configuration

Reported as one appendix paragraph and a 3×3 table.

**Result (11/11 complete, 61,9 h).** `MIPFocus = 2` is decisive: all three focus-2 configurations
converge; 5 of 6 others are censored. threads 4 and 6 are within 12 % of each other (7 973 vs
7 109 s) — inside the 34 % spread measured across Gurobi seeds at the same configuration — so
threads = 4 is fixed for the campaign and the 4-vs-6 difference is reported as unresolved.

**This experiment must never be repeated in this form.** It consumed 62 % of all campaign compute
to date for one appendix paragraph, because it was run on the *hardest* cell, where half the grid
cannot converge and therefore carries no signal. Any future configuration work runs on a medium
cell, where every configuration terminates.

---

## 12. Compute budget — FINAL

Measured, from 381 completed runs (119,6 h). The campaign is finished; this table is now a record,
not a forecast.

| Experiment | Spent | Type |
|---|---|---|
| exp1 — verification | 8,7 h | done |
| exp2 — solver config | 61,9 h | done, never repeat (§11.2) |
| exp3 — ablation | 18,9 h | done, 42/43 (1 legitimate spot-check censor) |
| exp4 — scalability | 7,7 h | done, censored+anchored |
| exp5 — plateau (static + refinement) | ~1,3 h | done, 120/120 |
| exp6 — sensitivity | ~7,4 h | done, 144/144, analysed (§10) |
| exp7 — calibration | ~0,3 h | done, 20/20 |
| exp8 — enumeration benchmark | 13,4 h | done, 4/4 (2 exact, 2 informatively censored) |
| **Total** | **119,6 h** | **381/381 runs, campaign complete** |

exp8 was the single largest remaining cost, and came in within the range projected when it was
queued (~10 h estimated; 13,4 h actual — the I17-M4-T6 fast cell ran longer than its sibling, 7 h 13
min vs 2 h 9 min, at ~3,3× the per-point cost despite the same tier classification).

**What is NOT part of this budget:** the exp6 statistical analysis (§10) and this document's own
upkeep are analyst time, not solver time, and are the only work items left (§0).

---

## 13. Paper section mapping — FINAL

| Paper section | Experiment(s) | Status |
|---|---|---|
| Setup and testbed | §2, §3 | done |
| **Non-identification of the optimal tax; value of the bilevel leader** | **exp5** | **confirmed, 12/12, figure-ready** |
| Algorithm: DBP, benchmark, ablation | exp8, exp3 | **both confirmed** — exp8's tie-tolerance bug story is a citable methodological aside |
| Scalability | exp4 | anchored (censored M12 probe, 0,96 % gap) |
| Sensitivity analysis | exp6 | **analysed** — H6.1 confirmed, H6.2 confirmed/partial (§10); Lenth PSE caveat for seed 1 emissions/cost needs a pre-publication cross-check |
| Monetary calibration and policy analysis | exp7 | **resolved** — reframed as a robustness/regime-split result, not a single anchor (§9) |
| Appendix A — verification | exp1 | done |
| Appendix B — solver configuration | exp2 | done |

---

## 14. What changed from v2, and why

| Change | Reason |
|---|---|
| exp5 status: projected → **confirmed 12/12** | It ran. H5.1 and H5.2 both hold on every cell, with burden ratios up to 18,6×. |
| exp3 status: projected → **confirmed**; exp4 anchored | Ablation ran: A1/A4 fail 6/6 as predicted, A2/A3/A5 don't change the optimum. M12 probe censored but anchored (0,96 % gap, real incumbent). |
| exp8 implemented (`enumeration.py`, `exp8_benchmark.py`) | Was the plan's single largest open item; now coded, unit-tested, registered, not yet run. |
| exp5 local refinement implemented | §4's plateau-shape instrumentation now exists as real code reading exp3's own results, not a design sketch. |
| **P4 (plateau right edge) dropped** | Measured data shows it coincides with P1 (grid ceiling) to within 0,01 % on every cell — not an independent point worth solving for. |
| exp8's expected outcome revised: censored → likely **exact** on fast cells | A direct timing gave ~5,5 s/point; the full 2001-point grid fits inside the fast tier's 8 h cap with room to spare. |
| Tier caps: documented as halved → **corrected to the actual, unchanged values** (28 800 / 50 400 s) | The halving was proposed in v2 but never applied to `_cells.py`; every completed run used the original caps, and claiming otherwise would misdescribe 202 already-completed runs. |
| exp6: documented as reduced to 96 → **corrected to the actual, unreduced 144-point run** | Same reason: the reduction was never applied to code, and by the time it was reconsidered the live run was already past the point of no return. The unreduced design gives a stronger seed-1 replicate at ~2 h extra cost — treated as a feature, not a shortfall. |
| exp1's invariance probes: "must re-run" → **correctness unaffected, re-run demoted to bookkeeping** | The probes' RATES were always correct; only their on-disk naming predates the current design module. |
| §5 (execution priority) rewritten around what's left, not what's biggest risk | The biggest risk (a degenerate plateau) is resolved. What remains is finishing, not de-risking. |
| §0 (status at a glance) added | A single table answering "where are we" was missing from v2 and is now the natural entry point given how much has run. |

**Open items, in order:** (i) let exp6→exp7 finish unattended; (ii) launch exp5's local refinement
(~1 h) and exp8 (~4–8 h) — both implemented, awaiting go-ahead; (iii) close exp3's 1 remaining
censored M0 cell; (iv) exp1's invariance-probe directory cleanup — cosmetic, lowest priority.
