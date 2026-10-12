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

The bilevel problem is solved with the DBP of Soares et al. (2021). The procedure alternates between the high-point relaxation (HPR) of the bilevel problem, which yields lower bounds on the leader's objective $F$, and evaluations of the follower, which yield upper bounds. It stops when the relative gap between the two bounds is at most a prescribed tolerance $\varepsilon$.

The HPR minimises $F$ over the follower's physical constraints only, without requiring the follower's response to be optimal. These constraints do not contain $\tau$, so every follower response is feasible at every tax rate, and each evaluated response yields a cut that is valid for the whole problem.

**Parameters**

- $\varepsilon$ (`dbp_relative_gap`, default $10^{-4}$): optimality tolerance on the relative gap.
- $\varepsilon'$: a very small tolerance on the follower's objective, added only to keep the subproblems numerically feasible, as in Soares et al. (2021). It is set separately for the follower's second stage (`lex_epsilon_prime`, $10^{-6}$ relative, floored at an absolute $10^{-7}$) and for the cuts (`dbp_cut_epsilon`, $10^{-5}$ absolute, or `dbp_cut_epsilon_relative`, $10^{-7}$, times the cut's cost if larger).
- Subproblems are solved to Gurobi's default relative MIP gap, $10^{-4}$ (`mip_gap` for the follower, `hpr_mip_gap` for the HPR). Subproblems that reach their time limit are handled as described below.

**Initialisation.** The weight $w$ is fixed beforehand (see Problem). Solve the HPR without cuts. Its value (the bound proven by the solver) is the initial lower bound $\mathrm{LB}$, and its tax rate is the first proposal $\tau_0$. Set $\mathrm{UB} = +\infty$ and $k = 0$.

**Iteration** ($k = 0, 1, \dots$)

1. **Evaluate the follower.** Solve the follower's problem at $\tau_k$ with the optimistic rule, obtaining $y_k$: stage 1 minimises $f$, giving $f^*$; stage 2 minimises $E$ subject to $f \le f^* + \varepsilon'$. If $F(\tau_k, y_k) < \mathrm{UB}$, set $\mathrm{UB} = F(\tau_k, y_k)$. The incumbent is the evaluated pair with the least $F$, ties being broken towards the lower tax.
2. **Add a value-function cut.** Append $f(\tau, y) \le f(\tau, y_k) + \varepsilon'$ to the HPR. The follower's constraints do not contain $\tau$, so $y_k$ is feasible for every $\tau$. If $(\tau, y^*)$ is bilevel-feasible, $y^*$ minimises $f(\tau, \cdot)$ over the follower's feasible set, which contains $y_k$; hence $f(\tau, y^*) \le f(\tau, y_k)$ and the cut removes no bilevel-feasible point (Lemma 2 of Soares et al., 2021). Only feasibility of $y_k$ is needed, not optimality.
3. **Re-solve the HPR.** The new $\mathrm{LB}$ is the larger of the previous $\mathrm{LB}$ and the bound proven by the HPR solve, which can oscillate within the solver's MIP gap. The HPR's tax rate is the next proposal $\tau_{k+1}$.
4. **Test termination**, after the re-solve of step 3. If $(\mathrm{UB} - \mathrm{LB}) / \max(1, |\mathrm{UB}|) \le \varepsilon$, stop and classify the result below; otherwise set $k \leftarrow k + 1$ and return to step 1.

At termination, the incumbent is returned together with $\mathrm{LB}$ and $\mathrm{UB}$. The gap is tested first; the comparison $\tau_{k+1} = \tau_k$ is with the tax rate just evaluated, not with the incumbent's. Soares et al. keep the latest point when two evaluated points tie on $F$; here the lower tax is kept. "Optimal" holds up to the optimality tolerances of the solvers and $\varepsilon'$: Soares et al. note that with positive MIP gaps and elastic variables convergence cannot be ensured.

| Outcome | Condition |
|---|---|
| Optimal | Gap $\le \varepsilon$ and $\tau_{k+1} = \tau_k$ (Lemma 3 of Soares et al., 2021); the HPR was solved to optimality without elastic slack, and the follower response attaining $\mathrm{UB}$ was solved to optimality |
| $\varepsilon$-optimal | Gap $\le \varepsilon$, but at least one condition above fails |
| Gap not closed | Run ended by the auxiliary stop or by a run limit |

<details>
<summary>Time limits, fallbacks and auxiliary stopping rule</summary>

- **HPR time limit.** An HPR that reaches its time limit still yields a valid lower bound (its dual bound) and, if it holds an incumbent point, the next tax proposal. Otherwise the cuts are made elastic (below). If the elastic HPR also returns no point, the run ends with the incumbent; Soares et al. do not specify this case, so it is a safeguard of this implementation.
- **Follower time limit.** If stage 1 reaches its time limit with a positive gap, subproblem (P6) first searches for a better response, before the freeze $f \le f^* + \varepsilon'$ of stage 2 is set. If stage 2 finds nothing feasible, the stage-1 (or P6) response is kept. Such a response is not proven optimal, so the result is at most $\varepsilon$-optimal.
- **Elastic cuts.** The value-function cuts of the HPR are made elastic (formulation P5-D) the first time it returns no feasible point.
- **Auxiliary stop.** The procedure also stops after `stagnation_limit` (default 10) consecutive iterations in which neither bound changes, as in Soares et al. (a change of incumbent at an unchanged upper bound does not count). The gap test of step 4 is applied first, so this stop occurs only while the gap exceeds $\varepsilon$.
- **Run limit.** `--wall-clock-cap` optionally bounds the whole run; when it is exhausted, the incumbent is returned with the last lower bound.

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

The result class in `summary.json` follows the outcome table of the method section. It is an extension of this repository; Soares et al. define no such classes.

| `result_class` | Outcome | Termination reasons |
|---|---|---|
| `optimal` | Optimal | `optimal` |
| `epsilon_optimal` | $\varepsilon$-optimal | `epsilon_optimal` |
| `bounded` | Gap not closed | `incumbent_stagnation`, `incumbent_time_limit`, `incumbent_wall_clock_cap` |

`clsc-solve --help` lists every option. `--emissions-cap` adds the optional cut $F \le \mathrm{UB}$ (Mitsos, 2010) to the HPR; it is off by default because it is not part of Soares et al.'s procedure.

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
| `mip_gap` | `--mip-gap` | `1e-4` | Gurobi MIP gap for the follower (solver default; the follower is solved to optimality) |
| `hpr_mip_gap` | `--hpr-mip-gap` | `1e-4` | Gurobi MIP gap for the HPR |
| `time_limit` | `--time-limit` | `600` s | time limit per MILP subproblem (`--hpr-time-limit` sets the HPR's separately) |
| — | `--wall-clock-cap` | none | optional limit on a whole run |
| `stagnation_limit` | — | `10` | number of iterations without a bound update before the run stops |
| `tax_weight_relative` | `--leader-tax-weight-relative` | `1e-4` | $q$ in $w = q \cdot E_{\text{ref}}$ (see "Problem") |
| `threads`, `mip_focus` | `--threads`, `--mip-focus` | `4`, `2` | Gurobi settings |

`--leader-tax-weight` sets $w$ directly, in kg CO2e per USD/t, as an alternative to `tax_weight_relative`. The tax grid step is `TAX_SCALE_FACTOR = 1e-3` USD/kg CO2e (1 USD/t per index), set in [`src/clsc/config/tax_scale.py`](src/clsc/config/tax_scale.py). The benchmark instances use a tax range of 0–200 USD/t.

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
