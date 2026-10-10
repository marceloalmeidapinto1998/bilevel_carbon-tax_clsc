# CLSC Network Design under Carbon Pricing - Bilevel Mixed-Integer Program 

## Overview

### Problem

A regulator (the leader) fixes a carbon-tax rate; a closed-loop supply chain (CLSC) operator (the follower) responds by redesigning and operating its network to minimise its own cost plus the tax it pays. The leader anticipates this response and chooses the tax that minimises its own objective over it.

### Leader problem

The leader's decision is modelled through an integer tax index $x_u \in X_u = \{0, 1, \dots, \bar{x}_u\}$ (`tax_index` in the code), where the upper bound $\bar{x}_u$ is instance-specific ($\bar{x}_u = 200$ in the benchmark set). The carbon tax rate is given by $\tau = \theta \, x_u$, where $\theta = 10^{-3}$ USD/kg CO₂e denotes the grid step (`TAX_SCALE_FACTOR`), such that each unit increment in $x_u$ corresponds to an increase of 1 USD/t CO₂e. The leader seeks to minimise

$$F(x_u, y) = E(y) + w \, x_u,$$

where $y$ denotes the follower's response, $E(y)$ the corresponding total physical emissions (kg CO₂e), and $w > 0$ a policy weight expressed in kg CO₂e per tax increment. The weight $w$ represents the emissions the regulator would accept in exchange for a tax rate one step lower. Unless stated otherwise, we set $w = q \, E_{\text{ref}}$, with $q = 10^{-4}$ (`tax_weight_relative`) and $E_{\text{ref}}$ the minimum emissions level attainable in the relaxation master problem prior to the addition of any cuts. Since $w > 0$, the lowest tax is selected among those yielding equal emissions.

### Follower problem

For a fixed tax index, the follower solves a mixed-integer linear program over a multi-period, multi-product CLSC network of suppliers, factories, warehouses, retailers and airport/seaport hubs, connected by truck, air and sea transport. Its decisions are:

- strategic: which factories and warehouses to open, their installed floor-area capacities, and which production and remanufacturing technologies to install at each factory;
- tactical/operational, period by period: raw-material purchases from suppliers, production and remanufacturing volumes, warehouse inventory levels, and forward flows of final products and reverse flows of recovered products across the network's transport arcs and modes.

The follower minimises $f = c(y) + \tau \cdot \beta(y)$: its own discounted operating cost $c(y)$ (procurement, production, remanufacturing, transport, handling and inventory) plus the carbon tax levied on $\beta(y)$, the discounted emissions aggregate it is taxed on. $\beta(y)$ equals the leader's (undiscounted) $E$ only when the instance carries no interest rate; the benchmark instances are generated with one, so in general $\beta(y) \neq E$.

### Tie-breaking

Among the responses that minimise $f$, the follower is assumed to pick the one with least physical emissions $E$ — the optimistic rule — enforced by a two-stage lexicographic solve. Stage 1 minimises $f$, giving $f^*$. Stage 2 re-minimises $E$ subject to $f \le f^* + \varepsilon'$, where $\varepsilon'$ (`lex_epsilon_prime`, $10^{-6}$ relative, floored at an absolute $10^{-7}$) freezes Stage 1's value within a numerical tolerance before re-optimising. If Stage 1 stops at its time limit, subproblem (P6) first searches for a response that improves on it before the freeze is set; if Stage 2 finds nothing feasible, the Stage-1 (or P6) response is kept.

### Solution method

The bilevel problem is solved with the Deterministic Bounding Procedure (DBP) of Soares, Alves and Henggeler Antunes (2021). A relaxation master — the leader's objective $F$ minimised over the follower's physical constraints only, independent of the tax — is solved first with no cuts, then iteratively re-solved with one value-function cut added per iteration: each cut, built from an evaluated response $(x_{u,k}, y_k)$, enforces $f(x,y) \le f(x,y_k) + \varepsilon'$ and is valid at every tax index, since the follower's constraints do not depend on it. The master's optimum is a lower bound on $F$; the least $F$ attained by any evaluated follower response is an upper bound. The loop proposes the master's tax index, evaluates the follower there, adds the resulting cut, and re-solves the master, until the relative gap $(\mathrm{UB}-\mathrm{LB})/\max(1,|\mathrm{UB}|)$ falls at or below `dbp_relative_gap` ($10^{-4}$ by default). The result is reported optimal if the master then re-proposes the tax index just evaluated (Lemma 3 of the reference); otherwise it is epsilon-optimal. A master that times out still yields a valid dual bound and a usable tax proposal; a follower that times out is passed through subproblem (P6); and the master's cuts are made elastic (P5-D) the first time it returns no feasible point.

### Benchmark instances

The repository includes a deterministic instance generator, based on the sampling rules of Tautenhain, Barbosa-Póvoa, Mota and Nascimento (2021) for the CLSC model of Mota, Gomes, Carvalho and Barbosa-Póvoa (2018), and the 15 instances it produces, named `STD_I<entities>_M<materials>_T<periods>`. Twelve form the standard testbed, spanning every combination of a total entity count `I` ∈ {17, 25} (suppliers, factories, warehouses, retailers, airports and seaports), a materials/products code `M` ∈ {4, 8} (`M4`: 2 raw materials, 1 product; `M8`: 4 raw materials, 2 products), and a planning horizon `T` ∈ {3, 6, 12} periods. Three escalation instances (`STD_I25_M12_T6`, `STD_I25_M16_T6`, `STD_I33_M8_T6`) push the materials/products or entity-count axis one point past the standard range, for scalability probes, and are not written by the routine `benchmark` command. Every instance uses 3 production and 3 remanufacturing technologies.

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
- Tautenhain, Barbosa-Póvoa, Mota and Nascimento (2021). An efficient Lagrangian-based heuristic to solve a multi-objective sustainable supply chain problem. *European Journal of Operational Research*, 294, 70–90.
- Mota, Gomes, Carvalho and Barbosa-Póvoa (2018). Sustainable supply chains: An integrated modeling approach under uncertainty. *Omega*, 77, 32–57.
