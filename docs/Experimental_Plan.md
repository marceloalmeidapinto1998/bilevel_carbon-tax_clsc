# Experimental Plan v4 — Bilevel CLSC under a Carbon Tax

This document specifies the computational campaign that produces every quantitative result in the
paper. It supersedes v3 (git history: `docs/Experimental_Plan.md` at commit `d43d8c7` and earlier).
v3's 8-experiment campaign (`campaign_01`, ~380 solves) fully ran and confirmed its headline claim,
but was more than a single paper needs, and several of its files (`capital_charge`, `discounting`,
`labour_cost`, `product_rotation`, `supplier_cost`, `min_tax_confirmation` — see the corresponding
`tests/test_*.py`) were fixed after it ran, so its numbers are stale regardless. v4 **deletes all
prior campaign_01 data and results and rebuilds from a smaller, consolidated design**: the same
headline claim and every supporting claim category a referee would expect, at roughly a third of
the compute.

**Design philosophy.** Unchanged from v3 in substance, restated for the smaller campaign:

1. **One headline contribution, evidenced to the hilt; everything else is support.** The paper's
   claim is that the emissions-optimal carbon tax is a *plateau*, not a point — the leader's
   objective is flat over a wide range of tax levels — and that the least-intervention tax τ\* (the
   lexicographic Phase-2 result) is the defensible selection from that plateau. Every experiment
   either establishes that claim or earns its place by making it credible.
2. **A certificate is necessary but not sufficient.** DBP's own lower-bound/upper-bound
   convergence proves the algorithm is *correct*; it does not by itself prove it is *worth
   having*. v4 planned exhaustive grid enumeration as that baseline; it was **removed from the
   code on 2026-10-08** (see §4), so this principle is now carried by the ablations alone.
3. **Replication where it means something.** The solver is deterministic, so re-solving the same
   instance is not replication. Variability is designed in through *instance seeds* (generalization
   over the problem distribution) and *Gurobi `Seed`* (MIP performance variability; Lodi &
   Tramontani 2013) — used sparingly here, as light spot-checks rather than full seed replication.
4. **One tax grid, and a stated validity envelope.** All tax quantities live on the single campaign
   fine grid (§2.3) and are reported as rates. Absolute USD/t claims appear only in Experiment 3's
   calibration stage, on the one instance whose valuation ratio is explicitly justified.
5. **Consolidate, don't merely trim.** Four experiments, not eight: each old experiment that
   produced no claim of its own (solver configuration) or that only restated a sibling experiment's
   question from a different angle (ablation/scalability/benchmark; leader-value/calibration) is
   folded into the experiment that does carry a claim, rather than kept as a separate small DOE.

**Budget discipline.** Statistical volume runs on fast/medium cells; hard cells are reserved for the
handful of points where a hard cell is itself the point (the scalability probes, the two hard
cells in Experiment 3 that each carry a distinct finding). No sweep, grid, or factorial runs on a
hard cell.

---

## 0. Status at a glance

| Experiment | Design | Status |
|---|---|---|
| exp1 — verification | 24 pts | designed, not yet run |
| exp2 — computational performance | 17 pts | designed, not yet run |
| **exp3 — policy value & calibration (headline)** | 12 (P0-P2) + 16 (refinement) + 5 (ρ sweep) + 13 (anchored suite) = 46 pts | designed, not yet run |
| exp4 — sensitivity | 32 pts | designed, not yet run |

**Total: ~121 design points**, down from v3's ~380. Solver-configuration tuning (v3's exp2) is
**not** a formal experiment here — see §5.

---

## 1. Research questions and contribution map

