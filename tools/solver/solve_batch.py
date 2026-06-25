"""Compatibility wrapper for the batch instance solver.

This executes ``batch/core.py`` in this module namespace so direct file execution and
tests still see the batch solver's module-level functions.
"""

from __future__ import annotations

from pathlib import Path

_CORE_PATH = Path(__file__).with_name("batch") / "core.py"
globals()["__file__"] = str(_CORE_PATH)
exec(compile(_CORE_PATH.read_text(encoding="utf-8"), str(_CORE_PATH), "exec"), globals())
