"""Command-line batch solver for bilevel CLSC instances.

Run it as ``python -m clsc.solver_cli`` (or ``clsc-solve`` once the package is installed).
``cli`` parses arguments and runs the solves, ``results`` writes the output files, and
``validation`` revalidates each saved solution.
"""

from .cli import SUPPORTED_SOLVER_METHODS, build_parser, main
from .results import RESULT_SCHEMA_VERSION

__all__ = [
    "RESULT_SCHEMA_VERSION",
    "SUPPORTED_SOLVER_METHODS",
    "build_parser",
    "main",
]
