# EJOR manuscript

The manuscript for the *European Journal of Operational Research*, its Supplementary Material, highlights and cover letter. This LaTeX source is the reference version; the Claude Doc of 22 October 2026 is older.

## Compile

```
latexmk -pdf main.tex           # manuscript first: the supplement reads its .aux for cross-references
latexmk -pdf supplementary.tex
latexmk -pdf highlights.tex
latexmk -pdf cover_letter.tex
```

Do not run `latexmk -c` between the manuscript and the supplement: `supplementary.tex` takes the numbers of the manuscript's equations, tables and sections from `main.aux` (package `xr-hyper`).

The references use biblatex with the `apa` style and **biber**, not BibTeX. Without latexmk, run `pdflatex main`, `biber main`, `pdflatex main`, `pdflatex main`, then the same for `supplementary`. Tested with MiKTeX 25.12 (pdfTeX 4.23, elsarticle 3.5, biblatex-apa).

Both documents compile with no errors and no overfull or underfull boxes. Four hyperref warnings remain in `main` ("Token not allowed in a PDF string"); they come from the corresponding-author mark in the PDF metadata and do not affect the PDF.

## Files

| File | What it is |
| --- | --- |
| `main.tex` | Manuscript, 26 pages: elsarticle, option `review` (single column, 1.5 line spacing), 11 pt, A4 with 2.5 cm margins. The model is complete in Section 2 (notation, cost, emissions, every constraint and valid inequality) |
| `supplementary.tex` | Supplementary Material, 9 pages: the original instances' fixed-tax and sensitivity analyses (S1), the case study's sensitivity (S2), the robustness checks (S3) and the enumeration on all 24 calibrated instances (S4) |
| `references.bib` | Verified Crossref and DataCite records; biblatex prints only the cited ones (45 in the manuscript) |
| `highlights.tex`, `highlights.txt` | Highlights (5 bullets, at most 85 characters, no acronyms) |
| `cover_letter.tex` | Cover letter to the editor |
| `figures/staircase.pdf` | Figure 1, from `python paper/tools/make_figure.py` |
| `figures/sensitivity_tornado.pdf` | Figure S1 (original instances), from `python -m clsc.experiments figures` |
| `tools/make_tables.py` | Writes the rows of Tables 5, 6 and 7 and of Table S4 from `results/experiments`; run from the repository root |

No separate title page: EJOR uses single-anonymized review, so the author details stay in the manuscript.

## Where the numbers come from

Every number in Section 4 comes from `results/experiments` (experiments P1, E1, E2, C1, C2 and C3 of `src/clsc/experiments/plan.py`). `python paper/tools/make_tables.py` rewrites the table rows between their `%% BEGIN table` and `%% END table` markers and prints the aggregates the text quotes; `python paper/tools/make_figure.py` draws Figure 1. The calibrated set in the manuscript is replicates 0 and 1 (24 instances); replicate 2 and the escalation sizes are generated in `data/calibrated` for a revision. The case study's enumeration figures (seven taxes in 1 h, six follower solves on their time limit, the best value 0.85% above the DBP's upper bound) are those of the pilot run logged in `results/experiments/run_E1E2_pilot.log`.

## EJOR requirements checked

Source: EJOR Guide for Authors, read from the Wayback Machine capture of 10 February 2024 (the live page refuses scripted access). Check the live guide before submitting: https://www.sciencedirect.com/journal/european-journal-of-operational-research/publish/guide-for-authors

| Requirement | Status |
| --- | --- |
| At most 30 pages, including abstract, figures, tables and references | 26 pages |
| Single column, 11 pt, 1.5 line spacing, no line numbers | Done |
| Abstract of 50 to 250 words, no formulae, references or unexplained acronyms | 161 words, no numbers, only CLSC as acronym |
| First keyword from the EJOR list, at most 5 | "OR in environment and climate change" plus 4 |
| Highlights: 3 to 5 bullets, at most 85 characters, no acronyms | Done |
| APA references with DOIs | Done (biblatex-apa) |
| Declarations of interest, funding, data, generative AI | Sections present, to be completed |

## To fill in before submission (`TODO` in the files)

- ORCID iDs of the authors (`main.tex`). Authors, affiliations and the corresponding author (Samuel Moniz) are those of Pinto et al. (2024); the cover letter is signed by the corresponding author.
- CRediT roles of every author.
- FCT grant reference, or the no-funding sentence.
- Repository URL and archived DOI for the data statement.
- The generative AI declaration: say what the tool was used for.
- Confirm "Declarations of interest: none".
