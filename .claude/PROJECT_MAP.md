# PROJECT MAP — Bilevel CLSC under a Carbon Tax

Authoritative orientation document for every agent in this system. Read this **before** touching
any file. It answers: what exists, where it lives, what it is authoritative for, and what it is
*not* authoritative for.

Last mapped: 2026-08-03, branch `campaign-01-remap`, commit `cde0a97`.

---

## 1. What the project is

A **bilevel optimization** study of a Closed-Loop Supply Chain (CLSC) under a carbon tax.

- **Leader** (regulator): chooses a carbon-tax index on a discrete grid to minimise total
  supply-chain emissions, lexicographically preferring the *smallest* tax that still attains the
  emissions minimum (least-intervention tie-break).
- **Follower** (industry): a large MILP choosing network configuration, technology installation,
  transport modes, production/remanufacturing flows to minimise cost given the tax.
- **Solution method**: DBP (Decomposition-Based Procedure) with a lexicographic leader objective
  and a Phase-2 min-tax bisection. Baseline competitor: exhaustive grid enumeration.
- **Headline claim**: the emissions-optimal tax is **not identified** — the leader objective is
  flat over a plateau of tax levels — and τ\* (plateau left edge) is the defensible selection.

Environment: Python 3.14, Gurobi 13 (academic), venv `.venv_py314_gurobi13`. Package installed
editable as `clsc` (`pip install -e .`).

---

## 2. Layer map — where everything lives

### 2.1 Mathematical model

| What | Where | Authoritative for |
|---|---|---|
| Instance data model, validation, JSON I/O | `src/clsc/models/instance.py` (669 l) | parameter names, units, structural invariants |
| Gurobi model builders (leader relaxation, follower MILP, lexicographic stages, cuts) | `src/clsc/models/subproblems.py` (2038 l) | **the model as actually solved** |
| Formal statement (notation, sets, leader, follower) | `paper/sections/04a_notation.tex`, `04b_leader.tex`, `04c_follower.tex` | **the model as published** |
| Notation table | `paper/tables/tab_notation.tex` | symbol ↔ meaning ↔ unit |

> **Critical**: `subproblems.py` and `04c_follower.tex` are two independent statements of the same
> model. Keeping them in agreement is the Mathematical Model Expert's standing job. Where they
> disagree, the **code** is what produced every number in the campaign — the LaTeX is what a
> referee will check. Both must be reconciled; neither silently wins.

Key constants: `EMISSIONS_SCALE = 1e6` (kg → kt) in `subproblems.py`;
`SCALE_FACTOR = 0.01` USD/kg per tax index and `PRODUCT_ROTATION_PER_PERIOD = 4.5` in
`instance.py` — both **deliberately duplicated** from the generator to avoid a model→generator
dependency, with a sync comment. Treat any change to one without the other as a defect.

### 2.2 Solver / algorithm

| What | Where |
|---|---|
| DBP lexicographic bilevel solver, Phase-2 bisection, ablation switches | `src/clsc/solvers/dbp_lex.py` (909 l) |
| Exhaustive grid enumeration baseline (exp8) | `src/clsc/solvers/enumeration.py` |
| Tax breakpoint utilities | `src/clsc/solvers/tax_breakpoints.py` |
| Tolerance config (`ToleranceConfig`, `DEFAULT`) | `src/clsc/config/gap_tol.py` |
| Batch CLI (`python -m clsc.solver_cli.solve_batch`) | `src/clsc/solver_cli/core.py`, `solve_batch.py` |
| Published algorithm pseudocode | `paper/algorithms/alg_{bounding_procedure,lower_bound,upper_bound}.tex` |

### 2.3 Instance generation and data

| What | Where |
|---|---|
| Generator (Tautenhain-based sampler, feasibility repair, geometry, sampling) | `src/clsc/generator/` |
| Literature-derived parameter tables | `src/clsc/generator/tautenhain_data.py` |
| **Base instances** (12 structural cells + toys) | `data/instances/base/*.json` |
| **Campaign instances** (materialised per design point) | `data/instances/campaigns/campaign_01/exp{1..8}/<cell>/` |

