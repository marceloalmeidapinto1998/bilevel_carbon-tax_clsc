"""The follower's abatement curve E(tax), found exactly, and the leader's optimum read off it.

The follower's optimal value f*(tax) = min_y c(y) + tax/1000 * beta(y) is the lower envelope of one
line per response y, with intercept c(y) and slope beta(y)/1000: concave and piecewise linear in the
tax. Each piece is one response; the taxes where two pieces meet are the break points, where the
follower is indifferent and the optimistic rule takes the response with fewer emissions. Between two
break points the response, and so its emissions E, does not change.

The pieces are found by the Eisner-Severance method: solve the follower at both ends of the tax range;
if the two responses are different lines, solve again where the lines intersect; if that solve finds a
line below both, recurse on each side, and otherwise the intersection is a break point. Every line of
the envelope is found with about two follower solves.

The leader minimises F(tax) = E(y(tax)) + w * tax. E is constant on each piece and w > 0, so F is least
at the left end of a piece: the leader's optimum is the best of the lower tax bound and the break
points, each evaluated with the optimistic response at that tax. This is an exact solution of the
bilevel problem up to the follower's MIP gap, independent of the DBP, and so a check of it.

Resolution: a line that lies below the envelope by less than the follower's MIP gap, and a piece
narrower than ``min_piece_width`` EUR/t, cannot be told apart and are merged into their neighbours.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import sys
import time

from clsc.config.constants import KG_PER_TONNE
from clsc.models.follower import build_follower_model, solve_follower_lexicographic
from clsc.models.instance_data import InstanceData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Response:
    """The follower's optimistic response at one tax."""

    tax: float
    cost: float
    tax_base: float
    emissions: float
    follower_objective: float
    mip_gap: float | None
    status: str
    seconds: float

    def value_at(self, tax: float) -> float:
        """The follower objective of this response at another tax: its line."""
        return self.cost + tax / KG_PER_TONNE * self.tax_base


@dataclass(frozen=True)
class BreakPoint:
    """A tax where two pieces meet, with the optimistic response there."""

    tax: float
    response: Response


@dataclass(frozen=True)
class AbatementCurve:
    lower_tax: float
    upper_tax: float
    lower_response: Response
    upper_response: Response
    break_points: tuple[BreakPoint, ...]
    follower_solves: int
    seconds: float
    mip_gap: float

    def candidates(self) -> list[Response]:
        """The responses at which the leader's optimum can lie: the lower bound and every break point."""
        return [self.lower_response, *(point.response for point in self.break_points)]

    def leader_optimum(self, weight: float) -> tuple[Response, float]:
        """The leader's best tax and F = E + w * tax, with w in kg CO2e per EUR/t."""
        best = min(self.candidates(), key=lambda response: (response.emissions + weight * response.tax, response.tax))
        return best, best.emissions + weight * best.tax


def abatement_curve(
    instance: InstanceData,
    *,
    lower_tax: float | None = None,
    upper_tax: float | None = None,
    mip_gap: float = 1e-6,
    time_limit: float | None = None,
    threads: int | None = None,
    seed: int | None = None,
    min_piece_width: float = 1e-3,
) -> AbatementCurve:
    """The exact abatement curve over [lower_tax, upper_tax] (default: the instance's tax range)."""
    lower = instance.lower_tax if lower_tax is None else float(lower_tax)
    upper = instance.upper_tax if upper_tax is None else float(upper_tax)
    follower = build_follower_model(instance)
    started = time.perf_counter()
    solves = 0

    def solve(tax: float) -> Response:
        nonlocal solves
        t0 = time.perf_counter()
        result = solve_follower_lexicographic(
            follower, tax, time_limit=time_limit, mip_gap=mip_gap, threads=threads, seed=seed,
        )
        solves += 1
        if not result.has_solution:
            raise RuntimeError(f"the follower found no solution at tax {tax} ({result.status_name})")
        response = Response(
            tax=tax, cost=float(result.cost), tax_base=float(result.tax_base), emissions=float(result.emissions),
            follower_objective=float(result.follower_objective), mip_gap=result.mip_gap,
            status=result.status_name, seconds=time.perf_counter() - t0,
        )
        logger.info("tax %.4f: cost %.2f, emissions %.2f, %.1f s", tax, response.cost, response.emissions, response.seconds)
        return response

    def tolerance(value: float) -> float:
        # Two follower values closer than the solves' MIP gap cannot be told apart.
        return 2.0 * mip_gap * max(1.0, abs(value))

    break_points: list[BreakPoint] = []

    def refine(left: Response, right: Response) -> None:
        # The lines of left and right meet where their values are equal.
        slope_difference = (left.tax_base - right.tax_base) / KG_PER_TONNE
        if slope_difference <= 0.0:
            return  # the same slope (or numerical noise): one line, no break point between them
        crossing = (right.cost - left.cost) / slope_difference
        if not left.tax < crossing < right.tax:
            return  # the lines do not meet inside the interval: within tolerance, one line
        middle = solve(crossing)
        envelope = left.value_at(crossing)
        if middle.follower_objective >= envelope - tolerance(envelope) or min(crossing - left.tax, right.tax - crossing) < min_piece_width:
            # No line lies below the two at their crossing: the crossing is a break point.
            break_points.append(BreakPoint(tax=crossing, response=middle))
            return
        refine(left, middle)
        refine(middle, right)

    low = solve(lower)
    high = solve(upper)
    refine(low, high)
    break_points.sort(key=lambda point: point.tax)
    return AbatementCurve(
        lower_tax=lower, upper_tax=upper, lower_response=low, upper_response=high,
        break_points=tuple(break_points), follower_solves=solves,
        seconds=time.perf_counter() - started, mip_gap=mip_gap,
    )


