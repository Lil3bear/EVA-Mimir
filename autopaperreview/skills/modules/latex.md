# LaTeX: From Exact Edit to Verified PDF

Independent application worksheet augmenting paper-pre-submission-review. Compilation, visual quality and scientific validity are different checks.

## Source Integrity

Use the current project revision and active main file. Preserve file encoding, math, citation keys, labels, environments and unrelated content. Match exact current source or a host-provided edit target; do not overwrite a whole file because PDF-extracted text does not match TeX. Reject ambiguous, overlapping, stale and no-op edits. Escaping must preserve the intended literal character without creating new commands.

## Build

Compile the candidate in an isolated build directory with the existing engine and class/BST assets. Inspect fatal errors, unresolved references/citations and relevant overfull warnings. A missing package is an environment issue, not permission to replace the document class or fabricate a PDF. Keep the previous source/PDF when compilation fails.

## Visual Pass

Inspect rendered changed pages and nearby float movement at readable print size. Check clipping, missing glyphs, captions, equations, legends, table width and pagination. Source review cannot verify a binary figure's arrows or small labels. Preserve quantitative values and distinguish a caption edit from a figure asset edit.

## Commit and Completion

Record effective source diffs, actual model/transport, Skills file hashes, comment IDs, parent revision, build result and Git commit. Refresh the paper PDF only from that compiled candidate. Archive only comments whose stated requirement is actually satisfied; a narrowed claim does not complete a requested ablation. State separately whether Overleaf was pushed; local Git history is not remote synchronization.
