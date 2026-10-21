---
name: snap-write
description: Polish selected academic sentences or short paragraphs into natural, precise English while preserving the author's logic, technical meaning, and information density. Use for local paper edits, terminology checks against relevant papers, and removal of Chinglish or robotic phrasing, especially for ICML, NeurIPS, and ICLR-style prose. Not a full-paper restructure or experiment-generation workflow.
---

# Snap Write

Refine the author's expression, not their research story. This skill captures the workspace author's preference for local academic editing: coherent, technically accurate prose with natural sentence rhythm, neither ornate nor telegraphic.

## Scope and Meaning

- Edit only the selected sentences or paragraph. Read nearby context to resolve references, notation, and the intended logical chain; do not rewrite surrounding sections without a request.
- Preserve the original propositions, causal direction, conditions, contrasts, and contribution ownership. Keep numbers, citations, notation, and claim strength intact unless an evidenced correction is needed.
- Add no new mechanism, experiment, result, comparison, novelty claim, or technical explanation merely to make the writing sound more academic.
- Fix grammar, semantics, and logical connections where the intended meaning is clear. If a correction requires choosing between different scientific meanings, flag the ambiguity rather than inventing the author's intent.
- Preserve substantive detail and approximately the original level of elaboration. Remove actual repetition, not explanations needed to follow the argument. Do not compress a paragraph into short slogans or substantially shorten it unless requested.

## Language and Rhythm

- Aim for idiomatic research English consistent with relevant ICML, NeurIPS, and ICLR papers, not a purported universal conference house style.
- Prefer precise, established vocabulary and direct verbs over inflated synonyms, noun piles, literal Chinese translations, or elaborate new names.
- Use moderate sentence lengths and varied, connected syntax. Split deeply nested clauses, but do not turn every clause into an isolated short sentence. A sentence can carry a main claim and a closely related explanation.
- Use commas for grammatical subordinate clauses and natural phrasing; do not join independent clauses with comma splices. Use a conjunction or a full stop when appropriate.
- Make logical relations explicit only where needed. Do not mechanically add transition words or repeat the previous sentence in a new form.
- Avoid defensive or manual-like prose: do not append generic disclaimers, implementation warnings, procedural instructions, or lists of what the method does not do to every claim. Integrate necessary scope into the sentence naturally. Preserve limitations that materially change correctness; never remove uncertainty to strengthen an unsupported claim.
- Use quotation marks, emphasis, parenthetical asides, dashes, and `\texttt{}` sparingly. Reserve `\texttt{}` for literal code identifiers or syntax when needed, not ordinary technical concepts.
- Avoid unnecessary A-B constructions, invented compound labels, and repeated hyphenation. Retain conventional hyphenated technical terms when they are correct; this is not a ban on standard terminology.
- Preserve valid LaTeX and citation commands. Do not introduce formatting to simulate importance.

## Terminology Checks Against Papers

Use this optional step when a term or collocation is uncertain, the author supplies a reference corpus, or the author explicitly asks to search N papers about topic XXX for usage YYY. N, XXX, and YYY are task parameters, not fixed search instructions.

1. Locate relevant papers in the supplied local folder or known paper library. Prefer original papers discussing the same mechanism, task, and section type. Do not scan unrelated private folders merely to fill a quota.
2. Search extracted text or source for the expression and plausible alternatives, then inspect the surrounding passage. Check the referent and technical definition, not just frequency or surface similarity. Verify PDF extraction against the page when mathematical symbols or hyphenation are ambiguous.
3. Record which papers were actually inspected and the section/page supporting each useful usage. If fewer than N suitable papers are available, state the actual count; do not imply a complete corpus search.
4. Choose the term that matches this manuscript's meaning and established local notation. A popular term is not a substitute for the correct concept. Distinguish a standard term from an author-defined one, and do not rename a concept in one sentence while leaving conflicting names elsewhere.
5. Use public primary sources if the user requests web research or uncertainty requires verification. Do not upload unpublished manuscript text to a search engine. Report the search scope and concise source references when terminology research materially affects the edit.

Learn usage and grammatical patterns, not distinctive sentences to copy. Do not add citations to the manuscript solely because a source informed the phrasing. A routine local polish with clear terminology does not require an external-model call or a literature survey.

## Local Editing Pass

Before editing, identify the passage's intended claim and logical progression. Draft a restrained revision, then compare original and revision for:

- Meaning: same claims, qualifiers, dependencies, and technical referents.
- Correctness: grammar, reference resolution, terminology, and causal language.
- Flow: natural transitions and clause boundaries, without long difficult sentences or robotic fragments.
- Density: no lost substantive detail and no added explanation unsupported by the source.
- Voice: professional research prose, not promotional copy, a defensive audit, or an operating manual.

If the original already works, retain it. Do not rewrite every word to demonstrate activity.

## Output and Application

Default to one polished version, in the original format. For English paper text, return English prose; for LaTeX, preserve LaTeX. If asked to turn Chinese notes into English, follow their logic rather than their literal syntax.

Add only brief notes for substantive terminology decisions, unresolved ambiguity, or a research-backed correction. If the user requests revised text only, omit routine explanation and alternatives. Do not silently resolve a scientific ambiguity just to satisfy that format.

When editing files, change only the authorized passage and retain version history through the existing workflow. Invoking this skill alone does not authorize publishing, pushing to Overleaf, marking comments complete, or calling paid external models.
