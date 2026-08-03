# Autonomous Scientific Analysis System — Bilevel CLSC

A multi-agent framework for analysing this project's bilevel optimization campaign, writing it up,
and refusing to let a claim reach the paper above its evidence.

**Design principle**: the value of a multi-agent system here is not parallelism — it is
**separation of duties**. The agent that measures is not the agent that interprets; the agent that
interprets is not the agent that writes; the agent that writes is not the agent that reviews. Every
number carries a locator, and no stage can quietly upgrade the strength of a claim it inherited.

---

## Layout

```
.claude/
  README.md                  ← you are here
  PROJECT_MAP.md             ← what exists in this repo and where  (read first)
  agents/
    00_AGENT_PROTOCOL.md     ← binding contract: evidence tiers, compute rules, response envelope
    project-manager.md            mathematical-model-expert.md
    optimization-expert.md        data-auditor.md
    statistical-analyst.md        domain-expert.md
    scientific-reviewer.md        scientific-writer.md
    editor.md
  workflows/
    00_WORKFLOW_PROTOCOL.md  ← execution model, gates, dependency order
    wf1_analyze_new_results.md          wf5_review_analysis.md
    wf2_analyze_full_campaign.md        wf6_suggest_experiments.md
    wf3_compare_scenarios.md            wf7_identify_limitations.md
    wf4_write_results_discussion.md     wf8_generate_future_work.md
  templates/
    claim_ledger.md          ← the register every claim lives in
    analysis_report.md   data_audit_report.md   review_report.md
    experiment_card.md   results_section.md     finding.md
    limitation_register.md   future_work.md
  standards/
    evidence_and_claims.md   ← the E0–E4 tier system  (the spine)
    known_pitfalls.md        ← nine traps that already cost this project
    statistical_standards.md numerical_and_solver_standards.md
    writing_style.md         reproducibility.md
  commands/                  ← /wf1… /wf8 slash commands (thin wrappers over workflows)
```

---

## The nine agents

| Agent | Owns | Writes to |
|---|---|---|
| **project-manager** | orchestration, gates, arbitration, the claim ledger | reports, ledger |
| **mathematical-model-expert** | code ↔ LaTeX ↔ notation correspondence, dimensional analysis | nothing (proposes diffs) |
| **optimization-expert** | certificates, convergence, benchmark fairness, tolerance scales | nothing |
| **data-auditor** | completeness, integrity, provenance, replication support | audit reports |
| **statistical-analyst** | all inference — **and the code that computes it** | `src/clsc/analysis/stats/`, `scripts/`, `tests/` |
| **domain-expert** | physical/economic plausibility, policy meaning, external validity | nothing |
| **scientific-reviewer** | adversarial review; **its REJECT is binding** | review reports |
| **scientific-writer** | LaTeX prose from the ledger | `paper/sections/` |
| **editor** | consistency, units, refs, citations, compilation | `paper/` (mechanics only) |

Model and solver code (`src/clsc/models/`, `src/clsc/solvers/`, `src/clsc/generator/`) and the raw
evidence (`results/runs/`, `data/instances/`) are **read-only to every agent**. A system that can
rewrite the model it is auditing cannot audit it.

---

## The eight workflows

| Command | Does | Solver cost |
|---|---|---|
| `/wf1-analyze-new-results` | triage a fresh batch of runs | 0 |
| `/wf2-analyze-full-campaign` | the deep pass: promote every E3 claim to E1/E2 | 0 |
| `/wf3-compare-scenarios` | rigorous comparison with a comparability gate | 0 |
| `/wf4-write-results-discussion` | draft Results + Discussion from the ledger | 0 |
| `/wf5-review-analysis` | adversarial review with independent recomputation | 0 |
| `/wf6-suggest-experiments` | ranked, costed experiment proposals | 0 |
| `/wf7-identify-limitations` | six-class limitation sweep | 0 |
| `/wf8-generate-future-work` | future work traceable to limitations | 0 |

All eight are designed to run at **zero solver hours** against the 381 runs already on disk.
Anything that would solve stops at a human gate.

---

## The evidence tiers (the one thing to remember)

| Tier | Meaning | In the paper? |
|---|---|---|
| **E0** | certified by the solver or by exhaustive enumeration | yes |
| **E1** | measured — read from the master table or a manifest, with the filter stated | yes |
| **E2** | derived — computed by a committed, named script from E0/E1 | yes |
| **E3** | reported — asserted in `docs/Experimental_Plan.md` or `paper/`, no locator | **no** |
| **E4** | inferred — an agent's reasoning | **never a claim** |

Every claim currently in `docs/Experimental_Plan.md` is **E3**, including the correct ones, because
none carries a locator. Promoting them is the system's first job.

---

## Two things this system was built around

**1. The plan document has corrected its own published numbers at least four times.** Its §3
correction of 2026-08-03 retracted a τ\* median (≈50 → 22.6 USD/t) and a policy conclusion ("already
inside the 20–200 band" → only 6 of 12 cells are). That is *good practice* — and it is also why no
document that mixes specification with findings can be its own evidence base. Hence the ledger.

**2. The statistical layer does not exist in code.** `Experimental_Plan.md` §2.4 prescribes
Wilcoxon, Friedman+Nemenyi, Holm, ANOVA, Lenth, Benjamini–Hochberg, and BCa bootstrap; §10 reports
results from them. A repo-wide search finds **zero** implementing code, and `statsmodels` is not
installed while `scipy` is present but undeclared. Every exp6 statistic is therefore currently
unreproducible. Building that layer is the single highest-value action available, and it costs
**zero solver hours**.

---

## Quick start

```
/wf5-review-analysis docs/Experimental_Plan.md      # cheapest first look: what actually holds up
/wf2-analyze-full-campaign                          # the deep pass; builds the stats layer
/wf7-identify-limitations                           # then limitations
/wf8-generate-future-work                           # then future work
/wf4-write-results-discussion                       # then the paper
```

Agents can also be used individually — ask for one by name, e.g. *"use the data-auditor to check
exp6 completeness"*.

---

## Extending the system

- **New agent**: add `agents/<name>.md` with YAML frontmatter (`name`, `description`, `tools`,
  `model`) and the seven required sections (mission, responsibilities, inputs, outputs, rules,
  response format, quality criteria). Reference the protocol; do not restate it.
- **New workflow**: add `workflows/wfN_<name>.md` with a stage table (agent, task, gate), plus a
  thin `commands/wfN-<name>.md` wrapper. Respect the dependency order
  `audit → analyse → interpret → review → write → edit`.
- **New pitfall**: append to `standards/known_pitfalls.md` the moment it costs something. That file
  is the project's institutional memory and is the reason a fresh session does not repeat a
  mistake from three months ago.
