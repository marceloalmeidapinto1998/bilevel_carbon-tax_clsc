# Experimental Plan — Bilevel CLSC under a Carbon Tax

This document specifies the computational campaign that produces every quantitative result in the
paper.

**Design philosophy.** Three principles drive every choice below:

1. **Certificates before claims, without an external comparison method.** DBP is the only exact
   bilevel algorithm exercised in this plan. Correctness is therefore established the way exact
   decomposition methods have always been validated in the literature (Benders 1962; Geoffrion
   1972's generalized Benders decomposition; Van Slyke & Wets 1969's L-shaped method): by the
   algorithm's own lower-bound/upper-bound convergence to a certified gap, cross-checked by
   hand-verifiable toy instances, structural invariants of the underlying mathematics, and
   independent re-validation of every reported solution in a freshly rebuilt model.
2. **Replication where it means something.** The solver is deterministic, so repeated re-solves of
   the same instance are not replication. Variability is designed in through (i) *instance seeds*
   (generalization over the problem distribution) and (ii) *Gurobi `Seed`* (MIP performance
   variability; Lodi & Tramontani 2013). Neither is substituted by re-running the same solve.
3. **Validity envelope respected.** The generator's cost and emission scales originate in different
   functional units, so absolute carbon-tax statements (USD/t) are only defensible after an explicit
   calibration step. Everywhere else, the carbon tax is reported as a dimensionless index; absolute
   monetary figures appear only in Experiment 7, on the one instance whose valuation ratio is
   explicitly justified.

---

## 1. Research questions and hypothesis map

| # | Question | Experiment | Hypotheses |
|---|---|---|---|
| Q1 | Is the implementation correct? | 1 | H1.1–H1.4 |
| Q2 | Is the solver configuration justified and reproducible? | 2 | H2.1 |
| Q3 | Does every component of the algorithm earn its place? | 3 | H3.1–H3.4 |
| Q4 | How does it scale; where are its limits? | 4 | H4.1–H4.2 |
| Q5 | What does the bilevel leader add over simpler policy rules? | 5 | H5.1–H5.2 |
| Q6 | Which parameters drive cost, emissions, and the optimal tax — including interactions? | 6 | H6.1–H6.2 |
| Q7 | Are the policy claims defensible in absolute monetary terms? | 7 | H7.1–H7.2 |

---

## 2. Testbed

### 2.1 Structural grid and instance seeds

Twelve base instances span the full 2×2×3 combination of three structural dimensions: I ∈ {17, 25}
(total supply-chain entities/nodes), M ∈ {4, 8} (materials/products richness — raw materials and
final products), T ∈ {3, 6, 12} (periods). (The production and remanufacturing technology counts
are held fixed at 3 each; the generator's `I`/`M` codes drive node counts and material/product
richness, respectively, not the technology menu.) These are not design factors — they define
structurally distinct optimization problems with different variable counts and difficulty classes.

