# Model consistency audit — paper vs. code vs. instance data

Date: 2026-06-24 (audit), fixes applied 2026-06-24. Status: items #1, #2 (confirmed dead, no
code change needed), #3, #6, #14 fixed in code; #4, #5, #7-#11 fixed in the paper text. See
"Fix log" at the end of this file for exactly what changed and what still needs follow-up
(regenerating/re-solving instances).

Three parallel workstreams (original audit, read-only at the time):
(1) sets/parameters/decision-variables/auxiliary-expressions/instance-validators, (2) follower
constraints equation-by-equation, (3) leader problem / DBP solvers / lettered assumptions.

Known, pre-existing, NOT re-reported here: `data/instances/base/*.json` predate the `f_w`/
`c_area_*` generator change (see `stale_base_instances` memory).

## Bucket 1 — Likely correctness bugs

1. **Area-installation cost `c_area_f`/`c_area_w` is structurally always zero — in the generator
   itself, not just in stale base files.**
   Paper: `paper/tables/tab_notation.tex:67` defines $c^{\mathrm{area}}_i$ (USD/m²) as a real cost
   parameter. Code: `src/models/shared_models.py:906-907` correctly multiplies it into the cost
   expression — the model is wired to use it. Generator: `data/generator/instance.py:218-219,229,
   239,552-553` declares `factory_area_cost`/`warehouse_area_cost` but hardcodes every entry to
   `0.0`; no sampler exists for this parameter anywhere in `tautenhain_data.py` (only
   `sample_construction_cost`, which feeds `f_f`/`f_w`, the *fixed* opening cost). Verified on a
   current (post f_w/c_area fix) experiment file
   (`data/instances/experiments/scenarios/combined/STD_I17_M4_T3_G6_L6_TM12.json`) — still all
   zero. **Every solved instance silently drops this cost term from the objective.**

2. **Outsourced-mode contracted-capacity fallback may use the wrong parameter when
   `ccamax_m == 0`/unset.** Paper `04c_follower.tex:338-341` (eq:contracted_active_cap) bounds
   transported weight by $\overline B_m\,\zeta_{ijmt}$ (contracted capacity). Code
   `shared_models.py:1452-1457`: when `ccamax_m[mode] == 0.0`, falls through to
   `bar_X_m[mode] * zt[...]` — `bar_X_m` is the road per-trip weight parameter ($\overline W_m$),
   not the outsourced contracted capacity. Silently substitutes the wrong bound **if** any
   instance has an active outsourced mode with `ccamax_m` unset/zero. Same root cause also drops
   the `eq:contracted_cap` ($\zeta\le\kappa_{mt}$) link entirely for such modes
   (`shared_models.py:1454-1455`). Needs a data check: confirm whether any currently-used instance
   actually has an active non-truck mode with `ccamax_m` unset — if not, this is dead code, not a
   live bug.

3. **`dbp_exact`/`dbp_certified`/`dbp_f_lex_exact` insert an undocumented third tie-break level.**
   Paper `04b_leader.tex:18-27` (eq:leader_obj): leader objective is strictly
   `lexmin (Emis(z), hat_tau)`. Code: `_is_better_candidate` in `src/solvers/dbp_exact.py:511-525`
   (shared by `dbp_certified.py` and `dbp_f_lex_exact.py`) compares
   `(emissions, follower_objective, hat_tau)` — inserting the follower's cost+tax objective between
   emissions and hat_tau. `enum_lf_lex_exact.py`'s own comparator (`:217-231`) is correctly
   two-level. **Low practical impact**: the paper's headline method, `dbp_lf_lex_exact.py`,
   bypasses this comparator entirely for its final answer (its phase-2 bisection,
   `_refine_hat_tau_tiebreak` at `:99-213`, picks `hat_tau` purely from an emissions-equality
   predicate). Only activates when emissions tie to `1e-7` across tax indices — near measure-zero —
   but is a genuine logic mismatch if `dbp_exact`/`dbp_certified` are ever run standalone (e.g. for
   a sensitivity check) and a real emissions tie occurs.

## Bucket 2 — Notation/documentation drift (paper vs. code/data disagree, not a numerical bug)

