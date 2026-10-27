# Carbon taxation under anticipated network redesign: a mixed-integer bilevel approach for closed-loop supply chains

![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue)
![Solver](https://img.shields.io/badge/solver-Gurobi%2013-red)
![License](https://img.shields.io/badge/license-MIT-green)

Code, instances and experiments of the manuscript of the same title (Pinto, Nascimento, Silva and Moniz).

A regulator sets a carbon tax; an operator responds by redesigning its closed-loop supply chain (suppliers, factories, warehouses, production and remanufacturing technologies, transport, fleet). The regulator anticipates the response, which makes the problem a bilevel mixed-integer program with a continuous tax. This repository solves it with two exact methods:

- **Enumeration of the switching prices**: the taxes at which the operator changes its network. An optimal tax lies at the lowest admissible tax or at one of them; the dichotomic scheme of Aneja and Nair (1979) finds them all with at most 2N − 1 follower solves.
- **Deterministic bounding procedure (DBP)** of Soares et al. (2021), adapted to a relaxation in which the tax multiplies a continuous emission aggregate. It returns valid lower and upper bounds even when the operator's problem cannot be solved to optimality.

The operator's model follows Mota et al. (2018). The manuscript in [`paper/`](paper/) is the reference for the model, the proofs and the results.

## Quick start

Requires Python ≥ 3.12 and [Gurobi](https://www.gurobi.com/) 13 with a full licence (a free academic licence works; the size-limited licence bundled with `gurobipy` is too small for these models).

```bash
git clone https://github.com/marceloalmeidapinto1998/bilevel_carbon-tax_clsc.git
cd bilevel_carbon-tax_clsc
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

clsc-solve data/STD_I17_M4_T3.json                      # the DBP; writes results/STD_I17_M4_T3/
```

On a laptop this instance ends `optimal` in 3 iterations and about 47 s, at a tax of 33.93 EUR/t. To enumerate the switching prices instead:

```python
from clsc.solvers.enumeration import enumerate_break_points

result = enumerate_break_points("data/STD_I17_M4_T3.json", run_time_limit=3600)
```

## What is here

| Path | Content |
|---|---|
| `src/clsc/` | the package: `models/` (the Gurobi models), `solvers/` (`dbp.py`, `enumeration.py`), `solver_cli/` (`clsc-solve`), `generator/` (`clsc-generate`), `experiments/` (the experiment runner and tables) |
| `data/` | 15 generated instances (`STD_*`), 39 calibrated instances (`calibrated/CAL_*`), the case study (`case_study/MOTA2018.json`) |
| `paper/` | the manuscript, its supplement and the scripts that fill its tables and figure |
| `docs/` | [`method.md`](docs/method.md) (model and methods in detail), [`instances.md`](docs/instances.md) (how the instances are built), [`experiments.md`](docs/experiments.md) (the experiment plan) |
| `tests/` | regression, certificate, run-control, formulation and experiment tests |

## Instances

- **Generated** (`STD_I<entities>_M<items>_T<periods>`): drawn with the generator of Tautenhain et al. (2021), 12 standard sizes plus three larger ones.
- **Calibrated** (`CAL_<size>_r<k>`): the same networks with the emission factors and return fractions of the case study, so that remanufacturing is competitive and a tax tests the closed loop. Three replicates of the twelve standard sizes and one of the three larger ones; the manuscript uses replicates 0 and 1.
- **Case study**: an electronics producer in Verona expanding to Europe and Brazil (Mota et al., 2018), built from the published tables.

Details and departures from the sources are in [`docs/instances.md`](docs/instances.md). To regenerate them:

```bash
clsc-generate benchmark --output-dir data          # the 12 standard instances
clsc-generate escalation --output-dir data         # the 3 larger ones
python -c "from clsc.generator.calibrated import write_calibrated_set; write_calibrated_set('data/calibrated')"
```

Generation is deterministic given a seed. Generating the standard and larger instances checks feasibility with Gurobi.

## Usage

### `clsc-solve`: the DBP

```bash
clsc-solve data/STD_I17_M4_T3.json                  # one instance
clsc-solve data                                     # every instance in a folder
clsc-solve data/STD_I17_M4_T3.json --run-time-limit 3600 --leader-tax-weight-relative 1e-5
```

A run writes to `results/<instance>/`:

| File | Content |
|---|---|
| `summary.json`, `summary.csv` | result class, tax (EUR/t), cost, emissions, bounds, gap, validation status |
| `result.json`, `solution.json` | the full result and the incumbent's variable values |
| `dbp_trace.csv`, `run.log` | one row and one log line per iteration; written as the run goes |
| `manifest.json` | the configuration used |

The result class is one of:

| Class | Meaning |
|---|---|
| `optimal` | the gap is at most ε and the next proposed tax equals the one evaluated (to 0.001 EUR/t), with no subproblem stopped on its time limit |
| `epsilon_optimal` | the gap is at most ε, but one of those conditions fails |
| `bounds` | the run ended before the gap closed (stagnation, time budget or iteration cap); the result is the interval [LB, UB] and its incumbent |
| `inconsistent` | the lower bound exceeds the upper bound |

Every incumbent is re-evaluated in a fresh model, which must reproduce its feasibility, cost, emissions and leader value (`validation_status`). The full account of the outcomes, time limits and elastic cuts is in [`docs/method.md`](docs/method.md).

### Enumeration

`enumerate_break_points` and `grid_search` (in `clsc.solvers.enumeration`) use the same two-stage optimistic solve as the DBP, so their results are directly comparable. A follower solve that stops on its time limit ends the recursion on its interval, and the result is then not certified (`certified` false); a search stopped by `run_time_limit` returns what it found (`complete` false).

### Experiments

```bash
python -m clsc.experiments list           # the experiments, with their jobs done and in total
python -m clsc.experiments run C1 C2      # run the jobs not done yet; an interrupted run resumes
python -m clsc.experiments report         # summary tables in results/experiments/tables/
python paper/tools/make_tables.py         # the manuscript's table rows, from results/experiments
python paper/tools/make_figure.py         # Figure 1 (needs the plots extra: pip install -e ".[plots]")
```

The experiments are declared in [`src/clsc/experiments/plan.py`](src/clsc/experiments/plan.py) and described in [`docs/experiments.md`](docs/experiments.md). Their files go to `results/experiments/`, which is not tracked by git.

### Tests

```bash
python -m pytest                  # all tests
python -m pytest -m "not slow"    # skip the solver tests
```

The tests that solve a model are skipped when no Gurobi licence is found.

## Configuration

The defaults are in [`src/clsc/config/defaults.py`](src/clsc/config/defaults.py).

| Parameter | Default | Meaning |
|---|---|---|
| `dbp_relative_gap` | `1e-4` | ε, the DBP's stopping tolerance on the relative gap |
| `mip_gap` | `1e-4` | Gurobi MIP gap of every subproblem |
| `time_limit` | `600` s | time limit per subproblem |
| `epsilon_prime` | `1e-6` | ε′, relative tolerance of the follower's tie-break |
| `tax_tolerance` | `1e-3` EUR/t | δ, how close the next proposed tax must be to the evaluated one |
| `stagnation_limit` | `10` | iterations without a bound update before the run stops |
| `tax_weight_relative` | `1e-4` | ξ in the leader's weight μ = ξ · E_ref on the tax |
| `threads`, `mip_focus` | `4`, `2` | Gurobi settings |

## Reproducibility

Tested with Python 3.14.4 and Gurobi 13.0.1 (academic licence) on Windows 11. Instance generation is deterministic given a seed; a DBP solve is deterministic given a Gurobi seed and thread count, subject to Gurobi's run-to-run variability under multithreading.

## References

- Aneja and Nair (1979). Bicriteria transportation problem. *Management Science*, 25(1), 73–78.
- Mota, Gomes, Carvalho and Barbosa-Póvoa (2018). Sustainable supply chains: an integrated modeling approach under uncertainty. *Omega*, 77, 32–57.
- Soares, Alves and Henggeler Antunes (2021). A deterministic bounding procedure for the global optimization of a bi-level mixed-integer problem. *European Journal of Operational Research*, 291, 52–66.
- Tautenhain, Barbosa-Póvoa, Mota and Nascimento (2021). An efficient Lagrangian-based heuristic to solve a multi-objective sustainable supply chain problem. *European Journal of Operational Research*, 294, 70–90.
- Tautenhain, Barbosa-Póvoa, Mota and Nascimento (2020). Data for: An efficient Lagrangian-based heuristic to solve a multi-objective sustainable supply chain problem. Mendeley Data, V2. https://doi.org/10.17632/f82by28vnm.2

## Citation

If you use this code, please cite the manuscript: Pinto, M., Nascimento, P. J., Silva, C. and Moniz, S., *Carbon taxation under anticipated network redesign: a mixed-integer bilevel approach for closed-loop supply chains* (in preparation). The citation will be updated with the archived release (Zenodo DOI).

## Licence

Released under the [MIT licence](LICENSE). Gurobi is not distributed with the code and needs its own licence.

## Contact

Marcelo Pinto, University of Coimbra, CEMMPRE, ARISE, Department of Mechanical Engineering, Coimbra, Portugal · [marcelo.pinto@dem.uc.pt](mailto:marcelo.pinto@dem.uc.pt) · ORCID [0000-0002-6909-3829](https://orcid.org/0000-0002-6909-3829)
