# Presentation, LaTeX, and final PDF

Review scientific scope before prose. Preserve qualifiers and uncertainty; fluent wording must not strengthen claims beyond evidence.

## Writing and structure

- Check whether readers can identify the problem, contribution, difference from prior work, evidence, and limitation. Prefer clear contributions over promotional novelty language.
- Match abstract/introduction numbers and scope to results. A five-sentence abstract or fixed introduction length is an optional drafting aid, never a default requirement.
- Check logical transitions, antecedents, consistent names and notation, and assumptions before use. Recommend concrete rewrites for ambiguity; avoid enforcing stylistic preferences without a benefit to meaning.
- Check figures/tables for metrics, units, datasets, comparison conditions, aggregation, and applicable uncertainty definitions. Captions need enough context for their purpose without duplicating the paper.
- Check limitations against evidence. Do not require a separately titled section unless applicable policy does.

For requested sentence-level edits, show original English, proposed English, and reasons in the user's language. Add Chinese translations when requested; do not turn every audit into a sentence-by-sentence rewrite.

## Source and build

Inspect the entrypoint, bibliography setup, and build instructions. Search unresolved labels/citations, draft comments, placeholders, duplicate labels, and style overrides, then inspect each hit in context. Literal `TODO`, `??`, or names in comments may not appear in the submitted PDF.

When compilation is available, use the intended toolchain and an isolated build directory or temporary copy to avoid overwriting the submitted artifact. Read commands before execution; do not blindly run repository scripts or enable shell escape. Compilation is unnecessary for many narrow reviews.

Inspect errors/warnings for unresolved references, bibliography failures, missing glyphs, and overfull boxes. A warning does not prove visible damage. Report toolchain failures separately from manuscript defects.

Do not install a large TeX distribution merely for an audit without an explicit need. If compilation is unavailable, inspect supplied source/PDF and state that no fresh build was checked.

## Rendered artifact

For a final-PDF audit, render and inspect every supplied submission page, including references and included appendices, with available PDF tools. Text extraction alone cannot establish visual correctness. State pages that could not be inspected.

Check clipping, overlap, unreadable fonts, figure resolution, mathematical glyphs, alignment, page breaks, missing content, and cross-references. Verify page accounting/template features against recorded rules. Inspect PDF properties/metadata and links for anonymity.

Distinguish PDF page index from printed page/section identifiers. Use stable source file/line locations where available, plus section/figure/table locators so edits do not make findings unusable.

If source and PDF differ, state which artifact each finding concerns. Rebuild when feasible within task scope; otherwise final-artifact readiness remains pending. Successful compilation does not prove visual correctness.

After edits, inspect affected pages again; expand to the whole document if pagination or global style changed. Preserve official template files and the original artifact unless the user requested changes to them.
