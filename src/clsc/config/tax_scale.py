from __future__ import annotations

# Scale factor converting the leader's INTEGER decision variable into a carbon-tax rate:
# tax_rate = TAX_SCALE_FACTOR * tax_index, in USD/kg CO2e.
#
# The leader does not choose a real number. It chooses a tax expressed to a fixed resolution,
# which makes tax_index an integer variable and TAX_SCALE_FACTOR the constant that turns it back
# into a tax rate -- the same device Soares et al. (2021) use for their tariffs: "we considered
# electricity prices with five decimal places. Therefore, the UL decision variables can be seen
# as integer variables by considering a 10^5 scale factor."
#
# The motivation differs, and the difference is worth stating. Their price multiplies BINARY
# follower variables, so the product linearises exactly by McCormick whatever the price's domain;
# the resolution is a modelling convenience. Here the tax multiplies EMISSIONS, which are sums of
# continuous flow variables, so the product is genuinely bilinear and McCormick only bounds it.
# The integer resolution is what makes the exact one-hot linearisation possible at all (see
# build_hpr). It is a requirement of the formulation, not a convenience.
#
# tax_index in {0..200} spans 0-0.2 USD/kg: the leader sets a WHOLE number of USD per
# tonne. That is the resolution Soares et al.'s phrasing needs -- 1e-3 is a power of ten,
# so the tax rate has 'three decimal places in USD/kg', and tax_index is its
# integer form. The previous 5e-4 (0.5 USD/t) was not a power of ten and could not be
# described that way. It also halves the one-hot gadget: 201 binaries instead of 401, in
# an HPR that is ~95% of every run's wall time.
#
# ONE resolution for the whole project: every base instance is generated, stored and solved at
# it (clsc.generator.config.TAX_SCALE_FACTOR imports this constant), so with_tax_grid_step() is a
# no-op on any current instance; it survives as the mechanism for a deliberate probe at a
# different resolution. Two resolutions used to coexist (a coarse one baked into the instances and
# a finer one applied at solve time), and keeping them apart once caused a silent 100x tau-scale
# mismatch -- which is why there is now only this one.
#
# Finer grids (1e-4, 2001 levels) were once observed not to converge, before the 2026-09-10 fix
# of EMISSIONS_SCALE (1e6 -> 1e3) repaired an invalid lower bound caused by the HPR's
# coefficient range. Whether that non-convergence survives the repair has NOT been retested.
TAX_SCALE_FACTOR = 1e-3
