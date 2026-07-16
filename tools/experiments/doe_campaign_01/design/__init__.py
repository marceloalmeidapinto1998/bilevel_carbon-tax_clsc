"""Generic, instance-agnostic DOE construction primitives used by `experiments/designs/`.

  full_factorial.py        full 2^k design (Family D)
  fractional_factorial.py  resolution->=IV fractional factorial via fold-over (Family C)
  frontier_sweep.py        fixed-tax grid (Family B)
  response_surface.py      dense univariate multiplier levels (Family E)
  robustness.py            seed and solver-tolerance grids (Family F)
  structural.py            technology/transport menu-breadth "low"/"high" levels (C, D)
"""
