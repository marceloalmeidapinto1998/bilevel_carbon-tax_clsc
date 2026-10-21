"""The experiments of the paper, declared once: which task runs on which instances, scenarios and seeds.

docs/experiments.md describes what each experiment answers; this module is what runs.

P1   the DBP on every instance: the main table, and the base of the sensitivity analysis.
P2a  the sensitivity analysis on the four small instances: six parameters, two levels each.
P2b  the same on the case study of Mota et al. (2018).
P3   the follower at a fixed reference tax, against which the regulator's optimal tax is compared
     (the follower at tax 0 is the DBP's first iteration, read from P1).
R1   P2a and its bases again at a MIP gap of 1e-6 instead of 1e-4: which changes of the optimal tax
     survive a tolerance 100 times tighter.
R2   the case study's base with 3 h instead of 1 h, to narrow its gap.

Tasks (clsc.experiments.tasks): ``dbp`` runs clsc-solve, so that its files are those of the main
results; ``follower`` solves the follower at given taxes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .scenarios import SENSITIVITY_SCENARIOS

DATA = "data"
CASE_STUDY = f"{DATA}/case_study/MOTA2018.json"


def _standard(*names: str) -> tuple[str, ...]:
    return tuple(f"{DATA}/STD_{name}.json" for name in names)


ALL_GENERATED = _standard(
    "I17_M4_T3", "I17_M4_T6", "I17_M4_T12", "I17_M8_T3", "I17_M8_T6", "I17_M8_T12",
    "I25_M4_T3", "I25_M4_T6", "I25_M4_T12", "I25_M8_T3", "I25_M8_T6", "I25_M8_T12",
    "I25_M12_T6", "I25_M16_T6", "I33_M8_T6",
)
ALL_INSTANCES = (*ALL_GENERATED, CASE_STUDY)
# Solved by the DBP in about a minute: the instances of the sensitivity analysis.
SMALL = _standard("I17_M4_T3", "I17_M8_T3", "I25_M4_T3", "I17_M4_T6")

# A fixed tax that does not anticipate the follower's response (EUR/t), to compare the regulator's
# optimal tax with. It stands for the EU ETS price; set it to the price and year the paper cites.
REFERENCE_TAX = 80.0


@dataclass(frozen=True)
class Experiment:
    key: str
    title: str
    task: str
    instances: tuple[str, ...]
    scenarios: tuple[str, ...] = ("base",)
    seeds: tuple[int, ...] = (0,)
    options: dict = field(default_factory=dict)


EXPERIMENTS: dict[str, Experiment] = {
    experiment.key: experiment
    for experiment in (
        Experiment("P1", "Main table: the DBP on every instance", "dbp", ALL_INSTANCES,
                   options={"run_time_limit": 3600.0}),
        Experiment("P2a", "Sensitivity analysis, small instances", "dbp", SMALL,
                   scenarios=SENSITIVITY_SCENARIOS, options={"run_time_limit": 1800.0}),
        Experiment("P2b", "Sensitivity analysis, case study", "dbp", (CASE_STUDY,),
                   scenarios=SENSITIVITY_SCENARIOS, options={"run_time_limit": 3600.0}),
        Experiment("P3", "The follower at the fixed reference tax", "follower", (*SMALL, CASE_STUDY),
                   options={"taxes": (REFERENCE_TAX,)}),
        Experiment("R1", "Robustness: the small-instance sensitivity at MIP gap 1e-6", "dbp", SMALL,
                   scenarios=("base", *SENSITIVITY_SCENARIOS), options={"run_time_limit": 1800.0, "mip_gap": 1e-6}),
        Experiment("R2", "The case study with a 3 h budget", "dbp", (CASE_STUDY,),
                   options={"run_time_limit": 10800.0}),
    )
}
