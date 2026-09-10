"""Fixed-tax sweep for the cost-emissions frontier (Family B).

Unlike Families A/C/D/E/F/G, Family B does not run the bilevel leader-follower procedure at
all — it fixes `tax_index` and solves the follower's MILP once per grid point
(`clsc.models.subproblems.solve_fixed_tax_follower`). This sidesteps the carbon-price
non-identification issue entirely: there is no leader optimization to mis-converge, so every
point on the resulting curve is exact for the given tax (subject to the MILP gap).
"""
from __future__ import annotations


def tax_grid(overline_tax_index: int, *, n_points: int = 11, step: int = 2) -> list[int]:
    """`n_points` integer tax_index values from 0 to `overline_tax_index`, spaced by `step`.

    Defaults to the plan's 0..ceiling grid in steps of 2 (11 points for ceiling=20).
    """
    grid = [i * step for i in range(n_points)]
    if grid[-1] != overline_tax_index:
        raise ValueError(
            f"Grid (0..{grid[-1]} step {step}, {n_points} points) does not reach the instance's "
            f"overline_tax_index={overline_tax_index}; adjust n_points/step for this instance."
        )
    return grid
