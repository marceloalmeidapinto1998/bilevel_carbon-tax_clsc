"""Exact alternatives to the DBP for a single tax: enumerating the break points of the follower's value
function, and a grid over the tax range.

With one tax, the follower's value ``phi(tau) = min_y c(y) + tau * beta(y) / 1000`` is the lower envelope of
finitely many lines, and an optimal tax lies at the lower end of the range or at a break point of that
envelope (Proposition 1 of the paper). The dichotomic scheme of Aneja and Nair (1979) finds every line that
is optimal somewhere in ``[tau_min, tau_max]``: solve the follower at both ends, solve it again where the two
lines cross, and recurse on both halves until no new line appears. Each solve is the same two-stage
optimistic solve the DBP uses (P3, then P4), so the leader's value at a candidate tax, ``E + w * tau``, is the
one the DBP's upper bound would record there. The weight ``w`` is set exactly as in the DBP, from the dual
bound of the HPR without the tax term.

A line is identified by the cost and the tax base of the cost-optimal response, which every optimal
response on an open interval between break points shares. Two lines are the same when both differ by at
most the follower's MIP gap, and a crossing yields no new line when the follower's value there is not
below the two lines by more than that gap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
import time

from clsc.config.defaults import DEFAULT
from clsc.models.follower import build_follower_model, solve_follower_lexicographic
from clsc.models.gurobi_utils import SolveResult
from clsc.models.hpr import build_hpr, solve_hpr
from clsc.models.instance_data import InstanceData
from .dbp import _coerce_instance

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TaxEvaluation:
    """The optimistic response at one tax: the follower's two-stage solve."""

    tax: float
    cost: float
    tax_base: float
    emissions: float
    follower_objective: float
    leader_objective: float
    solved: bool  # both stages reached their MIP gap
    seconds: float


@dataclass(slots=True)
class EnumerationResult:
    """Every tax evaluated, the break points found and the best candidate."""

    method: str  # "enumeration" or "grid"
    tax_weight_per_eur_t: float
    reference_emissions: float
    evaluations: list[TaxEvaluation] = field(default_factory=list)
    break_points: list[float] = field(default_factory=list)
    candidates: list[TaxEvaluation] = field(default_factory=list)
    best: TaxEvaluation | None = None
    complete: bool = False  # the search ended on its own rather than on the budget
    certified: bool = False  # complete, and every follower solve reached its MIP gap
    seconds: float = 0.0
    scale_seconds: float = 0.0

    @property
    def follower_solves(self) -> int:
        return len(self.evaluations)


class _Search:
    def __init__(
        self,
        instance: InstanceData,
        *,
        time_limit: float,
        mip_gap: float | None,
        threads: int | None,
        mip_focus: int | None,
        seed: int | None,
        run_time_limit: float | None,
        leader_tax_weight_relative: float,
        output_flag: bool,
    ) -> None:
        self.instance = instance
        self.time_limit = time_limit
        self.mip_gap = DEFAULT.mip_gap if mip_gap is None else mip_gap
        self.solver_options = dict(threads=threads, mip_focus=mip_focus, seed=seed, output_flag=output_flag)
        self.started_at = time.perf_counter()
        self.deadline = None if run_time_limit is None else self.started_at + run_time_limit
        self.follower_model = build_follower_model(instance)
        self.weight, self.reference_emissions, self.scale_seconds = self._tax_weight(leader_tax_weight_relative)
        self.evaluations: list[TaxEvaluation] = []
        self.out_of_budget = False

    def _tax_weight(self, relative: float) -> tuple[float, float, float]:
        """w = q * E_ref, with E_ref the dual bound of the HPR without the tax term, as in the DBP."""
        started = time.perf_counter()
        hpr = build_hpr(self.instance)
        result = solve_hpr(hpr, time_limit=self.limit(), mip_gap=self.mip_gap, **self.solver_options)
        if result.emissions is None:
            raise RuntimeError(f"the reference relaxation returned no bound (status {result.status_name})")
        reference = float(result.emissions)
        return relative * reference, reference, time.perf_counter() - started

    def limit(self) -> float:
        if self.deadline is None:
            return self.time_limit
        return max(min(self.time_limit, self.deadline - time.perf_counter()), 0.001)

    def budget_spent(self) -> bool:
        return self.deadline is not None and time.perf_counter() >= self.deadline

    def evaluate(self, tax: float) -> TaxEvaluation:
        started = time.perf_counter()
        result: SolveResult = solve_follower_lexicographic(
            self.follower_model, tax, time_limit=self.limit(), mip_gap=self.mip_gap, **self.solver_options
        )
        if not result.has_solution:
            raise RuntimeError(f"the follower returned no response at tax {tax} (status {result.status_name})")
        evaluation = TaxEvaluation(
            tax=tax,
            cost=float(result.cost),
            tax_base=float(result.tax_base if result.tax_base is not None else result.emissions),
            emissions=float(result.emissions),
            follower_objective=float(result.follower_objective),
            leader_objective=float(result.emissions) + self.weight * tax,
            solved=result.status_name == "OPTIMAL",
            seconds=time.perf_counter() - started,
        )
        self.evaluations.append(evaluation)
        logger.info(
            "tax %.4f EUR/t: E %.6g, c %.6g, beta %.6g, F %.6g (%s, %.1f s)",
            tax, evaluation.emissions, evaluation.cost, evaluation.tax_base, evaluation.leader_objective,
            "solved" if evaluation.solved else "time limit", evaluation.seconds,
        )
        return evaluation

    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at


