# Analysis Tools

Analysis tools post-process solved result folders and write derived outputs under `results/analysis/`.

## Commands

```powershell
python -m tools.analysis.aggregate
python -m tools.analysis.network
python -m tools.analysis.tables.optimization
python -m tools.analysis.tables.iterations
```

## Packages

- `aggregate/`: builds master result tables from `results/**`.
- `network/`: extracts per-instance network structure and tax-response artifacts.
- `tables/optimization/`: renders the aggregate optimization-result table.
- `tables/iterations/`: renders LF-Lex iteration path tables.
- `common/`: shared paths, fixed CSV schemas, robust readers, and plotting setup.
