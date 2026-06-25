"""Generate a Morris elementary-effects screening design over model factors.

For ``k`` factors and ``N`` trajectories this materializes ``N*(k+1)`` fully-valid instances (one
per design point) + a ``morris_design_matrix.csv`` recording the multiplier levels, trajectory id,
and step index. Sampling uses SALib if installed; otherwise a self-contained Morris trajectory
sampler (Morris 1991) keeps the design reproducible without extra dependencies. Both paths emit
points in the SALib sample order (one trajectory after another).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import io
from ..factors import DEFAULT_MORRIS_FACTORS, apply_levels, build_salib_problem

SCENARIO_NAME = "sensitivity_morris"  # metadata label (results route by path, not this name)
DEFAULT_OUTPUT_DIR = io.DATA_INSTANCES / "experiments" / "sensitivity" / "morris"


def sample_design(problem: dict, N: int, num_levels: int, seed: int) -> tuple[np.ndarray, str]:
    """Return (X, engine) where X has shape (N*(k+1), k) in actual multiplier units."""
    try:
        from SALib.sample import morris as _morris_sample  # type: ignore
        X = _morris_sample.sample(problem, N=N, num_levels=num_levels, seed=seed)
        return np.asarray(X, dtype=float), "salib"
    except Exception:  # noqa: BLE001 - fall back to the bundled sampler
        return _sample_bundled(problem, N, num_levels, seed), "bundled"


def _sample_bundled(problem: dict, N: int, num_levels: int, seed: int) -> np.ndarray:
    """Self-contained Morris trajectory sampler (Morris 1991 construction)."""
    rng = np.random.default_rng(seed)
    k = int(problem["num_vars"])
    bounds = np.asarray(problem["bounds"], dtype=float)
    low, high = bounds[:, 0], bounds[:, 1]
    p = int(num_levels)
    delta = p / (2.0 * (p - 1.0))

    levels = np.arange(p) / (p - 1.0)
    start_pool = levels[levels <= 1.0 - delta + 1e-9]

    blocks = []
    for _ in range(N):
        x_star = rng.choice(start_pool, size=k)
        d_star = np.diag(rng.choice([-1.0, 1.0], size=k))
        perm = rng.permutation(k)
        p_star = np.eye(k)[perm]
        B = np.tril(np.ones((k + 1, k)), -1)
        J = np.ones((k + 1, k))
        b_star = (np.outer(np.ones(k + 1), x_star) + (delta / 2.0) * ((2 * B - J) @ d_star + J)) @ p_star
        blocks.append(np.clip(b_star, 0.0, 1.0))

    x_norm = np.vstack(blocks)
    return low + x_norm * (high - low)


def generate(
    base_path: str | Path,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    factors: tuple[str, ...] = DEFAULT_MORRIS_FACTORS,
    N: int = 10,
    num_levels: int = 4,
    seed: int = 0,
    overwrite: bool = False,
) -> dict:
    problem = build_salib_problem(factors)
    X, engine = sample_design(problem, N, num_levels, seed)
    pts_per_traj = len(factors) + 1
    n_points = X.shape[0]

    base_payload = io.load_base_payload(base_path)
    source_name = str(base_payload["name"])
    subdir = Path(output_dir) / source_name
    subdir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for idx in range(n_points):
        trajectory, step = divmod(idx, pts_per_traj)
        levels = X[idx]
        run_id = f"M{idx:04d}"

        def mutate(params, _levels=levels):
            apply_levels(params, factors, _levels)

        dest = subdir / f"{run_id}.json"
        io.materialize_instance(
            base_payload, run_id, mutate, dest,
            scenario_name=SCENARIO_NAME,
            scenario_meta={"morris": {
                "engine": engine,
                "trajectory": int(trajectory),
                "step": int(step),
                "factors": list(factors),
                "levels": [float(v) for v in levels],
            }},
            overwrite=overwrite,
        )
        row = {"run_id": run_id, "trajectory": int(trajectory), "step": int(step)}
        row.update({name: float(val) for name, val in zip(factors, levels)})
        row["path"] = str(dest)
        rows.append(row)

    design_path = io.write_design_matrix(rows, subdir / "morris_design_matrix.csv")
    return {
        "engine": engine,
        "n_points": n_points,
        "n_trajectories": N,
        "factors": list(factors),
        "output_dir": str(subdir),
        "design_matrix": str(design_path),
    }
