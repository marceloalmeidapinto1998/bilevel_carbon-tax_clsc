# Workflow 4 — Write "Results and Discussion"

**Purpose**: produce publication-ready LaTeX for the paper's Results and Discussion, where every
sentence traces to a verified claim.

**Solver cost**: 0.

**Entry**: `/wf4-write-results-discussion [section scope]`

**Precondition** (hard): `claim_ledger.md` exists and the claims to be written are at tier **E0–E2**.
If they are still E3, this workflow **stops** and hands off to wf2. Writing from E3 is how a wrong
median reaches a manuscript.

---

## Stages

| # | Agent | Task | Gate |
|---|---|---|---|
| 0 | project-manager | Verify the precondition. List every claim to be written, with tier and status. Any E3 → stop, hand to wf2 | **BLOCKING** |
| 1 | **data-auditor** | Confirm the generated tables and figures are current: are `t*.tex` / `fig*.pdf` newer than the master table, and the master table newer than the newest run? If not, regenerate (safe) and say so | **BLOCKING** |
| 2 ‖ | **optimization-expert** | Supply exact phrasings for every algorithmic claim — the sentence the Writer may use, and no stronger | — |
| 2 ‖ | **domain-expert** | Supply the interpretive material for the Discussion: policy meaning, mechanisms (labelled demonstrated or hypothesised), validity envelope, external-validity limits | — |
| 3 | **scientific-writer** | Draft Results (ordered by contribution, per `templates/results_section.md`) and Discussion. Produce the claim–sentence map and the gap list | — |
| 4 | **scientific-reviewer** | Review the draft: claim–evidence audit, overreach scan, **mandatory disclosure check**, the three bilevel-referee questions | **BLOCKING** on REJECT |
| 5 | **scientific-writer** | Revise against objections. Any objection not addressed must be answered in writing | — |
| 6 | **editor** | Consistency sweep, units/symbols, decimal marks, cross-references, citations, table-family reconciliation, compilation | — |
| 7 | project-manager | Final check: disclosures still present **after** editing; ledger reconciles with the claim–sentence map | — |

---

## Rules specific to this workflow

- **The Writer writes from the ledger, never from the master table.** If a needed number is not in
  the ledger, it goes on the gap list and is requested — never estimated, never inferred from a
  table the Writer happens to be looking at.
- **All seven disclosures must appear in the main text**, not in footnotes or an appendix:
  H7.1 not supported · H6.2 partial · exp8 3/4 · exp5 H5.3 precision bound · exp6 Lenth failure ·
  exp4 M12 censored · 6-of-12 policy band.
- **Results reports; Discussion interprets.** A number appearing first in the Discussion is a defect.
- **Re-check disclosures after stage 6.** Editing for concision is exactly what deletes them; they
  read like removable hedges and are not.
- **Tables are `\input`, figures are `\includegraphics` from the generated directory** — never
  retyped (P9).
- **Convert decimal marks** from the plan's Portuguese `,` to `.`.

## Output

- `paper/sections/06_computational_experiments.tex`, `07_discussion.tex` (and `00_abstract.tex`,
  `08_conclusion.tex` if in scope).
- `results/analysis/campaign_01/reports/YYYY-MM-DD_wf4_writing_<scope>.md` — the claim–sentence
  map, the gap list, the review objections and their resolutions, the editor's consistency report.

## Success criteria

- [ ] Every numeric sentence maps to a ledger claim at E0–E2.
- [ ] Every numeric sentence carries n, cells, and certification status.
- [ ] All seven disclosures are present in the main text **after** the final editing pass.
- [ ] Results contains no interpretation; Discussion introduces no new numbers.
- [ ] The reviewer's verdict is ACCEPT or MINOR REVISION.
- [ ] The document compiles; the editor's consistency sweep found no unresolved discrepancy.
- [ ] The gap list is empty, or every remaining gap is explicitly deferred with a reason.
