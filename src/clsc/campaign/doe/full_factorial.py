"""Full 2^k two-level factorial design (Montgomery, Design and Analysis of Experiments, ch. 6)."""
from __future__ import annotations

import itertools


def full_factorial_signs(factor_names: tuple[str, ...]) -> list[dict[str, int]]:
    """All 2^k combinations of -1/+1 over the given factors, standard (Yates) run order."""
    return [
        dict(zip(factor_names, combo))
        for combo in itertools.product((-1, 1), repeat=len(factor_names))
    ]
