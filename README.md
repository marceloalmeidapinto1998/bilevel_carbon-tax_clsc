# Bilevel mixed-integer model for carbon tax setting and closed-loop supply chain network design

Exact and ε-optimal solutions to a bilevel closed-loop supply chain design problem under a carbon tax, computed with the Deterministic Bounding Procedure of Soares et al. (2021).

![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue)
![Solver](https://img.shields.io/badge/solver-Gurobi%2013-red)
![License](https://img.shields.io/badge/license-TBD-lightgrey)
<!-- TODO: choose a licence (e.g. MIT / Apache-2.0 / BSD-3-Clause), add a LICENSE file, and set `license` in pyproject.toml. No licence has been chosen yet; until one is added, the code is not licensed for reuse. -->

## Overview

This repository implements a bilevel mixed-integer model of closed-loop supply chain (CLSC) network design under a carbon tax, an exact solution method for it, and a reproducible benchmark set. A leader (the regulator) sets the tax rate; a follower (the CLSC operator) selects facility locations, installed capacities, technologies, and forward and reverse flows to minimise its own cost, inclusive of the tax. The leader anticipates the follower's response when choosing the tax, which makes the problem a bilevel mixed-integer program. The problem is solved with the Deterministic Bounding Procedure (DBP) of Soares et al. (2021), whose overall strategy is to generate a series of convergent upper and lower bounds on the leader's objective until their difference falls below a given threshold. The repository also provides a deterministic instance generator and fifteen instances, built from the sampling rules of Tautenhain et al. (2021).

## Installation and quick start

```bash
git clone https://github.com/marceloalmeidapinto1998/bilevel-clsc-carbon-pricing.git
cd bilevel-clsc-carbon-pricing
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

This command installs the `clsc` package together with two console scripts, `clsc-solve` and `clsc-generate` (equivalently, `python -m clsc.solver_cli` and `python -m clsc.generator`). Solving an instance requires a valid Gurobi licence; see "Requirements and reproducibility".

```bash
clsc-solve data/STD_I17_M4_T3.json --results-root results/runs
```

Each run writes to `results/runs/<dataset>/<instance>/dbp/`. The contents of each output file, and further command-line options, are described in "Usage".

## Problem formulation

**Leader problem.** The leader selects an integer tax index $x_u \in \{0, 1, \dots, \bar{x}_u\}$ (`tax_index` in the implementation), where the upper bound $\bar{x}_u$ is instance-specific ($\bar{x}_u = 200$ for the benchmark instances). The corresponding carbon tax rate is

$$\tau = \theta \, x_u,$$

with grid step $\theta = 10^{-3}$ USD/kg CO$_2$e (`TAX_SCALE_FACTOR`), so that each unit increase in $x_u$ raises the tax rate by 1 USD/t CO$_2$e. Let $y$ denote the follower's response — its network design and period-by-period operating plan — and let $E(y)$ denote the total physical emissions (kg CO$_2$e) it induces. The leader minimises

$$F(x_u, y) = E(y) + w \, x_u, \qquad w > 0,$$

where $w$ is a policy weight, expressed in kg CO$_2$e per unit of $x_u$, representing the emissions the regulator accepts in exchange for a tax rate one grid step lower. Unless specified otherwise, $w = q \, E_{\text{ref}}$, with $q = 10^{-4}$ (`tax_weight_relative`) and $E_{\text{ref}}$ the minimum emissions level attainable by the cut-free relaxation master problem (Solution method). The weight $w$ can alternatively be supplied directly, in kg CO$_2$e per USD/t. Because $w > 0$, the lowest tax index is selected among those attaining equal emissions, so the formulation requires no secondary tie-breaking rule on the leader's side.

**Follower problem.** For a fixed tax index $x_u$, the follower solves a mixed-integer linear program over a multi-period, multi-product closed-loop network comprising suppliers, factories, warehouses, retailers, and airport and seaport hubs, connected by truck, air and sea transport modes. Its decisions comprise:

- strategic decisions: which factories and warehouses to open, their installed floor-area capacities, and which production and remanufacturing technologies to install at each factory;
- tactical and operational decisions, per period: raw-material procurement from suppliers, production and remanufacturing volumes, warehouse inventory levels, and forward flows of final products and reverse flows of recovered products across the network's transport arcs and modes.

Let $c(y)$ denote the follower's operating cost (procurement, production, remanufacturing, transport, handling and inventory), discounted over the planning horizon, and let $\beta(y)$ denote the emissions aggregate on which the follower is taxed, discounted with the same present-value weights as $c(y)$. The follower minimises

$$f(x_u, y) = c(y) + \tau \cdot \beta(y).$$

The quantity $\beta(y)$ coincides with $E(y)$ only when the instance carries no interest rate; the benchmark instances are generated with a strictly positive interest rate, so in general $\beta(y) \neq E(y)$.

**Tie-breaking rule.** Multiple responses $y$ may attain the minimum of $f(x_u, \cdot)$ for a given $x_u$. The follower is assumed to select, among these, the response of least physical emissions $E(y)$ — the optimistic rule. This selection is enforced by a two-stage lexicographic procedure: Stage 1 minimises $f$, yielding $f^*$; Stage 2 minimises $E$ subject to $f(x_u, y) \le f^* + \varepsilon'$, where $\varepsilon'$ (`lex_epsilon_prime`, $10^{-6}$ relative, floored at an absolute $10^{-7}$) freezes the Stage-1 value within a numerical tolerance before re-optimisation. If Stage 1 terminates at its time limit, subproblem (P6) is solved first to search for an improving response before the freeze is applied; if Stage 2 returns no feasible point, the Stage-1 (or P6) response is retained.

## Solution method

The bilevel problem is solved with the Deterministic Bounding Procedure (DBP) of Soares, Alves and Henggeler Antunes (2021). The procedure maintains a lower bound and an upper bound on $F$ and terminates when their relative gap is within a specified tolerance.

1. Solve the relaxation master problem — the leader's objective $F$ minimised over the follower's physical constraints only, independent of the tax — to obtain a lower bound on $F$ and a proposed tax index $x_u$.
2. Solve the follower's problem at $x_u$ (see "Problem formulation") to obtain an evaluated response $y_k$, hence an upper bound on $F$.
3. Append a value-function cut, derived from $(x_u, y_k)$, to the master problem: $f(x,y) \le f(x,y_k) + \varepsilon'$. The cut is valid at every tax index, since the follower's constraints are independent of $x_u$.
4. Re-solve the master problem with the additional cut.
5. If the relative gap $(\mathrm{UB}-\mathrm{LB}) / \max(1, |\mathrm{UB}|)$ is at most `dbp_relative_gap` (default $10^{-4}$), terminate; otherwise return to step 2 with the master's updated proposal.

Upon termination, the result is classified as optimal if the master re-proposes the tax index just evaluated (Lemma 3 of Soares et al., 2021), and as epsilon-optimal otherwise.

<details>
<summary>Time-limit handling and additional tolerances</summary>

A master problem that reaches its time limit yields a valid dual bound and, if an incumbent is held, a usable tax-index proposal, from which the procedure continues. A follower problem that reaches its time limit is passed through subproblem (P6), which searches for an improving response before the tie-breaking freeze described in "Problem formulation" is applied. The master's value-function cuts are made elastic (formulation P5-D) the first time the master problem returns no feasible point.

</details>

## Benchmark instances

Instances are named `STD_I<entities>_M<materials>_T<periods>`, where `I` denotes the total number of entities (suppliers, factories, warehouses, retailers, airports and seaports), `M` the total item count, and `T` the number of periods in the planning horizon.

| Set | `I` | `M` | `T` | Instances | Purpose |
|---|---|---|---|---|---|
| Standard | 17, 25 | 4, 8 | 3, 6, 12 | 12 (every combination) | Primary benchmark set |
| Escalation | 25, 25, 33 | 12, 16, 8 | 6, 6, 6 | 3 | One axis (materials/products or entity count) extended beyond the standard range |

The code `M` equals $|M_{rm}| + |M_{fp}| + |M_{rp}|$, the number of raw materials plus final products plus recovered products, following the convention of Tautenhain, Barbosa-Póvoa, Mota and Nascimento (2021, Table 11); each final product has exactly one recovered counterpart, so $|M_{rp}| = |M_{fp}|$. For `M4`, the generator sets 2 raw materials, 1 final product and 1 recovered product ($2+1+1=4$); for `M8`, 4 raw materials, 2 final products and 2 recovered products ($4+2+2=8$). The escalation instances (`STD_I25_M12_T6`, `STD_I25_M16_T6`, `STD_I33_M8_T6`) are not produced by the `benchmark` command and are generated explicitly with `escalation` (see "Usage"). Every instance, standard or escalation, specifies 3 production and 3 remanufacturing technologies.

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

`clsc-solve --help` lists every option.

<!-- TODO: add an example `summary.json` (or excerpt) once a representative, citable run is agreed on. No example output was provided in the source material for this rewrite. -->

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

The method's defaults are specified in [`src/clsc/config/defaults.py`](src/clsc/config/defaults.py) (`DEFAULT`). A solve invoked without options uses these defaults; each CLI flag below overrides the corresponding one.

| Parameter | CLI flag | Default | Meaning |
|---|---|---|---|
| `dbp_relative_gap` | `--dbp-relative-gap` | `1e-4` | DBP stopping tolerance on the relative gap of $F$ (Soares et al., 2021) |
| `mip_gap` | `--mip-gap` | `1e-2` | Gurobi MIP gap for the follower (Tautenhain et al., 2021) |
| `master_mip_gap` | `--master-mip-gap` | `1e-4` | Gurobi MIP gap for the relaxation master |
| `time_limit` | `--time-limit` | `600` s | time limit per MILP subproblem (`--master-time-limit` sets the master's separately) |
| — | `--wall-clock-cap` | none | optional limit on a whole run |
| `stagnation_limit` | — | `10` | number of iterations without a bound update before the run stops |
| `tax_weight_relative` | `--leader-tax-weight-relative` | `1e-4` | $q$ in $w = q \cdot E_{\text{ref}}$ (see "Problem formulation") |
| `threads`, `mip_focus` | `--threads`, `--mip-focus` | `4`, `2` | Gurobi settings |

`--leader-tax-weight` sets $w$ directly, in kg CO$_2$e per USD/t, as an alternative to `tax_weight_relative`. The tax grid step is `TAX_SCALE_FACTOR = 1e-3` USD/kg CO$_2$e (1 USD/t per index), set in [`src/clsc/config/tax_scale.py`](src/clsc/config/tax_scale.py). The benchmark instances use a tax range of 0–200 USD/t.

## Requirements and reproducibility

- Python ≥ 3.12.
- [Gurobi](https://www.gurobi.com/) 13 with a valid licence (`gurobipy>=13,<14`). The licence is required both to solve instances and to generate them, as the generator checks each instance's feasibility with Gurobi.
- PyYAML, required only when reading or writing YAML instance files.
- pytest, for the test suite (`dev` extra).

Instance generation is deterministic given a seed (see "Usage"). The DBP solve is deterministic given a fixed Gurobi `Seed` and thread count, subject to Gurobi's own run-to-run variability under multithreading.

<!-- TODO: report expected runtime and hardware specification for the benchmark set (e.g. "STD_I17_M4_T3 solves in N minutes on M threads on <CPU>"). Not available in the source material for this rewrite. -->

## Project structure

```text
.
├── data/                      # the 15 benchmark instances (JSON)
├── src/clsc/                  # the Python package
│   ├── config/                #   method defaults, shared constants, tax-grid step
│   ├── generator/              #   instance generator (CLI: clsc-generate)
│   ├── models/                #   instance loading and the Gurobi models
│   │   ├── instance_data.py   #     load and validate an instance
│   │   ├── supply_chain.py    #     supply-chain MILP shared by follower and master
│   │   ├── follower.py        #     follower model and its two-stage optimistic solve
│   │   ├── master.py          #     DBP relaxation master
│   │   └── gurobi_utils.py    #     solve wrapper and result types
│   ├── solvers/dbp.py         #   the Deterministic Bounding Procedure
│   └── solver_cli/            #   batch solver CLI (clsc-solve): parsing, output files, revalidation
├── tests/test_baseline.py     # regression tests
├── pyproject.toml             # metadata, dependencies, console scripts, pytest settings
└── requirements.txt           # mirrors the dependencies in pyproject.toml
```

## Citation

```bibtex
@misc{clsc_carbon_tax,
  author = {<!-- TODO: authors -->},
  title  = {<!-- TODO: title -->},
  year   = {<!-- TODO: year -->},
  note   = {<!-- TODO: journal, DOI or repository URL -->}
}
```

<!-- TODO: add a CITATION.cff file so GitHub's "Cite this repository" feature resolves automatically; none exists yet. -->

## References

The method builds on:

- Soares, Alves and Henggeler Antunes (2021). A deterministic bounding procedure for the global optimization of a bi-level mixed-integer problem. *European Journal of Operational Research*, 291, 52–66.
- Tautenhain, Barbosa-Póvoa, Mota and Nascimento (2021). An efficient Lagrangian-based heuristic to solve a multi-objective sustainable supply chain problem. *European Journal of Operational Research*, 294, 70–90.
- Mota, Gomes, Carvalho and Barbosa-Póvoa (2018). Sustainable supply chains: An integrated modeling approach under uncertainty. *Omega*, 77, 32–57.

## Licence

<!-- TODO: choose a licence, add a LICENSE file and set `license` in pyproject.toml. -->
No licence has been chosen. Until one is added, the code is not licensed for reuse.

## Contact

Marcelo Pinto. <!-- TODO: affiliation, e-mail and profile links -->

<!-- TODO: state project status (e.g. active development, accompanying a submitted paper, archival). Not specified in the source material for this rewrite. -->
