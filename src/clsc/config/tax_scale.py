from __future__ import annotations

# Scale factor converting the leader's INTEGER decision variable into a carbon-tax rate:
# tax_rate = TAX_SCALE_FACTOR * tax_index, in USD/kg CO2e.
#
# The leader does not choose a real number. It chooses a tax expressed to a fixed resolution,
# which makes tax_index an integer variable and TAX_SCALE_FACTOR the constant that turns it back
# into a price -- the same device Soares et al. (2021) use for their tariffs: "we considered
# electricity prices with five decimal places. Therefore, the UL decision variables can be seen
# as integer variables by considering a 10^5 scale factor."
#
# The motivation differs, and the difference is worth stating. Their price multiplies BINARY
# follower variables, so the product linearises exactly by McCormick whatever the price's domain;
# the resolution is a modelling convenience. Here the tax multiplies EMISSIONS, which are sums of
# continuous flow variables, so the product is genuinely bilinear and McCormick only bounds it.
# The integer resolution is what makes the exact one-hot linearisation possible at all (see
# build_dbp_relaxation_master). It is a requirement of the formulation, not a convenience.
#
# tax_index in {0..400} spans 0-0.2 USD/kg, i.e. 0-200 USD/t.
#
# ONE resolution for the whole project: every base instance, every campaign design point and
# every execution mode (bilevel, fixed_tax, enumeration) is generated, stored, and solved at it.
# There used to be two -- a coarse 0.01 baked into the generated base instances and a finer 5e-4
# the campaign rescaled onto at solve time -- and keeping them apart caused a silent 100x
# tau-scale mismatch once (see clsc.campaign.orchestrator, "Tax-scale consistency"). Base
# instances are now generated directly at this resolution (clsc.generator.config.SCALE_FACTOR
# imports this constant), so with_tax_grid_step() is a no-op on any current one; it survives as
# the mechanism for a deliberate probe at a different resolution, not as part of the normal path.
#
# 5e-4 (0.5 USD/t per step, 401 levels) was chosen over the previously-planned 1e-4 (0.1 USD/t,
# 2001 levels) because the DBP loop did not converge at that finer resolution: on STD_TOY6 it
# exhausted its iteration cap and reported a tax far from its least-intervention edge. The
# failure looked like a threshold in level count rather than a gradient -- <=401 converged in
# single-digit iterations, >=1001 never did. That finding predates the 2026-09-10 scale fix
# (EMISSIONS_SCALE 1e6 -> 1e3), which repaired an invalid lower bound caused by the master's
# coefficient range; whether the fine-resolution non-convergence survives that repair has NOT
# been retested. Treat it as an open question, not a settled limit.
TAX_SCALE_FACTOR = 5e-4
