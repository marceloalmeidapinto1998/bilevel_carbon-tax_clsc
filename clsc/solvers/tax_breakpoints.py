"""PROTOTYPE: continuous carbon-tax optimum via breakpoint tracing.

No relaxation master, no grid, no bilinear linearisation -- only the follower
MILP, solved at a handful of tax rates chosen by parametric (dichotomic)
search. Exploits the structure directly: the optimistic follower response
emissions(z*(tau)) is a piecewise-constant, non-increasing staircase in tau
(finitely many MILP configurations); each configuration z is a line
cost(z) + tau*emissions(z) in tau, and the follower value is their lower
envelope. Two adjacent configurations A, B swap at the exact tie tau
    tau* = (c_B - c_A) / (e_A - e_B),
computed by exact arithmetic from genuine follower solutions -- no relaxation.

Algorithm (Aneja-Nair / Cohon dichotomic search for the supported points of a
bi-objective MILP), specialised to the leader's min-emissions objective:
  1. solve follower at tau_min -> dirtiest config; at tau_max -> cleanest.
  2. between two known adjacent configs, probe the tie tau; if the follower
     returns a strictly-better (lower weighted-objective) config, it is a new
     supported point -> recurse on both sides; else the two are adjacent and
     the tie tau is an exact breakpoint.
Terminates in O(#breakpoints) follower solves (a handful), each a normal MILP.

The leader (min emissions, then min tax) optimum is then read off directly:
the cleanest config occupies [last_breakpoint, tau_max]; the smallest tax
achieving the minimum emissions is that last breakpoint.

Runs entirely alongside dbp_lex; touches no other solver state.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from clsc.config.gap_tol import DEFAULT
from clsc.models.instance import InstanceData
from clsc.models.subproblems import (
    SolveResult,
    build_fixed_tax_follower_master,
    solve_fixed_rate_lexicographic,
)


@dataclass(frozen=True, slots=True)
class SupportedConfig:
    """A follower configuration optimal over a contiguous tax interval."""
    tax_lo: float          # left edge of this config's optimality interval (USD/kg)
    tax_hi: float          # right edge
    cost: float
    emissions: float


@dataclass(frozen=True, slots=True)
class TaxBreakpointResult:
    segments: tuple[SupportedConfig, ...]   # sorted by tax ascending (emissions descending)
    breakpoints: tuple[float, ...]          # interior tie taus (USD/kg), ascending
    leader_tax: float                       # smallest tax achieving min emissions (USD/kg)
    leader_emissions: float
    leader_cost: float
    follower_solves: int
    total_seconds: float
    leader_solution: SolveResult | None = None


@dataclass
class _Point:
    tax_probe: float
    cost: float
    emissions: float
    solution: SolveResult


def _tie_tax(dirty: _Point, clean: _Point) -> float:
    # cost_dirty + tau*e_dirty == cost_clean + tau*e_clean, with e_dirty > e_clean
    return (clean.cost - dirty.cost) / (dirty.emissions - clean.emissions)


def solve_tax_breakpoints(
    instance_or_path: InstanceData | str | Path,
    *,
    output_flag: bool = False,
    time_limit: float | None = None,
    follower_mip_gap: float | None = 1e-6,
    threads: int | None = None,
    mip_focus: int | None = None,
    max_configs: int = 64,
    emissions_tie_rel: float = 1e-6,
) -> TaxBreakpointResult:
    """Trace the follower's cost/emissions staircase over [underline_tau, overline_tau]
    and return the leader's (min-emissions, then min-tax) optimum plus every breakpoint."""
    instance = (
        instance_or_path
        if isinstance(instance_or_path, InstanceData)
        else InstanceData.from_file(instance_or_path)
    )
    tau_lo = float(instance.parameters["underline_tau"])
    tau_hi = float(instance.parameters["overline_tau"])

    follower_master = build_fixed_tax_follower_master(instance)
    solves = 0
    warm: dict[str, float] | None = None

    started = time.perf_counter()

    def solve(tau: float) -> _Point:
        nonlocal solves, warm
        result = solve_fixed_rate_lexicographic(
            follower_master, tau,
            output_flag=output_flag, time_limit=time_limit,
            capture_solution=True, warm_start_values=warm,
            mip_gap=follower_mip_gap, threads=threads, mip_focus=mip_focus,
        )
        solves += 1
        if not result.has_solution or result.status_name != "OPTIMAL":
            raise RuntimeError(f"follower at tau={tau:.6g} not OPTIMAL (status={result.status_name})")
        if result.variable_values is not None:
            warm = result.variable_values
        return _Point(tau, float(result.cost), float(result.emissions), result)

    low = solve(tau_lo)    # dirtiest (highest emissions) at the lowest tax
    high = solve(tau_hi)   # cleanest (lowest emissions) at the highest tax

    # Collect supported configs keyed by emissions (deduplicated). Every probe
    # returns a genuine follower point; the dichotomic recursion guarantees we
    # discover all supported points between the two anchors.
    points: dict[float, _Point] = {}

    def register(p: _Point) -> None:
        points[round(p.emissions, 3)] = p

    register(low)
    register(high)

    def tie_tol(weighted: float) -> float:
        return max(DEFAULT.eps, emissions_tie_rel * abs(weighted))

    # Explicit stack of (dirty, clean) adjacent-candidate pairs.
    stack: list[tuple[_Point, _Point]] = [(low, high)]
    while stack:
        if len(points) > max_configs:
            break
        dirty, clean = stack.pop()
        if dirty.emissions - clean.emissions <= tie_tol(dirty.emissions):
            continue  # same emissions plateau -> no interior breakpoint
        tau_star = _tie_tax(dirty, clean)
        if not (tau_lo < tau_star < tau_hi):
            continue
        probe = solve(tau_star)
        weighted_line = dirty.cost + tau_star * dirty.emissions  # == clean side too
        weighted_probe = probe.cost + tau_star * probe.emissions
        if weighted_probe < weighted_line - tie_tol(weighted_line):
            # Strictly below the dirty-clean line: a NEW supported config.
            register(probe)
            stack.append((dirty, probe))
            stack.append((probe, clean))
        # else: dirty & clean are adjacent; tau_star is their exact breakpoint.

    # Assemble segments sorted by emissions descending (== tax ascending).
    ordered = sorted(points.values(), key=lambda p: p.emissions, reverse=True)
    interior_breakpoints: list[float] = []
    for i in range(len(ordered) - 1):
        interior_breakpoints.append(_tie_tax(ordered[i], ordered[i + 1]))

    segments: list[SupportedConfig] = []
    edges = [tau_lo, *interior_breakpoints, tau_hi]
    for i, p in enumerate(ordered):
        segments.append(SupportedConfig(
            tax_lo=edges[i], tax_hi=edges[i + 1], cost=p.cost, emissions=p.emissions,
        ))

    # Leader optimum: cleanest config (min emissions) = last segment; the
    # smallest tax achieving it is that segment's left edge.
    cleanest = ordered[-1]
    leader_tax = segments[-1].tax_lo
    total = time.perf_counter() - started
    return TaxBreakpointResult(
        segments=tuple(segments),
        breakpoints=tuple(interior_breakpoints),
        leader_tax=leader_tax,
        leader_emissions=cleanest.emissions,
        leader_cost=cleanest.cost,
        follower_solves=solves,
        total_seconds=round(total, 4),
        leader_solution=cleanest.solution,
    )
