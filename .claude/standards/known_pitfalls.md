# STANDARD — Known pitfalls

Every entry here has already cost this project real time or produced a wrong published number.
Read before any analysis task. Sources: `docs/prompt_analise_campaign_01.md`,
`docs/Experimental_Plan.md` §3/§7/§10/§11.2, and the 2026-08-03 repository mapping.

---

## P1 — Two tax grids exist. Never recompute USD/t from a constant.

There are two grids over the *same real range* 0–200 USD/t:

| Grid | Step (USD/kg per index) | Index range | Used by |
|---|---|---|---|
| Fine (campaign) | `1e-4` | 0…2000 | everything except exp3 variant A4 |
| Coarse (instance-native) | `1e-2` | 0…20 | exp3 A4 only; also `models/instance.py::SCALE_FACTOR` |

A tax **index** is meaningless across grids — index 20 is 2 USD/t on the fine grid and 200 USD/t
on the coarse one.

**Rule**: always read `leader_tax_usd_per_tonne` from the master table. Never multiply
`leader_tax_index` by `SCALE_FACTOR` or by any hard-coded step. The aggregator derives the rate
from each run's own recorded `tax_grid_step_usd_per_kg`, with a documented fallback to the run's
`summary.json` for pre-fix manifests.

**Report in rates, never indices.**

## P2 — `censored` does not mean "no valid value"

Since the wall-clock enforcement fix, the cap is applied *inside* the solver: it clamps each
subproblem to the remaining budget and stops the loop between iterations, **returning the
incumbent, its variable values, and a certified gap**.

| `termination_reason` | Usable? |
|---|---|
| `relative_gap` | yes — E0, certified |
| `wall_clock_cap` | **yes** — real incumbent + certified gap; report as censored with its gap |
| `wall_clock_cap_killed` | no — subprocess backstop, results lost |
| `stagnation_limit_gap_not_closed` | partially — incumbent exists, gap not closed; treat as censored |

**Rule**: branch on `termination_reason`, never on `solve_status` alone. Examples that matter:
exp4's M12 probe (0.96 % gap, real incumbent — anchors the scalability frontier statement) and
exp8's two censored cells (one still agreed exactly with DBP because τ\* sat early in the scan).

## P3 — Some manifests were corrected post-hoc, legitimately

`results/.../exp8_benchmark/STD_I17_M4_T6/` was patched by
`scripts/recompute_enumeration_incumbent.py` after a real tie-tolerance bug in
`enumeration.py` was found and fixed. Its JSON carries a `_correction` field.

**Rule**: a `_correction` field is a documented amendment, not an anomaly to investigate. Read the
field, cite it, move on. Do *not* "restore" it, and do not treat the corrected run as suspect.

Background worth knowing (it is a citable result, `Experimental_Plan.md` §7): the bug was that a
2001-point linear scan reused DBP's near-machine-precision tie tolerance (1e-7), so accumulated
Gurobi solve-to-solve noise (~1e-8 relative) read as a chain of genuine improvements and walked
the reported incumbent from index 1264 to 1903 — a 0.00001 % emissions "improvement" inflating the
reported tax by 51 %. Fixed by using the plateau tolerance (1e-4). DBP's Phase-2 bisection is
immune because it visits O(log n) points, not O(n).

## P4 — Seed variance is structural, not noise

Cross-seed coefficient of variation reaches 40–50 % on the same structural cell. On I25-M8-T3, E\*
across seeds 0/1/2 is 1.42 / 1.14 / 0.70 ×10⁸.

**Rules**:
- No claim from a single seed on a standard or fast cell.
- All cross-condition comparisons are **paired within seed**.
- Hard-tier cells run at seed 0 with one seed-1 spot-check; report them per-cell, never pooled
  with the multi-seed cells as if they had the same support.

## P5 — Statistical volume on hard cells is a design error

exp2 consumed 61.9 h — 62 % of all campaign compute — for one appendix paragraph, because it was
run on the hardest cell, where half the configuration grid cannot converge and therefore carries
no signal. Compare exp5 (the headline result): ~1.3 h.

**Rule**: sweeps, grids, and factorials go on fast cells. Hard cells appear in the scalability
table and nowhere else. Any proposal violating this is rejected at Project Manager review with a
pointer to `Experimental_Plan.md` §11.2.

## P6 — The plan document has published wrong numbers about itself

Documented self-corrections in `Experimental_Plan.md`:
- §3 (2026-08-03): stated τ\* median ≈50 USD/t and "already inside the 20–200 policy band". Both
  wrong — actual median 22.6, and only 6 of 12 cells fall in the band.
- §11.1: exp1 invariance probes flagged "must re-run"; on inspection the rates were always correct
  and only the directory naming was stale.
- §10 and §14: tier caps and exp6 run counts were documented as reduced when `_cells.py` and
  `exp6_sensitivity.py` were never changed.

**Rule**: treat every number in that document as E3 until promoted. See
`standards/evidence_and_claims.md` R3.

## P7 — The statistical layer is not in the repository

`Experimental_Plan.md` §2.4 prescribes Wilcoxon, Friedman+Nemenyi, Holm, ANOVA with partial η²,
Lenth, Benjamini–Hochberg, BCa bootstrap. §10 reports results from OLS + Lenth + BH.

No code in `src/`, `scripts/`, or `tests/` implements any of it. `scipy` is importable but
**undeclared** (transitive via SALib); `statsmodels` is absent.

**Rules**:
- Every §10 statistic is E3 and may not enter the paper until re-derived by committed code.
- Declare `scipy` in `pyproject.toml` before depending on it.
- Prefer `numpy.linalg.lstsq` over adding `statsmodels` for saturated ±1 factorial effects.
- The known Lenth-PSE collapse on exp6 seed 1 (PSE ≈302 for emissions, ≈14 for cost, against
  effects in the hundred-thousands, yielding p = 0.0 across the board) is a **sparsity-of-effects
  violation, not a data error**. Do not publish those p-values. The rank-based conclusions (H6.1,
  H6.2) do not depend on Lenth and stand.

## P8 — Duplicated constants must move together

`SCALE_FACTOR` and `PRODUCT_ROTATION_PER_PERIOD` are deliberately duplicated between
`src/clsc/models/instance.py` and the generator, with sync comments, to keep the model layer free
of a generator dependency. Changing one without the other is a silent correctness break. Same
pattern applies to `EMISSIONS_SCALE = 1e6` in `subproblems.py`.

## P9 — Two parallel table families can disagree

`paper/tables/tab_*.tex` are hand-maintained; `results/analysis/campaign_01/tables/t{1..7}_*.tex`
are generated from the master table. They overlap. A number can be right in one and stale in the
other.

**Rule**: the generated family is authoritative. Any hand-maintained table that restates a
generated one is a defect for the Editor to resolve, preferably by `\input`-ing the generated file.
