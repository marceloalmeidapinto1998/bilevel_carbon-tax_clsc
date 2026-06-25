# Experiment Organization Prompt

You are advising on a PhD research codebase called `BilevelModel_CLSC`. It implements a bilevel
carbon-tax / closed-loop supply chain optimization model with a Gurobi solver layer, generated
benchmark instances, scenario/sensitivity tools, analysis scripts, a Streamlit dashboard, and a
LaTeX paper.

I want to redesign the computational experiments from scratch. Do not treat the experiments that
already exist in the repository as the plan to preserve. You may inspect them only to understand the
current code structure and what should be replaced or reorganized.

## Main Goal

Give me a systematic, literature-grounded plan for organizing model runs and result analysis for
this bilevel closed-loop supply chain model. I want the plan to be defensible in the operations
research and supply chain optimization literature, not a collection of ad hoc or random scenarios.

The plan should explain both:

1. What experiments should be run and why.
2. How the code, data, run outputs, metadata, and analysis scripts should be organized so the
   experiments are reproducible, understandable, and easy to extend.

## Important Constraints

- Disregard the experiments I have already run. Assume I am not satisfied with them and want to
  restart the experimental campaign from zero.
- Do not use Morris elementary-effects analysis. I want to remove Morris from the experimental
  design because I do not understand it well enough to defend it, and I do not want it in the paper.
- Do not propose vague "more sensitivity analysis" language. I want a concrete, structured
  experimental design.
- The design should be common and defensible in operations research computational studies,
  especially supply chain network design, closed-loop supply chains, sustainable supply chains,
  bilevel optimization, carbon regulation, and mixed-integer optimization.
- The plan should help reveal relationships between important variables in the model, including
  nonlinear effects, threshold effects, interaction effects, saturation, and discrete regime changes
  caused by binary decisions.
- Keep computational tractability in mind. This is a difficult bilevel/MILP model, so propose a
  tiered design if needed: a minimal publishable plan, a stronger plan if compute is available, and
  optional extensions.
- Do not implement code yet unless I explicitly ask. First produce a design and code-organization
  plan.

## Repository Context to Inspect

Please inspect the codebase before answering. Important areas are likely:

- `paper/sections/04_mathematical_model.tex`
- `paper/sections/05_solution_methodology.tex`
- `paper/sections/06_computational_experiments.tex`
- `src/models/shared_models.py`
- `src/models/instance_loader.py`
- `src/solvers/`
- `data/generator/`
- `data/instances/`
- `tools/solver/`
- `tools/experiments/`
- `tools/analysis/`
- `results/`
- `app/scn_dashboard.py`

Treat existing scenario, OAT, and Morris folders as legacy unless they contain reusable code
patterns. The new plan should be designed independently.

## Questions to Answer

Answer the following in a structured way.

### 1. What should the experimental campaign be trying to prove?

Define the main research questions that a well-organized experiment section should answer for this
model. For example:

- What carbon tax does the leader choose, and how does it change across instance classes?
- How does the follower's closed-loop supply chain structure respond to the tax?
- Which operational or design parameters drive emissions, cost, and tax decisions?
- Which variables create nonlinear, threshold, or saturation effects?
- Which investment/design levers are genuinely effective: technology, remanufacturing, returns,
  transport, capacity, network size, planning horizon, or carbon policy bounds?
- How robust are conclusions across instance sizes, random seeds, and solver tolerances?
- How scalable and reliable is the bilevel solution method?

Revise or replace these questions if the code and model suggest better ones.

### 2. What experimental design does the literature suggest?

Recommend a defensible experiment structure used in OR and supply chain optimization papers.
Discuss methods such as:

- structured benchmark instance classes;
- controlled scenario analysis;
- full factorial or fractional factorial designs;
- response surface designs;
- Latin hypercube or space-filling designs, if appropriate;
- local one-at-a-time analysis only where it is useful and clearly limited;
- robustness checks over seeds, instance classes, solver tolerances, or uncertain parameters;
- computational performance experiments.

Explain which methods fit this model and which do not. If you recommend a method, explain how it
would be defended in a paper. If you reject a method, explain why.

Do not recommend Morris.

Use literature where possible. Provide citations or at least named references/categories I should
look up. Separate:

- general OR computational-experiment practice;
- design-of-experiments / sensitivity-analysis practice;
- supply chain network design and closed-loop supply chain studies;
- bilevel optimization computational studies;
- sustainable supply chain / carbon regulation studies.

### 3. What experiment families should I run?

Propose a clean set of experiment families. For each family, define:

- purpose;
- factors varied;
- factor levels;
- fixed controls;
- base instances used;
- expected number of runs;
- required outputs;
- plots/tables to generate;
- interpretation in the paper.

At minimum, consider whether the campaign should include:

- baseline benchmark runs;
- tax-response or carbon-policy frontier runs;
- controlled design-lever experiments;
- factorial or fractional factorial experiments for interactions;
- response-surface or surrogate analysis to show nonlinear relationships;
- robustness checks;
- solver performance and validation experiments.

