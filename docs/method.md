# Method

The model and the solution methods in detail. The manuscript in [`paper/`](../paper/) is the reference; this page describes how the code implements them.

## Problem

**Leader problem.** The leader is the regulator, who sets a carbon tax rate $\tau$, a continuous variable between 0 and 200 EUR/t CO2e. The follower is the closed-loop supply chain operator. Let $y$ denote its response, comprising the network design and the period-by-period operating plan, and $E(y)$ the total physical emissions (kg CO2e) that it induces. When the follower has alternative optimal responses, the one most favourable to the leader is selected (optimistic approach). The leader minimises

$$F(\tau, y) = E(y) + w \, \tau, \qquad w > 0,$$

where $w$ (kg CO2e per EUR/t) is a policy weight. Since $w > 0$, the lowest tax is selected among those attaining equal emissions, and the regulator accepts $w$ additional units of emissions for each 1 EUR/t reduction in $\tau$. The weight is set as $w = q \, E_{\text{ref}}$, with $q = 10^{-4}$ and $E_{\text{ref}}$ (kg CO2e) the lower bound on $E(y)$ that the solver proves for the HPR without cuts, which is the minimum of $E(y)$ over all feasible network designs when that solve reaches optimality.

**Follower problem.** For a fixed tax rate $\tau$, the follower solves a mixed-integer linear program over a multi-period, multi-product closed-loop network of suppliers, factories, warehouses, retailers, and airport and seaport hubs, connected by truck, air and sea transport. Its decisions are of two kinds:

- **Strategic:** which factories and warehouses to open, their installed floor-area capacities, and which production and remanufacturing technologies to install at each factory.
- **Tactical and operational (per period):** raw-material procurement from suppliers, production and remanufacturing volumes, warehouse inventory levels, and forward flows of final products and reverse flows of recovered products across the transport arcs and modes of the network.

The constraints follow Mota et al. (2018): a selected supplier ships at least its minimum order of every raw material in every period (their eq. 10–11); an arc may be served by several modes in the same period, truck trips require both endpoints to be installed (eq. 26–27), and air and sea carry at most the contracted capacity (eq. 28). One departure remains: an installed remanufacturing technology may stand idle in a period. The instance generator gives every technology a positive minimum use (Mota's case has none for remanufacturing), returns must be remanufactured in the period they arrive, and none arrive before the first return lag has passed; Mota's minimum use in every period (eq. 37) would then make every instance infeasible. Here the minimum use applies in the periods in which the technology operates.

Let $c(y)$ denote the follower's operating cost (procurement, production, remanufacturing, transport, handling and inventory), discounted over the planning horizon, and $\beta(y)$ the emissions aggregate on which the follower is taxed, discounted with the same present-value weights. The follower minimises

$$f(\tau, y) = c(y) + \tau \, \beta(y).$$

All monetary quantities are in EUR. Emissions are the climate-change category of ReCiPe 2008, in kg CO2e, from raw-material acquisition, production, remanufacturing, transport and facility construction. The construction emissions of factories and warehouses are amortised over the facilities' 20-year asset life, as their capital cost is: each period carries the fraction (period length)/(20 years) of them. $E(y)$ sums the emissions of all periods undiscounted; $\beta(y)$ weights each period's emissions by its present-value factor.


## Solution method

The bilevel problem is solved with the DBP of Soares et al. (2021). The procedure alternates between two computations. The high-point relaxation (HPR) gives a lower bound $\mathrm{LB}$ on the leader's objective $F$. The evaluation of the follower gives an upper bound $\mathrm{UB}$. It stops when the relative gap between the bounds is at most $\varepsilon$.

**The problem that is solved.** The follower is taken to accept any response whose objective is within $\varepsilon'$ of its best, on top of the MIP gap to which its problem is solved (the $\varepsilon'$-optimistic problem, as in Soares et al. and Mitsos). The evaluation of the follower, and so $\mathrm{UB}$, refers to that problem. The cuts carry no $\varepsilon'$, so $\mathrm{LB}$ bounds the exact optimistic problem. The two bounds therefore belong to slightly different problems. The gap is reported with its sign, and a lower bound above the upper bound by more than $\varepsilon$ ends the run as `bound_inversion`.