def write_curve(curve: AbatementCurve, weight: float | None, directory: Path, instance_name: str) -> dict:
    """Write abatement_curve.csv (one row per candidate tax) and abatement.json; return the latter."""
    directory.mkdir(parents=True, exist_ok=True)
    fields = ["tax", "kind", "emissions", "cost", "tax_base", "follower_objective", "leader_objective", "mip_gap", "status", "seconds"]
    rows = [("lower_bound", curve.lower_response)] + [("break_point", p.response) for p in curve.break_points] + [("upper_bound", curve.upper_response)]
    with (directory / "abatement_curve.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for kind, response in rows:
            writer.writerow({
                "tax": response.tax, "kind": kind, "emissions": response.emissions, "cost": response.cost,
                "tax_base": response.tax_base, "follower_objective": response.follower_objective,
                "leader_objective": None if weight is None else response.emissions + weight * response.tax,
                "mip_gap": response.mip_gap, "status": response.status, "seconds": round(response.seconds, 3),
            })
    summary: dict = {
        "instance": instance_name,
        "tax_range": [curve.lower_tax, curve.upper_tax],
        "break_points": len(curve.break_points),
        "follower_solves": curve.follower_solves,
        "seconds": round(curve.seconds, 3),
        "follower_mip_gap": curve.mip_gap,
        "emissions_at_lower_tax": curve.lower_response.emissions,
        "emissions_at_upper_tax": curve.upper_response.emissions,
        "leader_tax_weight": weight,
    }
    if weight is not None:
        best, value = curve.leader_optimum(weight)
        summary["leader_optimum"] = {"tax": best.tax, "emissions": best.emissions, "cost": best.cost, "leader_objective": value}
    (directory / "abatement.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _weight_from_dbp_summary(path: Path) -> float | None:
    if not path.exists():
        return None
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary = summary[0] if isinstance(summary, list) else summary
    return summary.get("leader_tax_weight")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m clsc.analysis.abatement",
        description=(
            "Find the follower's abatement curve E(tax) exactly and the leader's optimum on it. "
            "Writes abatement_curve.csv and abatement.json to <results-root>/<instance>/."
        ),
    )
    parser.add_argument("instances", nargs="+", help="Instance JSON files.")
    parser.add_argument("--results-root", default="results")
    parser.add_argument(
        "--leader-tax-weight", type=float,
        help="w in kg CO2e per EUR/t (default: the one in <results-root>/<instance>/summary.json, from the DBP run).",
    )
    parser.add_argument("--mip-gap", type=float, default=1e-6, help="Follower MIP gap (default 1e-6).")
    parser.add_argument("--time-limit", type=float, help="Seconds per follower solve stage.")
    parser.add_argument("--threads", type=int)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    for path in map(Path, args.instances):
        instance = InstanceData.from_file(path)
        directory = Path(args.results_root) / path.stem
        weight = args.leader_tax_weight if args.leader_tax_weight is not None else _weight_from_dbp_summary(directory / "summary.json")
        curve = abatement_curve(instance, mip_gap=args.mip_gap, time_limit=args.time_limit, threads=args.threads, seed=args.seed)
        summary = write_curve(curve, weight, directory, path.stem)
        print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
