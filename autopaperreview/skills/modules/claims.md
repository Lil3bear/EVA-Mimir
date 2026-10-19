# Claims: Match the Verb to the Evidence

Independent worksheet augmenting paper-pre-submission-review. Its role is evidence calibration, not cautious-sounding prose for its own sake.

## Claim Record

For each consequential claim record: subject, asserted capability, conditions, quantifier, comparison, artifact and version. Classify the evidence as design, implemented path, observed execution, controlled measurement, proof or unknown. A design diagram cannot establish measured benefit; a log cannot by itself establish generality.

## Decision Tests

- 'Prevents', 'guarantees', 'ensures': require the asserted invariant and its assumptions, not just a filter or passing tests. A regex screens known patterns; it does not establish that all sensitive dependencies are absent.
- Component benefit: identify a comparison that changes that component while holding relevant conditions fixed. Otherwise describe a system-level observation and label mechanism explanations as untested where appropriate.
- Generalization: identify what was frozen, what data influenced selection and what remained outside selection. Repeated use of an admission set makes it validation data, not an untouched test set.
- Superiority: compare the same metric, information condition, task population and budget. Published best configurations may be useful references without constituting a controlled comparison.
- Efficiency: distinguish per-attempt, per-task and per-success cost; identify the treatment, matched population, failures, truncation and aggregation. Do not improve interpretability by silently inventing any of these.

## Rewriting Without Inventing Evidence

If the text overstates a supported design, narrow the claim and check abstract, captions, results and conclusion for the same assertion. If a core scientific requirement remains unproved, keep its issue open. 'May' or 'suggests' does not create evidence: explain the actual observation, or omit the speculation.

Synthetic example: separate 'each update edits one reference file' from 'updates cannot interfere behaviorally'. The former may follow from an enforced file boundary; the latter needs an additional argument or experiment. Preserve that distinction in every section.
