"""Aggregate optimization-result table across all base instances and methods."""

from .core import ResultRow, load_rows, render_all_methods_table, write_all_methods_outputs
from .cli import main

__all__ = [
    "ResultRow",
    "load_rows",
    "render_all_methods_table",
    "write_all_methods_outputs",
    "main",
]
