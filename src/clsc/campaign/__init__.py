"""campaign_01 experimental campaign (docs/Experimental_Plan.md).

Seven experiments (Verification, Solver Config, Ablation, Scalability, Leader Value,
Sensitivity, Policy Calibration) driven by `clsc.campaign.orchestrator`. Design points are
declared per experiment in `clsc.campaign.designs.exp{1..7}_*` and materialized into instance
variants by `clsc.campaign.instances.materialize`.
"""
