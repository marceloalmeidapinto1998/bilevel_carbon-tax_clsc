# EJOR manuscript

The manuscript for the *European Journal of Operational Research*, converted from the Claude Doc "Paper" tab (22 October 2026).

## Compile

```
latexmk -pdf main.tex           # manuscript (pdflatex + biber, run as often as needed)
latexmk -pdf highlights.tex
latexmk -pdf cover_letter.tex
latexmk -c                      # remove the auxiliary files
```

The references use biblatex with the `apa` style and **biber**, not BibTeX. The EJOR Guide for Authors asks for APA references, and biblatex-apa produces APA 7 exactly. Without latexmk, run `pdflatex main`, `biber main`, `pdflatex main`, `pdflatex main`. Tested with MiKTeX 25.12 (pdfTeX 4.23, elsarticle 3.5, biblatex-apa).

`main.tex` compiles with no errors and no overfull or underfull boxes. Four hyperref warnings remain ("Token not allowed in a PDF string"). They come from the corresponding-author mark in the PDF metadata and do not affect the PDF's content.

## Files

| File | What it is |
| --- | --- |
| `main.tex` | Manuscript: elsarticle, option `review` (single column, 1.5 line spacing, no line numbers), 11 pt, A4 with 2.5 cm margins |
| `references.bib` | 59 entries (57 articles, the ESMA report, the dataset), generated from the verified Crossref and DataCite records listed in the References audit tab of the doc |
| `highlights.tex`, `highlights.txt` | Highlights as a separate file (5 bullets, at most 85 characters each) |
| `cover_letter.tex` | Cover letter to the editor |
| `figures/sensitivity_tornado.pdf` | Figure 1, produced by `python -m clsc.experiments figures` (vector PDF) |

No separate title page is provided: EJOR uses single-anonymized review (single blind), so the author details and the declaration of interest stay in the manuscript.

## EJOR requirements checked

Source: EJOR Guide for Authors, read from the Wayback Machine capture of 10 February 2024. The live ScienceDirect page refuses scripted access, and the later captures redirect to that one. Check the live guide before submitting: https://www.sciencedirect.com/journal/european-journal-of-operational-research/publish/guide-for-authors

| Requirement | Status in `main.tex` |
| --- | --- |
| At most 30 pages, including the abstract, figures, tables and references | **37 pages: about 7 over** (see below) |
| Single column, 11 pt, 1.5 line spacing, no line numbers | Done (`review,11pt`; tables and the algorithm are single-spaced) |
| Title without abbreviations, acronyms or formulae | Done |
| Abstract of 50 to 250 words, with no formulae, references or unexplained acronyms | Done (245 words) |
| One keyword from the EJOR list first, at most 5 in total | "OR in environment and climate change" plus 4 |
| Highlights: 3 to 5 bullets of at most 85 characters, no acronyms (optional for a new submission, mandatory at revision) | Done, as a separate file |
| APA references, alphabetical, with DOIs | Done (biblatex-apa) |
| Figures and tables embedded next to the relevant text | Done |
| No unexplained acronyms in the text | Each acronym is defined at first use |
| Declaration of interest in the manuscript (single anonymized) | Section present, to be confirmed |
| Declaration of generative AI use, in its own section before the references | Section present, to be completed |
| Funding statement | Section present, to be completed |
| Data statement (encouraged) | Section present, to be completed |
| CRediT statement (not required by the guide; included as you asked) | Section present, to be completed |

## To fill in before submission (`TODO` in the files)

- Authors, affiliations, postal address, corresponding e-mail and ORCID iDs (`main.tex`, `cover_letter.tex`).
- CRediT roles of every author.
- FCT grant reference, or the no-funding sentence.
- Repository URL and archived DOI for the data statement.
- The generative AI declaration: say what the tool was used for.
- Confirm "Declarations of interest: none".

## Page budget: 37 against 30

The body ends on page 29, Appendix A and the declarations take pages 30–31, and the references (59) pages 32–37. Options, roughly in order of how little they cost the argument:

1. Move Table A.1 (parameters) and Table 6 (experiments) to Supplementary Material, which the guide allows for complete data: about 2 pages.
2. Shorten Section 3.4 (subproblems with a gap) to a paragraph, citing Soares et al. (2021, 2020) for the details: about 1 page.
3. Merge the two literature paragraphs on supply chains and shorten Table 1 to four rows: about 1 page.
4. Cut 10–15 references that support only background statements: about 1–1.5 pages.
5. Shorten Section 5.3 by moving the remanufacturing paragraph into Section 5.4: about half a page.

## Differences from the doc

- **Notation.** Several symbols clashed, so they were renamed:
  - The leader's weight $w$ (clashed with the warehouse index $w$) is now $\mu$.
  - The relative weight $q$ (clashed with production $q_{pfgt}$) is now $\xi$.
  - The tax tolerance $\delta$ (clashed with distance $\delta_{ij}$) is now $\delta_\tau$.
  - Working hours per period (an H, like the hub set $H$) are now $\Omega$.
  - The MIP gap in Proposition 2 ($\gamma$, clashed with the workers' parameters) is now $\bar g$.
  - The hub family index in constraint (20) is now $\chi$.
- **Figure 1** of the doc (the flowchart of the DBP) is now Algorithm 1. The tornado chart becomes Figure 1.
- **Figure annotation.** The tornado figure was regenerated so its annotation reads "0.2–2.4%", as the text does.
