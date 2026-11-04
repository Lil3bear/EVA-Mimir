---
name: experiment-figures
description: Turn verified experiment tables or raw observations into honest scientific charts and audit plot comments. Use for experimental visualization, not missing experiment generation.
---

# Evidence-Grounded Experiment Charts

Source inspiration: [Leey21/awesome-ai-research-writing, experimental charts](https://github.com/Leey21/awesome-ai-research-writing), accessed 2026-10-19. This is an independent operational checklist, not a copy of the prompt collection.

Select charts by the question: bars for discrete comparisons, lines for measured sequences, scatter for paired tradeoffs, heatmaps for matrices and distribution plots for actual repeated observations. Do not add charts just to increase the figure count.

For every plotted value store its source table, file, row, column, unit, dataset, split, backbone and evaluation condition. Resolve values from source cells, not model-generated numbers. Keep task counts distinct from percentages and percentage points. Recompute summaries only when denominators and definitions are available.

Separate published reference configurations from controlled same-backbone comparisons. Separate zero-day from one-day and development from held-out evaluation. An aggregate comparison does not isolate a controller, router or skill component. Do not visually imply causality, statistical significance, trajectories or generalization that the evidence does not establish.

No invented seeds, error bars, confidence bands or cost measurements. Start ordinary bar axes at zero; mark rate units and a valid range. Avoid dual axes and decorative radar charts when a direct comparison is clearer. Missing observations stay missing. Preserve tables as the numeric record and add a complementary figure only when it answers a useful question.

Captions identify the population, conditions and uncertainty coverage. Verify every source cell again before application; abort on stale data. Numerical reproducibility, compilation and visual inspection are separate checks. Keep unmatched author requests open with concrete missing evidence.
