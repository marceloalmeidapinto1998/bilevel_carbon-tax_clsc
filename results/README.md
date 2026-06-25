# `results/` layout

Two tiers: **raw** solver outputs under `runs/`, **derived** analysis under `analysis/`.

```
results/
  runs/                                  raw solver outputs, grouped by run generation
    <YYYYMMDD>/                          dated run folder (one per generation of solves)
      base/       <inst>/<method>/        baseline instances
      experiments/
        scenarios/  <type>/<inst>/<method>/ technology / transport / combined scenarios
        sensitivity/
          oat/      <base>/<code>/<method>/ one-at-a-time perturbations
          morris/   <base>/<run>/<method>/  Morris elementary-effects screening
  analysis/                              derived outputs (regenerated from runs/)
    tables/    *.csv  (master_runs, tax_response_long, scenario_2x2, sensitivity_matrix,
                       solver_robustness, censoring_flags, morris_*_indices)
    figures/   *.png
    reports/   SENSITIVITY_REPORT.md, build_log.txt
```

`<method>` is e.g. `lf_lex_exact` or `enum_lf_lex_exact`; each run dir holds `summary.json`,
`result.json`, `solution.json`, traces, and a `network/` subdir.

## Run versioning

Each dated folder under `runs/` is a complete generation of results. To start a new run:

1. Pass `--results-root results/runs/<YYYYMMDD>` to every solver/batch command.
2. Set `RUN_ID = "<YYYYMMDD>"` in `tools/analysis/common/paths.py` so the aggregator targets that generation.

To compare or switch between generations, change `RUN_ID` in `paths.py`; set it to `""` to scan the entire `runs/` tree.

## Who writes where

- **Solver** (`tools.solver.solve_batch` / `tools.solver.batch`) writes under `results/runs/<date>/`; the
  data-instance scope maps to the results path (`base`→`base`, `scenarios`→`experiments/scenarios`,
  `sensitivity`→`experiments/sensitivity/oat`, `sensitivity_morris`→`experiments/sensitivity/morris`).
- **Aggregator** (`tools.analysis.aggregate`) reads `runs/<date>/` (via `RUN_ID` in `paths.py`) → writes the tidy tables to `analysis/tables/`.
- **Sensitivity** (`tools.experiments.sensitivity`) reads `analysis/tables/` (and `runs/` for Morris) →
  writes elasticities/robustness/censoring to `tables/`, figures to `figures/`, the report to `reports/`.

## Regenerate the derived analysis (no solves)

```
python -m tools.experiments.sensitivity analyze-all
```

> Tax-range extension is an OAT spec (`tax_range_max040`, `tax_range_max080`), not a separate
> `tax_extended` scope.