Structural grid: I ∈ {17, 25} × M ∈ {4, 8} × T ∈ {3, 6, 12} = 12 cells. Tiers (fast / standard /
hard) are defined in `src/clsc/campaign/designs/_cells.py` and drive the time budgets.

### 2.4 Experimental campaign (DOE)

| What | Where |
|---|---|
| Orchestrator (`generate` / `run`, resumable) | `src/clsc/campaign/orchestrator.py` (729 l) |
| Per-experiment design specs `exp1..exp8` | `src/clsc/campaign/designs/exp*.py` |
| Shared cell definitions, tiers, time budgets | `src/clsc/campaign/designs/_cells.py` |
| **Canonical tax grid definition** | `src/clsc/campaign/designs/_common.py` |
| Generic DOE primitives (factorials, res-V, sweeps, RSM, robustness) | `src/clsc/campaign/doe/` |
| Continuous factor registry (exp6) | `src/clsc/campaign/factors.py` |
| Structural menu expansions (exp6) | `src/clsc/campaign/structural.py` |
| Emissions-valuation rescale ρ (exp7) | `src/clsc/campaign/valuation.py` |
| Hand-verifiable toy instances (exp1) | `src/clsc/campaign/toy.py` |
| **Generated design matrices** | `experiments/campaign_01/exp*/design_matrix.csv` |

Commands: `python -m clsc.campaign.orchestrator generate --experiment all|1..8`, then
`... run --experiment N`.

### 2.5 Results (raw)

`results/runs/campaign_01/<experiment>/<base_instance>/<design_point>/`, one directory per run,
each containing:

| File | Contents |
|---|---|
| `campaign_manifest.json` | design-point identity: experiment, variant, seed, factors, budgets |
| `manifest.json` | solver invocation: tolerances, `tax_grid_scale_factor`, code version |
| `result.json` | full solver result incl. termination reason, bounds, gap |
| `summary.json` / `summary.csv` | flattened headline values |
| `solution.json` | variable values of the incumbent |
| `dbp_trace.csv` | per-iteration LB/UB trace (exp8 also writes `enumeration_trace.csv`) |

381 completed runs, 119.6 h of solver time. **The campaign is complete.**

Run logs at `results/runs/campaign_01/_*.log` (`_heartbeat.log`, `_campaign_detached.log`, …).

### 2.6 Aggregation, tables, figures, reports

| Product | Producer | Output |
|---|---|---|
| **Master run table** (44 cols × 381 rows) | `src/clsc/analysis/campaign_01/aggregate.py` | `results/analysis/campaign_01/tables/master_runs_campaign_01.csv` |
| Paper tables T1–T7 (csv + booktabs tex + pdf) | `scripts/make_campaign_01_tables.py` | `results/analysis/campaign_01/tables/t{1..7}_*.{csv,tex,pdf}` |
| Paper figures 1–5 (pdf + png) | `scripts/make_campaign_01_figures.py` | `results/analysis/campaign_01/figures/fig{1..5}_*.{pdf,png}` |
| Per-run optimization / iteration tables (legacy renderers) | `python -m clsc.analysis.tables.optimization`, `... .tables.iterations` | ad-hoc |
| Canonical path constants | `src/clsc/analysis/campaign_01/paths.py` | — |
| Fixed column schemas | `src/clsc/analysis/common/schemas.py` | — |
| **Analysis reports** | *(nothing — see §4)* | `results/analysis/campaign_01/reports/` **← EMPTY** |

