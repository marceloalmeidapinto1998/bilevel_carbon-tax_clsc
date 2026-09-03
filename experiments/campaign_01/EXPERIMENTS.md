# campaign_01: experiment guide

This is the computational campaign behind the paper's results. It studies a **bilevel
optimization model** of a closed-loop supply chain (CLSC) under a carbon tax: a **leader**
(the regulator) chooses a carbon-tax rate τ to minimize total supply-chain emissions —
preferring, among every tax that achieves that minimum, the smallest one (least market
intervention) — and a **follower** (industry) responds by choosing its network design and
operations to minimize its own cost given that tax. The two problems are solved together by a
custom Decomposition-Based Procedure (DBP).

This file explains, in plain terms, what each of the four experiments tests and why — enough to
read the design-matrix CSVs and the eventual results without needing prior context.

## Layout

```
experiments/campaign_01/<exp>/design_matrix.csv           # what to run, one row per design point
data/instances/campaigns/campaign_01/<exp>/<cell>/*.json  # the materialized instance for each row
results/runs/campaign_01/<exp>/<cell>/<run_code>/         # solve outputs, once run
```

A "cell" is one of the benchmark's structural test instances, named `STD_I<n>_M<m>_T<t>` for
`n` supply-chain nodes, `m` a materials/products richness code, and `t` planning periods —
12 in total, spanning two sizes, two richness levels, and three horizons. A "design point" is one
row of a `design_matrix.csv`: a specific cell, solved under a specific configuration (a fixed
tax rate, a weakened algorithm variant, a scaled input factor, and so on).

Rebuild the design matrices: `python -m clsc.campaign.orchestrator generate --experiment all`.
Materialize instances and solve: `python -m clsc.campaign.orchestrator run --experiment <1..4|all>`.

## exp1 — Verification

**Is the implementation correct?** Before trusting any other result, this experiment checks that
the solver reliably finds the true optimum. It combines four checks: six hand-verifiable toy
instances small enough that a reader can re-derive the optimal network on paper; all 12 structural
test cells solved once each, to measure how often the solver certifies an exact optimum rather
than stopping on a gap; a check that a direct, single-tax follower solve reproduces the numbers a
full bilevel run reports at that same tax (they should agree, since the bilevel run is just many
such solves coordinated by the leader); and a check that changing the solver's internal random
seed changes *how* it searches but not the optimum it reports.

## exp2 — Computational performance

**Does the algorithm work, does every part of it matter, does it scale, and is it actually faster
than the obvious alternative?** DBP avoids solving the follower's problem at every possible tax
rate by using a smarter search procedure with several components. This experiment checks each
claim separately: the full method's performance on a spread of instance sizes; what happens when
one specific component is switched off (does the answer change, does it get slower?); a few probes
beyond the standard test set's size (more materials/products, more supply-chain nodes), to see
where performance starts to degrade; and a head-to-head comparison against the "brute-force"
alternative — solving the follower's
problem at every tax rate on a grid and picking the best. Since the leader only controls one
number on a finite grid, that brute-force approach is exact by construction, making it the
natural benchmark: if DBP doesn't beat it, DBP isn't earning its complexity.

## exp3 — Policy value and price calibration (the paper's central result)

**Is there really one "right" carbon tax, and can we say what it's worth in real currency?** This
is the experiment the paper's main claim rests on. The recurring finding is that the
emissions-minimizing tax is not a single point but a *plateau* — a whole range of tax rates that
all achieve the same minimum emissions, differing only in how much they cost the industry to
reach it. Within that range, the regulator has a natural, defensible choice: the smallest tax
that still gets the job done (least intervention).

This experiment (a) compares that chosen tax against simpler policy rules a regulator without a
bilevel model might use instead (no tax, the highest tax allowed, a middle-of-the-road tax), to
show how much cost the naive choices leave on the table for the same emissions outcome; (b) maps
the shape of that plateau in detail around the chosen tax; and (c) since everything up to this
point works in a relative tax *index*, calibrates what that index means in actual currency per
tonne of CO2e — including a cross-check against the tax rate that would be needed if the regulator
instead minimized emissions directly, ignoring cost.

Two of this experiment's stages depend on results from `exp2` (the full-method solve) and from an
earlier stage of `exp3` itself (the currency calibration), so its design matrix grows in two steps
as those results become available.

## exp4 — Sensitivity / robustness

**Which model inputs actually move the results?** The model has many input parameters — demand
levels, emission intensities, production capacities, and so on. This experiment perturbs eight of
them together, following a designed statistical screening pattern (a fractional factorial design)
that lets each factor's effect on cost and emissions be estimated from far fewer runs than testing
every combination would require.
