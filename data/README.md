# `data/` layout

- `generator/` — instance generator code (Tautenhain-based CLSC benchmark sampler).
- `instances/` — generated model instances, organized to **mirror `results/runs/`** exactly, so the
  subpath under `data/instances/` is reused verbatim under `results/runs/` when solved:

```
data/instances/
  base/         <inst>.json
  experiments/
    scenarios/  {tech,trans,tech_trans}/<inst>.json
    sensitivity/
      oat/      <base>/<code>.json  (+ design_matrix.csv)        one-at-a-time perturbations
      morris/   <base>/M*.json     (+ morris_design_matrix.csv) Morris screening design
```

## Who writes / reads where

- **base/** — `python -m data.generator benchmark` (also read by elasticity baselines).
- **experiments/scenarios/** — `tools.experiments.scenarios` generators.
- **experiments/sensitivity/oat/** — `tools.experiments.sensitivity oat design`.
- **experiments/sensitivity/morris/** — `tools.experiments.sensitivity morris design` (read back by
  `morris analyze`).

The solver (`tools.solver.solve_batch`) maps a `data/instances/<X>` path to `results/runs/<X>`
(identity); anything not under `base/` or `experiments/` defaults to `results/runs/base/`.

> Tax-range extension is an OAT spec (`tax_range_max040`, `tax_range_max080`), not a separate
> `tax_extended` scope.
