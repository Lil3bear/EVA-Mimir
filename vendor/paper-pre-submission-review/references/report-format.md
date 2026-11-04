# Report and evidence format

Adapt to the requested form. Default to Chinese for Chinese requests. Findings explain what is wrong, why it matters, and what would resolve it.

## Readiness

State paper version, year/track/stage, scope, and available materials. Use wording supported by checks: material corrections identified; no blocking issue found in completed checks with pending items stated; or insufficient coverage for a readiness conclusion. No detected issue is not compliance certification, proof of correct science, or acceptance probability.

## Priority and certainty

| Priority | Meaning |
| --- | --- |
| 必须修 / Must fix | Confirmed applicable submission violation, demonstrated error, or clearly unsupported central claim requiring correction or narrower wording. |
| 建议修 / Should fix | Material clarity, evidence, comparability, or reproducibility weakness. Explain the uncertain parts. |
| 文字优化 / Editorial | Wording, notation, layout, or cleanup improvement without established effect on validity/compliance. |

Record `confirmed`, `conditional`, or `pending verification` separately. Put unresolved policy/source questions in a pending list, not under confirmed violations. A serious conditional concern can be prominent without being declared proven.

Use one finding ID per underlying problem. If the abstract, caption, and conclusion repeat an unsupported claim, group them with multiple locations.

## review.md

1. **Readiness and scope:** Assessment, reviewed version/materials, material limitations.
2. **Priority overview:** ID, priority, short finding, location, certainty. Order by impact; no invented issue quota.
3. **Detailed findings:** Exact claim/observation, location, evidence, implication, and minimal repair or evidence needed. Give replacement wording when useful.
4. **Simulated review:** Brief summary, evidenced strengths, principal weaknesses by finding ID, and questions that could change assessment. Avoid repeating details. Score only when requested and using the actual rubric.
5. **Submission-rule status:** Applicable rule IDs and pass/fail/pending/not-applicable status, linked to evidence. Focused scientific reviews may omit this.
6. **Pending checks and repair order:** Missing materials, unavailable tools, unresolved policy, and author confirmations. In revision mode, list IDs actually repaired and rechecked.

## evidence.md

Maintain the claim–evidence map, source verification record, applicable rule ledger, and check coverage. Include calculations/commands and outputs only when useful to reproduce a finding. Do not include private chain-of-thought or a transcript of reasoning.

Distinguish reference metadata checks from full-text support checks. For PDF coverage, identify artifact and inspected pages. For build coverage, record freshness and relevant failures. Link records rather than duplicating them throughout the report.

## Small finding example

If a fictional table reports accuracy rising from 80% to 84%, “4% relative improvement” has incorrect arithmetic. The increase is 4 percentage points or 5% relative accuracy improvement. Locate the statement, establish intended quantity, and recommend matching wording. Do not change measured scores or infer significance.
