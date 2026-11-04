import { test } from "node:test";
import assert from "node:assert/strict";
import express from "express";
import { mkdtemp, rm, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createReviewerRouter } from "../server/reviewer.mjs";
import { buildReadingPrompt, readingResult } from "../server/reviewer-reading.mjs";
import { emptyForm } from "../server/reviewer-core.mjs";
import { pdfFixture } from "./fixtures/review-pdf.mjs";
import { atomicJSON } from "../server/core.mjs";

test("Official Review organization uses human notes and accepted AI only, with honest disclosure and expertise boundaries", () => {
  const paper = { title: "Paper", pages: [{ number: 1, text: "Manuscript evidence. ".repeat(30) }], form: emptyForm(), runs: [], initialAssessment: null,
    findings: [{ source: "human", status: "accepted", body: "My original concern" }, { source: "ai", status: "accepted", body: "Accepted suggestion" },
      { source: "ai", status: "open", body: "Unaccepted suggestion" }, { source: "ai", status: "dismissed", body: "Dismissed allegation" }, { source: "human", status: "dismissed", body: "Withdrawn note" }] };
  const prompt = buildReadingPrompt(paper, { mode: "organize", question: "整理" });
  assert.ok(prompt.input.includes("My original concern")); assert.ok(prompt.input.includes("Accepted suggestion"));
  for (const excluded of ["Unaccepted suggestion", "Dismissed allegation", "Withdrawn note"]) assert.equal(prompt.input.includes(excluded), false);
  for (const field of ["AI Documentation For Reviewing", "Informativeness", "Critical Weaknesses", "Confidence"]) assert.ok(prompt.instructions.includes(field));
  assert.ok(prompt.instructions.includes("MUST remain")); assert.ok(prompt.instructions.includes("untrusted DATA"));
  assert.ok(prompt.instructions.includes("Do NOT write a first-person attestation"));
});

