"""Public API for the network analysis package.

Use ``run_instance`` for almost all work. Internal modules by role:
  models   — data classes and variable schema
  io       — config, file loading, path layout, logging
  core     — metrics aggregation, structural phases, alignment
  pipeline — orchestration and CSV output
"""

from .io import DEFAULT, AnalysisConfig
from .models import (
    AlignmentReport,
    Phase,
    TauSnapshot,
    TauStructureResult,
    Transition,
)
from .pipeline import run_instance

__all__ = [
    "AnalysisConfig",
    "DEFAULT",
    "AlignmentReport",
    "Phase",
    "TauSnapshot",
    "TauStructureResult",
    "Transition",
    "run_instance",
]

