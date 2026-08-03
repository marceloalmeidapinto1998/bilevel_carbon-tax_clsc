# AGENT PROTOCOL — binding on every agent in this system

Not an agent. The shared contract each agent file incorporates by reference. Where an agent's own
file contradicts this document, **this document wins**, except where the agent explicitly states
"overrides protocol §N" with a reason.

---

## §1. Reading order (mandatory, every invocation)

1. `.claude/PROJECT_MAP.md` — what exists and where.
2. `.claude/standards/evidence_and_claims.md` — the evidence tiers and the provenance rule.
3. `.claude/standards/known_pitfalls.md` — the four traps that have already cost this project.
4. Your own agent file.
5. Only then: the artifacts your task names.

Do not skip step 3 because a task "looks simple". Every pitfall in that file was discovered *after*
someone made the mistake.

---

## §2. The provenance rule

> **No agent states a number without saying where it came from.**

Every quantitative claim carries an evidence tier (E0–E4) and a locator. Format:

`τ* = 8.0 USD/t [E1: master_runs_campaign_01.csv, experiment_id=exp3_ablation,
base_instance_id=STD_I17_M4_T3, algorithm_variant=M0, seed_offset=0 → leader_tax_usd_per_tonne]`

Tiers are defined in `standards/evidence_and_claims.md`. The short form:

| Tier | Meaning |
|---|---|
| **E0** | Certified by the solver (gap ≤ tolerance) or by exhaustive enumeration |
| **E1** | Measured — read directly from the master table or a run manifest |
| **E2** | Derived — computed by a named, committed script from E0/E1 inputs |
| **E3** | Reported — asserted in `docs/Experimental_Plan.md` or `paper/`, not re-verified |
| **E4** | Inferred — an agent's reasoning, no data behind it |

**Only E0–E2 may enter the paper.** E3 must be promoted to E1/E2 or dropped. E4 is never a claim;
it is a hypothesis and must be labelled one.

If you cannot locate the provenance of a number, say so explicitly:
`UNTRACEABLE: <number> appears in <source> but no run or script produces it.` That sentence is a
finding, not a failure.

---

## §3. Compute authorization

The campaign cost 119.6 h of Gurobi time across 381 runs. Re-solving is not free and is not
reversible in wall-clock terms.

**Never run without explicit human authorization in the current session:**
- `python -m clsc.campaign.orchestrator run ...`
- `python -m clsc.solver_cli.solve_batch ...`
- anything that constructs a Gurobi model and calls `optimize()`
- `python -m pytest` without `-m "not slow"` (the slow/gurobi marks solve real models)

**Always safe, run freely:**
- `python -m clsc.analysis.campaign_01.aggregate`
- `python scripts/make_campaign_01_tables.py`, `python scripts/make_campaign_01_figures.py`
- `python -m pytest -m "not slow"`
- any read of `results/`, `data/`, `experiments/`, `docs/`, `paper/`

To request compute, emit a **COMPUTE REQUEST** block (see §5) and stop. Do not launch and ask
later. An agent that wants one cheap solve must still ask.

---

## §4. Write boundaries

| Path | Who may write |
|---|---|
| `results/analysis/campaign_01/reports/` | any agent — this is the system's output surface |
| `src/clsc/analysis/**` | Statistical Analyst only |
| `scripts/**` | Statistical Analyst only |
| `paper/sections/**`, `paper/tables/**` | Scientific Writer, then Editor |
| `docs/Experimental_Plan.md` | Project Manager only, and only to record *decisions*, never results |
| `src/clsc/models/**`, `src/clsc/solvers/**`, `src/clsc/generator/**` | **nobody** — propose a diff, a human applies it |
| `results/runs/**`, `data/instances/**` | **nobody** — these are the evidence base; altering them destroys provenance |
| `tests/**` | Statistical Analyst (new stats tests only); other changes are proposals |

Model and solver code is read-only to this system by design. A multi-agent system that can rewrite
the model it is evaluating cannot audit it.

---

## §5. Response format

Every agent returns this envelope. Sections may be empty but must not be omitted.

```markdown
## VERDICT
<one sentence — the answer, not a summary of the process>

## EVIDENCE
| # | Claim | Value | Tier | Locator |
|---|---|---|---|---|
| 1 | ... | ... | E1 | master_runs...csv :: filter |

## REASONING
<why the evidence supports the verdict; the inferential steps, numbered where non-obvious>

## UNCERTAINTIES
<what would change the verdict; what is E3/E4 and still load-bearing; what you could not check>

## HANDOFF
to: <agent-name | human>
question: <the specific thing you need decided or done>
blocking: <yes|no>
```

Extra blocks, used when applicable:

```markdown
## COMPUTE REQUEST
command: <exact command>
cells: <which instances/design points>
estimated cost: <hours, with the basis for the estimate>
buys: <what claim this promotes, and from which tier to which>
alternative: <the cheapest thing that would partly answer this without solving>
```

```markdown
## DEFECT
severity: <blocker | major | minor>
location: <file:line>
observed: / expected: / consequence:
```

---

## §6. Disagreement

Agents will disagree. That is the point of having more than one.

1. **State the disagreement in the envelope**, do not resolve it silently by preferring your own
   analysis.
2. **Disagreements about a number** are settled by recomputation from E0/E1 — whoever can produce
   the locator wins, regardless of seniority in the workflow.
3. **Disagreements about interpretation** are escalated to the Project Manager, who records both
   positions in the report and marks the claim `CONTESTED`. A contested claim may not enter the
   paper until resolved.
4. **The Scientific Reviewer's objections are not advisory.** A workflow stage gated by the
   Reviewer does not proceed on a `REJECT` verdict. The Project Manager may overrule only by
   escalating to the human with both arguments stated.

Never manufacture consensus. "All agents agree" in a report where they did not is a fabrication.

---

## §7. Honesty rules specific to this project

- **Censored ≠ invalid.** Distinguish `termination_reason="wall_clock_cap"` (real incumbent,
  certified gap, usable) from `"wall_clock_cap_killed"` (nothing usable). Never impute a censored
  runtime; report it as censored.
- **Negative and non-monotone results are results.** H7.1 was not supported and that is reported
  as a finding. Do not smooth, do not fit a model whose premise the data rejects, do not quietly
  drop a cell that disagrees.
- **A single seed proves nothing on a standard/fast cell.** Cross-seed CV reaches 40–50 %.
  Comparisons are paired within seed.
- **Report n, always.** "6/6 cells" not "all cells". "3 of 4, 4th censored" not "confirmed".
- **Do not relitigate settled decisions.** ρ\*=1, P4 dropped, exp2 never repeated, tier caps
  unchanged — all decided with reasons on record (`Experimental_Plan.md` §14). Reopen only with
  new evidence, and say what the new evidence is.

---

## §8. Scope discipline

Do the task you were given. If you find something important outside it, put it in `UNCERTAINTIES`
or emit a `DEFECT` block and hand off — do not expand your own remit. A Data Auditor that starts
writing paper prose, or a Writer that starts re-running statistics, breaks the audit chain that
makes this system trustworthy.
