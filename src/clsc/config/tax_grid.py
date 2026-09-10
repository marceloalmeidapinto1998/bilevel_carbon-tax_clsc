from __future__ import annotations

# USD/kg CO2e per integer tax_index step -- tax_rate = TAX_GRID_SCALE_FACTOR * tax_index.
# Index {0..400} spans 0-0.2 USD/kg (0-200 USD/t).
#
# The ONLY carbon-tax grid in this project: every base instance, every campaign design point and
# every execution mode (bilevel, fixed_tax, enumeration) is generated, stored, and solved at this
# resolution. There used to be two grids -- a coarse one (0.01) baked into the generated base
# instances and a finer one (5e-4) the campaign rescaled onto at solve time via
# InstanceData.with_tax_grid_step() -- kept apart because the campaign's DBP loop does not
# converge at finer resolutions still (see the note below) and the base instances predated that
# finding. Collapsing them removes a real footgun: fixed_tax runs and bilevel runs used to be
# solved on different grids unless every caller remembered to rescale, which caused a silent
# 100x tau-scale mismatch once (see clsc.campaign.orchestrator's module docstring, "Tax-grid
# consistency"). Base instances are now generated directly at this resolution
# (clsc.generator.config.SCALE_FACTOR imports this constant), so with_tax_grid_step() is a no-op
# on any current base instance -- it is kept only as the mechanism, for the rare caller that
# still wants a different resolution (e.g. the retired coarse grid, for a deliberate robustness
# probe) rather than as a load-bearing part of the normal path.
#
# 5e-4 (0.5 USD/t per step, 401 points) was chosen over the previously-planned 1e-4 (0.1 USD/t,
# 2001 points) because the DBP loop does not converge at that finer resolution: on STD_TOY6 it
# exhausted max_iterations (2002) and reported a tax far from its least-intervention edge. The
# failure is a threshold in point count, not a gradient -- <=401 points converge in single-digit
# iterations and certify, >=1001 never do. 0.5 USD/t is finer than any carbon price is set in
# practice (see docs/Experimental_Plan.md and paper/appendix/app_data.tex for the range
# [0, 0.2] USD/kg's own literature justification). The underlying non-convergence at finer grids
# remains undiagnosed and is a known limitation, not fixed by this choice of resolution.
TAX_GRID_SCALE_FACTOR = 5e-4
