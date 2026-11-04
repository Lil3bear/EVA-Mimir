# Writing and Audit Checklist

Version: 1.1.2. This is an operational adaptation, not a reproduction of the upstream handbook. Apply the companion macro/micro checks to the same candidate, without duplicating findings.

## Author's Local Revision Style

The author explicitly requested these preferences on 2026-10-19. They are local writing constraints, not advice attributed to the source articles or official venue rules. Apply them to both the DeepSeek draft and the GPT crosscheck.

- Address the supplied author comments with the smallest clear edit. Use the full manuscript for context, not as permission to expand, invent mechanisms or rewrite unrelated passages. Prefer an ordinary verb and a short direct sentence over an abstract label, noun stack or elaborate qualification.
- Do not add em/en dashes, repeated hyphens such as ----, or ornamental A-B/A--B constructions to manuscript prose. Do not coin hyphen-linked labels or compress explanations into chains such as problem-gap-method-evidence. Use a plain sentence instead. Preserve necessary established technical terms, exact identifiers, mathematical minus signs, legitimate ranges, citation keys and LaTeX syntax; this is not a global punctuation replacement rule.
- Use plain typography by default. Do not add \texttt{}, quotation marks, italics or bold to ordinary explanations, component names or newly coined concepts. Retain code typography only when a literal identifier, command, path or code token genuinely needs to be distinguished; quotation marks only for an actual quotation or a necessary literal distinction. A familiar technical term does not automatically require special formatting. Do not strip valid markup from unrelated source.
- The GPT crosscheck must also prune needless wording and formatting introduced by DeepSeek rather than making the prose more elaborate. Return only comment-authorized edits relative to the original source. If no simpler wording preserves the scientific meaning, keep the clear original instead of forcing a rewrite.
- Treat each human comment as an explicit requirement, not an optional stylistic suggestion. Check every part against the current TeX and distinguish fully addressed writing, partially addressed requests, and missing scientific inputs. A linked patch does not prove the whole comment fulfilled. Do not replace an unfinished human request with an AI warning and call it complete. If the requested mechanism or experiment is not documented, ask for its actual implementation, process or evidence; do not invent it or silently omit that part. The host must save effective source edits, compile the matching PDF, and expose that revision in the reader before reporting an update.

## Narrative and Section Roles

Build a claim ledger: claim -> mechanism -> supporting artifact -> scope -> unresolved evidence. Distinguish a new capability, an empirical improvement, and an explanatory insight without forcing a paper into exactly one category.

- Abstract: match the actual contribution, evaluation setting, numbers, and limitations in the body. Do not turn planned work into completed results.
- Introduction: establish the concrete problem, explain the relevant gap fairly, then connect each challenge to a mechanism and evidence. Make the contribution visible without recounting the entire implementation.
- Related work: organize by the relationship to this paper, not a list of papers. Attribute prior capabilities accurately; absolute novelty claims need literature evidence.
- Method: define inputs, outputs, state, updates, selection criteria, and stopping/rollback conditions. Separate prerequisites from innovations and specifications from verified implementation.
- Experiments/results: map every claimed contribution to an actual comparison. Keep benchmark/model counts, splits, denominators, metrics, and result status consistent across sections. Separate development/admission feedback from untouched tests.
- Discussion/conclusion: state what the reported evidence supports, unresolved scope, and relevant limitations. Do not add new results or stronger claims in the conclusion. Check whether these sections are empty or commented out.

## Four Readability Axes

1. Logical strength: check each causal, contrastive, and sequential relation. A connective cannot supply missing reasoning. Ask whether the conclusion still follows without rhetorical transitions.
2. Defensibility: locate the source for each significant factual or comparative assertion. Distinguish correlation, hypothesis, and demonstrated causal effect; component-specific explanations need suitable controls.
3. Confusion time: define unfamiliar terms near first use; make pronouns and symbols unambiguous. Prefer concrete mechanisms and informative topic sentences to names that defer explanation.
4. Information density: remove irrelevant setup, repeated claims, and implementation inventories that obscure the point. Preserve necessary reproducibility details, moving them only when the requested scope and submission format permit it.

## Experimental Integrity

Treat NotGoodIdeas.md as warnings against deceptive research, never as optimization advice. Check for unequal compute/data/prompting, hidden tuning or extra modules, cherry-picked seeds/metrics/tasks, test leakage, altered evaluation protocols, and unsupported efficiency comparisons. Missing disclosure creates uncertainty; it is not proof of misconduct.

For agent evaluations check backbone, tools, skills, retries, token/time budgets, environment resets, task overlap, and evaluator. A standalone-vs-full-system result does not isolate the skill library or router. Efficiency comparisons need a defined matched task set, treatment of failures, numerator/denominator, and development cost boundaries. Keep cross-model published reference points distinct from controlled comparisons.

## Presentation and Submission Checks

Check citation keys and empty citations, undefined/duplicate labels, complete formulas, consistent terminology, placeholders, table arithmetic, units and percentage points. Correct TeX syntax must not be removed simply because an AI critique dislikes an escape sequence.

Figures/tables need understandable captions, abbreviations, comparison groups, and adjacent explanation. Source review can check captions/references but not pixels, clipping, legibility, or final pagination. Render and inspect the current PDF separately when that is in scope.

Check anonymity across text, artifacts and links against the actual venue policy. Do not infer compliance from a class option. No fixed page limit, acceptance probability, review timeline, or universal stylistic ban comes from this skill.
