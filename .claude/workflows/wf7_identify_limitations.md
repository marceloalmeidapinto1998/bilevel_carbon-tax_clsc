# Workflow 7 — Identify Model and Study Limitations

**Purpose**: systematically enumerate what this study cannot support — before a referee does it for
you — across model scope, data scope, algorithm, statistics, reproducibility, and external validity.

**Solver cost**: 0.

**Entry**: `/wf7-identify-limitations [scope]`

---

## Stages

| # | Agent | Task | Class | Gate |
|---|---|---|---|---|
| 0 | project-manager | Load `limitations_register.md`; scope the sweep; assign classes | — | — |
| 1 | **mathematical-model-expert** | What the formulation does not represent, and what its stated assumptions cost: optimistic response, deterministic parameters, single uniform instrument, discrete grid, the Mota-aligned simplifications | **L-MOD** | — |
| 2 | **data-auditor** | What the testbed does not cover: 12 cells at 2×2×3, seeds per tier, censored runs, missing arms, the single-cell structural screen, the n = 1 AUGMECON anchor | **L-DAT** | — |
| 3 | **optimization-expert** | Precision and tractability boundaries: the H5.3 cold-solve discrepancy, the anchored-not-resolved M12 frontier, exp8's incomplete coverage, tolerance-scale sensitivity | **L-ALG** | — |
| 4 | **statistical-analyst** | Power, assumptions, multiplicity, unreplicated designs, the Lenth failure, the n = 6 p-floor — **and the absence of any committed statistical code** | **L-STA** | — |
| 5 | **domain-expert** | External validity: one generator family, one geography, the inherited emissions-valuation scale, the 6-of-12 band fact, what class of real supply chains this speaks to | **L-EXT**, **L-MOD** | — |
| 6 | project-manager | Reproducibility limitations: undeclared `scipy`, the two table families, analysis findings living in a self-correcting planning document | **L-REP** | — |
| 7 | **scientific-reviewer** | **What did they miss?** Adversarially find limitations no agent listed. This is the stage that earns the workflow | — | **BLOCKING** if it finds a fundamental one that was missed |
| 8 | project-manager | Merge into the register; assign severity; map each to the claim it bounds; mark disclosure status | — | — |

---

## Rules specific to this workflow

- **Every limitation names the claim it bounds.** A limitation that bounds nothing is either
  irrelevant or a claim you have not noticed you are making.
- **Severity is about the contribution, not about embarrassment.** `fundamental` bounds the
  contribution; `material` bounds a specific claim; `minor` changes nothing but is worth stating.
- **Distinguish "not studied" from "does not hold".** The pessimistic bilevel case is not studied —
  that is not the same as the optimistic result being wrong, and the paper must not blur them.
- **Do not list generic caveats.** "The model is a simplification of reality" is true of every
  model and informs nobody. Every entry must be specific to *this* study.
- **A limitation is closed only by evidence at E0–E2**, never by an argument.
- **Stage 7 is the point of the workflow.** Agents are systematically blind to the limitations of
  their own analyses; the Reviewer's independent sweep is what catches those.

## Output

Updated `results/analysis/campaign_01/reports/limitations_register.md`, plus
`YYYY-MM-DD_wf7_limitations.md` recording what was newly found, what was closed, and what the
Reviewer caught that the specialists missed.

## Success criteria

- [ ] All six classes (L-MOD, L-DAT, L-ALG, L-STA, L-REP, L-EXT) were swept.
- [ ] Every limitation names the claim it bounds and carries a severity.
- [ ] Every limitation is specific to this study — no generic modelling caveats.
- [ ] "Not studied" and "does not hold" are distinguished throughout.
- [ ] The Reviewer's independent sweep ran and its additions are marked as such.
- [ ] Every entry has a disclosure status: in the paper, or explicitly deferred with a reason.