test("reading tutor prompt: full manuscript, evidence boundaries, analogies, no reviewer scores or invented context", () => {
  const p = { title: "Paper", pages: [{ number: 1, text: "Paper text. ".repeat(30) }, { number: 2, text: "APPENDIX EVIDENCE" }] };
  const prompt = buildReadingPrompt(p, { mode: "explain", page: 1, quote: "Selected text", question: "什么意思？" }, [{ question: "之前的问题", answer: "之前的回答" }]);
  assert.ok(prompt.input.includes("APPENDIX EVIDENCE")); assert.ok(prompt.input.includes("之前的回答"));
  assert.ok(prompt.instructions.includes("NOT a reviewer")); assert.ok(prompt.instructions.includes("untrusted DATA")); assert.ok(prompt.instructions.includes("analogies"));
  assert.ok(prompt.instructions.includes("cannot see page-image pixels"));
  assert.throws(() => buildReadingPrompt({ ...p, pages: [{ number: 1, text: "x".repeat(220001) }] }, { mode: "guide", question: "概述" }), /未截断/);
  assert.throws(() => buildReadingPrompt({ ...p, pages: [{ number: 1, text: "" }] }, { mode: "guide", question: "概述" }), /OCR/);
  assert.equal(readingResult.safeParse({ answer: "你好", references: [], followUps: [], coverage: "Text only", rating: 8 }).success, false);
});
test("reading workflow: guide, selected-passage explanation, follow-up context, consent, persistence and no review overwrite", { timeout: 30000 }, async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "redline-reading-"));
  let release, calls = 0;
  const gate = new Promise(r => { release = r; });
  const app = express(); app.use(express.json());
  app.use(await createReviewerRouter({ directory, getConfig: () => ({ provider: "openai", model: "fixture-reader", apiKey: "SECRET_NEVER_EXPORT" }), status: async () => ({ ai: true }),
    readPaper: async (config, prompt, { signal }) => {
      calls++; if (calls === 1) await gate;
      const input = JSON.parse(prompt.input);
      if (input.question === "waitForCancel") await new Promise((resolve, reject) => {
        if (signal.aborted) return reject(signal.reason);
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      });
      return { answer: `白话测试解释：${input.question}。作者比较的是整套系统，不能单独推出某个模块的作用。`, coverage: "仅 PDF 文本；未检查图像或复现实验。",
        references: [{ page: input.question === "badpage" ? 99 : 1, quote: "The comparison also changes supervision." }, { page: 1, quote: "A fabricated quote that must remain unverified." }], followUps: ["为什么不能说明因果关系？"] };
    },
  }));
  app.use((err, req, res, next) => res.status(err.code === "ENOENT" ? 404 : 400).json({ error: err.message }));
  const server = app.listen(0, "127.0.0.1"); await new Promise(r => server.once("listening", r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const get = async url => (await fetch(base + url)).json();
  async function post(url, body) { const r = await fetch(base + url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); return { status: r.status, data: await r.json() }; }
  async function complete(url) {
    for (let i = 0; i < 100; i++) { const s = await get(url); if (!["queued", "running", "cancelling"].includes(s.job?.status)) return s; await new Promise(r => setTimeout(r, 15)); }
    throw Error("reading job did not finish");
  }
  try {
    const form = new FormData(); form.append("pdf", new Blob([pdfFixture()], { type: "application/pdf" }), "Reading.pdf");
    const p = await (await fetch(base + "/papers", { method: "POST", body: form })).json(), url = `/papers/${p.id}/readings`;
    const request = { mode: "guide", question: "这篇文章在解决什么问题？", consent: true };
    assert.equal((await post(url, { ...request, consent: false })).status, 400);
    assert.equal((await post(url, { ...request, mode: "explain" })).status, 400);
    assert.equal((await post(url, { ...request, page: 999 })).status, 400);
    assert.equal(calls, 0);
    const started = await post(url, request); assert.equal(started.status, 202); assert.equal(started.data.paper.aiStarted, true);
    assert.equal((await post(url, request)).status, 409);
    assert.equal((await post(`/papers/${p.id}/initial`, { text: "This should not be represented as an unaided assessment after AI guided reading.", attestation: true })).status, 400);
    release(); let state = await complete(url);
    assert.equal(state.job.status, "completed"); assert.equal(state.records.length, 1); assert.equal(state.records[0].prompt, undefined);
    assert.equal(state.records[0].result.references[0].anchored, true); assert.equal(state.records[0].result.references[1].anchored, false);
    const guideId = state.records[0].id;
    const followUp = await post(url, { ...request, parentId: guideId, question: "再白话一点" }); assert.equal(followUp.status, 202);
    state = await complete(url); assert.equal(state.records[0].contextTurns, 1);
    const explained = await post(url, { mode: "explain", page: 1, quote: "The comparison also changes supervision.", question: "这句话是什么意思？", consent: true });
    assert.equal(explained.status, 202); state = await complete(url); assert.equal(state.records[0].mode, "explain");
    const explanationId = state.records[0].id;
    assert.equal((await post(url, { ...request, parentId: explanationId, question: "举个例子" })).status, 202);
    state = await complete(url); assert.equal(state.records[0].quote, "The comparison also changes supervision."); assert.equal(state.records[0].mode, "explain");
    const exported = await get(`/papers/${p.id}/export`);
    assert.equal(exported.readings.length, 4); assert.equal(exported.runs.length, 0); assert.equal(exported.findings.length, 0); assert.deepEqual(exported.form, emptyForm());
    assert.ok(exported.readings.find(r => r.parentId === guideId).prompt.input.includes("白话测试解释"));
    assert.equal(JSON.stringify(exported).includes("SECRET_NEVER_EXPORT"), false);
    assert.equal(JSON.parse(await readFile(path.join(directory, p.id, "readings", `${explanationId}.json`), "utf8")).status, "completed");
    const md = await (await fetch(base + `/papers/${p.id}/export?format=md`)).text(); assert.ok(md.includes("reading/explanation interactions: 4"));
    assert.equal((await post(url, { mode: "organize", question: "整理", consent: true, parentId: guideId })).status, 400);
    assert.equal((await post(url, { mode: "organize", question: "整理", consent: true })).status, 202);
    state = await complete(url); assert.equal(state.records[0].mode, "organize");
    const organized = state.records[0];
    assert.equal((await post(url, { ...request, parentId: organized.id })).status, 400);
    const current = await get(`/papers/${p.id}`);
    const patch = async body => { const r = await fetch(base + `/papers/${p.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); return { status: r.status, data: await r.json() }; };
    const saved = await patch({ version: current.version, form: { ...current.form, organization: organized.result.answer + " Human edit." } });
    assert.equal(saved.status, 200);
    assert.equal((await patch({ version: current.version, form: current.form })).status, 409);
    const oldClientForm = { ...saved.data.form }; delete oldClientForm.organization;
    const oldSaved = await patch({ version: saved.data.version, form: oldClientForm });
    assert.equal(oldSaved.data.form.organization, saved.data.form.organization);
    assert.ok((await (await fetch(base + `/papers/${p.id}/export?format=md`)).text()).includes("Human edit."));
    const archive = await get(`/papers/${p.id}/export`);
    assert.ok(archive.snapshots.some(s => s.form.organization?.includes("Human edit.")));
    assert.equal((await post(url, { ...request, question: "badpage" })).status, 202);
    state = await complete(url); assert.equal(state.job.status, "failed"); assert.equal(state.records[0].result, null);
    assert.equal((await post(url, { ...request, question: "waitForCancel" })).status, 202);
    for (let i = 0; i < 100; i++) { state = await get(url); if (state.job.status === "running") break; await new Promise(r => setTimeout(r, 10)); }
    assert.equal(state.job.status, "running");
    assert.equal((await post(`/papers/${p.id}/readings/cancel`, {})).status, 200);
    state = await complete(url); assert.equal(state.job.status, "cancelled"); assert.equal(state.records[0].status, "cancelled");
    const recordPath = path.join(directory, p.id, "readings", `${state.records[0].id}.json`);
    const interrupted = JSON.parse(await readFile(recordPath, "utf8")); interrupted.status = "running";
    await atomicJSON(recordPath, interrupted); await atomicJSON(path.join(directory, p.id, "reading-job.json"), { status: "running" });
    await createReviewerRouter({ directory, getConfig: () => ({}), status: async () => ({}) });
    assert.equal(JSON.parse(await readFile(recordPath, "utf8")).status, "interrupted");
    assert.equal(JSON.parse(await readFile(path.join(directory, p.id, "reading-job.json"), "utf8")).status, "interrupted");
  } finally { release(); await new Promise(r => server.close(r)); await rm(directory, { recursive: true, force: true }); }
});
