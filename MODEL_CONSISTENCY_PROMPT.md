Audit the BilevelModel_CLSC project for three-way consistency between (A) the mathematical model
as written in the paper, (B) the mathematical model as implemented in code, and (C) the instance
data that feeds that code. This is a verification pass, not a refactor — produce a findings report;
do not fix anything unless explicitly told to, since some divergences may be intentional
simplifications and need the user's judgment call.

## The three sources of truth

- **(A) Paper.** `paper/sections/04_mathematical_model.tex` (intro), `04a_notation.tex` (sets,
  assumptions, parameters, decision variables, auxiliary expressions — start here, it's the
  glossary), `04b_leader.tex` (leader/regulator problem), `04c_follower.tex` (follower/operator
  problem — constraints and objective), `paper/tables/tab_notation.tex` (symbol tables referenced
  from 04a), and `paper/appendix/app_proofs.tex` / `app_data.tex` for anything proved or
  parameterized there. `paper/styles/macros.tex` defines the LaTeX macros for set/parameter
  symbols (e.g. `\setF`, `\taxhat`) — resolve macros there if a symbol's meaning is unclear.
- **(B) Code.** `src/models/shared_models.py` (the actual Gurobi model: `addVar`/`addVars` calls
  define decision variables, `addConstr`/`addConstrs` calls define constraints — this is the
  primary file to check against the paper's equations) and `src/models/elastic_models.py`
  (elastic/relaxed variants). `src/models/instance_loader.py` defines how raw instance JSON is
  parsed into the parameter/set dictionaries the model consumes (`_normalize_sets`,
  `_apply_parameter_defaults`, `_validate_*` functions) — this is where you can check that every
  parameter the paper defines has a corresponding key the loader expects, and vice versa.
- **(C) Instances.** `data/generator/instance.py` (`generate_instance`, `write_instance`) is what
  actually produces parameter values (e.g. `f_w`, `c_area_f`, `c_area_w` at instance.py:551-553) —
  treat this as the authoritative definition of how each parameter is computed/sampled.
  `data/generator/config.py`/`sampling.py`/`geometry.py` hold the distributions and bounds behind
  those values. `data/instances/experiments/*.json` are current-generator instances; the files
  under `data/instances/base/*.json` are KNOWN STALE (predate the `f_w`/`c_area_*` addition — see
  project memory) and getting flagged again for that specific gap is not useful. If you find other,
  *different* gaps in the base instances beyond the already-known one, report them, but don't
  re-report the known one as new.

## What to check

1. **Sets and indices.** Every set in `04a_notation.tex` §Sets ($\setS,\setF,\setW,\setR,\setH$,
   $\setU,\setP,\setK,\setQ,\setG,\setL,\setM$, etc., plus derived sets like $\setNo$, $\setNv$,
   $\Omega^{\mathrm p}$, $\Omega^{\mathrm r}$) should map to a corresponding key in the instance
   JSON `sets` block and a corresponding variable/loop in `shared_models.py`. Flag: paper sets with
   no code/instance counterpart, or code/instance sets/loops with no paper definition.
2. **Parameters.** For every parameter in the notation tables (economic, capacity, demand,
   emission — `tab_econ_params`, `tab_capacity_params`, `tab_demand_params`, `tab_emission_params`),
   confirm (a) it is read somewhere in `shared_models.py` or `instance_loader.py` under a
   recognizable name, (b) the instance generator actually produces it, (c) units match — the paper
   states units in the notation table/assumptions (e.g. tax rate $\tau=\taxhat/100$ USD/kg CO$_2$e
   per `04a_notation.tex:142`); check `instance_loader.py`'s `_normalize_tax_parameter_units` /
   `_validate_unit_conventions` enforce the same convention, and that the generator emits values in
   that convention rather than e.g. per-tonne.
3. **Decision variables.** The follower vector
   $\bz=(y,YC,\lambda^{\mathrm p},\lambda^{\mathrm r},a,\sigma,\zeta,\kappa,Q,K,q^{\mathrm
   p},q^{\mathrm r},s^{\mathrm{inv}},s^{\mathrm{inv,r}},x)$ (`04a_notation.tex:150-153`) and the
   leader's $\hat\tau$ should each correspond to one `addVar`/`addVars` call in
   `shared_models.py`. Check variable domains too (binary/integer/continuous, lower/upper bounds) —
   e.g. $\hat\tau\in\{\taxlb,\ldots,\taxub\}$ vs `hat_tau = model.addVar(vtype=GRB.INTEGER,
   lb=lower_hat_tau, ub=upper_hat_tau, ...)` at shared_models.py:394. Report any paper variable
   with no matching `addVar`, or any modeled variable with no paper symbol (could be a legitimate
   implementation auxiliary — note it as such rather than flagging as an error).
4. **Auxiliary expressions.** $X^{\mathrm{in}}_{qit}$, $X^{\mathrm{out}}_{qit}$, $\bar y_i$,
   $YCT_{it}$ (`04a_notation.tex:174-208`) are shorthands the follower constraints build on. Find
   where (if anywhere) these are materialized in `shared_models.py` (e.g. inflow/outflow
   aggregation expressions feeding flow-balance constraints, or the `installed_area`/`YC` variable
   at shared_models.py:857 vs the $YCT_{it}$ floor-area expression) and check the algebra matches,
   not just that something with a similar name exists.
5. **Constraints, equation by equation.** Go through `04c_follower.tex` constraint-by-constraint
   (flow balance, capacity, technology-selection linking, inventory, demand satisfaction, hub
   cross-docking with no storage, emissions accounting, big-M / linking constraints) and match each
   to its `addConstr`/`addConstrs` call in `shared_models.py`. For each, check: (a) it exists, (b)
   the coefficients/sign/direction match (e.g. $\le$ vs $=$ vs $\ge$), (c) any big-M or
   linearization constant used in code is consistent with the paper's stated linearization (if the
   paper has one) or is at least not silently changing model semantics, (d) indices range over the
   same sets as the paper (e.g. is a sum over $\setM_{ij}$ in the paper but over all of $\setM$ in
   code — a common source of silent bugs).
