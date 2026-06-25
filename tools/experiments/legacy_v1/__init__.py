"""Deprecated v1 sensitivity-screening code, kept for historical reference only.

`oat/` (one-at-a-time perturbations) and `morris/` (Morris elementary-effects screening)
were the v1 campaign's screening methodology. The v2 campaign (2026-06-25 redesign) drops
both in favor of a resolution-IV fractional factorial design plus dense univariate response
curves (see `tools/experiments/v2/`) — see the redesigned-experiments plan for the rationale
(Morris is a cheap proxy for Sobol variance-based sensitivity and is hard to defend without
committing to that literature; classical DOE screening is the standard alternative in OR/SCND
computational studies).

Do not extend this code for new work. It still runs against v1 instances/results
(`data/instances/{base,experiments}`, `results/runs/20260619`) for reproducibility only.
"""