Master-table columns worth knowing: `campaign_id, experiment_id, design_point_id,
base_instance_id, I, M, T, algorithm_variant, seed_offset, gurobi_seed, valuation_ratio,
code_version, solver_method, solve_status, termination_reason, censored, cost, emissions,
follower_objective, leader_tax_index, tax_grid_step_usd_per_kg, leader_tax_usd_per_tonne,
runtime_seconds, wall_clock_seconds, mip_gap, time_limit_seconds, wall_clock_cap_seconds,
validation_status, error_type, output_path, notes`, plus 5 `*_menu` structural columns and 8
`factor__*` coded-factor columns.

### 2.7 Existing analyses (the prior art this system must respect)

| Artifact | Status | How agents must treat it |
|---|---|---|
| `docs/Experimental_Plan.md` (v3, 694 l) | **The de-facto analysis record.** Contains design spec *and* results *and* self-corrections, per experiment, with hypotheses H1.1–H8.2 | A **claim source to verify**, not ground truth (§3) |
| `docs/prompt_analise_campaign_01.md` | Analysis brief listing four campaign-specific traps | Absorbed into `standards/known_pitfalls.md` |
| `paper/sections/06_computational_experiments.tex` (195 l) | Draft | Verify every number against the master table |
| `paper/sections/07_discussion.tex` (119 l) | Draft | ditto |
| `paper/tables/tab_*.tex` | Hand-maintained, **parallel** to the generated `t1..t7` | Duplication risk — see §4.4 |
| `tests/` (19 files) | Green suite incl. golden/regression tests | Behavioural spec of solver + campaign |

---

## 3. Why `Experimental_Plan.md` is not ground truth

It is an excellent document and it is the single best summary of the campaign. It is also a
document that has **corrected its own published numbers at least four times** — see its §3
correction dated 2026-08-03 (a median and a policy-band conclusion, both wrong), and the four
"Correction from v2" entries in §10, §11.1, §14 (tier caps and exp6 run counts documented as
changed when the code was never changed).

The lesson the document itself teaches: *narrative drifts from data*. Therefore:

> **Every quantitative claim an agent repeats from `Experimental_Plan.md` is evidence tier E3
> ("reported") until it is recomputed from `master_runs_campaign_01.csv` or a run manifest.**
> See `standards/evidence_and_claims.md`.

This is not distrust of the author; it is the mechanism by which this system is worth more than a
careful re-read.

---

## 4. Gaps this system exists to close

Found during the 2026-08-03 mapping. These are the framework's initial backlog.

### 4.1 The statistical layer does not exist in code — **highest priority**

`Experimental_Plan.md` §2.4 mandates shifted geometric means, Wilcoxon signed-rank, Friedman +
Nemenyi, Holm correction, ANOVA with partial η², Lenth's method, Benjamini–Hochberg, and BCa
bootstrap CIs. §10 *reports results from* OLS + Lenth + a BH table.

A repo-wide search for `scipy.stats`, `statsmodels`, `lenth`, `bootstrap`, `wilcoxon`, `anova`,
`benjamini`, `holm`, `friedman`, `nemenyi`, `half_normal` across `src/`, `scripts/` and `tests/`
returns **zero hits**.

Dependency state, verified in `.venv_py314_gurobi13` on 2026-08-03:

| Package | Importable | Declared in `pyproject.toml` |
|---|---|---|
| `numpy`, `pandas`, `matplotlib`, `SALib` | yes | yes |
| **`scipy`** | **yes** | **no** — transitive, almost certainly via SALib |
| **`statsmodels`** | **no** | no |

So `scipy.stats` (Wilcoxon, Friedman, bootstrap, distributions) is available *by accident* and
must be **declared** before anything depends on it; `statsmodels` is absent, so OLS factorial
effects must either be computed with `numpy.linalg.lstsq` on the coded design matrix — entirely
adequate for a saturated ±1 factorial, and it avoids a heavy dependency — or `statsmodels` must
be added deliberately. Recommend `numpy.linalg.lstsq` plus an explicit `scipy>=1.11` declaration.

