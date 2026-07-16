"""Seed and solver-tolerance grids for the robustness checks (Family F, RQ6)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToleranceSetting:
    label: str
    mip_gap: float
    dbp_relative_gap: float


# Centered on the project default (1e-2/1e-2, aligned with Tautenhain et al. (2021)'s explicit
# CPLEX 1% stopping criterion, 2026-07-01); "tight"/"loose" bracket it by an order of magnitude
# each way to test whether RQ3-RQ5 conclusions are an artifact of the solver gap.
TOLERANCE_SETTINGS: tuple[ToleranceSetting, ...] = (
    ToleranceSetting("tight", mip_gap=1e-3, dbp_relative_gap=1e-3),
    ToleranceSetting("default", mip_gap=1e-2, dbp_relative_gap=1e-2),
    ToleranceSetting("loose", mip_gap=1e-1, dbp_relative_gap=1e-1),
)


def seed_grid(n_seeds: int = 4, *, seed_base: int = 0) -> list[int]:
    """`n_seeds` additional seeds (the base instance itself, seed_base, is run 0 elsewhere)."""
    return [seed_base + offset for offset in range(1, n_seeds + 1)]
