"""Dense univariate response curves (Family E) — what Morris's elementary effect approximated,
done explicitly: 7-9 multiplier levels per factor (vs. a 2-point OAT comparison), to read off
saturation/threshold/nonlinearity directly from the curve rather than from a summary statistic.
"""
from __future__ import annotations

import numpy as np


def dense_levels(low: float, high: float, *, n_levels: int = 9, baseline: float = 1.0) -> list[float]:
    """`n_levels` multipliers spanning [low, high], including the baseline if not already present."""
    levels = sorted(set(np.linspace(low, high, n_levels).round(6).tolist()) | {baseline})
    return [float(level) for level in levels]
