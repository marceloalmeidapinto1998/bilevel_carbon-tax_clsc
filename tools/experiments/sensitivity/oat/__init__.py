"""Local one-at-a-time (OAT) sensitivity: perturbation catalogue, instance generation, elasticities.

Modules by role:
  specs    — SensitivitySpec catalogue + parameter mutations + rel_input_change metadata
  design   — generate perturbed instances + design_matrix.csv
  analyze  — sensitivity_matrix.csv elasticities
"""

from .specs import SENSITIVITY_SPECS, SPECS_BY_CODE, SensitivitySpec

__all__ = ["SENSITIVITY_SPECS", "SPECS_BY_CODE", "SensitivitySpec"]
