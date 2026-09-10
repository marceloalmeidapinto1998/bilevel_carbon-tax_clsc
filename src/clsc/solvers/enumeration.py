"""Exhaustive grid enumeration: the naive exact baseline DBP is benchmarked against (Exp8).

The leader controls one integer on a finite grid, so solving the follower's lexicographic problem
at EVERY grid point is exact by construction -- no cuts, no relaxation master, no theory beyond
"try them all". It needs no new proof of correctness; it exists to answer the question DBP's own
optimality certificate cannot: is the decomposition worth having?

Fair comparison with DBP requires solving the SAME sub-problem DBP solves at each point
(`solve_follower_lexicographic`, the two-stage min-cost-then-min-emissions follower), with the
same warm-start discipline, under the same wall-clock budget mechanics as
:class:`clsc.solvers.dbp_lex._WallClockBudget`. Scanning ascending tax index exploits the same
non-increasing-emissions invariant DBP's own structural checks rely on (H1.3) only to report
emissions monotonically improving as evidence corroborating that invariant -- the (E*, tau*)
selected is still the true argmin/argmin-tax over every point actually visited, not an assumption.

Incumbent selection uses a loose tie tolerance (``PLATEAU_RELATIVE_GAP = 1e-4``, i.e. the
campaign's ``dbp_relative_gap`` / plateau tolerance from Experimental_Plan.md §4), NOT the tight
machine-precision tolerance DBP's main loop uses for its own few-iteration comparisons. A first
implementation reused the main-loop comparator and it broke silently on I17-M4-T6: 737
near-identical follower solves after the true left edge (tax_index 1264) each carry a few units of
Gurobi solve-to-solve noise (~1e-8 relative), which the tight tolerance misread as a sequence of
genuine improvements, walking the reported incumbent out to tax_index 1903 -- a 0,00001%
"improvement" in emissions bought a 51% inflation of the reported tax. DBP's own use_tax_confirmation
never hits this failure mode because it only ever compares candidates the master's Stage-2 itself
proposed as ties -- far less exposure to cumulative noise than visiting every grid point. That
asymmetry is itself a real, citable robustness advantage for DBP over brute-force enumeration on
long grids, independent of the already-large speed advantage.
"""
from __future__ import annotations

from dataclasses import dataclass

from clsc.config.gap_tol import DEFAULT
from clsc.models.instance import InstanceData
from clsc.models.subproblems import FollowerMaster, SolveResult, solve_follower_lexicographic
from clsc.solvers.dbp_lex import IncumbentSolution, SubproblemStatusError, _required_value, _WallClockBudget

PLATEAU_RELATIVE_GAP = 1e-4  # matches the campaign's dbp_relative_gap / plateau convention


def _is_better_on_plateau(
    candidate: IncumbentSolution, incumbent: IncumbentSolution | None, *, relative_gap: float,
) -> bool:
    """lexmin(emissions, tax_index), with a tie tolerance sized for a long ascending scan.

    ``tol = max(eps, relative_gap * |e_star|)``, looser than the main DBP loop's
    near-machine-precision comparator -- see the module docstring for why that
    distinction matters here specifically.
    """
    if incumbent is None:
        return True
    tolerance = max(DEFAULT.eps, relative_gap * abs(incumbent.emissions))
    if candidate.emissions < incumbent.emissions - tolerance:
        return True
    if abs(candidate.emissions - incumbent.emissions) <= tolerance:
        return candidate.tax_index < incumbent.tax_index
    return False


@dataclass(frozen=True, slots=True)
class GridPointRecord:
    tax_index: int
    emissions: float
    cost: float
    solve_seconds: float


@dataclass(frozen=True, slots=True)
class EnumerationResult:
    incumbent: IncumbentSolution
    incumbent_solution: SolveResult | None
    termination_reason: str  # "exhausted" (every grid point visited) or "wall_clock_cap"
    exact: bool              # True only if "exhausted": every point on the grid was checked
    points_visited: int
    points_total: int
    follower_seconds_total: float
    grid_records: tuple[GridPointRecord, ...]


