# STANDARD — Numerical, solver, and optimization claims

Binding on the Optimization Expert and the Mathematical Model Expert; enforced by the Reviewer.

---

## 1. Vocabulary — use these words precisely

| Word | Means | Does **not** mean |
|---|---|---|
| **exact** | the method is exact *by construction* (DBP with closed gap; enumeration that exhausted the grid) | "the answer is right" |
| **certified** | this run closed its gap: `termination_reason="relative_gap"`, `relative_gap ≤ 1e-4` | "optimal to machine precision" |
| **censored** | stopped by a budget cap; incumbent and gap survive (`wall_clock_cap`) | "failed" |
| **optimal** | attains the true optimum | reserve for E0 evidence; otherwise say "incumbent" |
| **converged** | gap closed to tolerance | "stopped" |
| **infeasible** | proven infeasible by the solver | "no solution found" |

Never write "the solver found the optimal solution" for a censored run. Write "incumbent at a
certified 0.96 % gap".

## 2. Tolerances — the campaign configuration

| Parameter | Campaign value | Where |
|---|---|---|
| `dbp_relative_gap` | 1e-4 | orchestrator / CLI per-run override |
| follower `mip_gap` | 1e-6 | ditto |
| Phase-2 min-tax bisection | ON | `refine_min_tax` |
| `threads` | 4 | fixed by exp2 |
| `MIPFocus` | 2 | fixed by exp2 (decisive: all focus-2 configs converged, 5 of 6 others censored) |
| Plateau tolerance δ | = `dbp_relative_gap` = 1e-4 | defines P = {τ : E(τ) ≤ E\*(1+δ)} |
| Enumeration tie tolerance | `_REFINE_TIE_REL = 1e-4` | `enumeration.py::PLATEAU_RELATIVE_GAP` |
| Neutral fallback (coarse) | 1 % | `clsc.config.gap_tol.DEFAULT` — **only** when no override given |

Time budgets (`designs/_cells.py`): standard tier 3 600 s per sub-MILP / 28 800 s wall;
hard tier 10 800 s / 50 400 s. Enforced **inside** the solver; a subprocess kill with 900 s grace
is a logged backstop only (`wall_clock_cap_killed`).

**Rule**: any analysis comparing runs must confirm they share tolerances and grid. A comparison
across different `tax_grid_scale_factor` values is invalid unless expressed in rates (P1).

## 3. Tolerance-scale discipline

The exp8 bug is the standing lesson: **a tolerance appropriate for O(log n) probes is wrong for an
O(n) scan.** Accumulated solve-to-solve noise (~1e-8 relative) over 737 consecutive solves read as
a chain of improvements under a 1e-7 comparator.

**Rule**: whenever a comparator is applied along a sequence of solves, state the sequence length
and check that the tolerance dominates `sqrt(length) ×` the per-solve noise scale. Report the
per-solve noise empirically (exp8 measured std ≈ 2 on emissions ≈ 9×10⁷) rather than assuming it.

## 4. Claims about the algorithm

A claim that DBP is *better* requires all three, separately:

1. **Correctness** — the certificate. DBP's LB/UB convergence. (exp1, exp3)
2. **A baseline** — versus the obvious exact alternative a referee will propose. Grid enumeration
   is exact by construction here because the leader controls one integer on a finite grid. (exp8)
3. **A cost metric that is not wall-clock alone** — follower-solve counts are the
   machine-independent measure. exp8: ~11 vs 2001 and ~15 vs 2001 follower solves (≈180× and
   ≈130×). Wall-clock corroborates; solve counts are the citable number.

Positioning requirement (no runs, but mandatory in the paper): DBP must be placed against exact
MIBLP methods — Fischetti et al. (2017) intersection cuts, MibS (Tahernejad & Ralphs), Moore &
Bard (1990) — not only against Benders-family decomposition.

## 5. Scalability claims

- Growth in T is **non-monotone** and must be reported as such, not smoothed: I17-M8-T6 (2.6 h)
  exceeds both T12 cells at the same M (0.69 h, 1.36 h).
- A censored probe anchors a frontier statement but does not resolve it. Correct form:
  *"exact up to M8 within hard-tier limits; M12 is 0.96 %-gap censored, not exact, at the same
  limits"*. Incorrect: *"tractable up to M8"*.
- Never extrapolate a growth exponent from 12 cells spanning 2×2×3.

## 6. Model-code correspondence

`src/clsc/models/subproblems.py` and `paper/sections/04c_follower.tex` are independent statements
of the same model. Standing requirements:

- Every constraint block in the LaTeX has a locatable counterpart in the builder, and vice versa.
- Every symbol in `paper/tables/tab_notation.tex` matches the parameter name and **unit** in
  `src/clsc/models/instance.py`.
- Unit conversions are explicit and single-sourced: `EMISSIONS_SCALE = 1e6` (kg → kt),
  `SCALE_FACTOR = 0.01` USD/kg per index, `PRODUCT_ROTATION_PER_PERIOD = 4.5`. The last two are
  deliberately duplicated between model and generator with sync comments (P8).
- The published pseudocode (`paper/algorithms/*.tex`) must match `solvers/dbp_lex.py` step for
  step, including the Phase-2 bisection and the incumbent cut.

A discrepancy is a `DEFECT`, severity **blocker** if it affects a number in the paper, **major**
otherwise. The code is what produced the results; the LaTeX is what referees check. Both get fixed.

## 7. Ablation semantics (exp3)

| Variant | Removes |
|---|---|
| M0 | — (full method) |
| A1 | Phase-2 min-tax bisection |
| A2 | lexicographic Stage-2 master |
| A3 | warm start |
| A4 | fine grid (uses coarse grid) |
| A5 | incumbent objective-upper-bound cut |

Interpretation rules:
- A1 and A4 being *faster* than M0 is expected — they are cheaper searches by construction. Speed
  is not evidence they are better; the loss of τ\*-minimality (A1) and aliasing bias (A4) is the
  finding.
- A2/A3/A5 leaving (E\*, τ\*) unchanged is a **correct** result: they are efficiency components,
  not correctness components. A5 being 11–13 % slower than M0 is the cut doing its job.
- Never report an ablation without stating which cells and how many.

## 8. Known open numerical issue — do not paper over

exp5 H5.3: on the two hardest cells an independent **cold** fixed-tax follower solve does not
reproduce E\* at DBP's τ\* — I17-M8-T6 +0.035 %, I25-M8-T6 +0.113 %, both above the 1e-4 plateau
tolerance, so not rounding. Hypothesised mechanism: DBP's Phase-2 warm-starts each bisection probe
from an incumbent already achieving E\*, and Stage-2 emissions minimisation runs inside a freeze
tolerance sized by the Stage-1 gap; a cold solve explores a different frozen band.

**This is a stated precision bound on τ\* for hard cells.** It must appear as such in the paper. It
does not touch the headline claim (the plateau is still 30–190 USD/t wide on those cells, burden
ratios unaffected). The mechanism is **hypothesised, not proven** — E4 — and must be labelled that
way until someone instruments the freeze band.
