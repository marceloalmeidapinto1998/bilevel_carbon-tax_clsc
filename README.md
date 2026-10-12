# Bilevel mixed-integer program for carbon tax setting and closed-loop supply chain network design

Exact and ε-optimal solutions to a bilevel closed-loop supply chain design problem under a carbon tax, computed with the Deterministic Bounding Procedure of Soares et al. (2021).

![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue)
![Solver](https://img.shields.io/badge/solver-Gurobi%2013-red)
![License](https://img.shields.io/badge/license-TBD-lightgrey)
<!-- TODO: choose a licence (e.g. MIT / Apache-2.0 / BSD-3-Clause), add a LICENSE file, and set `license` in pyproject.toml. No licence has been chosen yet; until one is added, the code is not licensed for reuse. -->

## Overview

This repository implements a bilevel mixed-integer model of closed-loop supply chain (CLSC) network design under a carbon tax, an exact solution method for it, and a reproducible benchmark set. A leader (the regulator) sets the tax rate; a follower (the CLSC operator) selects facility locations, installed capacities, technologies, and forward and reverse flows to minimise its own cost, inclusive of the tax. The leader anticipates the follower's response when choosing the tax, which makes the problem a bilevel mixed-integer program. The problem is solved with the Deterministic Bounding Procedure (DBP) of Soares et al. (2021), whose overall strategy is to generate a series of convergent upper and lower bounds on the leader's objective until their difference falls below a given threshold. The repository also provides a deterministic instance generator and fifteen instances, built from the sampling rules of Tautenhain et al. (2021).

## Installation

```bash
git clone https://github.com/marceloalmeidapinto1998/bilevel_carbon-tax_clsc.git
cd bilevel_carbon-tax_clsc
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

This command installs the `clsc` package together with two console scripts, `clsc-solve` and `clsc-generate` (equivalently, `python -m clsc.solver_cli` and `python -m clsc.generator`). Solving an instance requires a valid Gurobi licence; see "Requirements and reproducibility".

```bash
clsc-solve data/STD_I17_M4_T3.json --results-root results/runs
```

Each run writes to `results/runs/<dataset>/<instance>/dbp/`. The contents of each output file, and further command-line options, are described in "Usage".

## Problem

**Leader problem.** The leader is the regulator, who sets a carbon tax rate $\tau$ between 0 and 200 USD/t CO2e. In the computations, the tax rate is expressed in USD/kg CO2e with three decimal places, so that the leader's variable can be treated as an integer by applying a scale factor of $10^{3}$. The follower is the closed-loop supply chain operator. Let $y$ denote its response, comprising the network design and the period-by-period operating plan, and $E(y)$ the total physical emissions (kg CO2e) that it induces. When the follower has alternative optimal responses, the one most favourable to the leader is selected (optimistic approach). The leader minimises

$$F(\tau, y) = E(y) + w \, \tau, \qquad w > 0,$$

where $w$ (kg CO2e per USD/t) is a policy weight. Since $w > 0$, the lowest tax is selected among those attaining equal emissions, and the regulator accepts $w$ additional units of emissions for each 1 USD/t reduction in $\tau$. The weight is set as $w = q \, E_{\text{ref}}$, with $q = 10^{-4}$ and $E_{\text{ref}}$ (kg CO2e) the minimum of $E(y)$ over all feasible network designs.

**Follower problem.** For a fixed tax rate $\tau$, the follower solves a mixed-integer linear program over a multi-period, multi-product closed-loop network of suppliers, factories, warehouses, retailers, and airport and seaport hubs, connected by truck, air and sea transport. Its decisions are of two kinds:

- **Strategic:** which factories and warehouses to open, their installed floor-area capacities, and which production and remanufacturing technologies to install at each factory.
- **Tactical and operational (per period):** raw-material procurement from suppliers, production and remanufacturing volumes, warehouse inventory levels, and forward flows of final products and reverse flows of recovered products across the transport arcs and modes of the network.

Let $c(y)$ denote the follower's operating cost (procurement, production, remanufacturing, transport, handling and inventory), discounted over the planning horizon, and $\beta(y)$ the emissions aggregate on which the follower is taxed, discounted with the same present-value weights. The follower minimises

$$f(\tau, y) = c(y) + \tau \, \beta(y).$$


## Solution method

The bilevel problem is solved with the DBP of Soares et al. (2021). The procedure alternates between two computations. The high-point relaxation (HPR) gives a lower bound $\mathrm{LB}$ on the leader's objective $F$. The evaluation of the follower gives an upper bound $\mathrm{UB}$. It stops when the relative gap between the bounds is at most $\varepsilon$.

The HPR minimises $F$ over the follower's physical constraints alone and does not require the follower's response to be optimal. These constraints do not contain $\tau$. Every follower response is therefore feasible at every tax rate, and every evaluated response yields a cut that is valid for the whole problem.

**Tolerances**

- $\varepsilon$: tolerance on the relative gap.
- $\varepsilon'$: very small tolerance on the follower's objective, used only to keep the subproblems numerically feasible.
- Subproblems are solved to a relative MIP gap of $10^{-4}$.

**Initialisation.** Fix $w$ (see Problem) and solve the HPR without cuts. Set $\mathrm{LB}$ to the bound proven by the solver and $\tau_{0}$ to the tax rate of the HPR solution. Set $\mathrm{UB} = +\infty$ and $k = 0$.

**Iteration** ($k = 0, 1, \dots$)

1. **Evaluate the follower.** Solve the follower's problem at $\tau_{k}$ with the optimistic rule. Stage 1 minimises $f$ and gives $f^{\ast}$. Stage 2 minimises $E$ subject to $f \le f^{\ast} + \varepsilon'$ and gives $y_{k}$. If $F(\tau_{k}, y_{k}) < \mathrm{UB}$, set $\mathrm{UB} = F(\tau_{k}, y_{k})$. The incumbent is the evaluated pair of least $F$; ties go to the lower tax.
2. **Add a cut.** Add $f(\tau, y) \le f(\tau, y_{k}) + \varepsilon'$ to the HPR. The point $y_{k}$ is feasible for every $\tau$. If $(\tau, y^{\ast})$ is bilevel-feasible, $y^{\ast}$ minimises $f(\tau, \cdot)$, so $f(\tau, y^{\ast}) \le f(\tau, y_{k})$. The cut therefore removes no bilevel-feasible point.
3. **Re-solve the HPR.** Set $\mathrm{LB}$ to the larger of its previous value and the bound proven by this solve. Set $\tau_{k+1}$ to the tax rate of the HPR solution.
4. **Test termination.** If $(\mathrm{UB} - \mathrm{LB}) / \max(1, |\mathrm{UB}|) \le \varepsilon$, stop and classify the result. Otherwise set $k \leftarrow k + 1$ and return to step 1.

The outcomes below hold up to the solvers' tolerances and $\varepsilon'$.

| Outcome | Condition |
|---|---|
| Optimal | The gap is at most $\varepsilon$ and $\tau_{k+1} = \tau_{k}$. |
| $\varepsilon$-optimal | The gap is at most $\varepsilon$, but $\tau_{k+1} \neq \tau_{k}$. |
| Auxiliary stop | Neither bound changed during 10 consecutive iterations. |

<details>
<summary>Time limits and stopping rules</summary>

- **HPR time limit.** An HPR that reaches its time limit still yields a valid lower bound (its dual bound) and, if it holds a feasible point, the next tax proposal. Otherwise the cuts are made elastic. If the elastic HPR also returns no point, the run ends with the incumbent.
- **Elastic cuts (P5-D).** The first time the HPR returns no feasible point, each cut $k$ is relaxed to $f(\tau, y) \le f(\tau, y_{k}) + \varepsilon' + D_{k}$ with $D_{k} \ge 0$, and the sum of the $D_{k}$ is penalised in the HPR objective. The relaxed HPR is always feasible. If some $D_{k} > 0$, the result cannot be classified as optimal.
- **Follower time limit.** If stage 1 reaches its time limit with a positive gap, subproblem P6 first searches for a better response, before the constraint $f \le f^{\ast} + \varepsilon'$ of stage 2 is set. P6 minimises $D \ge 0$ subject to the follower's constraints and $f(\tau_{k}, y) \le \bar{f}\,(1 - g) + D$, where $\bar{f}$ is the best value of $f$ found by stage 1 and $g$ its relative MIP gap; $\bar{f}\,(1 - g)$ is the solver's bound on the follower's optimum, so a response with $D$ close to zero is nearly optimal. If stage 2 finds no feasible point, the stage-1 (or P6) response is kept. Such a response is not proven optimal, so the result is at most $\varepsilon$-optimal.
- **Auxiliary stop.** The procedure also stops after 10 consecutive iterations in which neither bound changes.

</details>

## Data

The instances are those of the test bed of Tautenhain et al. (2021), plus three larger instances added by this repository. They are stored in `data/`, one JSON file per instance.

Each instance is named `STD_I<entities>_M<items>_T<periods>`: `I` is the number of entities, `M` the number of items (raw materials, final products and recovered products), and `T` the number of periods.

| Set | `I` | `M` | `T` | Instances | Source | Generated with |
|---|---|---|---|---|---|---|
| Standard | 17, 25 | 4, 8 | 3, 6, 12 | 12 (every combination) | Tautenhain et al. | `benchmark` |
| Escalation | 25, 25, 33 | 12, 16, 8 | 6, 6, 6 | 3: `STD_I25_M12_T6`, `STD_I25_M16_T6`, `STD_I33_M8_T6` | This repository | `escalation` |

**Entities**

| `I` | Suppliers | Factories | Warehouses | Retailers | Airports | Seaports | Source |
|---|---|---|---|---|---|---|---|
| 17 | 3 | 3 | 3 | 4 | 2 | 2 | Tautenhain et al. |
| 25 | 3 | 3 | 9 | 4 | 4 | 2 | Tautenhain et al. |
| 33 | 3 | 3 | 17 | 4 | 4 | 2 | This repository |

Retailers are the customers of Tautenhain et al.

**Items**

| `M` | Raw materials | Final products | Recovered products | Source |
|---|---|---|---|---|
| 4 | 2 | 1 | 1 | Tautenhain et al. |
| 8 | 4 | 2 | 2 | Tautenhain et al. |
| 12 | 6 | 3 | 3 | This repository |
| 16 | 8 | 4 | 4 | This repository |

Each final product has one recovered counterpart. The rows `M12` and `M16` follow the same rule as `M4` and `M8`: half of `M` are raw materials, a quarter are final products and a quarter are recovered products.

Every instance has 3 production and 3 remanufacturing technologies.

## Usage

### Solving instances

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


### Generating instances

```bash
# the 12-instance benchmark (I in {17, 25} x M in {4, 8} x T in {3, 6, 12})
clsc-generate benchmark --output-dir data

# the three escalation instances (STD_I25_M12_T6, STD_I25_M16_T6, STD_I33_M8_T6)
clsc-generate escalation --output-dir data

# a custom instance
clsc-generate instance --name my_case --seed 1 --periods 6 --output data/my_case.json
```

Generation is deterministic: each benchmark instance's seed is derived from `--seed-base` (default 0) and its name.

### Running the test suite

```bash
python -m pytest                  # all regression tests
python -m pytest -m "not slow"    # skip the solver test
```

[`tests/test_baseline.py`](tests/test_baseline.py) checks that the generator reproduces the committed base and escalation instances, and that a default solve of `STD_I17_M4_T3` reproduces its reference summary. The tests require a Gurobi licence and are skipped without one.

## Configuration

The method's defaults are specified in [`src/clsc/config/defaults.py`](src/clsc/config/defaults.py) (`DEFAULT`). A solve invoked without options uses these defaults.

| Parameter | Default | Meaning |
|---|---|---|
| `dbp_relative_gap` | `1e-4` | DBP stopping tolerance on the relative gap of $F$ |
| `mip_gap` | `1e-4` | Gurobi MIP gap for the follower |
| `hpr_mip_gap` | `1e-4` | Gurobi MIP gap for the HPR |
| `time_limit` | `600` s | time limit per MILP subproblem (`--hpr-time-limit` sets the HPR's separately) |
| `stagnation_limit` | `10` | number of iterations without a bound update before the run stops |
| `tax_weight_relative` | `1e-4` | $q$ in $w = q \cdot E_{\text{ref}}$ (see "Problem") |
| `threads`, `mip_focus` | `4`, `2` | Gurobi settings |

## Requirements and reproducibility

- Python ≥ 3.12.
- [Gurobi](https://www.gurobi.com/) 13 with a valid licence (`gurobipy>=13,<14`). The licence is required both to solve instances and to generate them, as the generator checks each instance's feasibility with Gurobi.
- PyYAML, required only when reading or writing YAML instance files.
- pytest, for the test suite (`dev` extra).

Instance generation is deterministic given a seed (see "Usage"). The DBP solve is deterministic given a fixed Gurobi `Seed` and thread count, subject to Gurobi's own run-to-run variability under multithreading.

<!-- TODO: report expected runtime and hardware specification for the instances (e.g. "STD_I17_M4_T3 solves in N minutes on M threads on <CPU>"). Not available in the source material for this rewrite. -->

## Project structure

```text
.
├── data/                      # the 15 instances (JSON)
├── src/clsc/                  # the Python package
│   ├── config/                #   method defaults, shared constants, tax-grid step
│   ├── generator/              #   instance generator (CLI: clsc-generate)
│   ├── models/                #   instance loading and the Gurobi models
│   │   ├── instance_data.py   #     load and validate an instance
│   │   ├── supply_chain.py    #     supply-chain MILP shared by follower and HPR
│   │   ├── follower.py        #     follower model and its two-stage optimistic solve
│   │   ├── hpr.py             #     DBP high-point relaxation
│   │   └── gurobi_utils.py    #     solve wrapper and result types
│   ├── solvers/dbp.py         #   the Deterministic Bounding Procedure
│   └── solver_cli/            #   batch solver CLI (clsc-solve): parsing, output files, revalidation
├── tests/test_baseline.py     # regression tests
├── pyproject.toml             # metadata, dependencies, console scripts, pytest settings
└── requirements.txt           # mirrors the dependencies in pyproject.toml
```

## References

- Soares, Alves and Henggeler Antunes (2021). A deterministic bounding procedure for the global optimization of a bi-level mixed-integer problem. *European Journal of Operational Research*, 291, 52–66.
- Tautenhain, Barbosa-Póvoa, Mota and Nascimento (2021). An efficient Lagrangian-based heuristic to solve a multi-objective sustainable supply chain problem. *European Journal of Operational Research*, 294, 70–90.
- Mota, Gomes, Carvalho and Barbosa-Póvoa (2018). Sustainable supply chains: An integrated modeling approach under uncertainty. *Omega*, 77, 32–57.

## Licence

<!-- TODO: choose a licence, add a LICENSE file and set `license` in pyproject.toml. -->
No licence has been chosen. Until one is added, the code is not licensed for reuse.

## Contact

Marcelo Pinto  
University of Coimbra, Centre for Mechanical Engineering, Materials and Processes, Coimbra, Portugal  
[marcelo.pinto@dem.uc.pt](mailto:marcelo.pinto@dem.uc.pt)  
ORCID: [0000-0002-6909-3829](https://orcid.org/0000-0002-6909-3829)

<!-- TODO: state project status (e.g. active development, accompanying a submitted paper, archival). Not specified in the source material for this rewrite. -->
