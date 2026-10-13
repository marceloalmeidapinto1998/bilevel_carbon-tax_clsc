"""Constants shared by more than one part of the package, defined once."""
from __future__ import annotations

from clsc.config.defaults import DEFAULT

# Calendar: weeks in a year, used to convert per-period quantities to annual ones.
WEEKS_PER_YEAR = 52.0

# Tolerances for snapping solver values: an integer variable within INTEGER_SNAP_TOL of an
# integer is rounded to it, and a value within BOUND_SNAP_TOL outside a reported bound is
# clamped onto it.
INTEGER_SNAP_TOL = max(DEFAULT.eps, 1e-5)
BOUND_SNAP_TOL = max(DEFAULT.eps, 1e-6)

# The tax is a decision in EUR per tonne of CO2e; emissions are in kg. The tax rate per kg is
# therefore tax / KG_PER_TONNE, and the HPR works in tonnes (kg / KG_PER_TONNE).
KG_PER_TONNE = 1000.0
