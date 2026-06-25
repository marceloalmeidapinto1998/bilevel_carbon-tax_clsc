Organize and clean up the BilevelModel_CLSC repository. This is a research codebase (bilevel
carbon-tax / closed-loop supply chain model) with a Gurobi solver layer, a data generator, an
analysis/sensitivity pipeline, a Streamlit dashboard, and a LaTeX paper. The goal is to remove
dead weight and fix structural inconsistencies WITHOUT changing any model, solver, or analysis
behavior. This is housekeeping, not a refactor of logic.

## 0. Safety net first (do this before anything else)

This directory has a `.gitignore` but is **not actually a git repository** (no `.git/` folder
exists). Before touching anything:
1. Run `git init` and make one commit of the current state as-is, so every subsequent change in
   this cleanup is reviewable/revertible via `git diff` / `git log`.
2. Only after that baseline commit, start making changes. Commit in small, logically grouped
   steps (e.g. "remove stray build artifacts", "fix requirements.txt drift") rather than one
   giant commit, so the user can review or revert pieces independently.

## 1. Confirmed dead / stray files — remove

- `texput.log` (repo root) — leftover failed pdflatex run artifact. Not covered by any
  `.gitignore` rule (those only cover `paper/*.aux|*.log|*.out`). Delete it, and check whether a
  pdflatex invocation outside `paper/` is leaving these behind (if so, that's a one-line
  `.gitignore` fix: add `texput.log` at the root).
- `src/__pycache__/solver_method_utils.cpython-314.pyc` — orphaned bytecode for a module named
  `solver_method_utils.py` that **no longer exists anywhere in `src/`** and has zero references
  in any `.py` file. The source was deleted at some point but the cache wasn't. Harmless on its
  own (pycache is gitignored), but: grep `src/solvers/*.py` for whatever helper functions that
  module used to hold — if its logic was inlined/duplicated across `dbp_certified.py`,
  `dbp_exact.py`, `dbp_f_lex_exact.py`, `dbp_lf_lex_exact.py`, `enum_lf_lex_exact.py` instead of
  staying shared, that's a real duplication smell worth flagging (see §3).
- All `__pycache__/` and `.pyc` files under `src/`, `tools/`, `tests/`, `app/`,
  `data/generator/` — already gitignored, but delete them anyway so the tree you're inspecting
  reflects only real source files, not stale compiled artifacts from deleted modules.

## 2. Confirmed/likely duplication — needs a decision, then action

- `results/analysis_20260618_backup/` vs `results/analysis/` — this looks like a manual
  point-in-time backup of the analysis output dir, made by copy-pasting a folder instead of using
  version control. Now that git exists (per §0), this backup pattern is redundant — git history
  is the backup. Diff the two directories; if `analysis_20260618_backup` is strictly superseded
  by `analysis/` (it appears to be: `analysis/` has newer files like
  `base_tradeoff_20260619.csv` and `scenario_deltas_20260619.csv` that the backup lacks), delete
  the backup dir. If anything in it is NOT reproducible by re-running the analysis pipeline,
  confirm with the user before deleting.
