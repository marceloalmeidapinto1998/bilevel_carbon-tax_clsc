"""Entry point for the batch instance solver.

The implementation lives in ``tools/solver/batch/core.py``. This thin shim re-exports
it so the solver can be run as a script (``python tools/solver/solve_batch.py ...``),
as a module (``python -m tools.solver.solve_batch``), or imported for its module-level
functions -- all pointing at the single ``core`` implementation. It replaces the former
``exec(compile(core.py))`` indirection with a normal import, so the runner is debuggable,
coverage-traceable, and statically analysable.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Run as a script, sys.path[0] is this file's directory (tools/solver), not the repo
# root, so the absolute ``tools.``/``src.`` imports inside core would not resolve. Put
# the repo root first. No-op under ``-m`` / importlib (repo root already importable).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.solver.batch import core as _core  # noqa: E402

# Mirror every module-level name from core so importers of this module -- including the
# test-suite's importlib load of this file -- see exactly the API the old exec-wrapper
# exposed (main, build_parser, the build_* helpers, constants, ...), without exec().
globals().update({name: value for name, value in vars(_core).items() if not name.startswith("__")})


if __name__ == "__main__":
    raise SystemExit(_core.main())
