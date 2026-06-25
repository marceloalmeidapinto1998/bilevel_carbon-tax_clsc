"""Solver-tolerance sensitivity: does the bilevel incumbent depend on tolerance settings?"""
from __future__ import annotations

import contextlib
from dataclasses import replace
import importlib
from pathlib import Path
import time

import pandas as pd

from .. import io
from src.config import gap_tol

_TOLERANCE_MODULES = (
    "src.config.gap_tol",
    "src.models.shared_models",
    "src.models.instance_loader",
    "src.models.elastic_models",
    "src.solvers.dbp_exact",
    "src.solvers.dbp_certified",
    "src.solvers.dbp_f_lex_exact",
    "src.solvers.dbp_lf_lex_exact",
    "src.solvers.enum_lf_lex_exact",
)

DEFAULT_GRID: tuple[dict, ...] = (
    {},
    {"mip_gap": 1e-3},
    {"mip_gap": 1e-5},
    {"dbp_relative_gap": 1e-3},
    {"dbp_relative_gap": 1e-5},
    {"lex_epsilon_prime": 1e-5},
    {"lex_epsilon_prime": 1e-4},
    {"dbp_cut_epsilon": 0.05},
    {"dbp_cut_epsilon": 0.2},
    {"eps": 1e-6},
)


@contextlib.contextmanager
def patched_tolerances(**overrides):
    """Temporarily replace ``DEFAULT`` with an overridden ToleranceConfig in solver modules."""
    new_cfg = replace(gap_tol.DEFAULT, **overrides)
    saved: dict[str, object] = {}
    for name in _TOLERANCE_MODULES:
        try:
            mod = importlib.import_module(name)
        except Exception:  # noqa: BLE001
            continue
        if hasattr(mod, "DEFAULT"):
            saved[name] = mod.DEFAULT
            mod.DEFAULT = new_cfg  # type: ignore[attr-defined]
    try:
        yield new_cfg, tuple(saved)
    finally:
        for name, old in saved.items():
            importlib.import_module(name).DEFAULT = old  # type: ignore[attr-defined]


def _extract(result) -> dict:
    get = lambda key: getattr(result, key, None)  # noqa: E731
    return {
        "hat_tau": get("hat_tau"),
        "emissions": get("emissions"),
        "cost": get("cost"),
        "relative_gap": get("relative_gap"),
        "iterations": get("iterations"),
    }


def run(
    base_path: str | Path,
    grid: tuple[dict, ...] = DEFAULT_GRID,
    *,
    time_limit: float | None = None,
) -> Path:
    from src.solvers.dbp_lf_lex_exact import solve_bilevel_dbp_lf_lex_exact

    rows = []
    for overrides in grid:
        label = "baseline" if not overrides else ",".join(f"{key}={value}" for key, value in overrides.items())
        with patched_tolerances(**overrides):
            t0 = time.perf_counter()
            result = solve_bilevel_dbp_lf_lex_exact(Path(base_path), time_limit=time_limit)
            secs = time.perf_counter() - t0
        rows.append({
            "config": label,
            **{f"d_{key}": value for key, value in overrides.items()},
            **_extract(result),
            "solve_seconds": round(secs, 3),
        })

    df = pd.DataFrame(rows)
    base = df.iloc[0]
    df["d_hat_tau_vs_base"] = pd.to_numeric(df["hat_tau"], errors="coerce") - base["hat_tau"]
    df["pct_emissions_vs_base"] = (
        (pd.to_numeric(df["emissions"], errors="coerce") - base["emissions"])
        / base["emissions"]
        * 100
    )
    io.TABLES.mkdir(parents=True, exist_ok=True)
    out_csv = io.TABLES / "tolerance_sensitivity.csv"
    df.to_csv(out_csv, index=False)
    print(f"tolerance_sensitivity.csv: {len(df)} configs; "
          f"max |d hat_tau| vs base = {df['d_hat_tau_vs_base'].abs().max()}, "
          f"max |% emissions| vs base = {df['pct_emissions_vs_base'].abs().max():.3g}")
    return out_csv


def smoke() -> int:
    """Verify the tolerance-injection plumbing without solving."""
    before = gap_tol.DEFAULT.mip_gap
    with patched_tolerances(mip_gap=1e-2, eps=1e-5) as (cfg, mods):
        lf = importlib.import_module("src.solvers.dbp_lf_lex_exact")
        sm = importlib.import_module("src.models.shared_models")
        assert cfg.mip_gap == 1e-2 and cfg.eps == 1e-5
        assert lf.DEFAULT.mip_gap == 1e-2, "solver module did not see the patched tolerance"
        assert sm.DEFAULT.eps == 1e-5, "model module did not see the patched tolerance"
        print(f"OK: patched {len(mods)} modules; solver sees mip_gap={lf.DEFAULT.mip_gap}, "
              f"eps={sm.DEFAULT.eps}")
    assert gap_tol.DEFAULT.mip_gap == before, "DEFAULT not restored after context"
    print(f"OK: restored DEFAULT.mip_gap={gap_tol.DEFAULT.mip_gap}")
    return 0

