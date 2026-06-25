# Sensitivity Experiments

This package generates and analyzes sensitivity and robustness studies.

## Commands

```powershell
python -m tools.experiments.sensitivity oat design data/instances/base/STD_I17_M4_T3.json
python -m tools.experiments.sensitivity morris design data/instances/base/STD_I17_M4_T3.json -N 10
python -m tools.experiments.sensitivity robustness aggregate
python -m tools.experiments.sensitivity analyze-all
```

## Packages

- `oat/`: local one-at-a-time perturbation design and elasticity analysis.
- `morris/`: global Morris elementary-effects design and analysis.
- `robustness/`: solver robustness, tolerance, and censoring analysis.
- `report.py`: builds `results/analysis/SENSITIVITY_REPORT.md`.