def enumerate_tax_grid(
    instance_or_master: InstanceData | FollowerMaster,
    instance: InstanceData,
    *,
    time_limit: float | None = None,
    wall_clock_cap: float | None = None,
    mip_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
    seed: int | None = None,
    use_warm_start: bool = True,
    plateau_relative_gap: float = PLATEAU_RELATIVE_GAP,
) -> EnumerationResult:
    """Solve the fixed-tax lexicographic follower at every grid point in ``instance``'s tax range.

    ``instance_or_master`` may be a pre-built :class:`FollowerMaster` (reused across calls,
    mirroring DBP's own follower-master reuse) or the bare instance; ``instance`` is always the
    plain :class:`InstanceData`, needed for its tax-scale bounds regardless of which form the solve
    target takes. ``plateau_relative_gap`` is the tie tolerance for incumbent selection -- see the
    module docstring; the default matches DBP's own Phase-2 bisection and the campaign's plateau
    definition, so both methods report tau* on the same footing.
    """
    grid = list(instance.iter_tax_index())
    budget = _WallClockBudget(wall_clock_cap, time_limit)

    incumbent: IncumbentSolution | None = None
    incumbent_solution: SolveResult | None = None
    warm: dict[str, float] | None = None
    records: list[GridPointRecord] = []
    follower_seconds_total = 0.0

    for tax_index in grid:
        if budget.expired():
            break

        result = solve_follower_lexicographic(
            instance_or_master,
            tax_index=tax_index,
            time_limit=budget.subproblem_time_limit(),
            capture_solution=True,
            warm_start_values=warm if use_warm_start else None,
            mip_gap=mip_gap,
            threads=threads,
            mip_focus=mip_focus,
            seed=seed,
        )
        if not result.has_solution or result.status_name not in ("OPTIMAL", "TIME_LIMIT"):
            raise SubproblemStatusError(f"enumeration follower solve at tax_index={tax_index}", result)
        if result.status_name == "TIME_LIMIT":
            # This grid point itself didn't finish within its clamped share of the budget --
            # stop the scan here rather than accept a possibly-suboptimal follower solution as
            # a grid-point "result" (that would corrupt the argmin the baseline exists to certify).
            break

        follower_seconds_total += result.runtime or 0.0
        if result.variable_values is not None:
            warm = result.variable_values

        candidate = IncumbentSolution(
            tax_index=tax_index,
            cost=_required_value(result.cost, "enumeration cost"),
            emissions=_required_value(result.emissions, "enumeration emissions"),
            follower_objective=_required_value(result.follower_objective, "enumeration follower objective"),
            scale_factor=instance.scale_factor,
        )
        records.append(GridPointRecord(
            tax_index=tax_index, emissions=candidate.emissions, cost=candidate.cost,
            solve_seconds=result.runtime or 0.0,
        ))
        if _is_better_on_plateau(candidate, incumbent, relative_gap=plateau_relative_gap):
            incumbent = candidate
            incumbent_solution = result

    if incumbent is None:
        raise SubproblemStatusError(
            "enumeration produced no grid point before its budget expired",
            SolveResult(
                status_code=-1, status_name="TIME_LIMIT", has_solution=False,
                objective_value=None, cost=None, emissions=None, follower_objective=None,
                tax_index=None, mip_gap=None, runtime=0.0,
            ),
        )

    exhausted = len(records) == len(grid)
    return EnumerationResult(
        incumbent=incumbent,
        incumbent_solution=incumbent_solution,
        termination_reason="optimal_exhaustive" if exhausted else "incumbent_wall_clock_cap",
        exact=exhausted,
        points_visited=len(records),
        points_total=len(grid),
        follower_seconds_total=follower_seconds_total,
        grid_records=tuple(records),
    )