- `run_20260619.ps1` (repo root) — a one-off, dated solve script tied specifically to the
  `results/runs/20260619` run (hardcoded `$RunRoot = "results/runs/20260619"`). Root-level dated
  scripts will keep accumulating as new runs happen. Move it into
  `results/runs/20260619/run_20260619.ps1` (next to that run's own `RESULTS_ANALYSIS.md`) so the
  root stays generic, or — if this run is finished and the script has no future reuse value —
  confirm with the user whether to delete it instead of relocate it.

## 3. Structural inconsistencies — fix

- `requirements.txt` is missing `streamlit` and `plotly`, both imported directly by
  `app/scn_dashboard.py` (a 1591-line file). Anyone following `requirements.txt` cannot run the
  dashboard. Add both with the same `>=X,<Y` pinning style already used for the other deps.
- `requirements.txt` has a stale comment: `# ... Optional: tools/sensitivity/morris_design.py
  falls back to a bundled trajectory sampler when SALib is absent.` — that path doesn't exist;
  the real module is `tools/experiments/sensitivity/morris/design.py`. Fix the comment to point
  at the real path (and verify the "falls back without SALib" claim is still true by reading that
  file — update or remove the claim if it no longer applies).
- Check for other comments/docstrings anywhere in `tools/` and `src/` that reference module paths
  by their pre-refactor location (the `tools/experiments/sensitivity/` and `tools/analysis/` trees
  show signs of having been reorganized into subpackages at some point — `morris/`, `oat/`,
  `robustness/` under `sensitivity/`; `aggregate/`, `network/`, `tables/` under `analysis/`).
  Grep for old flat-file names like `morris_design.py`, `morris_analyze.py`, `oat_design.py` etc.
  across `*.md`, `*.py`, and `*.ps1` to catch any other stale path references like the one above.

## 4. Things to investigate but NOT touch without asking

- `IEEE_WIP/` (root) vs `paper/` (root) — two separate LaTeX paper trees. `paper/` looks like the
  actively maintained full paper (sectioned into `sections/`, `appendix/`, `tables/`,
  `algorithms/`, has a `README.md`). `IEEE_WIP/` looks like a separate IEEE conference-format
  attempt, single `main.tex`, no README. Ask the user whether `IEEE_WIP/` is abandoned (in which
  case move it under e.g. `paper/archive/` or delete it) or still a live, separate submission
  target (in which case leave it alone but maybe add a one-line README noting its relation to
  `paper/`).
- `src/solvers/` has five solver variants: `dbp_certified.py`, `dbp_exact.py`,
  `dbp_f_lex_exact.py`, `dbp_lf_lex_exact.py`, `enum_lf_lex_exact.py`. Per the project's trimmed
  experiment plan, only a subset of these may still be in active use (the `run_20260619.ps1`
  script only invokes `dbp_lf_lex_exact`). Do NOT delete or merge any of these without explicit
  confirmation — check `tools/solver/batch/core.py` and any CLI `--method` choices to see which
  ones are still wired up/reachable, and report which (if any) look unreachable from any CLI
  entry point. Flag them; don't remove them in this pass.
- `data/instances/base/*.json` — known to predate a generator change (missing `f_w`, `c_area_*`
  fields per existing project notes). Do not regenerate, edit, or delete these. Leave the whole
  `data/instances/` tree untouched in this cleanup.
- `notes/paper_findings_memo.md` says it is the "single source of truth" for numbers reported in
  the paper, generated 2026-06-11 from `results/analysis/`. Since `results/analysis/` now has
  newer files (`base_tradeoff_20260619.csv`, `scenario_deltas_20260619.csv` from a later run),
  flag to the user whether this memo is now stale and needs regenerating — don't regenerate it
  yourself as part of a "cleanup" pass, since that changes content, not structure.

## 5. Verification — do this after each batch of changes, not just at the end

- Run `pytest` (config at `pytest.ini`, tests in `tests/`) before starting and after each
  commit. All tests passing before your changes must still pass after. If something was passing
  by accident (e.g. relying on a stray `__pycache__` file), investigate rather than restoring the
  cruft to make the test pass again.
- For anything under `tools/` or `app/` that has a CLI/`__main__.py` entry point, do a smoke
  invocation (e.g. `--help`) after any file moves to confirm imports still resolve.
- Do not modify anything under `src/models/`, `src/solvers/`, or `data/generator/` logic itself —
  this pass is about file/dir hygiene, dependency declarations, and stale references, not solver
  or model behavior.

## Deliverable

A short summary (not a new doc file) of: what was deleted, what was moved and to where, what was
fixed in `requirements.txt`/comments, and an explicit list of the §4 items that need the user's
decision before further action — with your recommendation for each, not just the question.
