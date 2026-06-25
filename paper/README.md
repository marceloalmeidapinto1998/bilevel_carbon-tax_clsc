# Optimal Carbon Pricing of Closed-Loop Supply Chains: A Global-Optimisation of a Bi-Level Mixed-Integer Problem

## Project structure

```
bilevel-clsc-carbon/
├── main.tex                        ← compile this
├── references.bib                  ← BibTeX bibliography
├── README.md
├── styles/
│   ├── preamble.tex                ← packages, page layout, theorem envs
│   ├── macros.tex                  ← math operators and notation
│   └── tikz_styles.tex             ← TikZ node/edge styles
├── sections/
│   ├── 00_abstract.tex
│   ├── 01_introduction.tex
│   ├── 02_literature_review.tex
│   ├── 03_problem_description.tex  ← qualitative description only
│   ├── 04_mathematical_model.tex   ← Section 4 orchestrator; inputs 4a–4c
│   ├── 04a_notation.tex            ← assumptions, notation, auxiliary exprs
│   ├── 04b_formulation.tex         ← follower cost/emissions, bilevel program
│   ├── 04c_feasible_region.tex     ← constraint blocks (C1)–(C10), domains
│   ├── 05_solution_methodology.tex
│   ├── 06_computational_experiments.tex
│   └── 07_conclusion.tex
├── tables/
│   ├── tab_notation.tex            ← sets, parameters, decision variables
│   ├── tab_instances.tex
│   ├── tab_results_main.tex
│   └── tab_comparison.tex
├── algorithms/
│   ├── alg_bounding_procedure.tex  ← main DBP algorithm
│   ├── alg_lower_bound.tex         ← LB subroutine (inlined)
│   └── alg_upper_bound.tex         ← UB subroutine (inlined)
├── appendix/
│   ├── app_proofs.tex
│   ├── app_additional_results.tex
│   └── app_data.tex
├── cover/
│   ├── cover_letter.tex
│   ├── highlights.tex
│   └── author_statement.tex
└── figures/                        ← PDF/PNG figures
```

## Build instructions

### Local (command line)

```bash
pdflatex main
bibtex main
pdflatex main
pdflatex main
```

### Overleaf

1. Create a new project → **Upload Project** → zip this folder.
2. Project Settings → **Compiler**: `pdflatex`; **Main document**: `main.tex`.
3. Click **Recompile**.

## Section 4 (Mathematical Model) — organization

The formulation is split into three self-contained subfiles so that
each part can be edited without regenerating the whole section:

| File | Content |
|------|---------|
| `04_mathematical_model.tex`  | Section header + NP-hardness proposition; orchestrates the three subfiles. |
| `04a_notation.tex`           | Modeling assumptions (A1–A6); admissible-flow tuple $\Phi$; Sets/parameters/variables tables (via `tables/tab_notation.tex`); auxiliary expressions $X^{\mathrm{in}}$, $X^{\mathrm{out}}$, $\bar y_i$, $YCT_{it}$ (finished-product inventory area at warehouses only). |
| `04b_formulation.tex`        | Total cost $C(\mathbf z)$; total emissions $E(\mathbf z)$; follower problem; leader bilevel program. |
| `04c_feasible_region.tex`    | Ten constraint blocks (C1)–(C10) + variable domains. Each block is grouped with `subequations` and uses `alignat{2}` for consistent alignment. |

## Typographic conventions

- Equations numbered per section (`\numberwithin{equation}{section}`).
- `\allowdisplaybreaks` permits multi-page aligned equations.
- Constraint groups use `subequations` so the block has a single label
  (e.g. `\ref{eq:c6_techcap}`) and members carry individual sublabels.
- Theorems/propositions/lemmas/corollaries share a single counter;
  assumptions are numbered A1, A2, … with `\renewcommand{\theassumption}`;
  remarks share the theorem counter.
- `cleveref` is configured with `capitalize, nameinlink`.

## Required packages (all available on Overleaf)

`amsmath`, `amssymb`, `amsthm`, `mathtools`, `bm`, `algorithm2e`,
`booktabs`, `multirow`, `makecell`, `tabularx`, `longtable`, `dcolumn`,
`graphicx`, `subcaption`, `tikz`, `pgfplots`, `xcolor`, `hyperref`,
`cleveref`, `siunitx`, `microtype`, `lmodern`, `setspace`, `lineno`,
`geometry`, `enumitem`, `caption`, `natbib`.

Bibliography style: `plainnat`. Change in `main.tex` to match your
target journal (e.g. `elsarticle-num` for EJOR).

## Compilation status

Clean compile with `pdflatex` + `bibtex` (29 pages, zero undefined
references, zero missing citations).
