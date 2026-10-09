# Bilevel CLSC under a Carbon Tax

A bilevel model of a closed-loop supply chain under a carbon tax, solved to global ε-optimality with the Deterministic Bounding Procedure of Soares et al. (2021).

![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue)
![Solver](https://img.shields.io/badge/solver-Gurobi%2013-red)

## Overview

A regulator (the **leader**) sets a carbon tax rate `τ` on a finite grid. A closed-loop supply chain operator (the **follower**) responds by choosing its network (facilities, technologies, capacities, transport modes, and forward and reverse flows) to minimise operating cost plus tax. The leader minimises `F = E + w·τ`: the total emissions `E` of the follower's response plus a small weight `w` on the tax, so that among taxes that abate equally it prefers the lower one. The follower's problem is a mixed-integer linear program; ties are broken optimistically (lowest emissions among its cost-optimal responses).

The bilevel problem is solved with the Deterministic Bounding Procedure (DBP) of Soares et al. (2021). A relaxation master over the follower's feasible region gives a lower bound on `F`, exact follower evaluations give an upper bound, and value-function cuts tighten the master until the gap closes. Subproblems that cannot be solved to optimality within their time limit are handled as in the reference: dual bounds from timed-out masters, elastic cuts, and the follower-improvement subproblem P6.

The repository also contains an instance generator, based on the sampling rules of Tautenhain et al. (2021) for the supply-chain model of Mota et al. (2018), and the 15 benchmark instances it produces.

## Key features

- Bilevel carbon-tax model with a mixed-integer, multi-period closed-loop supply-chain follower (Gurobi).
- DBP solver with an exact linearisation of `τ · E` and certified lower and upper bounds on the leader's objective.
- Handling of subproblems that hit their time limit: partial-master dual bounds, elastic cuts as a remedy, follower improvement (P6), and an auxiliary stagnation stop.
- Each result is classified as `certified`, `epsilon_optimal` or `bounded`, and each saved solution is revalidated.
- Deterministic instance generator (`clsc-generate`) that reproduces the committed benchmark.
- Batch solver CLI (`clsc-solve`) that writes a summary, the full result, the solution, a per-iteration trace and a manifest of the configuration.

## Project structure

```text
.
├── data/     # the 15 benchmark instances (JSON)
├── src/clsc/                # the Python package
│   ├── config/              #   method defaults, shared constants, tax-grid step
│   ├── generator/           #   instance generator (CLI: clsc-generate)
│   ├── models/              #   instance loading and the Gurobi models
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

- Python ≥ 3.12 (developed on 3.14).
- [Gurobi](https://www.gurobi.com/) 13 with a valid licence (`gurobipy>=13,<14`). The licence is needed to solve and also to generate instances, because the generator checks each instance's feasibility with Gurobi.
- PyYAML (only for YAML instance files).
- pytest for the tests (`dev` extra).

## Installation

```bash
git clone https://github.com/marceloalmeidapinto1998/bilevel-clsc-carbon-pricing.git
cd bilevel-clsc-carbon-pricing
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

This installs the `clsc` package and two commands, `clsc-solve` and `clsc-generate`. `python -m clsc.solver_cli` and `python -m clsc.generator` are equivalent.

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
# the 12-instance benchmark (I ∈ {17, 25} × M ∈ {4, 8} × T ∈ {3, 6, 12})
clsc-generate benchmark --output-dir data

# the three escalation instances (STD_I25_M12_T6, STD_I25_M16_T6, STD_I33_M8_T6)
clsc-generate escalation --output-dir data

# a custom instance
clsc-generate instance --name my_case --seed 1 --periods 6 --output data/my_case.json
```

Generation is deterministic: each benchmark instance's seed is derived from `--seed-base` (default 0) and its name.

## Configuration

The method's defaults are in [`src/clsc/config/defaults.py`](src/clsc/config/defaults.py) (`DEFAULT`). A solve with no options uses them; each CLI flag overrides one.

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

**The tax weight is a policy assumption, not a tolerance.** `w = q · E_ref`, where `E_ref` is the lowest emissions the cut-free master can reach. `q = 1e-4` means *the regulator accepts losing 1 % of the minimum emissions to avoid 100 USD/t of tax*. `--leader-tax-weight` sets `w` directly, in kg CO2e per USD/t. The tax is resolved to about `dbp_relative_gap / q` USD/t (1 USD/t at the defaults).

The tax grid step is `TAX_SCALE_FACTOR = 1e-3` USD/kg CO2e (1 USD/t per index), set in [`src/clsc/config/tax_scale.py`](src/clsc/config/tax_scale.py). The instances use a range of 0–200 USD/t.

In the output, `leader_objective_lb` and `leader_objective_ub` bound `F`, not emissions alone. `emissions` is the incumbent's own emissions and `leader_tax_weight` records `w`.

## Data

The 15 benchmark instances are in [`data/`](data/), named `STD_I<nodes>_M<materials>_T<periods>`. Each is a JSON file with four keys:

- `name`: the instance name;
- `metadata`: seed, generator configuration, node coordinates, units;
- `sets`: index sets (suppliers, factories, warehouses, retailers, hubs, products, technologies, modes, periods, arcs);
- `parameters`: costs, capacities, demands, return rates, emission factors, distances and the tax range.

The data are synthetic, sampled by the generator; no external data set is needed. To solve your own case, create a file with the same structure (for example with `clsc-generate instance`) and pass its path to `clsc-solve`.

## Results / Examples

Solving `STD_I17_M4_T3` with the defaults (`clsc-solve data/STD_I17_M4_T3.json`) writes, in `summary.json`:

```json
{
  "instance": "STD_I17_M4_T3",
  "result_class": "certified",
  "termination_reason": "optimal",
  "iterations": 5,
  "tax_index": 26,
  "tax_rate": 0.026,
  "cost": 2525919.350079193,
  "emissions": 25406136.47956628,
  "leader_objective_lb": 25471977.012896396,
  "leader_objective_ub": 25471977.05849877,
  "relative_gap": 1.79e-09,
  "validation_status": "validated"
}
```

`tax_rate` is in USD/kg CO2e (26 USD/t), cost in USD and emissions in kg CO2e. This run takes about 1–2 minutes with 4 threads. Larger instances can take hours and may end as `epsilon_optimal` or `bounded`.

## Testing

```bash
python -m pytest                  # all regression tests (about 2 minutes)
python -m pytest -m "not slow"    # skip the solver test
```

[`tests/test_baseline.py`](tests/test_baseline.py) checks that the generator reproduces the committed base and escalation instances, and that a default solve of `STD_I17_M4_T3` reproduces the summary above. The tests need a Gurobi licence and are skipped without one.

## Contributing

Issues and pull requests are welcome. Please open an issue to discuss a change first, then work on a feature branch, run `python -m pytest`, and open a pull request.

## Citation

If you use this code, please cite:

```bibtex
@misc{clsc_carbon_tax,
  author = {<!-- TODO: authors -->},
  title  = {<!-- TODO: title -->},
  year   = {<!-- TODO: year -->},
  note   = {<!-- TODO: journal, DOI or repository URL -->}
}
```

The method builds on:

- Soares, Alves and Henggeler Antunes (2021). A deterministic bounding procedure for the global optimization of a bi-level mixed-integer problem. *European Journal of Operational Research*. <!-- TODO: check volume, pages and DOI -->
- Tautenhain, Barbosa-Póvoa, Mota and Nascimento (2021). An efficient Lagrangian-based heuristic to solve a multi-objective sustainable supply chain problem. *European Journal of Operational Research*. <!-- TODO: check volume, pages and DOI -->
- Mota et al. (2018). <!-- TODO: full reference -->

## License

<!-- TODO: choose a licence, add a LICENSE file and set `license` in pyproject.toml. -->
No licence has been chosen yet. Until one is added, the code is not licensed for reuse.

## Contact / Author

Marcelo Pinto. <!-- TODO: affiliation, e-mail and profile links -->