# Relative tolerance at which two responses' cost and tax base are the same number: round-off in the
# solution values, not the solver's MIP gap.
_NUMERICAL = 1e-8


def _line_value(evaluation: TaxEvaluation, tax: float) -> float:
    return evaluation.cost + tax * evaluation.tax_base / 1000.0


def _tolerance(value: float, mip_gap: float) -> float:
    return max(DEFAULT.eps, (mip_gap + DEFAULT.epsilon_prime) * abs(value))


def _same_line(first: TaxEvaluation, second: TaxEvaluation, mip_gap: float) -> bool:
    return (abs(first.cost - second.cost) <= _tolerance(first.cost, mip_gap)
            and abs(first.tax_base - second.tax_base) <= _tolerance(first.tax_base, mip_gap))


def _choose(candidates: list[TaxEvaluation]) -> TaxEvaluation:
    """The least leader value and, at an exact tie, the lower tax, as the DBP keeps its incumbent."""
    return min(candidates, key=lambda e: (e.leader_objective, e.tax))


def _result(search: _Search, method: str, break_points: list[float], candidates: list[TaxEvaluation]) -> EnumerationResult:
    complete = not search.out_of_budget
    return EnumerationResult(
        method=method,
        tax_weight_per_eur_t=search.weight,
        reference_emissions=search.reference_emissions,
        evaluations=list(search.evaluations),
        break_points=sorted(break_points),
        candidates=sorted(candidates, key=lambda e: e.tax),
        best=_choose(candidates) if candidates else None,
        complete=complete,
        certified=complete and all(e.solved for e in search.evaluations),
        seconds=search.elapsed(),
        scale_seconds=search.scale_seconds,
    )