The HPR minimises $F$ over the follower's physical constraints alone and does not require the follower's response to be optimal. These constraints do not contain $\tau$. Every follower response is therefore feasible at every tax rate, and every evaluated response yields a cut that is valid for the whole problem. The follower's objective $f(\tau, y) = c(y) + \tau\,\beta(y)$ contains the product of two continuous quantities, so the HPR is a non-convex bilinear program; Gurobi solves it by spatial branch-and-bound (`NonConvex=2`). As in the basic DBP of Soares et al. (2021), the HPR carries only the cuts. `--incumbent-cutoff` adds, once the upper bound is a proven value, the cutoff $F \le \mathrm{UB}$ and the bound $E \le \mathrm{UB}$ (a pruning cutoff after Mitsos, 2010; it is not their Section 8 constraint, which is bounded by the HPR's own bound). Gurobi relaxes the product by McCormick's envelopes, which are as tight as the bounds of its two operands, so the HPR keeps those bounds as narrow as the run has proven: with $E_{\text{ref}}$ the least emissions of any response and $d_t$ the per-period discount weights, $\beta(y) \ge d_{\min} E_{\text{ref}}$ always, and with the cutoff $\beta(y) \le d_{\max} \min(\mathrm{UB}, \bar{E})$ and $\tau \le (\mathrm{UB} - E_{\text{ref}})/w$, where $\bar{E}$ is the bound on $E$ with every facility and technology at capacity. None of these removes a point with $F \le \mathrm{UB}$.

**Tolerances**

- $\varepsilon$: tolerance on the relative gap.
- $\varepsilon'$: very small tolerance on the follower's objective, used only in the follower's tie-break $f \le f^{\ast} + \varepsilon'$.
- Subproblems are solved to a relative MIP gap of $10^{-4}$.
- $\delta$: tolerance on the tax, 0.001 EUR/t. The tax is continuous, so the HPR re-proposes the tax just evaluated only up to $\delta$.

**Initialisation.** Fix $w$ (see Problem) and solve the HPR without cuts. Set $\mathrm{LB}$ to the bound proven by the solver and $\tau_{0}$ to the tax rate of the HPR solution. Set $\mathrm{UB} = +\infty$ and $k = 0$.

**Iteration** ($k = 0, 1, \dots$)

1. **Evaluate the follower.** Solve the follower's problem at $\tau_{k}$ with the optimistic rule. Stage 1 minimises $f$ and gives $f^{\ast}$. Stage 2 minimises $E$ subject to $f \le f^{\ast} + \varepsilon'$ and gives $y_{k}$. If $F(\tau_{k}, y_{k}) < \mathrm{UB}$, set $\mathrm{UB} = F(\tau_{k}, y_{k})$. The incumbent is the evaluated pair of least $F$; ties go to the lower tax.
2. **Add a cut.** Add $f(\tau, y) \le f(\tau, y_{k})$ to the HPR. The point $y_{k}$ is feasible for every $\tau$. If $(\tau, y^{\ast})$ is bilevel-feasible, $y^{\ast}$ minimises $f(\tau, \cdot)$, so $f(\tau, y^{\ast}) \le f(\tau, y_{k})$. The cut therefore removes no bilevel-feasible point. It carries no $\varepsilon'$: $y_{k}$ already lies up to $\varepsilon'$ above $f^{\ast}$, and a second $\varepsilon'$ in the cut would let the HPR propose a tax at which a lower-emission response lies outside the follower's tie-break set, so the follower never returns it and the run stalls.
3. **Re-solve the HPR.** Set $\mathrm{LB}$ to the larger of its previous value and the bound proven by this solve. Set $\tau_{k+1}$ to the tax rate of the HPR solution.
4. **Test termination.** If $(\mathrm{UB} - \mathrm{LB}) / \max(1, |\mathrm{UB}|) \le \varepsilon$, stop and classify the result. Otherwise set $k \leftarrow k + 1$ and return to step 1.

The outcomes below hold up to the solvers' tolerances and $\varepsilon'$.

