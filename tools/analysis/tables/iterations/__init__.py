"""Publication-style lexicographic-DBP iteration path tables for base instances."""

from .cli import main
from .io import (
    load_csv,
    load_dbp_trace,
    load_instance_bounds,
    load_json,
    load_result,
    load_summary,
)
from .render import render_instance_table
from .rows import (
    FinalRow,
    IterationRow,
    build_final_row,
    build_phase1_rows,
)

__all__ = [
    "FinalRow",
    "IterationRow",
    "build_final_row",
    "build_phase1_rows",
    "load_csv",
    "load_dbp_trace",
    "load_instance_bounds",
    "load_json",
    "load_result",
    "load_summary",
    "main",
    "render_instance_table",
]
