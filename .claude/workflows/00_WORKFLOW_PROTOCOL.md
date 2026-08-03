# WORKFLOW PROTOCOL

How workflows are executed, gated, and combined. Binding on every workflow in this directory.

---

## 1. Execution model

Every workflow is driven by **project-manager**, which delegates each stage to the named agent via
the `Agent` tool (`subagent_type: <agent-name>`), collects the envelope, applies the gate, and
proceeds or stops.

Stages run **sequentially unless marked ‖ (parallel)**. Parallel stages must be genuinely
independent — no stage may read another parallel stage's output.

## 2. The universal dependency order

```
audit  →  analyse  →  interpret  →  review  →  write  →  edit
```

Nothing writes prose from unaudited data. Nothing is reviewed before it is interpreted. This order
is not negotiable; a workflow that appears to need otherwise is mis-specified.

## 3. Gates

| Gate | Meaning |
|---|---|
| `BLOCKING` | The workflow **stops** on a negative verdict. The Project Manager reports the block and the required fix to the human. |
| `ADVISORY` | A negative verdict is recorded in the report; the workflow continues. |
| `HUMAN` | Requires explicit human approval in-session. Always used for solver compute. |

Standing gates:
- **data-auditor `BLOCKED`** → BLOCKING.
- **scientific-reviewer `REJECT`** → BLOCKING.
- **any COMPUTE REQUEST** → HUMAN.

## 4. Every workflow produces

1. A dated report under `results/analysis/campaign_01/reports/`.
2. Updates to `claim_ledger.md` — every claim it touched, with tier/status before and after.
3. Updates to `limitations_register.md` if it found or closed a limitation.
4. An explicit statement of what it did **not** do and why.

## 5. Resumability

The Project Manager records stage state with TodoWrite. A workflow interrupted mid-stage resumes at
the last incomplete stage — it does not restart. Completed stage outputs are on disk; re-running a
stage that already produced a report is waste.

## 6. Cost discipline

Workflows here are **analysis-only by default**. Every one of them is designed to run at **zero
solver hours** against the existing 381 runs. Any workflow stage that would solve emits a COMPUTE
REQUEST and stops at a HUMAN gate.

## 7. Workflow index

| ID | Name | Purpose | Solver cost |
|---|---|---|---|
| `wf1` | analyze-new-results | Triage a fresh batch of runs | 0 |
| `wf2` | analyze-full-campaign | End-to-end campaign analysis; promote E3 → E1/E2 | 0 |
| `wf3` | compare-scenarios | Rigorous comparison of conditions/variants/methods | 0 |
| `wf4` | write-results-discussion | Draft the paper's Results and Discussion | 0 |
| `wf5` | review-analysis | Adversarial review of an existing analysis | 0 |
| `wf6` | suggest-experiments | Propose and cost new experiments | 0 (proposals only) |
| `wf7` | identify-limitations | Systematic limitation sweep | 0 |
| `wf8` | generate-future-work | Derive future work from limitations | 0 |

Invocation: `/wfN-<name>` (see `.claude/commands/`), or by asking project-manager to run it.
