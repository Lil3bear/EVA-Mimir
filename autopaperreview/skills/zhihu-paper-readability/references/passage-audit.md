# Passage Audit

Source inspiration: 丁霄汉, https://zhuanlan.zhihu.com/p/639732057. All examples and operational tests below are independently constructed extensions, not excerpts from the source.

## Four Lenses, Different Repairs

| Lens | Concrete test | Repair | Do not do |
| --- | --- | --- | --- |
| Logical strength | Replace "therefore" with the implied premise; is that premise stated and justified? Check what "this" refers to. | Supply a supported premise, name the referent, or remove the causal connector | Add a stronger connector to cover a missing argument |
| Defensibility | Can a reader find the artifact, result, or citation supporting the exact subject, scope and comparison? | Attach the precise support or narrow the assertion to what was measured | Turn "proves" into "suggests" while leaving an unsupported implication |
| Comprehension time | After one reading, can the reader identify the actor, input, operation and output? | Split roles, define an unfamiliar term locally, use consistent component names | Expand every familiar term or rename technical concepts for variety |
| Information density | Does each clause add mechanism, evidence, qualification or necessary context? | Remove repeated framing and move distracting operational detail | Remove sample size, units, failure cases or comparison conditions to save words |

A passage may fail more than one lens. Explain the scientific ambiguity first; avoid reporting four duplicate comments on the same sentence.

## Numerical and Caption Checks

- Identify the denominator and aggregation unit: pixels, frames, scenes, episodes or seeds. A pixel-level error statistic is not an episode success rate.
- Preserve whether an error is signed or absolute, and whether it is a mean, median or percentile. Do not replace P95 with "average."
- Check whether paired comparisons use the same samples. Changed validity masks may change the measured population; report coverage as well as error where relevant.
- Distinguish relative percent from percentage points. A change from 40% to 50% is 10 percentage points or 25% relative, not 10% relative.
- A caption should identify what is plotted, conditions, metric/unit, aggregation and meaning of shading or error bars when these exist. Do not invent uncertainty estimates absent from the figure's source.
- Do not declare plotted text legible or layout correct without rendering or viewing the actual figure/PDF.

## Synthetic Edits

Ambiguous: "This improves safety by 12%."

If the evidence reports a collision rate falling from 25% to 22% on the same fixed evaluation set: "Collision rate decreased from 25% to 22% on the evaluated episodes (3 percentage points)." Add the actual sample count and uncertainty only if available. This still does not establish causality or deployment safety.

Ambiguous: "The geometry is used to optimize it, thus guaranteeing robustness."

If the method only rejects candidates intersecting observed obstacles: "The evaluator rejects candidate trajectories that intersect reconstructed obstacles. Unobserved space and reconstruction errors remain sources of failure."

Dense but necessary: a sentence specifying camera frame, meters and synchronized timestamps should not lose these details merely because it is long. Split it into acquisition and transformation sentences instead.

## Output and Validation

For substantial edits, return location, original wording, ambiguity, minimal replacement and evidence impact. For a small authorized edit, revise directly and give a short explanation instead of a mandatory table.

Compare revised and original propositions: subject, quantifier, causal strength, conditions, values and uncertainty. Mark missing experiments or citations separately from fixed wording. Preserve existing ledger IDs and only close the language issue after checking the replacement in context. If LaTeX was edited, compile with the available required workflow; compilation alone does not validate the numbers or claims.
