# Bilevel CLSC under a Carbon Tax

Bilevel optimization model of a **Closed-Loop Supply Chain (CLSC)** under a carbon-tax
policy. A **leader** (regulator) chooses a carbon tax rate `τ` to minimize total supply-chain
emissions — lexicographically preferring the smallest (least-intervention) tax that still
attains that minimum — and a **follower** (industry) responds by choosing its network
configuration to minimize cost given the tax. Solved by a Decomposition-Based Procedure (DBP)
with a lexicographic leader objective and a Phase-2 min-tax bisection.

## Repository layout

```
src/clsc/                 # ALL active code (installable package: pip install -e .)
  generator/              #   instance generator (Tautenhain-based sampler; pure data code)
  config/                 #   solver tolerances (gap_tol.ToleranceConfig)
  models/                 #   instance data model + Gurobi subproblem builders
  solvers/                #   DBP lexicographic bilevel solver + tax breakpoints
  solver_cli/             #   batch runner CLI (core.py; run via solve_batch)
  campaign/               #   experimental campaign layer (campaign_01)
    orchestrator.py       #     generate / run, keyed by experiment (exp1..exp4)
    designs/              #     one spec module per experiment (exp1_verification .. exp4_sensitivity)
    doe/                  #     generic DOE primitives (fractional factorials, tax-grid sweeps)
    instances.py          #     instance materialization for design points
    toy.py                #     hand-verifiable toy instances (Experiment 1)
    factors.py            #     continuous factor registry (Experiment 4)
    structural.py         #     5-way technology/transport menu expansions (scenario builders only;
                           #     not used by campaign_01's own design points)
    valuation.py          #     emissions-valuation rescale (Experiment 3's rho sweep)
    scenarios/            #     scenario instance builders
  analysis/               #   aggregation, integrity checks, paper tables (analysis/campaign_01)
data/instances/           # base + campaign instances (DATA only; generator lives in src/clsc/generator)
experiments/              # generated design matrices (experiments/<campaign>/<experiment>/)
results/                  # solve outputs (git-ignored except README)
tests/                    # pytest suite
docs/                     # notes
archive/                  # superseded, INERT (not a package): legacy scenario dashboard
paper/                    # LaTeX manuscript
pyproject.toml            # packaging + pytest config  (CITATION.cff: how to cite)
```

## Environment

- Python 3.14, Gurobi 13 (academic licence). Virtualenv: `.venv_py314_gurobi13`.
- Install (editable, from repo root): `pip install -e .` — puts the `clsc` package on
  the path so every `python -m clsc.*` command below works from any directory.
  (`requirements.txt` mirrors the runtime deps declared in `pyproject.toml`.)

## Canonical commands

Run from the repo root (the venv Python is used in examples).

```bash
# --- Generate a fresh instance base set (deterministic) ---
python -m clsc.generator benchmark --output-dir data/instances/base

# --- Solve one instance on the campaign's fine tax grid + Phase-2 min-tax ---
python -m clsc.solver_cli.solve_batch data/instances/base/STD_I25_M8_T6.json \
    --method dbp_lex --scale-factor 0.0001 \
    --mip-gap 1e-6 --dbp-relative-gap 1e-4 --threads 4 --mip-focus 2 \
    --time-limit 10800 --results-root results/runs

# --- Campaign (campaign_01): build design matrices, then solve ---
python -m clsc.campaign.orchestrator generate --experiment all
python -m clsc.campaign.orchestrator run --experiment 1    # resumable; --fail-fast optional
# (--experiment accepts exp1..exp4 or 1..4 or 'all'; --base-instance restricts to one cell)

# --- Post-campaign analysis ---
python -m clsc.analysis.campaign_01.aggregate
python -m clsc.analysis.tables.optimization
python -m clsc.analysis.tables.iterations
```

## Solver configuration (campaign method)

Bilevel (leader-optimizing) solves use a **fine carbon-tax grid** (`--scale-factor 0.0001`,
index {0..2000} over 0–200 USD/t) with `dbp_relative_gap = 1e-4`, per-MILP `mip_gap = 1e-6`,
and the Phase-2 min-tax bisection (`refine_min_tax`, on by default). These are applied per-run
by the orchestrator/CLI; `clsc.config.gap_tol.DEFAULT` holds the neutral coarse-grid fallback
(1% tolerances) used only when no override is given. Each run's `manifest.json` records
`tax_grid_scale_factor`, tolerances, and the code version.

## Tests

```bash
python -m pytest              # full suite (slow/gurobi tests included)
python -m pytest -m "not slow"  # fast subset
```