| # | Question | Experiment | Paper section |
|---|---|---|---|
| **Q1** | **Is the optimal carbon tax identified, and what does the bilevel leader add over simpler policy rules?** | **exp3** | **Contribution (headline)** |
| Q2 | ~~Does DBP earn its complexity against the obvious exact alternative?~~ Dropped with the enumeration baseline (2026-10-08). | — | — |
| Q3 | Does every component of the algorithm earn its place? | exp2 | Algorithm (ablation table) |
| Q4 | How does it scale; where are its limits? | exp2 | Scalability |
| Q5 | Are the policy claims defensible in absolute monetary terms? | exp3 | Policy analysis |
| Q6 | Which inputs drive cost and emissions? | exp4 | Sensitivity |
| Q7 | Is the implementation correct? | exp1 | Appendix |

Experiment identifiers `exp1`..`exp4` are stable keys for the code (`clsc/campaign/designs/`) and
the results tree; they are not necessarily the order of presentation in the paper.

---

## 2. Testbed

### 2.1 Structural grid and instance seeds

Unchanged from v3. Twelve base instances span the full 2×2×3 combination of I ∈ {17, 25}
(supply-chain entities/nodes), M ∈ {4, 8} (materials/products richness), T ∈ {3, 6, 12} (periods).
Production and remanufacturing technology counts are held fixed at 3 each. These are not design
factors — they are structurally distinct optimization problems with different variable counts and
difficulty classes.

**Tiers and representative cells** (`clsc/campaign/designs/_cells.py`, unchanged):

| Tier | Cells |
|---|---|
| Fast | I17-M4-T3, I25-M4-T3, I17-M8-T3 |
| Standard | I17-M4-T6, I25-M4-T6, I25-M8-T3 |
| Hard | I17-M4-T12, I25-M4-T12, I17-M8-T12, I25-M8-T12, I25-M8-T6, I17-M8-T6 |

