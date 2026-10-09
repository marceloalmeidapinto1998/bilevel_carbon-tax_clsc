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
