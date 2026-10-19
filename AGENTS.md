# Codex Working Instructions

Read README.md before setup or manuscript work. This branch is the review website,
not the EVA research code. Never reuse private paths or account settings from an
earlier user as a new user's defaults.

## Paper Workflow

1. Establish the canonical paper, current revision, Overleaf remote and code commit.
   Back up and reconcile remote changes before editing.
2. Diagnose the active manuscript and author comments before polishing. Read
   skills/writing-ai-paper/SKILL.md and its references, both zhihu writing skills
   and their references, and skills/modules/contracts.md. Apply all relevant core
   modules in server/skills.mjs. Use paper-rebuttal for counterevidence review and
   figure skills when revising figures. Record scope and unverified evidence.
3. Read relevant Related Work originals and build a source-backed difference table.
   Do not infer novelty or support from titles alone.
4. Align Introduction claims with the real implementation and experiments. Obtain
   author agreement on the structural plan before broad rewriting.
5. Inspect supplied code statically at a recorded commit. Build a claim-to-section-
   to-code-to-evidence map. Never execute unknown research or exploit scripts.
6. Write Method from actual inputs, states, outputs, controls and update rules.
   Separate implemented behavior, proposed design and measured results.
7. Make bounded revisions. Preserve scientific meaning, equations, citations and
   evidence limits. Avoid decorative typography, needless jargon and invented facts.
8. Compare before/after across abstract, introduction, method and results. Reject
   new unsupported claims or contradictions; do not equate fluency with correctness.
9. For managed papers use the website's version-aware source/proposal workflow,
   not direct database or immutable snapshot edits. Compile and inspect the PDF.
   Do not archive untouched or partially addressed author comments.
10. Record files, reasons, model, skill manifest, source revision, checks and commits.
    Push only with authorization, without force. Fetch and compare before reporting
    sync success. Never merely change the base to evade a conflict.

## Access And Scope

- Computer Use is an optional interactive host capability, not part of the
  restricted background codex exec adapter. Access only authorized projects.
- Git URLs are not credentials. Do not scrape cookies or send secrets to models.
  Keep tokens out of logs, papers and commits. Follow tool confirmation and
  user-handoff requirements for credential creation and security warnings.
- Website revisions receive repository Skills explicitly. Host-installed Skills,
  arbitrary code repositories and linked web sources are not automatically loaded.
- Do not enable extra paid models or automatic revision without user authorization.
- Preserve tests, authentication, patch validation, compilation and version history
  when cleaning the repo. Do not alter EVA main or live deployments for doc changes.
