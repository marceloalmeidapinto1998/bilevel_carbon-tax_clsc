# Manuscript

The manuscript, its Supplementary Material and highlights. This LaTeX source is the reference version; the Paper tab of the Claude Doc mirrors it.

## Compile

```
latexmk -pdf main.tex           # manuscript first: the supplement reads its .aux for cross-references
latexmk -pdf supplementary.tex
latexmk -pdf highlights.tex
```

Do not run `latexmk -c` between the manuscript and the supplement: `supplementary.tex` takes the numbers of the manuscript's equations, tables and sections from `main.aux` (package `xr-hyper`).

The references use biblatex with the `apa` style and **biber**, not BibTeX. Without latexmk, run `pdflatex main`, `biber main`, `pdflatex main`, `pdflatex main`, then the same for `supplementary`. Tested with MiKTeX 25.12 (pdfTeX 4.23, elsarticle 3.5, biblatex-apa).

Both documents compile with no errors, no overfull or underfull boxes and no undefined or multiply defined labels. Four hyperref warnings remain in `main` ("Token not allowed in a PDF string"); they come from the corresponding-author mark in the PDF metadata and do not affect the PDF.

## Files

| File | What it is |
| --- | --- |
| `main.tex` | Manuscript, 24 pages: elsarticle, option `review` (single column, 1.5 line spacing), 11 pt, A4 with 2.5 cm margins. The model is complete in Section 2 (notation, cost, emissions, every constraint and valid inequality) |
| `supplementary.tex` | Supplementary Material, 8 pages: the original instances' fixed-tax and sensitivity analyses (S1), the case study's sensitivity (S2), the robustness checks (S3) and the enumeration on all 24 calibrated instances (S4) |
| `references.bib` | Verified Crossref and DataCite records; biblatex prints only the cited ones (37 in the manuscript, 7 in the supplement) |
| `highlights.tex`, `highlights.txt` | Highlights (5 bullets, at most 85 characters, no acronyms) |
| `figures/staircase.pdf`, `figures/staircase.png` | Figure 1 (the PNG is the copy shown in the Claude Doc) |
| `tools/make_tables.py` | Writes the rows of Tables 5, 6 and 7 and of Table S4 from `results/experiments`; run from the repository root |
| `tools/make_figure.py` | Draws Figure 1 from `results/experiments`; run from the repository root (needs matplotlib, the `plots` extra) |

No separate title page: the review is single-anonymized, so the author details stay in the manuscript.

## Where the numbers come from

Every number in Section 4 comes from `results/experiments` (experiments P1, E1, E2, C1, C2 and C3 of `src/clsc/experiments/plan.py`, described in `docs/experiments.md`). `python paper/tools/make_tables.py` rewrites the table rows between their `%% BEGIN table` and `%% END table` markers and prints the aggregates the text quotes; `python paper/tools/make_figure.py` draws Figure 1. The calibrated set in the manuscript is replicates 0 and 1 (24 instances); replicate 2, the escalation sizes and experiments C4, C5, A1 and A2 are for a revision. The case study's enumeration figures (seven taxes in 1 h, six follower solves on their time limit, the best value 0.85% above the DBP's upper bound) are those of the pilot run logged in `results/experiments/run_E1E2_pilot.log`. The Supplementary Material's Sections S1-S3 report the first version's experiments (P1-P3b, R1-R3).

## Format requirements checked

Source: the journal's Guide for Authors, read from the Wayback Machine capture of 10 February 2024 (the live page refuses scripted access). Check the live guide before submitting.

| Requirement | Status |
| --- | --- |
| At most 30 pages, including abstract, figures, tables and references | 24 pages |
| Single column, 11 pt, 1.5 line spacing, no line numbers | Done |
| Abstract of 50 to 250 words, no formulae, references or unexplained acronyms | 180 words, no numbers, only CLSC as acronym |
| First keyword from the journal's list, at most 5 | "OR in environment and climate change" plus 4 |
| Highlights: 3 to 5 bullets, at most 85 characters, no acronyms | Done |
| APA references with DOIs | Done (biblatex-apa) |
| Declarations of interest, funding, CRediT, data availability | Removed for now; the last version is in commit 36e1978 (Zenodo DOI still TODO) |
| Declaration of generative AI use | Removed by the authors; the Guide asks for it whenever such tools were used in writing |

## To fill in before submission (`TODO` in the files)

- ORCID iDs of the authors (`main.tex`). Authors and affiliation follow Pinto et al. (2024); the corresponding author is Marcelo Pinto.
- The declarations (commit 36e1978), with the Zenodo DOI for the data statement (the GitHub URL is in place): make the repository public, link it to Zenodo, publish a release for the submitted version.
