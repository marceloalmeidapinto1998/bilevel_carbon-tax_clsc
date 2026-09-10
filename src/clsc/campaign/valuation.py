"""Emissions-valuation rescale for Experiment 3 (carbon-price calibration).

The generator's cost and emission scales originate in different functional units, so the monetary
value of one emission unit relative to one cost unit is a free ratio ρ. Experiment 3 sweeps ρ and
reports the resulting τ*(ρ). A uniform rescale of ρ is applied here as a multiplier on every
emission-carrying parameter, so emissions are counted ρ× relative to cost in the follower's
objective while the physical network is unchanged.

Convention (decided 2026-07-23): the paper reports Experiment 3 by scaling the emission
*quantities* (e_prod_g / e_rem_l / e_raw_s_u / e_ship_m), as implemented here. This is
mathematically interchangeable with scaling the tax resolution (SCALE_FACTOR) by ρ for τ*(ρ) up to the
index mapping, but the quantity-scaling convention is the one every absolute USD/t statement in the
section is derived from.
"""
from __future__ import annotations

from typing import Any

from clsc.campaign.factors import _scale_param

_EMISSION_PARAMETERS = ("e_prod_g", "e_rem_l", "e_raw_s_u", "e_ship_m")


def apply_valuation_ratio(params: dict[str, Any], ratio: float) -> None:
    """Scale every emission-carrying parameter by `ratio` in place (ratio == 1.0 is a no-op)."""
    for key in _EMISSION_PARAMETERS:
        _scale_param(params, key, float(ratio))
