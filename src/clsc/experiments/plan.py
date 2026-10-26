"""The experiments of the paper, declared once: which task runs on which instances, scenarios and seeds.

docs/experiments.md describes what each experiment answers; this module is what runs.

P1   the DBP on every instance: the main table, and the base of the sensitivity analysis.
P2a  the sensitivity analysis on the four small instances: six parameters, two levels each.
P2b  the same on the case study of Mota et al. (2018).
P3   the follower without a tax and at a fixed reference tax, against which the regulator's optimal
     tax is compared, each response profiled (what the network changes).
R1   P2a and its bases again at a MIP gap of 1e-6 instead of 1e-4: which changes of the optimal tax
     survive a tolerance 100 times tighter.
R2   the case study's base with 3 h instead of 1 h, to narrow its gap.
P3b  P3 on the other seven instances that P1 closes, so that the fixed reference tax is compared with
     the optimal tax on every closed instance.
R3   the DBP on the four small instances with seeds 1-4; with seed 0 (P1), five seeds: how much the
     optimal tax and the reduction vary with the solver's seed.
E1   the break points of the follower's value function enumerated on every instance (Aneja and Nair's
     dichotomic scheme): the exact alternative to the DBP for one tax, and the staircase of emissions.
E2   a grid of taxes 1 EUR/t apart on the small instances: the simplest alternative, at the DBP's resolution.

Tasks (clsc.experiments.tasks): ``dbp`` runs clsc-solve, so that its files are those of the main
results; ``follower`` solves the follower at given taxes; ``enumeration`` enumerates the break points or
evaluates a grid.
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
# The other instances that P1 closes to its gap within 1 h (optimal or epsilon-optimal).
CLOSED_NOT_SMALL = _standard(
    "I17_M4_T12", "I17_M8_T6", "I25_M4_T6", "I25_M4_T12", "I25_M8_T3", "I25_M8_T12", "I33_M8_T6",
)

# The calibrated instances (clsc.generator.calibrated): the case study's emission factors and return
# fractions on the generated networks; three replicates of the twelve standard sizes, one of the three
# escalation sizes.
CALIBRATED = f"{DATA}/calibrated"
STANDARD_SIZES = (
    "I17_M4_T3", "I17_M4_T6", "I17_M4_T12", "I17_M8_T3", "I17_M8_T6", "I17_M8_T12",
    "I25_M4_T3", "I25_M4_T6", "I25_M4_T12", "I25_M8_T3", "I25_M8_T6", "I25_M8_T12",
)
ESCALATION_SIZES = ("I25_M12_T6", "I25_M16_T6", "I33_M8_T6")


def _calibrated(sizes: tuple[str, ...], replicates: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(f"{CALIBRATED}/CAL_{size}_r{k}.json" for k in replicates for size in sizes)


ALL_CALIBRATED = (*_calibrated(STANDARD_SIZES, (0, 1, 2)), *_calibrated(ESCALATION_SIZES, (0,)))
CALIBRATED_SMALL = _calibrated(("I17_M4_T3", "I17_M8_T3", "I25_M4_T3", "I17_M4_T6"), (0,))

# A fixed tax that does not anticipate the follower's response (EUR/t), to compare the regulator's
# optimal tax with: the 2025 annual average EU ETS spot price, EUR 74/tCO2e (ESMA, Market report on
# EU carbon markets 2026, ESMA50-481369926-34622, 9 July 2026).
REFERENCE_TAX = 74.0


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
        Experiment("P3", "The follower without a tax and at the fixed reference tax", "follower", (*SMALL, CASE_STUDY),
                   options={"taxes": (0.0, REFERENCE_TAX)}),
        Experiment("R1", "Robustness: the small-instance sensitivity at MIP gap 1e-6", "dbp", SMALL,
                   scenarios=("base", *SENSITIVITY_SCENARIOS), options={"run_time_limit": 1800.0, "mip_gap": 1e-6}),
        Experiment("R2", "The case study with a 3 h budget", "dbp", (CASE_STUDY,),
                   options={"run_time_limit": 10800.0}),
        Experiment("P3b", "The follower without a tax and at the reference tax, other closed instances", "follower",
                   CLOSED_NOT_SMALL, options={"taxes": (0.0, REFERENCE_TAX)}),
        Experiment("R3", "Robustness: the small instances with seeds 1-4", "dbp", SMALL,
                   seeds=(1, 2, 3, 4), options={"run_time_limit": 3600.0}),
        Experiment("E1", "Enumeration of the break points on every instance", "enumeration", ALL_INSTANCES,
                   options={"method": "enumeration", "run_time_limit": 3600.0}),
        Experiment("E2", "A grid of taxes 1 EUR/t apart on the small instances", "enumeration", SMALL,
                   options={"method": "grid", "step": 1.0, "run_time_limit": 3600.0}),
        Experiment("C1", "Calibrated instances: the DBP", "dbp", ALL_CALIBRATED,
                   options={"run_time_limit": 3600.0}),
        Experiment("C2", "Calibrated instances: enumeration of the break points", "enumeration", ALL_CALIBRATED,
                   options={"method": "enumeration", "run_time_limit": 3600.0}),
        Experiment("C3", "Calibrated instances: the follower without a tax and at the reference tax", "follower",
                   ALL_CALIBRATED, options={"taxes": (0.0, REFERENCE_TAX)}),
        Experiment("C4", "Calibrated instances: sensitivity analysis on the small instances", "enumeration",
                   CALIBRATED_SMALL, scenarios=SENSITIVITY_SCENARIOS,
                   options={"method": "enumeration", "run_time_limit": 3600.0}),
        Experiment("C5", "Calibrated instances: the grid of taxes on the small instances", "enumeration",
                   CALIBRATED_SMALL, options={"method": "grid", "step": 1.0, "run_time_limit": 3600.0}),
        Experiment("A1", "Ablation: the DBP without the bounds of the bilinear product", "dbp", CALIBRATED_SMALL,
                   options={"run_time_limit": 3600.0, "environment": {"CLSC_PRODUCT_BOUNDS": "off"}}),
        Experiment("A2", "Ablation: the DBP without the valid inequalities", "dbp", CALIBRATED_SMALL,
                   options={"run_time_limit": 3600.0, "environment": {"CLSC_STRENGTHENING": ""}}),
    )
}
