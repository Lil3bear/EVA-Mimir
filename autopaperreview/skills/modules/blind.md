# Anonymity and Reproducibility

Independent application worksheet augmenting AI-paper-reviewer. The two checks have different acceptance criteria and should not share an unsupported 'pass'.

## Anonymity

Use the venue module's applicable policy before declaring a violation. Check author block, acknowledgments, self-citation wording, repository links, figures, PDF metadata and supplements. An ordinary self-citation is not automatically forbidden. Do not delete valid attribution or publish private code to satisfy an assumed policy. If only TeX is available, visible PDF and metadata inspection remain pending.

## Reproduction Matrix

For each reported table or figure identify: artifact/library/model version; task lists and split roles; data available to the agent; prompts/tools; time, token and retry budgets; environment reset; seeds or run count; success criterion; failure/truncation treatment; denominator and aggregation. Mark each item supplied, absent or ambiguous.

For adaptive systems record which split can propose, select or only evaluate; library freeze point; initial versus retained content; candidate/predecessor run association; and source-to-result linkage. A Git hash supports identity, not evidence that the reported experiment ran with it.

Keep missing values missing. A single run may be reported honestly without invented variance. A documented protocol may still lack execution evidence. Do not run security experiments, contact services, upload datasets or disclose credentials merely to fill a checklist. Prepare precise data requests and limit paper edits to what the actual evidence permits.