def enumerate_break_points(
    instance_or_path,
    *,
    time_limit: float | None = None,
    mip_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
    seed: int | None = None,
    run_time_limit: float | None = None,
    leader_tax_weight_relative: float | None = None,
    min_interval: float | None = None,
    output_flag: bool = False,
) -> EnumerationResult:
    """Find the break points of the follower's value function on the tax range by the dichotomic scheme,
    evaluate the leader's objective at the lower end and at every break point, and return the best.

    ``min_interval`` (EUR/t, default the DBP's ``tax_tolerance``) stops the recursion on intervals shorter
    than that, where two crossings are indistinguishable. ``run_time_limit`` bounds the whole search; a
    search that runs out of it returns the candidates found so far, with ``complete`` false.
    """
    instance = _coerce_instance(instance_or_path)
    search = _Search(
        instance,
        time_limit=DEFAULT.time_limit if time_limit is None else time_limit,
        mip_gap=mip_gap, threads=threads, mip_focus=mip_focus, seed=seed,
        run_time_limit=run_time_limit,
        leader_tax_weight_relative=DEFAULT.tax_weight_relative if leader_tax_weight_relative is None else leader_tax_weight_relative,
        output_flag=output_flag,
    )
    shortest = DEFAULT.tax_tolerance if min_interval is None else min_interval
    low, high = instance.lower_tax, instance.upper_tax
    left = search.evaluate(low)
    right = search.evaluate(high)
    break_points: list[float] = []
    candidates: list[TaxEvaluation] = [left]
    # Intervals still to search, each bounded by the lines found at its two ends.
    pending: list[tuple[TaxEvaluation, TaxEvaluation]] = [(left, right)]
    while pending:
        if search.budget_spent():
            search.out_of_budget = True
            break
        a, b = pending.pop()
        if _same_line(a, b, _NUMERICAL) or b.tax - a.tax <= shortest:
            continue
        slope_gap = (a.tax_base - b.tax_base) / 1000.0
        if slope_gap <= 0.0:
            # The tax base cannot rise with the tax; a non-positive difference is round-off between
            # lines that are the same to the solver's tolerance.
            continue
        crossing = (b.cost - a.cost) / slope_gap
        if not a.tax + shortest < crossing < b.tax - shortest:
            # The lines cross at an end of the interval or outside it: they are parallel to round-off,
            # and no break point lies strictly inside.
            continue
        middle = search.evaluate(crossing)
        envelope = _line_value(a, crossing)
        if _same_line(middle, a, _NUMERICAL) or _same_line(middle, b, _NUMERICAL):
            # The response at the crossing lies on one of the two lines: no other line is optimal in
            # between, the crossing is a break point, and the evaluation there is the optimistic
            # response at that break point.
            break_points.append(crossing)
            candidates.append(middle)
            continue
        if middle.follower_objective > envelope + _tolerance(envelope, _NUMERICAL):
            # A response worse than both lines: the solve stopped short of the optimum. The lines of a
            # and b are the best known there, so the crossing is taken as a break point.
            logger.warning("tax %.4f: the follower's response lies above both lines; crossing kept as a break point", crossing)
            break_points.append(crossing)
            candidates.append(middle)
            continue
        # A new line, optimal somewhere between a and b, even if its value at the crossing is within
        # the MIP gap of the two lines: lines that differ little in cost can differ much in emissions.
        pending.append((middle, b))
        pending.append((a, middle))
    return _result(search, "enumeration", break_points, candidates)


def grid_search(
    instance_or_path,
    *,
    step: float = 1.0,
    time_limit: float | None = None,
    mip_gap: float | None = None,
    threads: int | None = None,
    mip_focus: int | None = None,
    seed: int | None = None,
    run_time_limit: float | None = None,
    leader_tax_weight_relative: float | None = None,
    output_flag: bool = False,
) -> EnumerationResult:
    """Evaluate the leader's objective on a grid of taxes ``tau_min, tau_min + step, ..., tau_max`` and return
    the best. Its tax is within ``step`` above the break point it approximates, the resolution the DBP's
    certificate gives at the default settings."""
    instance = _coerce_instance(instance_or_path)
    search = _Search(
        instance,
        time_limit=DEFAULT.time_limit if time_limit is None else time_limit,
        mip_gap=mip_gap, threads=threads, mip_focus=mip_focus, seed=seed,
        run_time_limit=run_time_limit,
        leader_tax_weight_relative=DEFAULT.tax_weight_relative if leader_tax_weight_relative is None else leader_tax_weight_relative,
        output_flag=output_flag,
    )
    low, high = instance.lower_tax, instance.upper_tax
    count = int(math.floor((high - low) / step + 1e-9)) + 1
    taxes = [low + i * step for i in range(count)]
    if taxes[-1] < high - 1e-9:
        taxes.append(high)
    candidates: list[TaxEvaluation] = []
    for tax in taxes:
        if search.budget_spent():
            search.out_of_budget = True
            break
        candidates.append(search.evaluate(tax))
    return _result(search, "grid", [], candidates)
