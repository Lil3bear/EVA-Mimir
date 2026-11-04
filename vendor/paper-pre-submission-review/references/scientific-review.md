# Scientific and numerical review

Select checks by contribution type. Empirical, theory, dataset, and analysis papers should not receive the same mandatory experiment list.

## Claims and significance

Map central claims in the title, abstract, introduction, results, conclusion, and major captions to evidence. Preserve qualifiers, population, datasets, compute budget, and assumptions. Compare what authors claim, what artifacts show, and what the reviewer infers.

For novelty, identify nearest work and the precise difference in problem, mechanism, assumptions, evaluation, or findings. Read original passages before declaring equivalence. Consider work available by the submission cutoff; later papers may be context but cannot be an earlier omission. Shared terminology and small absolute gains alone do not dismiss a contribution.

Credit supported empirical insights, rigorous negative findings, simpler approaches, and useful theoretical clarification. Separate unclear presentation of a contribution from absence of a contribution.

## Experimental evidence

Examine comparisons supporting central claims:

- Dataset versions, train/validation/test splits, preprocessing, filtering, metrics, and aggregation conventions.
- Matched supervision, teacher quality, pretraining data, retrieval access, tuning budget, training/inference compute, and model selection. Mark unmatched factors before attributing gains to the proposed component.
- Test-set reuse, selection leakage, contamination evidence, and dependencies between samples. A possible risk is not proof that leakage occurred.
- Whether ablations isolate the claimed mechanism. When factors change together, distinguish measured system benefit from causal attribution to one component.
- Whether robustness, generalization, efficiency, or scaling claims are tested over their stated range. Do not demand unrelated benchmarks merely to enlarge the experiment section.
- Reproducibility details needed for these results: hyperparameters and selection, seeds, data/model versions, hardware, evaluation code, and supplied commands. Missing public code is not automatically a validity failure or policy violation.

Recommend experiments only when they could resolve material uncertainty in a central claim. Give the smallest informative control and what its outcomes would imply. Narrowing a claim or clarifying an existing result can suffice.

## Numbers and statistics

- Recompute headline improvements and table aggregates from supplied numbers. Distinguish percentage-point change, relative improvement, and relative error reduction; check denominators and metric direction.
- Check prose, tables, captions, appendix, and supplied logs for agreement in counts, seeds, runtimes, and results. Allow stated rounding; do not allege inconsistency from hidden precision alone.
- Identify the unit of replication: runs, examples, folds, or bootstrap samples. Distinguish standard deviation, standard error, and confidence intervals.
- Assess support for statistical-significance claims. A single score lacks an uncertainty estimate but does not prove a result false. Do not invent p-values or infer significance from error-bar overlap without valid analysis.
- Check averaging, weighting, sample sizes, paired comparisons, selection effects, and multiplicity where relevant. Recompute statistical tests only when necessary data and assumptions are available.

State which calculations were performed. A manuscript-only review cannot certify underlying data or reproduce an experiment.

## Theory and mechanisms

Check dimensions, definitions, quantifiers, assumptions, boundary cases, and whether conclusions follow from supplied derivations. Trace theorem dependencies into the appendix. Distinguish an omitted proof step from a counterexample; state the conditions under which a suspected flaw applies.

For complexity/efficiency claims, identify the varying quantity, preprocessing/training costs, memory model, and hardware/protocol. Compare like quantities. Empirical agreement is not proof; a bound under strong assumptions does not establish unrestricted practical behavior.

## Turn observations into findings

Each material concern needs location, evidence, implication, and repair. If a headline attributes gains to module M but the comparison also adds data, the supported concern is confounding. Suggest a matched-data comparison or narrower system-level claim; do not assert M is ineffective.

Keep genuine strengths and remaining uncertainty. Questions should identify information that could change the assessment, rather than repeat demands.