6. **Leader problem.** `04b_leader.tex` — confirm the leader's objective/feasible region
   ($\hat\tau\in\mathcal T^\tau$, optimistic bilevel convention per assumption `as:opt`) matches how
   the DBP solvers in `src/solvers/` (`dbp_certified.py`, `dbp_exact.py`, `dbp_f_lex_exact.py`,
   `dbp_lf_lex_exact.py`, `enum_lf_lex_exact.py`) enumerate/bound $\hat\tau$ and pick among
   follower-optimal ties (lowest emissions, per `as:opt` — check this tie-break is actually
   implemented, not just assumed).
7. **Assumptions as code/data invariants.** Each lettered assumption in §Assumptions
   (`as:det`, `as:lin`, `as:emis`, `as:lead`, `as:dem`, `as:hub`, `as:feas`, `as:stackelberg`,
   `as:fixednet`, `as:singleop`, `as:opt`) is a claim about the model that the code should either
   enforce structurally or that the data generator should satisfy by construction. For each, name
   the file/function that relies on or enforces it, or flag it as an assumption with no
   corresponding code/data check (not necessarily wrong, but worth knowing — e.g. `as:feas`
   explicitly says feasibility "can be verified a priori" — check whether anything in
   `data/generator/` or `instance_loader.py` actually performs that verification, or whether it's
   left to chance).
8. **Instance validation vs. paper constraints.** `instance_loader.py`'s `_validate_*` functions
   (`_validate_arc_sets`, `_validate_pair_sets`, `_validate_flow_sets`,
   `_validate_distance_coverage`, `_validate_mode_parameters`, `_validate_unit_conventions`) encode
   some subset of the paper's structural requirements (e.g. $\Omega^{\mathrm p}$/$\Omega^{\mathrm
   r}$ compatibility, $\setM_{ij}\subseteq\setM$ coverage). Identify which paper-level structural
   requirements have a validator and which don't — gaps here mean a malformed instance could
   silently violate the paper's model assumptions and still solve.

## How to report

For each finding, give: the paper location (section/equation/line), the code location
(file:line), and the instance/data location if relevant, then a one-line verdict — **consistent**,
**inconsistent** (say exactly how), or **untraceable** (couldn't find a corresponding piece in one
of the three sources). Group findings by severity: (1) likely correctness bugs — silent mismatch
that would produce wrong solver results, (2) notation/documentation drift — code and data agree
with each other but disagree with what the paper claims (or vice versa), (3) minor/cosmetic.

Do not modify `data/instances/base/*.json` or re-litigate the known `f_w`/`c_area_*` gap there.
Do not change solver/model behavior in `src/models/` or `src/solvers/` as a side effect of this
audit — this is read-only verification.
