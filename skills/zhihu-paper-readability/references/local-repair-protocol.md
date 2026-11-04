# Local Repair Protocol

Source inspiration: **丁霄汉**, [微观可读性](https://zhuanlan.zhihu.com/p/639732057). This independently written protocol extends the four attributed axes. It does not reproduce the source article.

## Identify the Defect Before Rewriting

Read the paragraph plus its preceding and following paragraphs, referenced definitions and relevant result rows. Give each sentence a role: setting, claim, reason, operation, observation, interpretation or boundary. A paragraph can have several roles; do not force a fixed order.

| Axis | Concrete test | Repair decision |
| --- | --- | --- |
| 逻辑强度 | What are the operands of 'therefore', 'unlike', 'because'? Are the compared dimensions compatible? | Name the premise, fix the contrast or remove a false causal link |
| 防御弹性 | What precise observation would contradict the sentence? What evidence answers that possibility? | Bound the claim to measured conditions; keep unresolved science explicit |
| 迷惑时间 | Can a reader identify the actor, object, operation and output without a distant lookup? | Define the role near first use, replace ambiguous pronouns, split a dependency chain |
| 信息密度 | What new information does each clause add to this paragraph's question? | Remove repetition and irrelevant setup without deleting scope or controls |

Keep a good sentence unchanged. One defect may touch several axes, but should generate one repair rather than repeated complaints.

## Common Repair Cases

1. **Unsupported causal explanation.** Full system A exceeds baseline B while training data and model differ. State the observed comparison. Do not credit a single component until a suitable control exists.
2. **Ambiguous contrast.** One sentence discusses architecture, the next loss, introduced by 'in contrast'. Compare architectures or objectives on both sides, or use a neutral transition.
3. **Hidden mechanism.** 'The module improves reliability' leaves its operation unclear. Explain what it reads, what decision it makes and what it changes. Use only actual implemented operations.
4. **Premature terminology.** A component name appears pages before its function. Provide a short local role, preserving the established name instead of inventing a second one.
5. **Decorative hedging.** Replacing 'guarantees' with 'may guarantee' does not fix unsupported scope. Replace with the actual enforced condition or measured observation.
6. **Overloaded sentence.** Multiple actors, nested qualifiers and several comparisons obscure the subject. Split at a genuine reasoning boundary, retaining condition and citation attachments.
7. **Evidence inventory.** Repeating every table cell obscures the result. Name the decisive contrast and interpretation, but preserve exceptions that challenge it.

## Numerical and Experimental Meaning

Preserve baseline, dataset/split, denominator, units, metric direction, aggregation and uncertainty. Distinguish relative percent from percentage points, runtime per scene from total pipeline cost, config values from achieved throughput, unit tests from physical task success, and qualitative examples from population estimates.

Synthetic example: 60% to 75% is +15 percentage points or +25% relative, under the same evaluation denominator. Do not choose the larger-looking expression without explaining its basis. 'Fast' requires the actual measured interval and hardware. A saved configuration of 256 environments does not prove a 256-environment run finished.

## Minimal Edit Record

Use: exact source location / original clause / axis and reader impact / revised clause / preserved scientific meaning / unresolved evidence. Keep this private unless the user asks for a change log. For editable manuscripts, preserve citations, equation labels, macros and symbol definitions.

Compare before and after on actor, action, object, quantifier, comparison, condition, evidential strength and citation scope. Check neighboring sentences for repeated conclusions or broken references. Compile and inspect PDF only when needed by the changed source; source reading alone cannot confirm visual fit.

For slides, reduce sentence count before shrinking type. Keep status labels and the one caveat that changes the claim. Put reproducibility details in notes, not illegible footers.
