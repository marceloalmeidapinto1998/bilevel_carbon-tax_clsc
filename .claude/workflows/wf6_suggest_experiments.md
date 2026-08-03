# Workflow 6 — Suggest New Experiments

**Purpose**: identify what is still genuinely unknown, and propose the **cheapest** experiments
that would resolve it — ranked by contribution per hour, with the bad ideas rejected in writing.

**Solver cost**: 0. This workflow produces *proposals*. Nothing runs without a human decision.

**Entry**: `/wf6-suggest-experiments [research question or area]`

---

## Stages

| # | Agent | Task | Gate |
|---|---|---|---|
| 0 | project-manager | Assemble the open-question set from `claim_ledger.md` (OPEN, PARTIAL, INDICATIVE, CONTESTED, NOT SUPPORTED), `limitations_register.md`, and `PROJECT_MAP.md` §4–§5 | — |
| 1 | **data-auditor** | For each open question: **is it already answerable from data on disk?** 381 runs carry more than has been analysed. An answer found here costs zero hours | **BLOCKING** — anything answerable from disk is removed from the proposal set |
| 2 ‖ | **statistical-analyst** | Which questions need more data vs. better analysis? Where would replication actually change a conclusion, and where would it just add cost? Estimate the n required | — |
| 2 ‖ | **optimization-expert** | Which algorithmic questions remain? Cost each with a **measured** per-point rate from a comparable cell | — |
| 2 ‖ | **domain-expert** | Which questions would a domain referee ask that the campaign cannot yet answer? | — |
| 3 | project-manager | Write one **experiment card** per surviving proposal (`templates/experiment_card.md`); apply the rejection checks; rank by contribution per hour | — |
| 4 | **scientific-reviewer** | Attack each proposal: would the result actually change a conclusion? Is the design confounded? Is the hypothesis falsifiable? Is the cost estimate honest? | **BLOCKING** on REJECT per card |
| 5 | project-manager | Present the ranked, costed portfolio with a recommendation | **HUMAN** — only the human authorizes compute |

---

## Rejection checks (applied at stage 3, non-negotiable)

| Check | Rationale |
|---|---|
| Sweep / grid / factorial confined to **fast or standard** tier | exp2: 61.9 h on the hardest cell for one appendix paragraph (P5) |
| Not re-solving something already on disk | stage 1 exists to catch this |
| Cost estimate has a **measured** basis, cited | "should be quick" is not an estimate |
| States a claim promotion (tier before → after) | curiosity is not evidence |
| Hypotheses have refutation conditions | otherwise it cannot fail, so it cannot inform |
| Statistical plan pre-specified, with the computing code named | post-hoc analysis choice is how false positives enter |
| Cheaper alternatives section is non-empty | there is nearly always a cheaper partial answer |
| Does not relitigate a settled decision without new evidence | ρ\*=1, P4 dropped, exp2 never repeated, tier caps unchanged |

## Rules specific to this workflow

- **Analysis before data collection, always.** The highest-value item currently open —
  building the statistical layer and re-deriving §10 — costs **zero solver hours** and unblocks a
  whole paper section. Rank such items first, every time.
- **Contribution per hour is the ranking metric**, not logical dependency. exp5 produced the
  headline result in ~1.3 h; exp2 produced an appendix paragraph in 61.9 h.
- **Propose the smallest sufficient design.** If 16 runs on a fast cell answers it, do not propose
  64 on a standard cell.
- **Keep rejected cards.** A recorded rejection with its reason prevents the idea being
  re-proposed blind in six months.
- **Never launch anything.** Not even one cheap cell. The output is a portfolio and a
  recommendation.

## Output

- `results/analysis/campaign_01/reports/YYYY-MM-DD_wf6_proposals.md` — the ranked portfolio.
- One experiment card per proposal (accepted and rejected), in the same report or alongside it.

## Success criteria

- [ ] Every open question was first tested against data already on disk.
- [ ] Zero-solver-cost analysis items are ranked above data-collection items.
- [ ] Every card passes all rejection checks or is recorded as rejected with its reason.
- [ ] Every cost estimate cites a measured per-point rate from a named comparable cell.
- [ ] Every proposal names the ledger claim it would promote, and the tier transition.
- [ ] Cards are ranked by contribution per hour, with the metric shown.
- [ ] Nothing was launched.
