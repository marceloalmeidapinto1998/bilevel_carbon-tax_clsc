"""Resolution-IV two-level fractional factorial design via fold-over of a resolution-III base.

Construction (Montgomery, *Design and Analysis of Experiments*, ch. 8.4 "Resolution III and
Fold-Over Designs"; Box, Hunter & Hunter, *Statistics for Experimenters*):

1. Pick `k0 = ceil(log2(k + 1))` "basic" factors and lay out their full 2^k0 factorial
   (the smallest power-of-two design that *could* accommodate k factors at all).
2. Assign each remaining factor to a distinct generalized interaction (product) of the basic
   columns — by construction no two main-effect columns coincide, so the base design has
   resolution >= III (main effects are clear of each other, but some are aliased with a
   two-factor interaction among the basic columns).
3. Fold over: append the same design with every sign reversed. The classical fold-over
   theorem says reversing all factor signs de-aliases every main effect from every two-factor
   interaction, raising the resolution from III to >= IV. This doubles the run count
   (2^(k0+1) runs total) but needs no generator-word lookup table, which keeps the
   construction exact and easy to verify for an arbitrary factor count.

This is deliberately simpler than chasing a minimum-aberration design from a table (e.g. a
2^(8-4) design) — both are resolution IV, and the fold-over result is provably so rather than
asserted from a lookup table, which makes it easier to defend in the paper (Family C, RQ3/RQ6).
"""
from __future__ import annotations

import itertools
import math

# Minimum-aberration resolution-V generators, keyed by factor count. `k0` basic factors get a full
# 2^k0 factorial; each remaining factor (by position, after the first k0) is the product of the
# basic columns at the given positions. Defining words all have length >= 5, so every main effect
# and every two-factor interaction is estimable free of the others (Montgomery ch. 8).
#   8 factors -> 2^(8-2)_V: basic positions 0-5 (64 runs); pos6=product(0,1,2,3), pos7=product(0,1,4,5).
#   5 factors -> 2^(5-1)_V: basic positions 0-3 (16 runs); pos4=product(0,1,2,3).
_RESOLUTION_V_GENERATORS: dict[int, dict[str, object]] = {
    5: {"k0": 4, "extra": ((0, 1, 2, 3),)},
    8: {"k0": 6, "extra": ((0, 1, 2, 3), (0, 1, 4, 5))},
}


def resolution_v_signs(factor_names: tuple[str, ...]) -> list[dict[str, int]]:
    """Resolution-V two-level fractional factorial over `factor_names` (5 or 8 factors).

    Returns one +-1 dict per run. Unlike `fractional_factorial_signs` (fold-over, resolution IV),
    this uses explicit minimum-aberration generators (assigned positionally) so all two-factor
    interactions are estimable (required for Experiment 6's interaction hypothesis H6.1).
    """
    k = len(factor_names)
    if k not in _RESOLUTION_V_GENERATORS:
        raise ValueError(
            f"No resolution-V generator table entry for k={k} factors "
            f"(have {sorted(_RESOLUTION_V_GENERATORS)}); add its minimum-aberration generators."
        )
    entry = _RESOLUTION_V_GENERATORS[k]
    k0 = int(entry["k0"])
    extra_generators = entry["extra"]
    if len(extra_generators) != k - k0:
        raise ValueError(f"Generator table for k={k} is inconsistent (k0={k0}, extra={len(extra_generators)})")
    basic_names = factor_names[:k0]
    extra_names = factor_names[k0:]

    design: list[dict[str, int]] = []
    for run in itertools.product((-1, 1), repeat=k0):
        row: dict[str, int] = dict(zip(basic_names, run))
        for name, generator in zip(extra_names, extra_generators):
            product = 1
            for index in generator:
                product *= run[index]
            row[name] = product
        design.append(row)
    return design


def _generalized_interaction_columns(k0: int) -> list[tuple[int, ...]]:
    """All non-empty subsets of {0..k0-1} of size >= 2, ordered by size then lexicographically.

    Each subset denotes a generalized interaction column (product of those basic columns).
    """
    columns: list[tuple[int, ...]] = []
    for size in range(2, k0 + 1):
        columns.extend(itertools.combinations(range(k0), size))
    return columns


def fractional_factorial_signs(factor_names: tuple[str, ...]) -> list[dict[str, int]]:
    """Resolution->=IV two-level design over `factor_names`. Returns one dict per run, +-1 levels."""
    k = len(factor_names)
    if k < 2:
        raise ValueError("Need at least 2 factors for a fractional factorial design")

    k0 = max(2, math.ceil(math.log2(k + 1)))
    n_extra = k - k0
    generators = _generalized_interaction_columns(k0)
    if n_extra > len(generators):
        # k0 too small to generate enough extra columns (shouldn't happen given the k0 formula,
        # but fall back to growing k0 rather than raising).
        k0 += 1
        generators = _generalized_interaction_columns(k0)
        n_extra = k - k0

    basic_names = factor_names[:k0]
    extra_names = factor_names[k0:]
    extra_generators = generators[:n_extra]

    base_runs = list(itertools.product((-1, 1), repeat=k0))

    design: list[dict[str, int]] = []
    for fold_sign in (1, -1):  # fold-over: identical base design with every sign reversed
        for run in base_runs:
            row: dict[str, int] = {
                name: fold_sign * level for name, level in zip(basic_names, run)
            }
            for name, generator in zip(extra_names, extra_generators):
                product = 1
                for index in generator:
                    product *= run[index]
                row[name] = fold_sign * product
            design.append(row)
    return design
