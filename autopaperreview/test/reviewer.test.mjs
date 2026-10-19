import { test } from "node:test";
import assert from "node:assert/strict";
import express from "express";
import { mkdtemp, rm, readFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { createReviewerRouter } from "../server/reviewer.mjs";
import { emptyForm, extractPDF, locateQuote, reviewMarkdown, validateFindings } from "../server/reviewer-core.mjs";
import { buildReviewRequest } from "../server/reviewer-ai.mjs";
import { pdfFixture } from "./fixtures/review-pdf.mjs";
test("PDF evidence: extract actual pages, verify quotes, never certify fabricated evidence", async () => {
  const parsed = await extractPDF(pdfFixture());
  assert.equal(parsed.pages.length, 1);
  assert.ok(parsed.pages[0].text.includes("physical validity"));
  assert.equal(locateQuote(parsed.pages, 1, "Our method improves physical validity."), true);
  assert.equal(locateQuote(parsed.pages, 2, "Our method improves physical validity."), false);
  const [finding] = validateFindings([{ page: 1, quote: "A sentence the authors never wrote.", certainty: "confirmed" }], parsed.pages, "run");
  assert.equal(finding.anchored, false); assert.equal(finding.certainty, "unverified");
  await assert.rejects(() => extractPDF(Buffer.from("not a PDF")), /有效/);
});
test("review prompt includes full appendix, policy safeguards and selected scientific lenses", async () => {
  const request = await buildReviewRequest({ title: "Example", venue: "ICLR 2027", pages: [{ number: 1, text: "Evidence ".repeat(60) }, { number: 2, text: "APPENDIX EVIDENCE" }], findings: [] },
    { mode: "explore", language: "en", skillIds: ["claims", "logic"], instructions: "Check causality." });
  assert.ok(request.input.includes("APPENDIX EVIDENCE"));
  assert.ok(request.instructions.includes("Do not generate numeric scores"));
  assert.ok(request.instructions.includes("untrusted data"));
  await assert.rejects(() => buildReviewRequest({ pages: [{ number: 1, text: "x".repeat(220100) }], findings: [] }, { skillIds: ["claims"], language: "zh" }), /未截断/);
});
test("PDF review lifecycle: immutable initial assessment, concurrent edits, AI provenance, exports and persistence", { timeout: 30000 }, async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "redline-test-"));
  let release;
  const generated = new Promise(resolve => { release = resolve; });
  const result = { summary: "Evidence-grounded review.", strengths: "Useful problem.", weaknesses: "Comparison changes supervision.", questions: "Please clarify inputs.", limitations: "Text-only.", ethics: "No concern identified.", justification: "A matched comparison is needed.", coverage: "Read extracted text; no figures or experiments verified.",
    findings: [{ title: "Confounded comparison", page: 1, quote: "The comparison also changes supervision.", section: "Experiments", body: "The comparison changes more than one factor.", impact: "Attribution is uncertain.", request: "Match supervision.", counterevidence: "System-level utility is still supported.", severity: "major", certainty: "conditional", category: "experiments" }] };
  const app = express(); app.use(express.json());
  let translationCalls = 0;
  app.use(await createReviewerRouter({ directory, getConfig: () => ({ provider: "openai", model: "fixture-model", apiKey: "DO_NOT_EXPORT" }), status: async () => ({ ai: true }), generate: async () => { await generated; return result; },
    translationModel: "", translatePassage: async (text, config) => { translationCalls++; assert.equal(config.model, "fixture-model"); return { translation: "该比较还改变了监督条件。" }; },
  }));
  app.use((err, req, res, next) => res.status(err.code === "ENOENT" ? 404 : 400).json({ error: err.message }));
  const server = app.listen(0, "127.0.0.1"); await new Promise(resolve => server.once("listening", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  async function call(url, body, method = "POST") { const res = await fetch(base + url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); return { status: res.status, data: await res.json() }; }
  try {
    const form = new FormData(); form.append("pdf", new Blob([pdfFixture()], { type: "application/pdf" }), "example.pdf");
    const imported = await fetch(`${base}/papers`, { method: "POST", body: form });
    assert.equal(imported.status, 201); let p = await imported.json(); const url = `/papers/${p.id}`;
    assert.equal((await fetch(base + `${url}/pdf`)).headers.get("content-type"), "application/pdf");
    const translation = { text: "The comparison also changes supervision.", engine: "quality", consent: true };
    assert.equal((await call(`${url}/translate`, { ...translation, consent: false })).status, 400);
    assert.equal((await call(`${url}/translate`, { ...translation, text: "x".repeat(10001) })).status, 400);
    assert.equal((await call(`${url}/translate`, { ...translation, engine: "fast" })).status, 400);
    assert.equal(translationCalls, 0);
    const translated = await call(`${url}/translate`, translation); assert.equal(translated.status, 200); assert.equal(translated.data.translation, "该比较还改变了监督条件。");
    const afterTranslation = await (await fetch(base + url)).json(); assert.equal(afterTranslation.version, p.version); assert.equal(afterTranslation.aiStarted, false);
    const request = { mode: "official", language: "en", instructions: "Focus on central claims.", skillIds: ["claims", "experiments", "synthesis"], consent: true };
    assert.equal((await call(`${url}/runs`, request)).status, 400);
    assert.equal((await call(`${url}/initial`, { text: "My independent assessment: useful contribution, but causal evidence is incomplete.", attestation: true })).status, 200);
    assert.equal((await call(`${url}/initial`, { text: "This replacement must not be allowed after the assessment is sealed.", attestation: true })).status, 400);
    assert.equal((await call(`${url}/runs`, { ...request, consent: false })).status, 400);
    const started = await call(`${url}/runs`, request);
    assert.equal(started.status, 202, JSON.stringify(started.data));
    assert.equal((await call(`${url}/runs`, request)).status, 409);
    p = await (await fetch(base + url)).json();
    const manualForm = { ...emptyForm(), summary: "Independent HUMAN draft must survive AI completion.", rating: "Human score" };
    const edited = await call(url, { version: p.version, form: manualForm }, "PATCH"); assert.equal(edited.status, 200);
    assert.equal((await call(url, { version: p.version, form: emptyForm() }, "PATCH")).status, 409);
    release();
    for (let i = 0; i < 100; i++) { p = await (await fetch(base + url)).json(); if (p.job?.status === "completed") break; await new Promise(r => setTimeout(r, 30)); }
    assert.equal(p.job.status, "completed"); assert.equal(p.form.summary, manualForm.summary); assert.equal(p.form.rating, "Human score");
    assert.equal(p.findings[0].anchored, true); assert.equal(p.runs[0].result.summary, result.summary); assert.ok(p.runs[0].prompt.input.includes("Appendix A"));
    assert.equal((await call(`${url}/findings`, { title: "Manual finding", body: "My reasoning.", page: 99, quote: "", category: "logic", severity: "major" })).status, 400);
    const added = await call(`${url}/findings`, { title: "Manual finding", body: "My reasoning.", page: 1, quote: "Our method improves physical validity.", category: "logic", severity: "major" });
    assert.equal(added.status, 200);
    assert.equal((await call(`${url}/findings/${p.findings[0].id}`, { status: "accepted", reviewerNote: "Checked against the appendix." }, "PATCH")).status, 200);
    const exported = await (await fetch(base + `${url}/export`)).json();
    assert.equal(exported.translations.length, 1); assert.equal(exported.translations[0].text, translation.text);
    assert.equal(translationCalls, 1);
    assert.equal(exported.snapshots.length, 1); assert.ok(exported.initialAssessment.text.startsWith("My independent"));
    assert.equal(JSON.stringify(exported).includes("DO_NOT_EXPORT"), false);
    assert.ok((await (await fetch(base + `${url}/export?format=md`)).text()).includes("Independent HUMAN"));
    const stored = JSON.parse(await readFile(path.join(directory, p.id, "paper.json"), "utf8")); assert.equal(stored.findings.length, 2);
    assert.ok(reviewMarkdown(stored).includes("Original human assessment"));
    assert.equal((await fetch(base + "/papers/not-a-uuid")).status, 400);
  } finally { release(); await new Promise(resolve => server.close(resolve)); await rm(directory, { recursive: true, force: true }); }
});