| Outcome | Condition |
|---|---|
| Optimal | The gap is at most $\varepsilon$ and $\lvert\tau_{k+1} - \tau_{k}\rvert \le \delta$; the last HPR did not stop on its time limit and has no active elastic slack; the follower's response behind $\mathrm{UB}$ was solved within its time limit. |
| $\varepsilon$-optimal | The gap is at most $\varepsilon$, but one of the conditions above fails; or the HPR, cut off at $F \le \mathrm{UB}$, has no point, so that no response satisfying every cut does better than the incumbent and $\mathrm{LB} = \mathrm{UB}$. |
| Bound inversion | $\mathrm{LB}$ exceeds $\mathrm{UB}$ by more than $\varepsilon$ (relative): one of them is not a bound. |
| Bounds | The run ends before the gap closes: the auxiliary stop (neither bound changed during 10 consecutive iterations), the run budget or the iteration cap. |

**Bounds.** As in Soares et al. for subproblems that cannot be solved to optimality, the result is the interval $[\mathrm{LB}, \mathrm{UB}]$ with its gap, and the incumbent that attains $\mathrm{UB}$. $\mathrm{LB}$ is the HPR's dual bound, valid whatever the HPR's own gap. $\mathrm{UB}$ is certified (`upper_bound_certified` is true in the summary) when every follower response behind it was solved within its time limit; otherwise it is the value of the best response found, which a time-limited follower solve does not prove optimal. The result class for a crossed pair of bounds is `inconsistent`.

In the summary files the outcomes appear as the result classes `optimal`, `epsilon_optimal`, `bounds` and `inconsistent`, with the termination reason alongside (`optimal`, `epsilon_optimal`, `epsilon_optimal_cutoff_infeasible`, `bound_inversion`, `incumbent_stagnation`, `incumbent_time_limit`, `incumbent_iteration_limit`). `final_tax_change` records $\lvert\tau_{k+1} - \tau_{k}\rvert$ where the gap closed.

The follower's response changes at break points, taxes at which the follower is indifferent between two responses and the optimistic rule picks the one with fewer emissions. On `STD_I17_M4_T3` the optimal tax lies at such a break point, between 33.91 and 33.95 EUR/t, where the emissions drop by 0.33%. The tie-break accepts responses up to $\varepsilon'$ above the follower's best, so the reported tax can lie slightly below the exact break point. This repository does not certify the tax as an interval; $\lvert\tau_{k+1} - \tau_{k}\rvert$ is reported (`final_tax_change`) so that the distance between the evaluated tax and the HPR's proposal is visible.

<details>
<summary>Time limits and stopping rules</summary>

- **HPR time limit.** An HPR that reaches its time limit still yields a valid lower bound (its dual bound) and, if it holds a feasible point, the next tax proposal. Otherwise the cuts are made elastic. If the elastic HPR also returns no point, the run ends with the incumbent.
- **Elastic cuts (P5-D).** The first time the HPR returns no feasible point, unless it is proven infeasible under the cutoff $F \le \mathrm{UB}$ (which ends the run, see the outcomes), each cut $k$ is relaxed to $f(\tau, y) \le f(\tau, y_{k}) + D_{k}$ with $D_{k} \ge 0$, and the sum of the $D_{k}$ is penalised in the HPR objective. The relaxed HPR is always feasible. If some $D_{k} > 0$, the result cannot be classified as optimal; if, moreover, its dual bound exceeds the cutoff, no point satisfies every cut with $F \le \mathrm{UB}$, and the run ends as above.
- **Follower time limit.** If stage 1 reaches its time limit with a positive gap, subproblem P6 first searches for a better response, before the constraint $f \le f^{\ast} + \varepsilon'$ of stage 2 is set. P6 minimises $D \ge 0$ subject to the follower's constraints and $f(\tau_{k}, y) \le \bar{f}\,(1 - g) + D$, where $\bar{f}$ is the best value of $f$ found by stage 1 and $g$ its relative MIP gap; $\bar{f}\,(1 - g)$ is the solver's bound on the follower's optimum, so a response with $D$ close to zero is nearly optimal. If stage 2 finds no feasible point, the stage-1 (or P6) response is kept. Such a response is not proven optimal, so the result is at most $\varepsilon$-optimal.
- **Auxiliary stop.** The procedure also stops after 10 consecutive iterations in which neither bound changes.

</details>