`REPRESENTATIVE_CELLS` (used by Experiment 2's `full` reference) = 2 fast + 2 medium + 2 hard = 6 cells:
I17-M4-T3, I17-M4-T6 (fast); I17-M8-T6, I25-M4-T6 (medium); I25-M8-T6, I25-M8-T12 (hard).

### 2.2 Replication policy

Deliberately light in this campaign — full 3-seed replication is a v3-scale luxury this design
doesn't spend:

| Source of variation | Where used | Levels |
|---|---|---|
| Instance seed (generator) | exp1 base gate (seed 0 only) | 1 (no seed sweep) |
| Gurobi `Seed` | exp1 (1 fast cell), exp2 (`full` seed-noise check, 1 fast + 1 hard cell) | {0, 1, 2} on selected cells |
| Algorithmic repetition | nowhere | the solver is deterministic |

### 2.3 Time limits, tolerances, environment

Revised 2026-10-08 to follow the literature instead of v3's calibration. Every MILP subproblem
gets a 600 s budget; the follower stops at a 1% MIP gap and the relaxation master at the solver
default 1e-4 (a 1% target on the master freezes the lower bound at its first dual bound); there
is no cap on a run as a whole (`clsc/campaign/designs/_cells.py`, `CAMPAIGN_*` in the orchestrator). Sources: Soares et
al. (2021) bound each subproblem (5 and 10 min) and not the run, and use eps = 1e-4, eps' = 1e-5
and a 10-iteration auxiliary stop; Tautenhain et al. (2021) stop CPLEX at a 1% gap on this very
follower model.

Tolerances: `dbp_relative_gap = 1e-4`, follower `mip_gap = 1e-2`, master `mip_gap = 1e-4`, in-loop min-tax
confirmation ON, `threads = 4`, `MIPFocus = 2` (see §5). One machine, one fixed software stack;
solver version and code commit recorded per run.

Consequence for reporting: where a subproblem stops on its time limit the 1e-4 criterion cannot
be met, and the run ends on the auxiliary stop and reports the
interval [LB, UB] with the incumbent (`result_class = bounded`), exactly as Soares et al. report
their harder model ("optimal or nearly optimal", convergence not guaranteed under positive
subproblem gaps). The hard gate of §3 (certified-exact rate) must be read in that light.

The leader's tax grid is `[0, 200]` USD/t CO2e on the project's one carbon-tax grid (index 0..400,
`TAX_GRID_SCALE_FACTOR = 5e-4`, i.e. 0.5 USD/t per step). Every base instance is generated
directly at this resolution; there is no separate "native" instance grid and "campaign" solve
grid to keep in sync -- that used to be two grids (a coarse 0.01 baked into the generated
instances, rescaled at solve time to a finer campaign step), and mixing them once caused a silent
100x tau-scale mismatch between bilevel and fixed-tax runs. The grid was 1e-4 (index 0..2000,
0.1 USD/t) until the DBP loop was found not to converge at that resolution: on STD_TOY6 it
exhausted max_iterations and reported a tax on the emissions plateau but far from its
least-intervention edge. The failure is a threshold, not a gradient -- 401 indices converge in
4-6 iterations and certify exact, 1001 and above never do -- and tightening `dbp_relative_gap`
100x does not help. 0.5 USD/t is finer than any carbon price is set in practice; the underlying
non-convergence remains undiagnosed and is a known limitation at finer resolutions. A different
resolution remains reachable per design point via `InstanceData.with_tax_grid_step()` (e.g. a
deliberate coarser robustness probe, the retired coarse-resolution variant), but no scheduled point in this
campaign uses it.

### 2.4 Statistical reporting standards

Unchanged from v3:
- **Runtimes:** shifted geometric means (shift 10 s; Achterberg 2007) plus medians and IQR. Censored
  runs are reported as censored, never imputed.
- **Paired comparisons:** Wilcoxon signed-rank for two conditions. α = 0.05, Holm correction within
  each experiment.
- **Factorial effects:** half-normal plots with Lenth's PSE for the Experiment 4 screening design.

---

## 3. Experiment 1 — Verification and Solution Validation

**Objective.** Establish correctness: a hand-verifiable floor, and a certified-exact gate on the
full structural testbed. This is the hard gate for the rest of the campaign — a low certified-exact
rate here blocks proceeding to Experiments 2-4.

**Design.**
- 6 toy instances (`clsc.campaign.toy`), 1-2 products/periods, one node per echelon — small enough
  to re-derive the optimal network by hand.
- All 12 base structural cells, seed 0, full bilevel DBP solve.
- Structural-invariant probe: 1 fast cell + 1 hard cell, each solved at 2 fixed-tax points (0 and
  the grid ceiling) — a direct follower solve should reproduce the bilevel run's values at those
  taxes.
- Gurobi-seed invariance probe: 1 fast cell at `Seed` ∈ {1, 2} (seed 0 is the base-cell run) — the
  certified optimum must not depend on solver-internal tie-breaking.

**Instances / repetitions.** 6 + 12 + (2 cells × 2 tax points) + (1 cell × 2 seeds) = 24 solves.

**Metrics.** Certified-exact rate on the 12 base cells (H1.1); toy-instance solution match against
hand derivation (H1.2); structural-invariant probe agreement (H1.3); seed-invariance of (E\*, τ\*)
(H1.4).

---

## 4. Experiment 2 — Computational Performance

**Objective.** Establish that DBP works, that each of its components earns its keep, that it scales
to the full testbed's range. Consolidates v3's ablation and scalability experiments, which all
ultimately answered this one question from different angles. (The exhaustive-enumeration benchmark
v4 also placed here was removed from the code on 2026-10-08.)

**Design.**
- **`full` DBP reference:** the 6 `REPRESENTATIVE_CELLS`, seed 0. A light seed-noise check adds
  seed 1 on 1 fast + 1 hard cell.
- **Ablation, both variants on the same 3 cells spanning tiers** (1 fast, 1 medium, 1 hard):
  `no_tax_confirmation` (claim-carrying) removes the in-loop min-tax confirmation, testing whether
  the tie-break to τ\* is load-bearing; `no_emissions_cap` (efficiency-only) removes the master's
  emissions cap, the one variant that showed a real timing effect in the prior campaign
  (`no_lex_master_stage2` and `no_warm_start` did not — dropped from the design matrix, the solver
  flags remain supported for a follow-up if needed). The coarse-resolution variant, which tested
  resolution bias on τ\*, is dropped for the same reason:
  the underlying `scale_factor` override remains supported and tested at the unit level, it is
  just no longer a scheduled campaign claim.
- **Scalability, two escalation axes**, each a curve of 3-4 points, only the last of which is a
  new solve:
  - *Materials/products richness* at fixed I25-T6: M4, M8 (both read off the `full` reference above,
    no re-solve) -> `STD_I25_M12_T6` -> `STD_I25_M16_T6` (new; `raw_materials=8, products=4`).
  - *Node count* at fixed M8-T6: I17, I25 (both read off the `full` reference above) ->
    `STD_I33_M8_T6` (new; `entity_split(33)`).
  - *Periods*, for free: T3 -> T6 -> T12 at every I x M combination is already solved once each in
    Experiment 1's base gate — no new solves, just an unclaimed axis in the write-up.
  All three new escalation bases (`STD_I25_M12_T6`, `STD_I25_M16_T6`, `STD_I33_M8_T6`) are
  hard-tier and generated by `clsc.generator.build_escalation_specs` /
  `generate_escalation_bases` — deliberately separate from `python -m clsc.generator benchmark`
  so they never silently appear in the standard 12. Past M8/I25 the algorithm may censor rather
  than certify exact; that is the point of these probes, not a failure of them — a curve showing
  *how* the optimality gap grows past the tractable range is more informative than one that stops
  exactly at the edge.

**Why no KKT/Big-M single-level reformulation baseline.** The follower problem is a genuine MIP,
not an LP or convex NLP: it has ten families of binary decision variables (`y_s`, `y_f`, `y_w`,
`y_h`, `u_prod`, `u_rem`, `zt`, `contract`, `order_su`, plus the transport-mode indicator; see
`clsc.models.subproblems`). KKT-stationarity and strong-duality single-level reformulations of a
bilevel program both require the lower level to be continuous — neither is valid when the lower
level is a MIP. This is a structural fact about this problem class, not a modelling choice left
unexplored: there is no exact single-level reformulation to compare against. (Because the leader's
variable is a single scalar on a finite grid, exhaustive enumeration over that grid would be the
theoretically appropriate exact comparator; it is no longer implemented.) (This note belongs in the paper's methodology or limitations section too, once
`paper/sections/06_computational_experiments.tex` — already known-stale — is redrafted.)

**Instances / repetitions.** 8 (`full`) + 3 (`no_tax_confirmation` × 3 cells) + 3 (`no_emissions_cap` × 3 cells) + 3 (escalation: M12,
M16, I33) = 17 solves.

**Metrics.** Paired per-instance comparison of (E\*, τ\*) and runtime, `full` vs. each variant; runtime
growth in I/M/T.

---

## 5. Experiment 3 — Policy Value and Carbon-Price Calibration (headline)

**Objective.** The paper's central claim: the emissions-optimal tax is a non-degenerate plateau,
not a point, and τ\* is the defensible selection from it — plus the absolute-currency calibration
that makes the claim policy-relevant. Consolidates v3's leader-value and policy-calibration
experiments.

**Cells.** Four: the fast anchor (`STD_I17_M4_T3`), one medium cell (`STD_I25_M4_T6`), and *both*
hard cells that carried a distinct, separately-reportable finding in the prior campaign —
`STD_I25_M8_T6` (a genuine τ\*-precision limitation against an independently re-solved cold check)
and `STD_I25_M8_T12` (the most dramatic burden ratio, ~18.6× in the prior campaign). Both are kept
despite the smaller design because losing either drops a distinct finding.

**Stage 1 (always).** Policy rules on all 4 cells, as fixed-tax follower solves: P0 no tax (index
0); P1 tax ceiling (index 2000); P2 mid-grid flat tax (index 1000). P3 (τ\*, bilevel lexicographic)
is read from Experiment 2's `full` result on the same cell, not re-solved.

**Stage 2 (data-dependent on Experiment 2).** Local plateau refinement: 2 points geometrically
spaced below τ\*, 2 above, per cell — enough to resolve the descending slope for the staircase
figure without the prior campaign's denser 7-point-per-cell survey.

**Stage 3a (always).** Valuation-ratio sweep ρ ∈ {1, 10, 50, 100, 200} on the anchor cell, each a
full bilevel DBP solve, to trace τ\*(ρ) and locate the defensible ratio ρ\*.

**Stage 3b (data-dependent on 3a).** Once ρ\* is identified: the anchored suite at ρ\* — one
bilevel solve, an 11-point tax-indexed frontier (follower-only), and an AUGMECON min-emissions
anchor.

**Instances / repetitions.** 12 (P0-P2 × 4 cells) + 16 (refinement, 4 points × 4 cells) + 5 (ρ
sweep) + 13 (anchored suite: 1 + 11 + 1) = 46 solves.

**Metrics.** Emissions at the ceiling vs. E\* (plateau extent, H3.1); burden ratio (follower
objective at the ceiling ÷ at τ\*) per cell (H3.1); plateau left-edge location vs. an independent
cold check on the two hard cells (H3.1); τ\*(ρ) trend and the chosen ρ\* (H3.2); cost-emissions
frontier shape at ρ\* (H3.3).

---

## 6. Experiment 4 — Sensitivity / Robustness Screening

**Objective.** Which inputs actually move cost and emissions. A screening-only result (main
effects, a tornado chart) — this campaign does not need two-factor interactions or curvature, which
v3's resolution-V design and CCD augmentation stage were built to resolve.

**Design.** Single cell (`STD_I17_M4_T3`), single seed. The 8 continuous factors
(`clsc.campaign.factors.CONTINUOUS_FACTORS`) in a resolution-IV two-level fractional factorial via
fold-over (`clsc.campaign.doe.fractional_factorial.fractional_factorial_signs`), 2^(k0+1) = 32 runs
for k=8. v3's separate 5-factor structural half-fraction and face-centred CCD curvature-augmentation
stage are dropped entirely: structural breadth is already partially exercised by the testbed's own
I/M variation in Experiments 1-2, and curvature is not needed for a "these are the inputs that
matter" claim.

**Instances / repetitions.** 32 solves.

**Metrics.** Main-effect magnitude on cost and emissions per factor, ranked; half-normal plot with
Lenth's PSE to separate active from inactive factors.

---

## 7. Dropped as a formal experiment: solver configuration

v3's exp2 (a full 3×3 `threads` × `MIPFocus` grid on the hardest cell, 11 solves) produced an
implementation choice, not a paper claim. This campaign keeps the values it found
(`threads=4`, `MIPFocus=2`) and re-confirms them with a 2-point ad hoc spot check on the hardest
cell (current defaults vs. one alternative), run manually outside the DOE framework and reported as
one sentence in the paper's implementation notes — not tracked as a campaign experiment or a
design-matrix module.

---

## 8. Execution order

Value-first, same principle as v3: run in order of contribution-per-hour, not logical dependency,
so a negative result surfaces early and cheaply.

1. **exp1** (cheap, gates everything downstream).
2. **exp2** (Experiment 3 reads its `full` manifests for P3/refinement — must complete, or at least its
   `full` arm on the 4 policy cells, before Experiment 3's stage 2 can materialize).
3. **exp3** (the headline experiment; stage 1/3a are independent of exp2 and can start immediately
   after exp2's M0 arm on the policy cells lands).
4. **exp4** (fully independent of the others; can run in parallel with exp2/exp3 if compute allows).
