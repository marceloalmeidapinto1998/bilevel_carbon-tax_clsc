"""OAT elasticities: build sensitivity_matrix.csv from master_runs.csv.

Reads the generic tidy table produced by ``tools.analysis.aggregate`` and computes, per
(instance, perturbation), percentage changes versus the base run, relative input changes,
and normalized cost/emissions/tax elasticities. Perturbations whose effect is within the
solver-noise floor are flagged.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from tools.experiments.sensitivity import io
from .specs import SPECS_BY_CODE, canonical_code


def analyze() -> Path:
    master = pd.read_csv(io.TABLES / "master_runs.csv")
    base_ref = (
        master[master.category == "base"]
        .set_index("base_instance")[["effective_tax", "emissions", "cost"]]
    )
    sens = master[master.category == "sensitivity"].copy()

    recs = []
    for _, r in sens.iterrows():
        if r.base_instance not in base_ref.index:
            continue
        b = base_ref.loc[r.base_instance]
        pct_emissions = (r.emissions - b.emissions) / b.emissions * 100
        pct_cost = (r.cost - b.cost) / b.cost * 100
        pct_tax = (
            (r.effective_tax - b.effective_tax) / b.effective_tax * 100
            if b.effective_tax
            else np.nan
        )

        raw_code = str(r.sa_dim)[3:] if str(r.sa_dim).startswith("SA_") else str(r.sa_dim)
        code = canonical_code(raw_code)
        spec = SPECS_BY_CODE.get(code)
        rel = spec.rel_input_change(io.base_params(r.base_instance)) if spec else None
        elastic = lambda pct: pct / (rel * 100) if rel else np.nan  # noqa: E731
        recs.append({
            "base_instance": r.base_instance,
            "sa_dim": code,
            "factor": spec.factor if spec else "",
            "kind": spec.kind if spec else "",
            "rel_input_change": rel if rel is not None else np.nan,
            "tau": r.effective_tax,
            "d_tau": r.effective_tax - b.effective_tax,
            "emissions": r.emissions,
            "pct_emissions": pct_emissions,
            "cost": r.cost,
            "pct_cost": pct_cost,
            "pct_tax": pct_tax,
            "elasticity_cost": elastic(pct_cost),
            "elasticity_emissions": elastic(pct_emissions),
            "elasticity_tax": elastic(pct_tax),
            "below_noise": bool(abs(pct_cost) < io.NOISE_PCT and abs(pct_emissions) < io.NOISE_PCT),
        })

    sens_m = pd.DataFrame(recs).sort_values(["base_instance", "sa_dim"])
    io.TABLES.mkdir(parents=True, exist_ok=True)
    out = io.TABLES / "sensitivity_matrix.csv"
    sens_m.to_csv(out, index=False)
    n_elastic = int(sens_m["elasticity_cost"].notna().sum()) if not sens_m.empty else 0
    n_noise = int(sens_m["below_noise"].sum()) if not sens_m.empty else 0
    print(f"sensitivity_matrix.csv: {len(sens_m)} (instance, code) rows; "
          f"{n_elastic} with finite elasticity; {n_noise} below {io.NOISE_PCT}% noise floor")
    return out