Make the final recommendation concrete. I want something like an experiment blueprint, not a list of
possibilities.

### 4. Which model factors should be varied?

Identify the important independent variables in this model and group them into meaningful factor
families. Consider:

- demand level and demand mix;
- return availability, mandatory return floor, or collection rates;
- production and remanufacturing emission intensities;
- supplier or scope-3 emission intensities;
- production and remanufacturing capacities;
- technology availability and technology efficiency;
- fixed facility costs, construction/area costs, and capacity expansion costs;
- transport cost, transport capacity, and transport emissions;
- network size, topology, and geography;
- planning horizon length;
- tax lower bound, tax upper bound, and tax discretization;
- bill-of-material or remanufacturing yield parameters;
- inventory costs and holding behavior;
- solver configuration only for computational experiments.

Do not vary everything blindly. Recommend a short, defensible core set of factors and explain why
those are the right ones for this model.

### 5. How should nonlinear and interaction effects be analyzed?

I specifically want to highlight relationships between important variables, including nonlinear
relationships. Propose analysis tools that are interpretable and defendable, such as:

- response curves;
- marginal abatement curves;
- tax-emissions frontiers;
- cost-emissions trade-off curves;
- heatmaps for two-factor interactions;
- interaction plots from factorial designs;
- piecewise or segmented response analysis;
- regime classification based on facility openings, technology choices, return flows, or transport
  mode choices;
- simple surrogate models or interpretable regression models if appropriate.

Explain how to detect and report:

- saturation;
- thresholds;
- discontinuities caused by binary decisions;
- interaction effects;
- differences across instance classes;
- robust versus instance-specific conclusions.

### 6. How should the code be organized?

Recommend a clean code and folder structure for the new experiment campaign. Address:

- where experiment design definitions should live;
- how to generate instance variants;
- how to store design matrices;
- how to launch solve batches;
- how to store solver outputs;
- how to store run metadata;
- how to aggregate results;
- how to generate paper tables and figures;
- how to keep dashboard exploration separate from paper-grade analysis;
- how to avoid dated one-off scripts and manually copied result folders.

I want a structure that separates:

- experiment design;
- instance generation;
- solver execution;
- validation;
- aggregation;
- statistical/DOE analysis;
- visualization;
- paper table/figure export.

Suggest concrete paths and naming conventions, for example:

- `experiments/designs/`
- `experiments/manifests/`
- `data/instances/experiments/v2/`
- `results/runs/v2/<experiment_id>/<run_id>/`
- `results/analysis/v2/<experiment_id>/`
- `tools/experiments/v2/`
- `tools/analysis/v2/`

Use the existing repository style where possible, but do not preserve bad structure just because it
already exists.

### 7. What metadata should every run record?

Define a run manifest/schema. Include fields such as:

- experiment id;
- run id;
- instance id;
- base instance id;
- random seed;
- factor levels;
- scenario family;
- solver method;
- solver settings;
- code version or git commit;
- input instance path;
- output path;
- solve status;
- objective values;
- leader tax;
- cost;
- emissions;
- follower objective;
- runtime;
- MIP gaps;
- DBP iterations;
- validation status;
- notes on infeasibility or time limits.

Recommend whether this should be CSV, JSON, YAML, or a combination.

### 8. What outputs should be analyzed?

List the dependent variables and derived metrics that should be collected from every run. Consider:

- leader tax decision;
- effective carbon tax;
- total emissions;
- total cost;
- cost components;
- emissions components;
- follower objective;
- facility openings;
- capacity installed;
- technology selected;
- production and remanufacturing quantities;
- return flows and recovery rates;
- transport mode shares;
- inventory;
- unmet or slack variables if any;
- solver runtime and convergence metrics;
- relative changes from baseline;
- elasticity or marginal effects where meaningful;
- regime labels or structural solution classes.

Explain which outputs are primary for the paper and which are diagnostic.

### 9. What should the final paper section look like?

Propose a clear structure for the computational experiments section. Include:

- subsections;
- tables;
- figures;
- what each figure/table should prove;
- how to phrase limitations;
- how to avoid overclaiming from too few runs;
- how to explain instance-specific versus general findings.

### 10. What should I do first?

End with a phased action plan:

1. immediate cleanup or archiving of old experiments;
2. design of the new experiment matrix;
3. code changes needed to support the new organization;
4. pilot runs;
5. full runs;
6. analysis;
7. paper integration.

For each phase, state the concrete deliverables and a stopping criterion.

## Expected Deliverable

Produce a detailed but practical recommendation. I want:

- a recommended experimental architecture;
- a proposed experiment matrix;
- a code/folder organization plan;
- a run metadata schema;
- a list of analysis outputs and visualizations;
- a phased implementation plan;
- citations or literature anchors;
- explicit explanation of why Morris is excluded and what replaces it.

Be critical. If my current experiment approach is weak, say exactly why and replace it with a
stronger one. The answer should be something I can use to reorganize the project and rewrite the
computational experiments section of the paper.
