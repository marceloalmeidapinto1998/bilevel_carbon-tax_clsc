---
description: Draft publication-ready Results and Discussion from the claim ledger
argument-hint: [section scope]
---

Run workflow **wf4_write_results_discussion** of the scientific analysis system.

1. Read `.claude/workflows/00_WORKFLOW_PROTOCOL.md` and `.claude/workflows/wf4_write_results_discussion.md` in full.
2. Read `.claude/PROJECT_MAP.md`, `.claude/agents/00_AGENT_PROTOCOL.md`, and `.claude/standards/known_pitfalls.md`.
3. Act as **project-manager** (`.claude/agents/project-manager.md`): publish the PLAN block, then delegate each stage to its named agent with the `Agent` tool using `subagent_type` set to that agent's name.
4. Enforce every gate. A `BLOCKING` gate stops the workflow; a `HUMAN` gate stops and asks. Never authorize solver compute yourself.
5. Write the dated report to `results/analysis/campaign_01/reports/` and update the claim ledger.

Scope for this run: $ARGUMENTS
