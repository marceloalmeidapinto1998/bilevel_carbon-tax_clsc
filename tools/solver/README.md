# Solver Tools

Solver tools run model instances and write structured outputs under `results/`.

## Commands

```powershell
python -m tools.solver.solve_batch data/instances/base/STD_I17_M4_T3.json --method dbp_lf_lex_exact
python -m tools.solver.batch data/instances/base --method dbp_lf_lex_exact
```

The file path command is also available:

```powershell
python tools/solver/solve_batch.py data/instances/base/STD_I17_M4_T3.json --method dbp_lf_lex_exact
```

## Packages

- `batch/`: solves one instance file or a directory of instance files.
- `solve_batch.py`: direct wrapper around the batch solver package.