**Consequence**: the exp6 statistical results in §10 cannot currently be reproduced from this
repository. They may well be correct — they were computed somewhere — but they have no provenance
and no regression test. The Lenth-PSE anomaly §10 flags for a pre-publication cross-check cannot
be cross-checked either, for the same reason.

Owner: **Statistical Analyst**, gated by **Data Auditor**. This is the one place where the system
is expected to *write new code*, not just analyse.

### 4.2 `results/analysis/campaign_01/reports/` is empty

The path exists and `ensure_analysis_dirs()` creates it, but nothing writes there. Analysis lives
as prose inside a planning document. Every workflow in this system writes its durable output
**there**, using the templates.

### 4.3 Specification and findings are entangled in one document

`Experimental_Plan.md` is simultaneously the pre-registration, the lab notebook, and the results
summary. That is why corrections are hard to track. This system separates them:
plan → `docs/Experimental_Plan.md` (frozen spec), evidence → `reports/claim_ledger.md`,
narrative → `paper/`.

### 4.4 Two parallel table families

`paper/tables/tab_*.tex` (hand-maintained: `tab_results_main`, `tab_sensitivity`, `tab_instances`,
`tab_scenarios`, `tab_comparison`) and the generated `results/analysis/campaign_01/tables/t*.tex`
(T1–T7). These overlap in content and can disagree. The Editor owns resolving this; the target
state is that `paper/` includes generated tables rather than restating them.

### 4.5 Open scientific items carried from the plan

- exp6 seed-1 Lenth PSE collapse → needs half-normal plot or bootstrap noise estimate (§10).
- exp3: 1 censored M0 cell of 43 (§8.1).
- exp5 H5.3: cold fixed-tax solves fail to reproduce E\* at τ\* on the 2 hardest cells
  (+0.035 %, +0.113 %) — a stated precision bound on τ\*, mechanism hypothesised (lexicographic
  freeze band) but not proven (§6).
- exp8: 1 of 4 cells censored before reaching the true left edge (§7).
- exp7: AUGMECON anchor shows a ~0.5 % tax-instrument gap vs. the physical emissions minimum,
  observed on a single cell (§9).
- exp1: invariance-probe directory naming is stale (cosmetic, §11.1).

---

## 5. Canonical commands

```bash
# aggregate raw runs -> master table   (read-only over results/runs; cheap; safe)
python -m clsc.analysis.campaign_01.aggregate

# regenerate paper tables and figures  (reads the master table; cheap; safe)
python scripts/make_campaign_01_tables.py
python scripts/make_campaign_01_figures.py

# tests
python -m pytest                 # full suite (gurobi + slow)
python -m pytest -m "not slow"   # fast subset

# EXPENSIVE — requires explicit human authorization, see standards/reproducibility.md
python -m clsc.campaign.orchestrator generate --experiment all
python -m clsc.campaign.orchestrator run --experiment N
python -m clsc.solver_cli.solve_batch <instance.json> --method dbp_lex ...
```

---

## 6. Cost model — why agents must not solve casually

| Experiment | Spent | Note |
|---|---|---|
| exp1 verification | 8.7 h | |
| exp2 solver config | **61.9 h** | 62 % of campaign compute for one appendix paragraph — run on the hardest cell where half the grid cannot converge. **Never repeat in this form.** |
| exp3 ablation | 18.9 h | |
| exp4 scalability | 7.7 h | |
| exp5 plateau (headline) | ~1.3 h | best contribution-per-hour in the campaign |
| exp6 sensitivity | ~7.4 h | |
| exp7 calibration | ~0.3 h | |
| exp8 enumeration benchmark | 13.4 h | |
| **Total** | **119.6 h / 381 runs** | |

The exp2 vs exp5 contrast is the system's guiding heuristic: **statistical volume runs on fast
cells; hard cells are for the scalability table only.** Any proposal for a sweep, grid, or
factorial on a hard-tier cell is a design error and the Project Manager must reject it.