Statistical experiments run on **3 instance seeds per cell on the 7 standard-tier cells**
(seed ∈ {0, 1, 2}, generated fresh with the project's deterministic generator), because a single
draw per cell supports no inference about the instance distribution (Rardin & Uzsoy 2001, §4). The
**5 hard-tier cells** (I25-M8-T6 and the four T12 cells) run at **seed 0**, plus **one seed-1
spot-check on I25-M8-T6** as a stability witness — a stated budget trade-off: inference is
supported on the standard tier, hard-tier results are reported per-cell with the spot-check as
corroboration. Headline results are per-cell medians over seeds with bootstrap 95% confidence
intervals where seeds exist.

### 2.2 Replication policy

| Source of variation | Where used | Levels |
|---|---|---|
| Instance seed (generator) | Experiments 3, 6 | 3 per standard cell, 1 (+1 spot-check) per hard cell |
| Gurobi `Seed` | Experiments 1, 2 | {0, 1, 2} on selected cells |
| Algorithmic repetition | nowhere | the solver is deterministic; re-running is not replication |

### 2.3 Time limits, tolerances, environment

Two-tier limits: standard tier 3,600 s per sub-MILP / 28,800 s wall-clock; hard tier (I25-M8-T6 and
the four T12 cells) 10,800 s / 50,400 s. Campaign tolerances: fine tax grid (scale 1e-4, index
0..2000), `dbp_relative_gap = 1e-4`, follower `mip_gap = 1e-6`, Phase-2 min-tax bisection ON —
except where a tolerance is itself the experimental factor. One machine, one fixed software stack,
recorded per run (solver version, code commit) in every manifest.

### 2.4 Statistical reporting standards (all experiments)

- **Runtimes:** shifted geometric means (shift 10 s; Achterberg 2007) plus medians and IQR; never
  arithmetic means alone. Censored runs are reported as censored, never imputed as the time limit.
- **Paired comparisons within an experiment:** Wilcoxon signed-rank for two conditions, Friedman
  with Nemenyi post-hoc for three or more (Demšar 2006). α = 0.05, Holm correction within each
  experiment.
- **Factorial effects:** ANOVA on the factorial design, effect sizes (partial η²), half-normal
  plots with Lenth's method; Benjamini–Hochberg correction across responses.
- **Confidence intervals:** BCa bootstrap (10,000 resamples) for medians and ratios.

---

## 3. Experiment 1 — Verification and Solution Validation

*Hard gate: the campaign does not proceed to Experiment 2 until every check below passes.*

**Objective.** Establish computational correctness of the model implementation and the DBP solver,
using only the algorithm's own optimality certificate, hand-verifiable toy cases, structural
invariants of the underlying mathematics, and independent re-validation.

**Hypotheses.**
- **H1.1** — DBP terminates with its own certified-exact status (relaxation lower bound equal to the
  incumbent upper bound within the declared relative gap) on every base structural cell, within its
  time-tier limit. This is the standard optimality certificate for decomposition-based exact MILP
  methods (Geoffrion 1972; Van Slyke & Wets 1969).
- **H1.2** — On tiny, hand-verifiable toy instances (small enough that the optimal network
  configuration can be derived by direct inspection or manual calculation), DBP's certified optimum
  matches the manually-derived optimum.
- **H1.3** — Structural invariants implied by the model's mathematics hold on every solve: the
  follower's optimistic emissions response is non-increasing in the tax; the follower's value
  function is piecewise-linear, concave, and non-decreasing in the tax (standard parametric-MILP
  theory). Tested by solving the follower directly at a handful of tax points per instance and
  checking the implied pairwise inequalities — a local structural check, not an attempt to certify
  a global optimum by covering the tax grid.
- **H1.4** — Every reported incumbent re-validates feasible when its variable values are loaded into
  an independently rebuilt model (zero constraint violations beyond floating-point snap tolerances).

**Independent variables.** None (a validation battery, not a factorial design); checks are applied
uniformly across the testbed.

**Dependent variables.** Certified-exact rate; manual-agreement rate on toy instances; invariant
violation counts; re-validation violation counts.

**Controlled parameters.** Campaign tolerances (§2.3).

**Metrics.** Percentage of structural cells terminating certified-exact within their time tier;
percentage of toy instances in exact agreement with the manual solution; invariant-violation count
(target zero); re-validation violation count (target zero).

**Instances.**
- **6 hand-verifiable toy instances** (2–3 nodes/products, a single or two periods, a coarse tax
  grid), generated fresh at reduced dimensions — small enough for a reader to re-derive the optimal
  network choice on paper.
- **All 12 base structural cells**, solved once at seed 0 — establishes the certified-exact rate
  (H1.1) that gates the rest of the campaign.
- **Structural-invariant probes:** 4 representative cells (2 fast, 2 hard), each solved at 4 tax
  points spanning the grid — direct follower solves, not a systematic sweep aimed at locating an
  optimum.
- **Gurobi-seed invariance probes:** 2 fast cells solved at Gurobi `Seed` ∈ {1, 2} (seed 0 is already
  produced by the base-cell run above) — confirms the reported *solution* is seed-invariant (runtime
  may differ).

**Repetitions.** One solve per instance per check (deterministic); the Gurobi-seed probes are the
only repeated solves, and they test seed-invariance, not statistical replication.

**Statistical design / tests.** Certificate-style: exact agreement within declared floating-point
tolerances, and pass/fail against the algorithm's own optimality condition. No inferential tests —
these are deterministic checks, not a sample from a population.

**Expected result.** Certified-exact status on every base cell within its time tier; full agreement
on the toy instances; zero invariant or re-validation violations. Any failure is a defect to fix
before the campaign proceeds.

**Contribution.** The paper's validation subsection — converts "is this correct?" from a discussion
point into a table with a hard pass/fail criterion, using only the algorithm's own guarantees.

---

## 4. Experiment 2 — Solver Configuration

**Objective.** Choose and justify `threads`/`MIPFocus` for the rest of the campaign, and quantify
MIP performance variability so later runtime comparisons are read against a known noise floor.

**Hypotheses.**
- **H2.1** — Configuration effects on runtime exceed Gurobi-seed noise (otherwise configuration
  choice is immaterial and the solver defaults would be indistinguishable from any sweep result).

**Independent variables.** `threads` ∈ {2, 4, 6} × `MIPFocus` ∈ {0, 1, 2} — full 3×3 grid; Gurobi
`Seed` ∈ {1, 2} probes on the winning configuration.

**Dependent variables.** Wall time, DBP iterations, per-stage MIP gaps.

**Controlled parameters.** The hardest structural cell (I25-M8-T6); campaign tolerances.

**Metrics.** Shifted geometric mean runtime per cell; coefficient of variation across Gurobi seeds.

**Instances / repetitions.** 9 fresh bilevel solves (full 3×3 grid) + 2 fresh Gurobi-seed probes on
the winning cell = **11 runs**.

**Statistical design / tests.** Two-way layout, descriptive emphasis (the grid is too small for a
powered inferential test); the coefficient of variation from the seed probes is carried forward as
the noise floor against which Experiments 3–4's runtime differences are interpreted.

**Expected result.** One configuration performs within seed-noise of the best across the grid; it is
fixed for every subsequent experiment.

**Contribution.** Reproducibility note; pre-empts "was the configuration cherry-picked?" and gives
later runtime comparisons a stated noise floor.

---

## 5. Experiment 3 — Ablation Study of the DBP Algorithm

**Objective.** Show that each design component of the DBP algorithm earns its place, by comparing
the full method against systematically weakened versions of itself.

**Hypotheses.**
- **H3.1** — Removing the Phase-2 minimum-tax bisection loses τ\*-minimality on a non-trivial share
  of instances: the reported tax is strictly above the true least-intervention tax at the same
  certified emissions floor, verifiable directly since both variants report the same emissions
  target and only the reported tax differs.
- **H3.2** — Removing the lexicographic Stage-2 in the relaxation master increases the number of DBP
  iterations and/or wall time needed to reach the same certified gap.
- **H3.3** — Removing warm starts between successive follower solves increases per-iteration solve
  time without changing the certified optimum.
- **H3.4** — Solving on the coarse tax grid instead of the fine grid biases the reported τ\* relative
  to the fine-grid result on the same instance (grid aliasing), and can report a different (weaker)
  certified emissions floor E\*.
- **H3.5** — Removing the incumbent objective-upper-bound cut increases DBP iterations and/or wall
  time needed to reach the same certified gap.

**Independent variables.** Algorithm variant ∈ {M0 = full DBP (reference); A1 = no Phase-2
bisection; A2 = no lexicographic Stage-2 in the master; A3 = no warm starts; A4 = coarse tax grid;
A5 = no incumbent objective-upper-bound cut}.

**Dependent variables.** Runtime; number of follower solves; number of DBP iterations; E\*; τ\*;
certified-exact rate.

**Controlled parameters.** Experiment 2's configuration; campaign tolerances (except A4, by design).

**Metrics.** Shifted geometric-mean runtime and iteration-count ratios against M0; deviation of each
variant's (E\*, τ\*) from M0's on the same instance; percentage of instances where a variant loses
τ\*-minimality or degrades E\*.

**Instances.**
- **M0 (reference):** all 12 structural cells, fresh — 3 seeds on the 7 standard-tier cells, 1 seed
  on the 5 hard-tier cells, plus the Gurobi-seed spot-check on I25-M8-T6 (§2.1) = **27 bilevel
  solves**.
- **A1, A4** (claim-carrying — they change the algorithm's certified guarantees): 6 representative
  instances (2 fast, 2 medium, 2 hard), seed 0, each = **12 fresh bilevel solves**.
- **A2, A3, A5** (secondary — they affect efficiency, not correctness): 2 fast instances, seed 0,
  each = **6 fresh bilevel solves**.

**Repetitions.** As specified above; deterministic beyond the seed axis already designed in §2.1–2.2.

**Statistical design / tests.** Paired per-instance comparisons against M0 on the same instance;
Wilcoxon signed-rank per variant; Holm correction across the five-variant family.

**Expected result.** A1 loses τ\*-minimality on cells with a non-trivial tax plateau; A4 biases τ\*
and occasionally E\* through grid aliasing; A2, A3, A5 each cost measurable time or iterations while
leaving the certified optimum unchanged.

**Contribution.** The ablation section — the strongest section for an operations-research reviewer,
since it isolates and quantifies the contribution of each algorithmic component rather than treating
the method as a black box.

---

## 6. Experiment 4 — Scalability Analysis

**Objective.** Characterize runtime growth in I, M, T and locate the practical tractability
frontier through direct evidence, not assertion.

**Hypotheses.**
- **H4.1** — Runtime is driven primarily by M (materials/products richness), super-linearly; growth
  in T is sub-linear and non-monotone.
- **H4.2** — There exists a cell size beyond which the certified-exact rate falls below 50% within
  hard-tier limits.

**Independent variables.** Structural dimensions I, M, T. The core 12-cell grid (Experiment 3's M0
arm) plus **one escalation probe on the empirically dominant axis**: M ∈ {8 → 12} at (I25, T6), one
seed, hard-tier caps.

**Dependent variables.** Wall time; DBP iterations; per-stage times; censoring status; model size
(variables, constraints, nonzeros).

**Controlled parameters.** Experiment 2's configuration; hard-tier limits on the escalation probe.

**Metrics.** Log–log regression of runtime on I, M, T with an M×T interaction term; censored
fraction per cell; elasticities with confidence intervals.

**Instances / repetitions.** The 12-cell core grid is the same execution as Experiment 3's M0 arm —
no separate solves. **One additional escalation probe** (M12, capped at the hard-tier wall clock).

**Statistical design / tests.** OLS on log-transformed variables with heteroscedasticity-robust
standard errors; censoring is reported explicitly, never imputed; the escalation probe anchors the
frontier statement (exact-or-censored within the stated cap).

**Expected result.** M's elasticity substantially exceeds I's and T's; an explicit, evidence-backed
frontier statement (e.g., "exact within the hard-tier cap up to M12 at I25×T6").

**Contribution.** The scalability section, with inferential content rather than a descriptive
scaling note.

---

## 7. Experiment 5 — Value of the Bilevel Leader

**Objective.** Quantify what explicit leader optimization buys over the policy rules a single-level
(non-bilevel) analysis would use.

**Hypotheses.**
- **H5.1** — The set of emissions-optimal tax indices forms a non-degenerate plateau (an interval,
  not a point) on most structural cells — a single "optimal tax" is not identified without an
  explicit tie-breaking rule.
- **H5.2** — The least-intervention tax τ\* (the lexicographic Phase-2 result) attains the certified
  emissions floor E\* at strictly lower follower cost burden than the plateau's right edge and than
  the tax ceiling.

**Independent variables.** Policy rule ∈ {P0 no tax; P1 tax ceiling; P2 mid-grid flat tax; P3 τ\*
(bilevel lexicographic); P4 plateau right edge}.

**Dependent variables.** Emissions; follower cost; follower objective; plateau width (the
tax-identifiability band); regulation efficiency ΔE/Δτ.

**Controlled parameters.** Campaign tolerances; one fresh follower solve per non-P3 rule per cell.

**Metrics.** Per-cell (emissions, cost) under each rule; percentage of emissions reduction achieved
by τ\* relative to the tax ceiling; excess cost burden of the naive rules.

**Instances / repetitions.** All 12 structural cells. P3 (τ\*) is Experiment 3's M0 result on the
same cell — the same fresh bilevel solve, not a separate run. P0, P1, P2, P4 are one fresh
follower-only lexicographic solve each per cell = **48 fresh follower solves**.

**Statistical design / tests.** Directional sign tests across cells for H5.1 (plateau existence) and
H5.2 (cost-burden ordering); one summary figure per cell (the emissions-vs-tax staircase with the
plateau shaded and τ\* marked at its left edge).

**Expected result.** Plateaus present on nearly every cell; τ\* materially cheaper than the naive
rules at identical emissions — turning the tax's non-identification from an apparent weakness into
the paper's central methodological contribution.

**Contribution.** The centerpiece of the contribution section: a quantitative answer to "why
formulate this as bilevel at all?"

---

## 8. Experiment 6 — Global Sensitivity Analysis

**Objective.** Identify the dominant drivers of cost, emissions, and τ\*, including two-factor
interactions that a one-factor-at-a-time design structurally cannot detect (Saltelli et al. 2010;
Montgomery 2017).

**Hypotheses.**
- **H6.1** — At least one two-factor interaction among {demand, capacity, return availability,
  emission intensities} is significant at α = 0.05 after Benjamini–Hochberg correction.
- **H6.2** — The top-3 factor set is stable across instance seeds (identical membership across both
  seeds tested).

**Independent variables.**
- 8 continuous factors at coded ±1 levels (registered multiplier bounds): a **2^(8−2) resolution-V
  fractional factorial** (64 runs) — every main effect and every two-factor interaction estimable
  free of confounding with the others.
- 5 structural factors (technology and transport menu expansions) in a separate **2^(5−1)
  resolution-V half-fraction** (16 runs) — kept separate because the menu expansions are discrete
  jumps, not continuous levels, and mixing the two families in one design would confound curvature
  with the discrete effects.

**Dependent variables.** E\*, cost\*, τ\* (index); structural descriptors (number of open facilities,
remanufacturing share of output, transport-mode shares).

**Controlled parameters.** The fast structural cell (I17-M4-T3); campaign tolerances; every factor
not under test held at baseline.

**Metrics.** Standardized effects; partial η²; half-normal plots (Lenth's method); Pareto-of-effects
chart.

**Instances / repetitions.**
- Continuous design × **2 instance seeds** = 64 × 2 = **128 fresh bilevel solves**.
- Structural half-fraction × 1 seed = **16 fresh bilevel solves**.
- **Curvature augmentation:** the top-3 factors from the screening analysis, in a face-centred
  central composite design (**15 fresh runs**, seed 0).
- **Confirmatory check:** the single top-ranked factor, at low/baseline/high, on one hard-tier cell
  (**3 fresh bilevel solves**) — confirms the dominant effect is not an artifact of the fast cell.

**Statistical design / tests.** Blocked ANOVA (seed = block, 2 blocks); Lenth's method for effect
screening; Benjamini–Hochberg correction across the three primary responses; top-3 set agreement
across seeds for stability; curvature F-test in the central composite design.

**Expected result.** Demand, capacity, and emission-intensity effects dominate; at least one
economically interpretable interaction (e.g., demand × capacity through a binding-constraint regime
change); the top-3 ranking is stable across seeds and confirmed on the hard-tier cell.

**Contribution.** Replaces a one-factor-at-a-time design with a defensible global design at
comparable computational cost; pre-empts the single most common sensitivity-analysis criticism in
review (ignoring interactions).

---

## 9. Experiment 7 — Carbon-Price Validity and Policy Calibration

**Objective.** Establish the domain of validity of monetary carbon-price statements, then make the
paper's absolute policy claims on a single, defensibly-calibrated instance.

**Hypotheses.**
- **H7.1** — τ\* scales approximately linearly with the cost:emission valuation ratio ρ.
- **H7.2** — At the defensible ratio ρ\* (independently justified from the instance's cost and
  emission scales), τ\* falls inside the plausible policy band of 20–200 USD/t.

**Independent variables.** Valuation ratio ρ ∈ {1, 5, 10, 20, 50, 100, 200} (log-spaced), applied as
a uniform rescale of the emissions valuation, each solved as a full bilevel DBP problem.

**Dependent variables.** τ\*(ρ); at ρ\*: the certified bilevel optimum, the cost–emissions frontier,
and the resulting USD/t statements.

**Controlled parameters.** Instance structure fixed across the sweep; only the valuation ratio
varies, isolating its own effect. The sweep runs on the fast structural cell (I17-M4-T3) to keep
each of the 7 points a full but cheap bilevel solve.

**Metrics.** The τ\*(ρ) curve with a fitted trend and confidence interval; the position of τ\* at ρ\*
relative to the 20–200 USD/t policy band.

**Instances / repetitions.**
- **Ratio sweep:** 7 fresh full bilevel DBP solves on the fast cell (one per ρ value).
- **Anchored instance:** one instance at ρ\* — one fresh full DBP solve, one fresh 11-point
  tax-indexed frontier sweep (follower-only solves at each of 11 tax levels), and one fresh
  AUGMECON-style epsilon-constraint frontier (a payoff-table minimum-emissions anchor plus 10
  intermediate follower-only solves at equally-spaced emissions caps; the minimum-cost anchor is the
  tax-indexed sweep's zero-tax point, already produced above).

**Statistical design / tests.** OLS of τ\* on ρ in log–log space; the fitted slope's confidence
interval is compared against unit elasticity. Every absolute-USD/t claim in the paper is confined to
this section by construction.

**Expected result.** Near-unit elasticity of τ\* in ρ; the anchored instance's τ\* falls inside the
policy band.

**Contribution.** Converts the testbed's known monetary-calibration limitation into a rigorous
sensitivity result — the only section of the paper reporting absolute carbon prices, and the section
that makes every other section's dimensionless-index reporting defensible.

---

## 10. Execution sequence and dependencies

```
1 (verification) ── hard gate: any failure stops the campaign
    └─► 2 (configuration)
           └─► 3 (ablation study)
                  ├─► 4 (scaling; consumes 3's M0 arm, then runs its own escalation probe)
                  └─► 5 (policy value; consumes 3's M0 arm as its P3 rule, adds 4 fresh policy rules)
           6 (sensitivity screening ─► curvature augmentation, after the screening analysis)
           7 (ratio sweep ─► anchored instance, after the sweep locates ρ*)
```

Experiments 6 and 7 depend only on Experiment 2's configuration and can run in parallel with
Experiment 3–5's chain. Within Experiment 6 and Experiment 7, the second stage (curvature
augmentation; the anchored instance) is generated only after its first stage's analysis completes —
an analysis gate, not just a run gate, mirroring standard sequential DOE practice.

**Every experiment in this plan is indispensable to the paper's core claims.**

**Pre-declared contingency (if the wall-clock budget is at risk, cut in this order — no
improvisation mid-campaign):**
1. Experiment 4's escalation probe — the frontier statement is then made from the core grid alone.
2. Experiment 6's curvature augmentation and hard-tier confirmatory check — the screening result
   stands alone.
3. Experiment 3's secondary variants (A2, A3, A5) — A1 and A4 carry the algorithm's exactness
   claims and are never cut.

Never cut: Experiment 1 (the hard gate), Experiment 7's anchored instance, Experiment 3's A1/A4
variants, Experiment 6's screening design.

---

## 11. Compute budget

| Experiment | New solves | Dominant cost | Wall estimate |
|---|---|---|---|
| 1 — Verification | 6 toy + 12 base-cell + 16 invariant probes + 2 seed probes | 5 hard-tier base-cell solves | ~1–1.5 days |
| 2 — Configuration | 9 + 2 seed probes = 11 | hard-tier grid | ~1 day |
| 3 — Ablation study | 15 new M0 (seeds beyond Exp. 1's base run) + 18 variant solves = 33 | hard-tier M0 and A1/A4 solves | ~1–1.5 days |
| 4 — Scalability | 1 escalation probe (core grid shared with Exp. 3) | the capped probe | ≤ 1 day |
| 5 — Value of the leader | 48 follower solves (P3 shared with Exp. 3) | hard-tier followers | ~0.5 day |
| 6 — Sensitivity | 128 + 16 + 15 + 3 = 162 | volume, not depth | ~1 day |
| 7 — Policy calibration | 7 ratio-sweep solves + 1 anchored suite (≈23 solves) | anchored bilevel + frontier | ~0.5–1 day |
| **Total** | **≈ 300 new solves** | — | **≈ 6–7 days**, sequential |

The plan is interruptible and resumable; independent components (Experiment 6's fast-cell volume,
Experiment 7's ratio sweep) can run unattended while earlier experiments' results are analyzed. The
contingency in §10 absorbs any overrun within the one-week ceiling.

---

## 12. Paper section mapping

| Paper section | Experiment(s) |
|---|---|
| Setup and testbed | §2 |
| Validation | Experiment 1 |
| Solver configuration (appendix) | Experiment 2 |
| Ablation study | Experiment 3 |
| Scalability | Experiment 4 |
| Value of the bilevel leader | Experiment 5 |
| Sensitivity analysis | Experiment 6 |
| Monetary calibration and policy analysis | Experiment 7 |
