# Bilevel CLSC under a Carbon Tax

Bilevel optimization model of a **Closed-Loop Supply Chain (CLSC)** under a carbon-tax
policy. A **leader** (regulator) chooses a carbon tax rate `τ` to minimize `F = E + w·τ` — total
supply-chain emissions `E` plus a small weight `w` on the tax, so that among taxes that abate the
same it prefers the lower one — and a **follower** (industry) responds by choosing its network
configuration to minimize cost given the tax. Solved by the Deterministic Bounding Procedure (DBP)
of Soares et al. (2021).

## Repository layout

```
src/clsc/                    # the installable package
  config/
    defaults.py              #   the method's defaults (tolerances, budgets, tax weight)
    constants.py             #   constants shared across the package
    tax_scale.py             #   the one tax-grid step, TAX_SCALE_FACTOR
  generator/                 #   instance generator (Tautenhain-based sampler; `clsc-generate`)
    instance_builder.py      #     generate_instance / write_instance
    benchmark.py             #     the 12-instance benchmark and the escalation instances
    ...                      #     config, sampling, geometry, feasibility, tautenhain_data
  models/
    instance_data.py         #   loading and validating an instance (InstanceData)
    supply_chain.py          #   the supply-chain MILP shared by follower and master
    follower.py              #   the follower's model and its two-stage optimistic solve
    master.py                #   the DBP relaxation master: objective, cuts, caps, elastic cuts
    gurobi_utils.py          #   solve wrapper and result types
  solvers/
    dbp.py                   #   the Deterministic Bounding Procedure
  solver_cli/                #   batch CLI (`clsc-solve`)
    cli.py                   #     argument parsing and the main loop
    results.py               #     the output files
    validation.py            #     revalidation of the saved solution
data/instances/base/         # base instances (the 12-instance testbed + 3 escalation instances)
tests/                       # regression tests (test_baseline.py)
```

## Environment

- Developed on Python 3.14 with Gurobi 13 (academic licence). The package declares
  `requires-python = ">=3.12"`.
- Install (editable, from the repo root): `pip install -e ".[dev]"` (the `dev` extra adds
  pytest). This installs the `clsc` package and two commands, `clsc-generate` and `clsc-solve`.
  `requirements.txt` mirrors the dependencies declared in `pyproject.toml`.
- A Gurobi licence is required to solve, and to generate instances (each instance's feasibility
  is checked with Gurobi).

## Commands

```bash
# Generate the base instance set (deterministic)
clsc-generate benchmark --output-dir data/instances/base

# Solve one instance with the default method (see "Solver configuration")
clsc-solve data/instances/base/STD_I25_M8_T6.json --results-root results/runs

# Solve every instance in a folder
clsc-solve data/instances/base --results-root results/runs
```

The three escalation instances (`STD_I25_M12_T6`, `STD_I25_M16_T6`, `STD_I33_M8_T6`), which
extend the testbed past its standard range, are not written by `benchmark`:

```bash
clsc-generate escalation --output-dir data/instances/base
```

`python -m clsc.generator` and `python -m clsc.solver_cli` are equivalent to the two commands;
`clsc-solve --help` lists every option.

Each run writes `summary.json`/`summary.csv`, `result.json`, `solution.json`, `dbp_trace.csv`
and a `manifest.json` recording the tolerances, budgets, tax weight and code version.

## Solver configuration

The tax is chosen on a single grid (`TAX_SCALE_FACTOR = 1e-3` USD/kg per index, i.e. 1 USD/t per
step, index 0..200). The defaults in `clsc.config.defaults.DEFAULT` are the method; every CLI flag
only overrides one of them.

