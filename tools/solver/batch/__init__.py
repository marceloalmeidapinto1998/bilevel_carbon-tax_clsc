"""Batch solver for one or more generated instance JSON files."""

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

