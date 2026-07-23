"""Epsilon grid for Family B's AUGMECON-style epsilon-constraint sweep (Mavrotas, 2009).

Sweeps emissions caps strictly between the two payoff-table anchors -- unconstrained minimum
emissions and the emissions level at unconstrained minimum cost -- so the endpoints are not
duplicated (they are the anchor solves themselves, not epsilon-constraint runs).
"""
from __future__ import annotations

import numpy as np


def epsilon_grid(min_emissions: float, max_emissions: float, *, n_points: int) -> list[float]:
    """`n_points` equally spaced emissions caps strictly inside (min_emissions, max_emissions)."""
    if max_emissions <= min_emissions:
        raise ValueError(
            f"max_emissions ({max_emissions}) must exceed min_emissions ({min_emissions})"
        )
    fractions = np.linspace(0.0, 1.0, n_points + 2)[1:-1]
    return [float(min_emissions + frac * (max_emissions - min_emissions)) for frac in fractions]
