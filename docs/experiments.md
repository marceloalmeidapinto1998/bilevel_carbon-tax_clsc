# Experiment plan

The experiments are declared in [`src/clsc/experiments/plan.py`](../src/clsc/experiments/plan.py) and run with `python -m clsc.experiments run <key>`; an interrupted job resumes where it stopped. The results go to `results/experiments/<key>/seed<s>/<instance>/`, the summary tables to `results/experiments/tables/` (`python -m clsc.experiments report`), and the rows of the manuscript's tables come from `python paper/tools/make_tables.py`.

One run at a time, 4 threads, seed 0 (except R3). Each DBP job runs `clsc-solve` in its own process; the enumerations and the follower evaluations run in the campaign's process.

## Questions

| | Question | Experiments |
|---|---|---|
| Q1 | How do the two exact methods compare? | P1, E1, E2, C1, C2, C5, A1, A2 |
| Q2 | Where is the optimal tax, and what does a fixed tax achieve? | C2, C3, C4 (and P3, P3b on the original instances) |
| Q3 | How does the tax act on a real network? | P1, P2b, R2 (case study) |

## Experiments

### First version: original instances and case study (20–21 October)

| Key | What | Instances | Runs | Limit |
|---|---|---|---|---|
| P1 | The DBP on every instance (also the base of P2) | 15 generated + Mota | 16 | 1 h |
| P2a | Sensitivity: 6 parameters × 2 levels, one at a time | 4 small | 48 | 30 min |
| P2b | The same sensitivity | Mota | 12 | 1 h |
| P3 | The follower without a tax and at the fixed reference tax (EUR 74/t, the 2025 average EU allowance price, ESMA 2026) | 4 small + Mota | 5 | 600 s per stage |
| P3b | P3 on the other 7 instances that P1 closes | 7 closed | 7 | 600 s per stage |
| R1 | Robustness: P2a and the bases of the 4 small instances with `--mip-gap 1e-6` (instead of 1e-4) | 4 small | 52 | 30 min |
| R2 | Mota, base, with 3 h | Mota | 1 | 3 h |
| R3 | Robustness: the 4 small instances with seeds 1–4 (with seed 0 of P1, five seeds) | 4 small | 16 | 1 h |

The 4 small instances are STD_I17_M4_T3, STD_I17_M8_T3, STD_I25_M4_T3 and STD_I17_M4_T6.

### Second version: the two methods and the calibrated instances (since 26 October)

| Key | What | Instances | Limit |
|---|---|---|---|
| E1 | Enumeration of the switching prices (dichotomic scheme of Aneja and Nair) | 15 generated + Mota | 1 h |
| E2 | A grid of taxes 1 EUR/t apart | 4 small | 1 h |
| C1 | The DBP | 39 calibrated | 1 h |
| C2 | Enumeration of the switching prices | 39 calibrated | 1 h |
| C3 | The follower without a tax and at EUR 74/t | 39 calibrated | 600 s per stage |
| C4 | Sensitivity (the 6 parameters) by enumeration | 4 small calibrated (replicate 0) | 1 h |
| C5 | A grid of taxes | 4 small calibrated (replicate 0) | 1 h |
| A1 | Ablation: the DBP without the bounds on the bilinear product (`CLSC_PRODUCT_BOUNDS=off`) | 4 small calibrated | 1 h |
| A2 | Ablation: the DBP without the valid inequalities (`CLSC_STRENGTHENING=`) | 4 small calibrated | 1 h |

The 39 calibrated instances are three replicates of the twelve standard sizes and one of the three larger sizes (`data/calibrated/`, see the README). The manuscript uses replicates 0 and 1 (24 instances); replicate 2, the larger sizes and experiments C4, C5, A1 and A2 are for a revision.

## The six sensitivity parameters

| Parameter | Levels | Why |
|---|---|---|
| Regulator's weight q (w = q·E_ref) | 1e-5, 1e-3 (base 1e-4) | The regulator's trade-off between emissions and the tax level |
| Production emission intensity (`e_prod_g`, this one only) | ×0.5, ×2 | Weight of production against raw materials and remanufacturing |
| Remanufacturing emission intensity (`e_rem_l`) | ×0.5, ×2 | Environmental advantage of remanufacturing |
| Return fractions (`rho`, minimum and maximum) | ×0.5, ×2 (capped at 1) | How much can be remanufactured |
| Cost of the cleanest production technology (variable and investment) | ×0.5, ×2 | Price of producing cleanly |
| Interest rate | 5%, 20% (base 10%) | Discounts the tax paid but not the emissions; weighs capital against operations |

The scale of all emissions is not varied: multiplying every emission factor by k divides every switching price by k and leaves the share of cost paid as tax unchanged (Proposition 2 of the manuscript). Transport (0.2–0.5% of E) and demand (which can make instances infeasible by capacity) are left out.

## Measured responses

For each DBP run: the optimal tax, emissions, cost, tax paid, emission reduction and cost increase against τ = 0, remanufacturing share, emissions by source, facilities and technologies, result class and gap. For each enumeration: every tax evaluated (`evaluations.csv`), the switching prices, the optimal tax, and whether the enumeration was complete and certified (`summary.json`).

## Tables

| Table (`results/experiments/tables/`) | Content |
|---|---|
| `main` | P1 by instance: class, LB, UB, gap, iterations, HPR and follower time |
| `sensitivity` | P2a and P2b: each instance and scenario, with the base from P1 |
| `policy` | P3 and P3b: without a tax, at the reference tax, at the regulator's optimum, and the least emissions E_ref, with the network profile |
| `robustness` | R1 against P2a: the optimal tax and the reduction at gap 1e-4 and 1e-6 |
| `seeds` | R3 with P1: the optimal tax, reduction, class and time of the 4 small instances with seeds 0–4 |
| `methods` | The DBP against the enumeration and the grid, instance by instance (P1, E1, E2; C1, C2, C5) |
| `staircase` | The candidate taxes of each enumeration, with the emissions and the leader's value: the staircase of Figure 1 |
| `calibrated_policy` | Calibrated instances: without a tax, at EUR 74/t (C3), at the optimum (C2) and E_ref |
| `calibrated_sensitivity` | C4 with the bases from C2 |

Tables 5–7 and S4 of the manuscript come from `paper/tools/make_tables.py`, and Figure 1 from `paper/tools/make_figure.py`.

## Limitations

- One seed per run, except on the 4 small instances (five seeds, R3).
- The hard instances and Mota do not close the gap in 1 h. On Mota, differences between scenarios smaller than the gap are inconclusive.
- An enumeration is certified only when every follower solve finishes within its time limit.

## Budget

First version: about 24–26 machine hours, on 20 and 21 October (P2a, P1, P3, P2b; then R1 and R2; P3b and R3 after the referee report). Second version: the campaign `C2 C3 C1 C4 C5 A1 A2 E1` launched on 26 October, logged in `results/experiments/run_campaign.log`.
