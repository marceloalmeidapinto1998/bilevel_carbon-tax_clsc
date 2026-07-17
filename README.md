# Bilevel CLSC under a Carbon Tax

Bilevel optimization model of a **Closed-Loop Supply Chain (CLSC)** under a carbon-tax
policy. A **leader** (regulator) chooses a carbon tax rate `τ` to minimize total supply-chain
emissions — lexicographically preferring the smallest (least-intervention) tax that still
attains that minimum — and a **follower** (industry) responds by choosing its network
configuration to minimize cost given the tax. Solved by a Decomposition-Based Procedure (DBP)
with a lexicographic leader objective and a Phase-2 min-tax bisection.

## Repository layout

```
clsc/                     # ALL active code
  config/                 #   solver tolerances (gap_tol.ToleranceConfig)
  models/                 #   instance data model + Gurobi subproblem builders
  solvers/                #   DBP lexicographic bilevel solver + tax breakpoints
  solver_cli/             #   batch runner CLI (core.py; run via solve_batch)
  campaign/               #   experimental campaign layer
    orchestrator.py       #     doe_campaign_02 orchestrator (generate / run)
    designs/              #     one declarative spec module per family (0, A-F)
    doe/                  #     generic DOE primitives (factorials, sweeps, ...)
    instances.py          #     instance materialization for design points
    factors.py            #     continuous/structural factor registry
    structural.py         #     technology/transport menu expansions
    scenarios/            #     scenario instance builders
  analysis/               #   aggregation, integrity checks, paper tables
data/                     # instance generator + base instances (data/instances/base)
manifests/                # generated design matrices (manifests/<campaign>/<family>/)
results/                  # solve outputs (git-ignored except README)
tests/                    # pytest suite
docs/                     # notes
archive/                  # superseded: doe_campaign_01 runner+analysis, legacy dashboard
paper/                    # LaTeX manuscript
```

## Environment

- Python 3.14, Gurobi 13 (academic licence). Virtualenv: `.venv_py314_gurobi13`.
- Install: `pip install -r requirements.txt`.

## Canonical commands

Run from the repo root (the venv Python is used in examples).

```bash
# --- Generate a fresh instance base set (deterministic) ---
python -m data.generator benchmark --output-dir data/instances/base

# --- Solve one instance on the campaign's fine tax grid + Phase-2 min-tax ---
python -m clsc.solver_cli.solve_batch data/instances/base/STD_I25_M8_T6.json \
    --method dbp_lex --scale-factor 0.0001 \
    --mip-gap 1e-6 --dbp-relative-gap 1e-4 --threads 4 --mip-focus 2 \
    --time-limit 10800 --results-root results/runs

# --- Campaign (doe_campaign_02): build design matrices, then solve ---
python -m clsc.campaign.orchestrator generate --family all
python -m clsc.campaign.orchestrator run --family A       # resumable; --fail-fast optional

# --- Post-campaign analysis ---
python -m clsc.analysis.doe_campaign_02.integrity_check
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
