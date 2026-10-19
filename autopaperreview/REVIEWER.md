# Redline: PDF-first ICLR review desk

Start the existing server with `PORT=4318 npm run dev`, then open `http://localhost:4318/review`.
The original authoring application at `/` is unchanged. Models and the authenticated access boundary are shared; reviewer records are separate under `data/reviewer/` (or `$DATA_DIR/reviewer/`). Do not expose this local-only instance to the internet without configuring the existing authenticated deployment.

## Workflow

- Import one or more PDFs. The original bytes, SHA-256, page text and geometry are retained locally. PDFs are rendered with PDF.js; text selections can become page-linked human annotations.
- Selecting PDF text opens an anchored Chinese translation panel. It reuses the browser-native translation client and its cache; unsupported browsers never silently fall back to a paid model. A cloud translation requires explicit selection-text consent; an optional per-paper checkbox enables subsequent automatic cloud translation for that paper while it is open. Switching papers revokes that automation. Cloud requests translate only the selected passage, do not modify reviews, and are recorded separately in the full JSON export.
- The AI reading panel provides whole-paper guided reading and plain-language explanations of selected passages. Follow-up questions retain the selected passage and the most recent six completed turns. Answers distinguish manuscript claims, evidence, background and illustrative analogies; their PDF citations are checked and can be opened in the reader. It reads extracted text, not figure pixels. Requests require cloud consent and use the configured model. Background reading jobs have independent progress, cancellation and restart recovery. Prompts, results, questions and model provenance are saved under each paper's `readings/` directory and included in the JSON export. Reading does not overwrite the review, but does mark AI assistance as started so a later record cannot be represented as an unaided original assessment.
- Start an AI exploratory review, or seal your independently written initial assessment before starting formal review assistance. The initial record is immutable and cannot be created after this system has started AI review. This cannot certify whether other AI tools were used; the reviewer remains responsible for truthful disclosure.
- Review AI findings individually. Exact quotes are checked against the stated physical PDF page. Quotes that cannot be matched remain unverified, not silently accepted. Findings include severity, certainty, decision impact, counterevidence, and a minimal rebuttal question.
- Accept, dismiss, annotate, or explicitly copy a finding into the editable ICLR-style review fields. AI never overwrites the human form or assigns human confidence/numeric ratings. Whole AI drafts can be adopted only through an explicit confirmation.
- Text fields autosave after a short debounce. Optimistic versions prevent silent overwrites; earlier forms are snapshotted. Jobs survive navigation, are cancellable, and interrupted work is marked on server restart. AI inputs and validated outputs are retained per round.
- Export the human review as Markdown, or a complete JSON archive including prompts, outputs, initial assessment, annotations, event history and previous forms. Export contains confidential manuscript text; protect it accordingly. Nothing is submitted automatically to OpenReview.

## Review skills and provenance

`skills/iclr-review.md` is an original ICLR-oriented adapter. It orchestrates contribution/evidence reading, experimental validity, logical/theoretical checks, skeptical adjudication and formal review synthesis in a structured model request. The model performs these reading passes; there are no hidden autonomous agents or experimental executions.

The scientific and mathematics reference prompts are loaded from the existing, pinned MIT-licensed resources documented in `ATTRIBUTION.md`:

- https://github.com/chantsss/paper-pre-submission-review
- https://github.com/FanBroWell/AI-paper-reviewer

CSPaper was researched as a product reference: https://github.com/cspaper/platform-examples. Its published repository provides API examples, not the complete proprietary reviewer skills. No CSPaper API is called and no CSPaper results are simulated.

Official sources checked 2026-10-17:

- https://iclr.cc/Conferences/2027/ReviewerGuidelines
- https://iclr.cc/Conferences/2027/AIPolicyForReviewers

The 2027 official review invitation was not publicly retrievable (403). Fields follow the common ICLR structure: Summary, Strengths, Weaknesses, Questions, Limitations, Ethical Concerns, Rating Justification, Soundness, Presentation, Contribution, Rating, Confidence. Numeric scales are deliberately not labeled as verified 2027 rules: the human must match their assigned OpenReview form.

## Coverage limits

The AI currently receives PDF-extracted text, not page-image pixels. It cannot reliably verify figure-only evidence, malformed extracted equations, external citation identity or experimental code. These limitations are part of every prompt; no OCR or fake findings are provided. Scanned PDFs remain readable and annotatable, but AI runs require a usable text layer. PDFs above 150 pages or 40 MB, and text requests above 220,000 characters, are rejected explicitly rather than silently truncated.

API keys remain in the shared model configuration in memory, not reviewer exports. Model requests still send extracted manuscript text and selected human context to the configured cloud provider, including in Codex mode; each run requires consent.

## Checks

`node --test test/reviewer.test.mjs` checks actual PDF extraction, quote validation, manuscript/policy prompts, immutable original assessments, conflict protection, asynchronous review provenance, human-edit preservation, export and persistence. Tests use an explicitly injected fixture model; the running application has no mock review provider.
