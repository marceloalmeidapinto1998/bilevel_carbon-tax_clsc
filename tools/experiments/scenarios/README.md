# Scenario Experiments

Scenario generators create modified instance JSON files under `data/instances/experiments/scenarios/`.

## Commands

```powershell
python -m tools.experiments.scenarios technology
python -m tools.experiments.scenarios transport
python -m tools.experiments.scenarios combined
```

Direct package commands are also available:

```powershell
python -m tools.experiments.scenarios.technology
python -m tools.experiments.scenarios.transport
python -m tools.experiments.scenarios.combined
```

## Packages

- `technology/`: adds production and remanufacturing technology options.
- `transport/`: adds road, air, and sea transport mode options.
- `combined/`: applies technology and transport expansions together.
- `common/`: shared constants for scenario paths.

