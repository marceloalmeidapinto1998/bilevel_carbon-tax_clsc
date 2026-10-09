# Closed-Loop Supply Chain Network Design under Carbon Pricing

A bilevel model of a closed-loop supply chain under a carbon tax, solved to global ε-optimality with the Deterministic Bounding Procedure of Soares et al. (2021).

## Overview

A regulator (the leader) sets a carbon tax rate `τ` on a finite grid. A closed-loop supply chain operator (the follower) responds by choosing its network — facilities, technologies, capacities, transport modes, and forward and reverse flows — to minimise operating cost plus tax, as a mixed-integer linear program. The leader minimises `F = E + w·τ`: the follower's emissions `E` plus a small weight `w` on the tax rate, so that among taxes that abate emissions equally it prefers the lower one. Ties in the follower's problem are broken optimistically, in favour of the lowest emissions among its cost-optimal responses.

The bilevel problem is solved with the Deterministic Bounding Procedure (DBP) of Soares, Alves and Henggeler Antunes (2021): a relaxation master over the follower's feasible region gives a lower bound on `F`, exact follower evaluations give an upper bound, and value-function cuts tighten the master until the two bounds close within a chosen tolerance. The repository also includes an instance generator, based on the sampling rules of Tautenhain et al. (2021) for the supply-chain model of Mota et al. (2018), and the 15 benchmark instances it produces.

## Project structure

```text
.
├── data/                    # the 15 benchmark instances (JSON)
├── src/clsc/                # the Python package
│   ├── config/              #   method defaults, shared constants, tax-grid step
│   ├── generator/           #   instance generator (CLI: clsc-generate)
│   ├── models/               #   instance loading and the Gurobi models
│   │   ├── instance_data.py #     load and validate an instance
│   │   ├── supply_chain.py  #     supply-chain MILP shared by follower and master
│   │   ├── follower.py      #     follower model and its two-stage optimistic solve
│   │   ├── master.py        #     DBP relaxation master
│   │   └── gurobi_utils.py  #     solve wrapper and result types
│   ├── solvers/dbp.py       #   the Deterministic Bounding Procedure
│   └── solver_cli/          #   batch solver CLI (clsc-solve): parsing, output files, revalidation
├── tests/test_baseline.py   # regression tests
├── pyproject.toml           # metadata, dependencies, console scripts, pytest settings
└── requirements.txt         # mirrors the dependencies in pyproject.toml
```

## Requirements

- Python ≥ 3.12.
- [Gurobi](https://www.gurobi.com/) 13 with a valid licence (`gurobipy>=13,<14`). The licence is needed both to solve instances and to generate them, because the generator checks each instance's feasibility with Gurobi.
- PyYAML (only used when reading or writing YAML instance files).
- pytest, for the test suite (`dev` extra).

## Installation

```bash
git clone https://github.com/marceloalmeidapinto1998/bilevel-clsc-carbon-pricing.git
cd bilevel-clsc-carbon-pricing
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

This installs the `clsc` package and two commands, `clsc-solve` and `clsc-generate`. `python -m clsc.solver_cli` and `python -m clsc.generator` are equivalent to them.

## Usage

### Solve instances

```bash
# one instance, default configuration
clsc-solve data/STD_I17_M4_T3.json --results-root results/runs

# every instance in a folder
clsc-solve data --results-root results/runs

# a different tax weight (see Configuration)
clsc-solve data/STD_I17_M4_T3.json --leader-tax-weight-relative 1e-5
```

Each instance writes to `results/runs/<dataset>/<instance>/dbp/`:

| File | Content |
|---|---|
| `summary.json`, `summary.csv` | result class, termination reason, tax, cost, emissions, bounds, gap, validation status |
| `result.json` | full result: bounds with certificates, follower stage gaps, timings |
| `solution.json` | the incumbent's variable values |
| `dbp_trace.csv` | one row per DBP iteration: proposed tax, bounds, subproblem times |
| `manifest.json` | configuration used: tolerances, time limits, tax weight, flags |

`clsc-solve --help` lists every option.

### Generate instances

```bash
# the 12-instance benchmark (I in {17, 25} x M in {4, 8} x T in {3, 6, 12})
clsc-generate benchmark --output-dir data

# the three escalation instances (STD_I25_M12_T6, STD_I25_M16_T6, STD_I33_M8_T6)
clsc-generate escalation --output-dir data

# a custom instance
clsc-generate instance --name my_case --seed 1 --periods 6 --output data/my_case.json
```

Generation is deterministic: each benchmark instance's seed is derived from `--seed-base` (default 0) and its name.

### Run the tests

```bash
python -m pytest                  # all regression tests
python -m pytest -m "not slow"    # skip the solver test
```

[`tests/test_baseline.py`](tests/test_baseline.py) checks that the generator reproduces the committed base and escalation instances, and that a default solve of `STD_I17_M4_T3` reproduces its reference summary. The tests need a Gurobi licence and are skipped without one.

## Configuration

The method's defaults are in [`src/clsc/config/defaults.py`](src/clsc/config/defaults.py) (`DEFAULT`). A solve with no options uses them; each CLI flag below overrides one.

| Parameter | CLI flag | Default | Meaning |
|---|---|---|---|
| `dbp_relative_gap` | `--dbp-relative-gap` | `1e-4` | DBP stopping tolerance ε on the relative gap of `F` (Soares et al., 2021) |
| `mip_gap` | `--mip-gap` | `1e-2` | Gurobi MIP gap for the follower (Tautenhain et al., 2021) |
| `master_mip_gap` | `--master-mip-gap` | `1e-4` | Gurobi MIP gap for the relaxation master |
| `time_limit` | `--time-limit` | `600` s | time limit per MILP subproblem (`--master-time-limit` sets the master's separately) |
| — | `--wall-clock-cap` | none | optional limit on a whole run |
| `stagnation_limit` | — | `10` | stop after this many iterations without a bound update |
| `tax_weight_relative` | `--leader-tax-weight-relative` | `1e-4` | `q` in `w = q · E_ref` (see below) |
| `threads`, `mip_focus` | `--threads`, `--mip-focus` | `4`, `2` | Gurobi settings |

The tax weight is a policy assumption, not a tolerance: `w = q · E_ref`, where `E_ref` is the lowest emissions the cut-free master can reach. `q = 1e-4` reads as "the regulator accepts losing 1% of the minimum emissions to avoid 100 USD/t of tax". `--leader-tax-weight` sets `w` directly, in kg CO2e per USD/t.

The tax grid step is `TAX_SCALE_FACTOR = 1e-3` USD/kg CO2e (1 USD/t per index), set in [`src/clsc/config/tax_scale.py`](src/clsc/config/tax_scale.py). The benchmark instances use a tax range of 0–200 USD/t.

## References

The method builds on:

- Soares, Alves and Henggeler Antunes (2021). A deterministic bounding procedure for the global optimization of a bi-level mixed-integer problem. *European Journal of Operational Research*, 291, 52–66.
- Tautenhain, Barbosa-Póvoa, Mota and Nascimento (2021). An efficient Lagrangian-based heuristic to solve a multi-objective sustainable supply chain problem. *European Journal of Operational Research*.
- Mota et al. (2018), whose closed-loop supply chain network design model the instance generator and the follower/master formulation are based on.