| Parameter | Default | Source |
|---|---|---|
| DBP stopping tolerance `dbp_relative_gap` (eps) | 1e-4 | Soares et al. (2021) |
| Subproblem slack eps' | 1e-5 absolute floor (`dbp_cut_epsilon`); ~1e-6 relative (`lex_epsilon_prime`) | Soares et al. (2021) |
| MIP gap, follower (`--mip-gap`) | 1e-2 | Tautenhain et al. (2021), this follower model |
| MIP gap, relaxation master (`--master-mip-gap`) | 1e-4 | solver default, as Soares et al. ran it (a percentage target freezes the lower bound) |
| Time limit per MILP subproblem (`--time-limit`) | 600 s | Soares et al. (2021) |
| Time limit per run (`--wall-clock-cap`) | none | Soares et al. (2021) |
| Auxiliary stop | 10 iterations without a bound update | Soares et al. (2021) |
| Leader's tax weight `q` (`--leader-tax-weight-relative`) | 1e-4 | policy assumption (below) |
| Gurobi threads / MIPFocus | 4 / 2 | |

### The leader's objective

The leader minimizes `F = E + w·τ`. One criterion means Soares et al. (2021)'s DBP applies as
written: a single master stage, the `UB_F − LB_F` gap against `dbp_relative_gap`, and their
Step 6 — once the gap has closed, the result is **optimal** if the master re-proposes the tax just
evaluated (Lemma 3) and **epsilon-optimal** otherwise. The bounds in the summary
(`leader_objective_lb`, `leader_objective_ub`) are bounds on `F`;
`leader_tax_weight` records `w` (kg CO2e per USD/t) and `emissions` the incumbent's own emissions.

`w` is a **policy assumption**, not a tolerance: how much emissions the regulator gives up to avoid
1 USD/t of tax. `--leader-tax-weight-relative q` sets `w = q · E_ref`, with `E_ref` the least
emissions the cut-free master can reach, so that `q` means the same on every instance; the default
`q = 1e-4` states *the regulator accepts losing 1 % of the minimum achievable emissions to avoid
100 USD/t of tax*. `--leader-tax-weight` gives `w` directly in kg per USD/t instead. It is a value
judgement, recorded per run and meant to be varied (0.1 % / 1 % / 10 % per 100 USD/t is
`q = 1e-5 / 1e-4 / 1e-3`). The tax resolution follows from it: the gap cannot tell two taxes apart
if their `F` differ by less than `dbp_relative_gap`, so the tax is resolved to about
`dbp_relative_gap / q` USD/t — 1 USD/t at the defaults — and that resolution should be reported
with the results.

### Subproblems that cannot be solved to optimality

Soares et al.'s Section 7 treatment is implemented in full. The lower bound is the master's dual
bound even when it times out (the exact form of their `UB_F = F(1+gap)`), and a timed-out master's
incumbent tax is proposed next instead of ending the run. The first time the master returns no
point at all, its cuts are made elastic in place — one penalised slack per cut (P5-D) — and it is
re-solved from the best evaluated point (`--no-elastic-master` disables this). A follower that
times out is improved by their subproblem P6 (`--no-follower-improvement`), its best response is
used, and a tie-break that finds nothing keeps the Step-2 response (P4-D). The master carries
`F <= UB` (their `F <= UB_F`, after Mitsos 2010; `--no-emissions-cap` removes it).

Where a subproblem stops on its time limit the eps criterion cannot be certified, and the run ends
on the auxiliary stop and reports the interval `[leader_objective_lb, leader_objective_ub]` with
the incumbent attaining the upper bound. `result_class` in the summary says which case applies:
`certified`, `epsilon_optimal` or `bounded`.

## Tests

```bash
python -m pytest                 # both regression tests (about 2 minutes)
python -m pytest -m "not slow"   # the generator tests only
```

`tests/test_baseline.py` checks that the generator reproduces the 12 committed base instances
and the 3 escalation instances, and that a default solve of `STD_I17_M4_T3` reproduces its
reference summary (certified, tax index 26).
All need a Gurobi licence and are skipped without one.

## Licence

No licence has been chosen yet (see the TODO in `pyproject.toml`); until one is added, the code is
not licensed for reuse.
