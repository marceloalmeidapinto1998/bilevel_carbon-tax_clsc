# STANDARD — Statistical practice

Binding on the Statistical Analyst; enforced by the Data Auditor and the Scientific Reviewer.
Derived from `docs/Experimental_Plan.md` §2.4, made operational and reproducible.

---

## 1. The reproducibility requirement (currently unmet — see `known_pitfalls.md` P7)

> **A statistic that no committed script produces does not exist.**

Every test, effect, interval, and p-value reported by this system must be computed by code under
`src/clsc/analysis/` or `scripts/`, deterministic given the master table, and covered by at least
one test in `tests/`.

Target module layout (to be created; none of this exists yet):

```
src/clsc/analysis/stats/
    __init__.py
    descriptive.py     # shifted geometric mean, median, IQR, censoring-aware summaries
    paired.py          # Wilcoxon signed-rank, Friedman + Nemenyi, Holm
    factorial.py       # coded-design effects via lstsq, Lenth PSE, half-normal plot data
    multiplicity.py    # Holm and Benjamini-Hochberg
    resampling.py      # BCa bootstrap for medians and ratios
tests/test_stats_*.py  # against textbook worked examples with known answers
```

Dependency note: declare `scipy>=1.11` in `pyproject.toml` (currently importable but undeclared).
Use `numpy.linalg.lstsq` for factorial effects rather than adding `statsmodels`.

## 2. Descriptive statistics

- **Runtimes**: shifted geometric mean, shift **s = 10 s** (Achterberg 2007):
  `sgm({x_i}, s) = exp(mean(log(x_i + s))) − s`. Report alongside median and IQR, never alone.
- **Censored runs are never imputed.** Report `n_total`, `n_censored`, and the statistic over
  completed runs only, with censoring stated. Where censored runs carry a certified gap
  (`termination_reason="wall_clock_cap"`), report the gap; the incumbent may be used for
  *bounding* statements ("at least", "no worse than"), never for central tendency.
- **Ratios** (burden ratios, speedups) are summarised by the median and a BCa interval, not the
  mean — they are ratio-scale and skewed.

## 3. Paired comparisons

The design is paired by construction: the same instance under different variants/conditions.

| Situation | Test | Post-hoc |
|---|---|---|
| Two conditions | Wilcoxon signed-rank | — |
| ≥3 conditions | Friedman | Nemenyi |

- α = 0.05, **Holm correction within each experiment's family** of comparisons.
- Pairing is **within seed and within cell**. Never pool across seeds before pairing (P4).
- Report the effect size and the n alongside every p. With n = 6 cells, the minimum attainable
  two-sided Wilcoxon p is 0.031 — **state this explicitly** whenever n ≤ 6, because it bounds what
  significance can mean and a referee will notice before you do.
- Where the direction is unanimous (e.g. exp3 A1 fails 6/6), the sign test / unanimity is the
  honest statement and a p-value adds nothing. Say "6/6, unanimous" and give the effect sizes.

## 4. Factorial analysis (exp6)

Design: 2^(8−2) resolution-V fractional factorial, 64 runs per seed, seeds 0 and 1; plus a
2^(5−1) resolution-V structural half-fraction (16 runs, seed 0, cell I17-M4-T3).

**Required checks before any effect is reported:**
1. **Design rank check** — main effects + 2FI model matrix must have rank 37/37. Confirm
   empirically; do not assume it from the generator's construction.
2. **Balance check** — every coded column must be balanced ±1 and orthogonal to the others.
3. **Response completeness** — all 64 runs present and uncensored for the response in question;
   report any missing cell rather than fitting around it.

**Effects**: OLS on coded ±1 factors via `numpy.linalg.lstsq`; report effects (2× coefficients),
partial η², and the ranking.

**Lenth's method** — usable only when its assumption holds. Mandatory guard:

> Compute the PSE. If PSE is implausibly small relative to the effect distribution — operationally,
> if the ratio `max|effect| / PSE` exceeds ~10³, or if the 12 smallest |effects| are not
> concentrated near zero — **Lenth's sparsity-of-effects assumption has failed. Do not report
> Lenth p-values.** Fall back to (a) a half-normal plot read qualitatively, or (b) a bootstrap
> noise estimate.

This guard exists because it already fired: exp6 seed 1 gave PSE ≈ 302 (emissions) and ≈ 14 (cost)
against effects in the hundred-thousands, producing p = 0.0 across the board. Seed 0 and the τ\*
response behaved normally (PSE 0.08–0.47). The published rank-based conclusions do not depend on
Lenth and stand; the p-values must not be published as computed.

**Multiplicity**: Benjamini–Hochberg across responses within a seed; state the FDR level.

**Seed stability**: report top-k rank agreement across seeds explicitly as a fraction (e.g.
"emissions 3/3 identical, cost 2/3, τ\* 2/3"), not as a single "stable/unstable" verdict.

## 5. Confidence intervals

BCa bootstrap, **10 000 resamples**, fixed RNG seed recorded in the output. Applies to medians,
ratios, and effect sizes. With n = 12 cells a BCa interval is wide — report it anyway; a wide
honest interval is a result, and suppressing it is not.

## 6. What this project may not do

- **No OLS of log τ\* on log ρ.** H7.1's premise (smooth log-linear response) is rejected by the
  data — τ\*(ρ) is certified non-monotone (1→8.0; 5→1.6; 10→189.1; 20→94.6; 50→100.9; 100→180.1;
  200→87.7 USD/t, all with gaps ≤ 1e-4). Fitting a model whose premise the data rejects
  misrepresents it. The regime-split description stands in its place.
- **No imputation of censored runtimes.**
- **No pooling across seeds before pairing.**
- **No claim from n = 1** beyond "observed on one cell", explicitly scoped.
- **No p-value without n and effect size.**
- **No significance claim from a design whose rank/balance was not checked.**

## 7. Reporting template for any test

```
Test:        Wilcoxon signed-rank (two-sided)
Hypothesis:  H3.1 — A1 (no Phase-2) loses tau*-minimality vs M0
Pairing:     within (cell, seed); n = 6 cells, seed 0
Data:        master_runs_campaign_01.csv :: experiment_id=exp3_ablation,
             algorithm_variant in {M0, A1}, seed_offset=0
Result:      W = ..., p = ..., Holm-adjusted p = ...
Effect:      median tau* ratio A1/M0 = ...x  [BCa 95% CI ..., ...]
n floor:     with n=6 the minimum attainable two-sided p is 0.031
Direction:   6/6 unanimous
Computed by: src/clsc/analysis/stats/paired.py::wilcoxon_by_cell (commit <sha>)
Status:      SUPPORTED
```
