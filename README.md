# Bilevel CLSC under a Carbon Tax

Bilevel optimization model of a **Closed-Loop Supply Chain (CLSC)** under a carbon-tax
policy. A **leader** (regulator) chooses a carbon tax rate `τ` to minimize total supply-chain
emissions — lexicographically preferring the smallest (least-intervention) tax that still
attains that minimum — and a **follower** (industry) responds by choosing its network
configuration to minimize cost given the tax. Solved by a Decomposition-Based Procedure (DBP)
with a lexicographic leader objective and in-loop certification of the least-intervention tax,
benchmarked against exhaustive grid enumeration.

## Repository layout

```
src/clsc/                 # ALL active code (installable package: pip install -e .)
  generator/              #   instance generator (Tautenhain-based sampler; pure data code)
  config/                 #   solver tolerances (gap_tol.ToleranceConfig) + the project's one
                          #   carbon-tax grid step (tax_grid.TAX_GRID_SCALE_FACTOR)
  models/                 #   instance data model + Gurobi subproblem builders
  solvers/                #   DBP lexicographic bilevel solver (dbp_lex) + the exhaustive-grid
                          #   exact baseline it is benchmarked against (enumeration)
  solver_cli/             #   batch runner CLI (core.py; run via solve_batch)
  campaign/               #   experimental campaign layer (campaign_01)
    orchestrator.py       #     generate / run, keyed by experiment (exp1..exp4)
    designs/              #     one spec module per experiment (exp1_verification .. exp4_sensitivity)
    doe/                  #     generic DOE primitives (fractional_factorial, frontier_sweep)
    instances.py          #     instance materialization for design points
    toy.py                #     hand-verifiable toy instances (Experiment 1)
    factors.py            #     continuous factor registry (Experiment 4)
    structural.py         #     5-way technology/transport menu expansions (scenario builders only;
                           #     not used by campaign_01's own design points)
    valuation.py          #     emissions-valuation rescale (Experiment 3's rho sweep)
    scenarios/            #     scenario instance builders
  analysis/               #   run aggregation -> master table, plus the paper tables
data/instances/           # base + campaign instances (DATA only; generator lives in src/clsc/generator)
experiments/              # generated design matrices (experiments/<campaign>/<experiment>/)
results/                  # solve outputs (git-ignored except README)
scripts/                  # figure and table drivers for the paper
tests/                    # pytest suite
docs/                     # notes (Experimental_Plan.md: the campaign specification)
paper/                    # LaTeX manuscript
pyproject.toml            # packaging + pytest config  (LICENSE/CITATION.cff: still TODO)
```

## Environment

- Developed on Python 3.14 with Gurobi 13 (academic licence); virtualenv `.venv_py314_gurobi13`.
  The package itself declares `requires-python = ">=3.12"`.
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
    --method dbp_lex --scale-factor 0.0005 \
    --mip-gap 1e-6 --dbp-relative-gap 1e-4 --threads 4 --mip-focus 2 \
    --time-limit 10800 --results-root results/runs

# --- Campaign (campaign_01): build design matrices, then solve ---
python -m clsc.campaign.orchestrator generate --experiment all
python -m clsc.campaign.orchestrator run --experiment 1    # resumable; --fail-fast optional
# (--experiment accepts exp1..exp4 or 1..4 or 'all'; --base-instance restricts to one cell)
# `run` refuses to start (exit 3) unless src/, data/instances/base/ and pyproject.toml match
# HEAD -- see "Provenance" below. Add --allow-dirty for a development run.

