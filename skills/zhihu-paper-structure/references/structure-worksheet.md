# Structure Worksheet

Source inspiration: 丁霄汉, https://zhuanlan.zhihu.com/p/593195527. The worksheet, schemas and synthetic examples below are our operational extensions, not quotations or claims about the original article's exact organization.

## Diagnose Before Reordering

Read the abstract, introduction, method opening, main results and conclusion together. Write a short argument spine in the manuscript's own terms: problem -> specific limitation -> proposed mechanism -> observable consequence -> supporting evidence -> boundary. A missing link is a diagnosis, not permission to invent it.

Use only the rows needed for the requested scope:

| Question | Inspect | Failure signal | Smallest defensible repair |
| --- | --- | --- | --- |
| Is the problem concrete? | Introduction's task and failure setting | Broad motivation with no condition under which prior practice fails | Name the condition and affected outcome; cite or label it as a hypothesis |
| Does the mechanism address that problem? | Method overview and data flow | Component inventory with no explanation of what each output changes | Explain input, transformation, downstream decision and assumption |
| Who owns the contribution? | Contributions, component citations, implementation | Borrowed estimator or simulator presented as newly invented | Attribute the component and identify the actual new interface, formulation or evaluation |
| Is the contribution testable? | Each contribution paired with experiment | Claim of better safety supported only by startup or unit tests | Narrow to demonstrated behavior; record the required end-to-end evidence separately |
| Is the story consistent? | Abstract vs method vs conclusion | A proposed capability becomes a completed result later | Align state and scope across the affected passages |
| Does the evidence isolate the mechanism? | Baselines and ablations | Changed backbone, observation or budget credited to one module | State the confound; do not call the comparison causal |

For an architecture paper, distinguish three things: use of existing components, engineering work required to integrate them, and the scientific claim about why the integrated design matters. Engineering effort alone is not novelty; a genuinely new integration may be a contribution when its nontrivial design and evaluation are explicit.

## Revision Artifact

For substantive review, use a compact map rather than a second outline disconnected from the text:

| Claim / passage | Reader question | Mechanism and ownership | Evidence location and state | Gap | Proposed edit |
| --- | --- | --- | --- | --- | --- |

Use exact source locations. Evidence states can be design, implemented, tested under a stated scope, failed, or unknown. Preserve the existing project's ledger IDs if present. Do not create a new ledger for a one-paragraph request.

If restructuring is authorized, identify the new role of each moved paragraph and what duplicate content disappears. Leave equations, citations and reported measurements intact unless their correction is independently supported. Keep important failures in limitations or analysis; moving them out of the introduction is not a license to omit them.

## Synthetic Example and Countercheck

Unsupported: "We introduce a stereo physics engine that guarantees safe navigation."

When the evidence is only a wired stereo estimator and simulator: "We integrate an existing stereo estimator with a physics-based candidate evaluator. The current implementation has passed interface tests; navigation safety remains unvalidated."

This wording repairs attribution and evidence state, but it does not establish a publishable contribution. Ask what design differs from prior integrations and which controlled test could distinguish its benefit.

Countercheck the strongest contribution: could the same result arise from a better controller, additional observations, evaluator-only ground truth, or more compute? If yes, preserve that alternative explanation until an appropriate comparison excludes it. Report the missing comparison as an experiment need, not a prose defect that has been closed.

## Completion

Re-read the revised argument spine across sections. A successful structural repair makes the proposed mechanism and its current evidence understandable; it does not certify correctness, venue compliance, or acceptance.
