# STANDARD — Reproducibility, provenance, and compute governance

---

## 1. The evidence base is immutable

`results/runs/**` and `data/instances/**` are **append-only** to this system. No agent edits,
deletes, moves, or regenerates them. They are the provenance chain for 119.6 h of solver time; a
rewritten run directory cannot be distinguished from a fabricated one.

The one sanctioned exception already happened and shows the correct pattern: the exp8 incumbent
correction was applied by a **committed, named script**
(`scripts/recompute_enumeration_incumbent.py`), which **replayed saved traces without re-solving**,
and **recorded a `_correction` field** in the affected JSON. Any future amendment follows exactly
that pattern: script + replay + recorded amendment, never a manual edit.

## 2. Compute authorization

See `agents/00_AGENT_PROTOCOL.md` §3 for the always-safe / never-without-authorization split.

A **COMPUTE REQUEST** must state:

| Field | Requirement |
|---|---|
| command | exact, runnable, with all flags |
| cells | which instances / design points, and their tier |
| estimated cost | hours, **with its basis** (a measured per-point rate from a comparable cell, cited) |
| buys | which claim moves from which tier to which; which hypothesis it closes |
| alternative | the cheapest partial answer available without solving |

Rejection criteria, applied by the Project Manager:
- statistical volume on a hard-tier cell (P5) — reject, cite `Experimental_Plan.md` §11.2;
- re-solving something already on disk — reject, point to the run;
- cost estimate without a measured basis — reject, ask for the basis;
- no stated claim promotion — reject, this is curiosity not evidence.

## 3. What every analysis output must record

Any report, table, or figure produced by this system records, in a header block:

```
generated:      <ISO date>
by:             <workflow id> / <agent>
inputs:         master_runs_campaign_01.csv (sha256 <first 12>, 381 rows, mtime <ts>)
                docs/Experimental_Plan.md (commit <sha>)
code version:   <git commit sha>, branch <name>, dirty: <yes|no>
rng seed:       <if any resampling was used>
regenerate:     <exact command>
```

The `regenerate` line is the test: if it cannot be written, the output is not reproducible and
must not be cited.

## 4. Determinism

- The solver is **deterministic** given (instance, tolerances, Gurobi seed, thread count).
  Re-solving the same configuration is **not** replication and carries no statistical information.
- Genuine variation comes from two designed sources only:
  - **instance seed** (`seed_offset`) — generalisation over the problem distribution;
  - **Gurobi `Seed`** (`gurobi_seed`) — MIP performance variability (Lodi & Tramontani 2013),
    affects runtime, not the optimum.
- Any resampling (bootstrap) fixes and records its RNG seed.
- `threads = 4` is part of the determinism contract; a comparison across thread counts is a
  different experiment (exp2), not a repetition.

## 5. Code version tracking

Every run manifest already records the code version. Analysis must:
- verify that all runs entering a single comparison share a `code_version`, and **flag it loudly**
  if they do not;
- record the analysis-time commit in the report header;
- refuse to publish a number computed on a dirty working tree without saying so.

## 6. The test suite is part of the evidence

`tests/` (19 files) pins solver behaviour, campaign design generation, and the enumeration
tie-tolerance regression. Rules:

- New statistical code ships with tests against **textbook worked examples with known answers**,
  not against its own output.
- `python -m pytest -m "not slow"` runs freely. The full suite solves real models — authorization
  required (§2).
- A change that makes a test fail is a defect in the change until proven otherwise.

## 7. Report lifecycle

```
results/analysis/campaign_01/reports/
    claim_ledger.md                          # living, one per campaign
    YYYY-MM-DD_<workflow>_<scope>.md         # dated, immutable once written
    limitations_register.md                  # living
    future_work.md                           # living
```

Dated reports are **never edited after the fact**. A superseding analysis is a new dated file that
cites and supersedes the old one. The living documents (`claim_ledger`, `limitations_register`,
`future_work`) are edited in place and carry a changelog section at the bottom.

This is the mechanism that would have prevented the four self-corrections in
`docs/Experimental_Plan.md` from being invisible.