# --- Post-campaign analysis ---
python -m clsc.analysis.campaign_01.aggregate
python -m clsc.analysis.tables.optimization
python -m clsc.analysis.tables.iterations
```

## Solver configuration (campaign method)

Bilevel (leader-optimizing) solves use a **fine carbon-tax grid** (`--scale-factor 0.0005`,
index {0..400} over 0-200 USD/t, i.e. 0.5 USD/t per step) with `dbp_relative_gap = 1e-4` and
per-MILP `mip_gap = 1e-6`
(`CAMPAIGN_*` in `clsc.campaign.orchestrator`). These are applied per-run
by the orchestrator/CLI; `clsc.config.gap_tol.DEFAULT` holds the neutral coarse-grid fallback
(1% tolerances) used only when no override is given. Each run's `manifest.json` records
`tax_grid_scale_factor`, tolerances, and the code version.

The least-intervention tax is checked **inside** the DBP loop (`confirm_min_tax`, on by default),
at the exact point the emissions gap closes. The gap is the gate, exactly as in Soares et al.
(2021)'s Step 6: a run that reaches the check has already closed `UB - LB <= dbp_relative_gap`
and is **epsilon-optimal** whatever follows. What the check adds is the upgrade to a certified
optimum, and it is their Lemma 3 verbatim -- one condition, `x^{u(K+1)} = x^{uK}`: the master,
re-solved with every accumulated cut, proposes a tax no lower than the confirmed one.

When the proposal *does* undercut the incumbent, the loop **probes it** rather than stopping:
the master's proposal is a certified lower bound on the least-intervention tax, so a smaller
proposal is a direction to search, not a reason to quit. This is the one place the workflow
extends Soares et al. rather than following them, and it exists because their leader has no
second criterion to certify. The probe is budgeted (`stagnation_limit`), because an unbounded
one has no limit short of the grid: it once took STD_TOY6 2002 iterations. Runs that exhaust
the budget report `termination_reason="relative_gap_tax_unconfirmed"`, `exact=False`, and carry
`tax_lower_bound` -- the bracket `[tax_lower_bound, tax_index]` containing the true minimum,
rather than a bare "unconfirmed".

There is **no separate refinement phase and no bisection**; the earlier two-phase workflow
(`lf_lex_exact`) was retired. `--no-confirm-min-tax` disables the check entirely (ablation A1)
and reports the incumbent's tax, an upper bound on the true minimum; confirmation also requires
the Stage-2 lexicographic master (`use_lex_master_stage2`, ablation A2).

## Provenance

Every run writes a `campaign_manifest.json` recording the commit it ran at. That hash only means
something if the working tree matched it, so `orchestrator run` **refuses to start** (exit code 3)
while any result-bearing path differs from HEAD:

| Path | Watched | Why |
|---|---|---|
| `src/` | yes | the code that produced the numbers |
| `data/instances/base/` | yes | campaign instances are materialized from these |
| `pyproject.toml` | yes | dependency pins |
| `paper/`, `docs/`, `tests/`, `results/`, `experiments/` | no | editing the manuscript mid-campaign is normal and cannot change a result |

`--allow-dirty` lifts the refusal for development runs; it prints a warning and stamps
`code_dirty: true` on every manifest it produces, so such runs stay identifiable afterwards.

Each manifest (and each row of `master_runs_campaign_01.csv`) carries:

- `code_version` -- the commit, or `"unknown"` if git could not be consulted;
- `code_dirty` -- `false` (verified clean), `true` (ran anyway), or `null` (unverifiable; **not**
  the same as clean, and never publication-safe);
- `code_dirty_paths` -- exactly which paths differed;
- `instance_sha256` -- the bytes actually solved, for verification against the committed instance;
- `instance_content_sha256` -- only the problem-defining fields (`name`/`sets`/`parameters`), so
  it is comparable across re-materializations, which rewrite `metadata.generated_at_utc`.

## Tests

```bash
python -m pytest              # full suite (slow/gurobi tests included)
python -m pytest -m "not slow"  # fast subset
```

CI (`.github/workflows/tests.yml`) runs the fast subset on every push/PR to `main`; every `gurobi`-marked
test is also `slow` in this suite, so CI never touches the optimizer and needs no Gurobi licence. The
`slow`/`gurobi` tests remain a local, licensed-machine responsibility.
