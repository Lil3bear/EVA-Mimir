# Response and Counterevidence Worksheet

Source inspiration: 丁霄汉, https://zhuanlan.zhihu.com/p/602024489. The decision table, ledger and synthetic examples below are our engineering extensions. They are not quotations, a reproduction of the article, or official conference rules.

## Classify the Scientific Issue

| Concern type | First check | Defensible response | Evidence absent |
| --- | --- | --- | --- |
| Factual misunderstanding | Is the supposedly missing material actually present and sufficiently explicit? | Point to exact location and clarify the ambiguous wording | Acknowledge missing explanation rather than fault the reviewer |
| Valid methodological defect | Does it invalidate a claim or only narrow its scope? | Accept the specific defect, state the actual correction, update affected claims | Keep the limitation open; do not promise it away |
| Missing baseline or experiment | Would it distinguish the claimed mechanism from a plausible alternative? | Provide the comparison if run and permitted, or narrow the claim | State not run; explain what remains unestablished |
| Out-of-scope request | Does the paper itself make the broader claim that invites it? | Explain the task boundary; remove inconsistent broad claims | Do not use scope as a shield for the paper's own assertions |
| Conflicting reviews | Do they disagree on a factual premise, interpretation, or preference? | Resolve the precise premise with evidence | Preserve disagreement without manufacturing consensus |
| Possible procedural issue | Is there an applicable verified rule and demonstrable violation? | Prepare a separate factual chair note only when requested and allowed | Do not accuse or speculate about motives |

## Counterevidence Pass During Simulated Review

For each high-impact finding, construct the strongest legitimate defense from existing artifacts. Then ask:

1. Does the defense answer the reviewer's actual concern, or a weaker substitute?
2. Does cited evidence cover the same system version, setting, denominator and claimed capability?
3. Is there contrary evidence such as failed runs, excluded samples, changed budgets or untested branches?
4. What observation would falsify the defense? Is that test already available, or only proposed?

Return one of: supported defense, partial defense with remaining limitation, concern confirmed, or unresolved because evidence is missing. These are adjudication labels, not acceptance predictions. A persuasive-sounding response is not counterevidence. Keep simulated reviews explicitly labeled; never invent conference reviewer IDs or scores.

## Concern Ledger

Use the manuscript's existing ledger if it has one. For actual reviews preserve reviewer numbering, even when grouping duplicate concerns.

| ID / source | Fair interpretation | Position | Supporting and contrary evidence | Manuscript change / location | Verification | Remaining limitation |
| --- | --- | --- | --- | --- | --- | --- |

Record proposed, edited, compiled and evidence-verified separately where relevant. A compile pass proves syntax, not that a promised experiment ran. Do not mark a finding closed until the specific acceptance condition is met. If an experiment is needed, record its design and owner/status without fabricating results or starting unauthorized computation.

## Write the Answer

Use an answer-first paragraph: position -> precise evidence -> concrete change -> remaining scope. Prioritize validity and contribution questions under the actual response limit; preserve links from grouped answers to all concerns. No mandatory apology, flattery or combative phrase.

Synthetic example: Reviewer asks, "How can the safety claim be justified when only unit tests are reported?"

Unsupported response: "Our 37 passing tests prove robust navigation."

Defensible response with only unit-test evidence: "We agree that the reported tests do not establish navigation safety. They validate the evaluator's input checks, not closed-loop behavior. We have removed the safety guarantee from [verified manuscript location] and state closed-loop validation as outstanding." Use "will remove" if the edit has not actually been made. Do not invent the location.

Synthetic factual disagreement: a reviewer says depth ground truth is fed to the policy. A data-flow diagram alone is incomplete proof. Inspect the evaluation/agent boundary and relevant run configuration. If they establish separation, cite both and clarify the protocol; if a debug path leaks ground truth, accept and repair the issue before defending the claim.

## Final Checks

Verify every quoted review passage against the supplied full review, preserving caveats. Check figures, values and manuscript locations after edits. Ensure no proposed run is described in the past tense. Verify venue restrictions on new results and confidential notes rather than inferring them from another year. Never submit or contact reviewers merely because drafting was authorized.
