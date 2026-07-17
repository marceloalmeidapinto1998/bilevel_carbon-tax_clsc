"""Command-line batch solver for bilevel CLSC instances.

The implementation lives in :mod:`clsc.solver_cli.core`; the campaign orchestrator
shells out to ``python -m clsc.solver_cli.solve_batch`` (or the equivalent
``clsc/solver_cli/solve_batch.py`` script path).
"""

from .core import (
    RESULT_SCHEMA_VERSION,
    SUPPORTED_SOLVER_METHODS,
    build_parser,
    main,
)

__all__ = [
    "RESULT_SCHEMA_VERSION",
    "SUPPORTED_SOLVER_METHODS",
    "build_parser",
    "main",
]
