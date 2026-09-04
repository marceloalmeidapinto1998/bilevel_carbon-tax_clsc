from __future__ import annotations

# USD/kg CO2e per integer tax_index step, on the base instances' native (coarse) grid --
# tax_rate = COARSE_SCALE_FACTOR * tax_index, index {0..20} spanning 0-0.2 USD/kg.
#
# Single source of truth for this constant. It used to be independently defined in
# clsc.generator.config, clsc.models.instance and clsc.campaign.designs._common, each with a
# hand-maintained "keep both values in sync if this is ever changed" comment -- a real risk of
# drift, not just a style complaint. All three now import it from here; clsc.config has no
# dependency on generator/models/campaign, so this does not introduce the generator -> models
# coupling that the original duplication was trying to avoid.
#
# The campaign's finer solve grid (FINE_SCALE_FACTOR = 1e-4) is a separate, deliberately
# different constant -- see clsc.campaign.designs._common -- not a candidate for merging here.
COARSE_SCALE_FACTOR = 0.01