4. **`paper/appendix/app_data.tex:9-13` cites files that don't exist**: `data/generator/
   generate_data.py` and `data/DATASET.md`. Actual entrypoints are `data/generator/instance.py`
   (`generate_instance`/`write_instance`), `cli.py`, `__main__.py`; `tautenhain_data.py` is
   correctly named. Reproducing results from the appendix's literal path will fail.

5. **DBP pseudocode describes a different algorithm than what's implemented.**
   `paper/algorithms/alg_bounding_procedure.tex` describes grid-sampling over tax indices with
   geometric bisection refinement ($\delta=\alpha^k(\overline\tau-\underline\tau)/s_0$, LB from LP
   relaxation per grid point, UB from MIP per grid point). The actual solvers
   (`dbp_exact.py`/`dbp_certified.py`/`dbp_f_lex_exact.py`) implement a single relaxation master
   tightened by Benders-style cuts (`build_dbp_relaxation_master`, `add_dbp_relaxation_cut`,
   `add_dbp_lex_emissions_cut` in `shared_models.py:381-479+`) — no grid `G`, no `s0`/`α`/`δ`
   anywhere in `src/solvers/`. The high-level LB/UB-bracketing-until-gap-closes logic matches in
   spirit; the concrete mechanics (cuts vs. grid points) do not. Worth flagging to whoever
   maintains the methodology section — this is the most significant drift item found.

6. **`as:feas` ("verifiable a priori") has no corresponding check anywhere in code.** Paper
   (`04a_notation.tex:51-57`) explicitly says feasibility "can be verified a priori by checking
   that the network has sufficient installed capacity to cover maximum aggregate demand."
   `InstanceData.validate()` (`instance_loader.py:143-196`) checks set/parameter completeness and
   tax-index consistency but performs no capacity-vs-max-demand check; nothing in
   `data/generator/*.py` does either. An infeasible instance would only surface as a Gurobi
   INFEASIBLE status at solve time, not be caught a priori as the paper claims is possible.

7. **Big-M for trips/vehicles: paper has one flat per-mode constant $M^{\mathrm{trip}}_m$; code has
   two different derivations plus an undocumented override.** `_trip_big_m`
   (`shared_models.py:1671-1698`) derives an arc/node-specific tightened bound from `ecmax_i`,
   `ccamax_m`, `bar_X_m`, optionally `trip_big_m_m`. `eq:vehicle_act`/`eq:vehicle_flow_link` use a
   separately configurable `max_vehicle_i_m` override (`:1620,1628-1630`, no paper counterpart)
   that, when unset, falls back to a *different*, looser single-argument `_trip_big_m` call than
   the one used for `eq:trip_link`. Each individual bound is still mathematically valid (non
   -excluding), but the paper presents one symbol where the code has two derivations plus an
   undocumented knob — recommend documenting or removing `max_vehicle_i_m`.

8. **`eq:vehicle_hours` has a fallback branch with no paper counterpart.**
   `shared_models.py:1647-1668` — when `mode_speed<=0 or mode_hours<=0`, substitutes a trip-count
   cap via `_trip_big_m` instead of the paper's unconditional hour-based bound
   (`04c_follower.tex:369-373`). Acceptable as a degenerate-data guard, but not literally in the
   paper.

9. **$\setM_{ij}$ (per-arc permitted modes) is not data-driven — it's a hardcoded topology rule.**
   Paper (`04a_notation.tex:119-120`) presents $\setM_{ij}$ as general per-arc instance data. Code
   `_allowed_modes` (`shared_models.py:1864-1880`) computes it purely from node-type membership
   (air-air → air modes, sea-sea → sea modes, else → truck-family). No instance JSON stores a
   literal per-arc mode map. Currently harmless because the generator's own arc topology never
   produces a case the rule can't represent, but the implementation is less general than what the
   paper's notation implies.

10. **Paper's $apu_q$ parameter table claims coverage over all of $\setQ=\setU\cup\setP\cup\setK$,
    but the only formula using it ($YCT_{it}$) never references raw materials $\setU$.** Generator
    samples `apu_u` (`sampling.py:72-74`, `instance.py:590-597`) but it's confirmed unused in
    `shared_models.py` — code and data agree with each other (correctly omit raw-material area),
    it's the paper's own table that's broader than its own usage equation. Minor paper looseness,
    not a code defect.

11. **Redundant "all nodes" sets `I` and `N`** — every instance JSON carries both as identical
    lists; `instance_loader.py:162-166` validates `I == N`; `shared_models.py` reads neither
    directly (rebuilds node groups from `S/F/W/R/AIR/PORT`). Paper defines only $\setN$, no
    $\setI$. Harmless legacy alias.

## Bucket 3 — Minor / cosmetic

12. `_derive_recovered_product_area` logic is duplicated between `instance_loader.py:432-445` and
    `shared_models.py:1400-1410` (same formula, same inputs — maintenance risk only).
13. No validator checks capacity/area bound consistency ($\underline A_i\le\overline A_i$, etc.) —
    no violations found in current instances, but it's a missing defense-in-depth check.
14. No validator checks every product/recovered-item has ≥1 compatible technology
    ($\Omega^p$/$\Omega^r$ coverage) — `_validate_pair_sets` only checks listed pairs are valid, not
    that every product is covered. Borders the `as:feas` gap (Bucket 2, #6).
15. `eq:weight_trip` lower bound is only emitted when `ctmin_m > 0` (`shared_models.py:1445-1446`)
    — when zero, the omitted constraint is implied by `x >= 0` anyway. Redundant-constraint
    elision, not a math change.
16. `LEGACY_CARBON_TAX_SCALE = 10.0` alongside active `CARBON_TAX_SCALE = 0.01`
    (`instance_loader.py:11-12`) — a units-migration shim for older instance files, not
    leader-objective-relevant.
17. All variable-naming differences between paper symbols and code identifiers (`q^p`↔`q`,
    `s^{inv}`↔`inv_f/inv_w`, `YC_i`↔`installed_area`, `λ^p/λ^r`↔`u_prod/u_rem`, `ζ`↔`zt`, `Q`↔`trip`,
    `K`↔`vehicle`, etc.) were checked and are cosmetic only — domains/bounds and algebra match.

## What's confirmed consistent (positive findings worth keeping in mind)

- **`as:opt` (optimistic bilevel tie-break, lowest emissions) is correctly implemented in all five
  reachable solvers** — verified at the constraint level (not just by filename), via either the
  solve-then-cap-reoptimize pattern (`dbp_exact`, `dbp_certified`) or the explicit two-stage
  `solve_fixed_tax_lexicographic` (`dbp_f_lex_exact`, `dbp_lf_lex_exact`, `enum_lf_lex_exact`).
  This was the single most important check in the leader/solver workstream and it passes.
- **`as:fixednet`, `as:stackelberg`, `as:singleop`** are structurally enforced (not just narrative):
  facility/technology binaries carry no period index; `hat_tau` is a plain Python int inside the
  follower model, a Gurobi var only in the leader-side relaxation master; one model spans all
  echelons per solve.
- **Hub cross-docking (`as:hub`) and exact demand satisfaction (`as:dem`)** verified at the
  constraint level: no inventory variable exists at hub nodes anywhere in `shared_models.py`;
  market-demand constraints are strict equalities, not `>=`.
- **All ten follower constraint families (flow balance, reverse logistics, raw-material supply,
  facility/area capacity, inventory bounds, technology selection, transport mode/shipment,
  fleet/node activation, intermodal hub routing, valid inequalities) plus all variable domains
  were matched constraint-by-constraint against `shared_models.py` — no sign/direction/index-set
  errors found.** The paper's own stated omission of `eq:vi_capacity_demand` (Remark
  `rem:valid_ineq`) is correctly honored (absent from code).
- The follower decision vector $\bz$ (all 15 components) and leader's $\hat\tau$ map 1:1 to
  `addVar`/`addVars` calls with matching domains and bounds; auxiliary expressions $X^{in}/X^{out}$,
  $\bar y_i$, $YCT_{it}$ all have correct algebraic realizations.
- Tax-rate unit convention ($\tau=\hat\tau/100$ USD/kg CO2e, `CARBON_TAX_SCALE=0.01`) is applied
  consistently everywhere it's referenced.
- All five solvers are reachable from `tools/solver/batch/core.py`; the paper's headline method is
  `dbp_lf_lex_exact`, cross-validated against `enum_lf_lex_exact` via
  `--validate-with-enumeration-oracle`.

## Fix log (2026-06-24)

1. **#1 fixed.** Added `sample_area_installation_cost` to `data/generator/tautenhain_data.py`
   (new `AREA_INSTALLATION_COST_FRACTION_RANGE = (0.05, 0.20)`, applied to the same
   `LABOR_COST_RANGE` already used by `sample_construction_cost`) and wired it into
   `data/generator/instance.py` for both `factory_area_cost`/`warehouse_area_cost`. Updated the
   two stale-zero assertions in `tests/test_generate_data.py`.
   **Consequence requiring follow-up**: instance generation uses one shared seeded
   `random.Random` stream; inserting this new draw shifts every subsequent sampled value for
   the same seed. Every committed instance under `data/instances/experiments/` (and, separately,
   the already-known-stale `data/instances/base/`) was generated before this fix and is now
   stale relative to the corrected generator. Regenerating + re-solving was deliberately **not**
   done as part of this fix (expensive Gurobi re-solves, and overwriting existing stored results
   is a decision for the user, not an automatic side effect of a bug fix). Re-run
   `python -m data.generator benchmark` (and downstream experiment generators) and re-solve
   before trusting any reported cost number going forward.
2. **#2 confirmed dead, no code change.** `data/generator/instance.py:311-312` hardcodes
   `ccamax_m = CONTRACTED_CAPACITY_KG = 300000.0` for every air/sea mode — never 0 — so the
   `else` branch in `shared_models.py` (`_add_transport_constraints`) that substitutes the wrong
   parameter is unreachable under the current generator. Left untouched per the "fix only if
   live" instruction.
3. **#3 fixed.** `src/solvers/dbp_exact.py::_is_better_candidate` no longer compares
   `follower_objective` as a middle tie-break; it now matches the paper's
   `lexmin(emissions, hat_tau)` exactly (same two-level structure as
   `enum_lf_lex_exact._is_better_emissions_then_tax`). Shared by `dbp_certified.py` and
   `dbp_f_lex_exact.py` via import, so one edit fixes all three.
4. **#6 + #14 fixed.** Added `_validate_technology_coverage` (every product in `P` must have
   ≥1 compatible production or remanufacturing technology) and `_validate_capacity_feasibility`
   (network-wide max potential production+remanufacturing capacity per product must cover that
   product's largest single-period aggregate demand — the necessary, not sufficient, check the
   paper's `as:feas` describes) to `src/models/instance_loader.py`, wired into `validate()`.
   Verified against all 942 currently-committed instance files (base + experiments): zero
   failures. Verified both validators actually trigger on deliberately broken synthetic
   instances.
5. **#4, #5, #7-#11 fixed in the paper.** `app_data.tex` citation corrected to the real
   generator entrypoint; `alg_bounding_procedure.tex`/`alg_lower_bound.tex`/`alg_upper_bound.tex`
   rewritten to describe the actual Benders-style cut-generation procedure (relaxation master +
   per-iteration follower evaluation + cut), exploiting the structural fact that the follower's
   feasible region $\setX$ does not depend on $\taxhat$ (only the objective does) — this gives a
   *simpler and stronger* finite-termination bound ($\le\taxub-\taxlb+1$ iterations) than the
   original grid/bisection description. `05_solution_methodology.tex` and `app_proofs.tex`
   updated to match (Lemma `lb_validity`/`ub_validity` restated, `thm:convergence` proof
   rewritten, `rem:iter` rewritten). Smaller remarks added for #7 (big-$M$ derivation), #8
   (degenerate vehicle-hours fallback), #9 ($\setM_{ij}$ topology rule), #10 (`apu_q` table
   scope), #11 (`I`/`N` legacy alias). Full paper recompiles cleanly (39 pages, no undefined
   references).

**Recommend the paper's author re-read the rewritten Algorithm 1 / Lemma / proof text in
`05_solution_methodology.tex` and `app_proofs.tex` carefully before submission** — the underlying
argument was verified against the actual `shared_models.py`/`dbp_exact.py` mechanics (and is, if
anything, a tighter result than the original), but it is a substantive mathematical rewrite, not
a wording tweak, and deserves a human check.

**Pre-existing, unrelated test failures discovered during verification** (not caused by, and out
of scope of, this fix pass): `tests/test_solve_instances.py::test_solve_instances_writes_structured_results`,
`::test_solve_instances_supports_dbp_lf_lex_method`, `::test_solve_instances_supports_enumeration_lf_lex_method`
all assert `manifest["solver"]["tolerances"]["lex_epsilon_prime"] == 0.1`, but
`DEFAULT.lex_epsilon_prime` in `src/config/gap_tol.py:37` is `1e-6` with no CLI override wiring
that would produce `0.1` — a stale test expectation vs. current config default, unrelated to
`c_area`, the validators, or the tie-break comparator.
