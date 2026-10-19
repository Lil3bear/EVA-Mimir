import express from "express";
import multer from "multer";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, readdir, writeFile, rm } from "node:fs/promises";
import { z } from "zod";
import { atomicJSON } from "./core.mjs";
import { Jobs } from "./jobs.mjs";
import { extractPDF, emptyForm, formSchema, locateQuote, validateFindings, reviewMarkdown } from "./reviewer-core.mjs";
import { lenses, buildReviewRequest, requestReview } from "./reviewer-ai.mjs";
import { translate } from "./translate.mjs";
import { installReadingRoutes, readingRecords } from "./reviewer-reading.mjs";

const uuid = z.string().uuid();
const now = () => new Date().toISOString();
const wrap = fn => async (req, res, next) => { try { await fn(req, res); } catch (e) { next(e); } };
const noteSchema = z.object({
  title: z.string().trim().min(1).max(300), body: z.string().trim().min(1).max(15000),
  page: z.number().int().positive(), quote: z.string().max(10000).default(""),
  severity: z.enum(["critical", "major", "moderate"]), category: z.enum(["claims", "experiments", "logic", "evaluation", "novelty"]),
});
export async function createReviewerRouter({ directory, getConfig, status, generate = requestReview, translatePassage = translate, translationModel = process.env.TRANSLATION_MODEL, readPaper }) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const router = express.Router();
  const folder = id => path.join(directory, uuid.parse(id));
  const file = id => path.join(folder(id), "paper.json");
  const load = async id => JSON.parse(await readFile(file(id), "utf8"));
  const save = p => atomicJSON(file(p.id), p);
  const translationLog = id => readFile(path.join(folder(id), "translations.json"), "utf8").then(JSON.parse).catch(e => { if (e.code === "ENOENT") return []; throw e; });
  const queues = new Map();
  async function locked(id, fn) {
    uuid.parse(id);
    const prior = queues.get(id) || Promise.resolve();
    const task = prior.catch(() => {}).then(fn);
    queues.set(id, task);
    try { return await task; } finally { if (queues.get(id) === task) queues.delete(id); }
  }
  function event(p, type, detail, extra = {}) {
    p.version++; p.updated = now(); p.history.unshift({ id: randomUUID(), time: p.updated, type, detail, ...extra });
  }
  const jobs = new Jobs({
    read: id => readFile(path.join(folder(id), "job.json"), "utf8").then(JSON.parse).catch(e => { if (e.code === "ENOENT") return null; throw e; }),
    write: (id, state) => atomicJSON(path.join(folder(id), "job.json"), state),
  });
  for (const id of await readdir(directory)) {
    if (!uuid.safeParse(id).success) continue;
    const p = await load(id);
    if (p.runs.some(r => ["queued", "running"].includes(r.status))) {
      await jobs.get(id);
      for (const run of p.runs.filter(r => ["queued", "running"].includes(r.status))) {
        Object.assign(run, { status: "interrupted", error: "服务重启，未将未完成输出当作正式结果", completed: now() });
      }
      await save(p);
    }
  }
  const publicPaper = async p => ({ ...p, job: await jobs.get(p.id) });
  await installReadingRoutes(router, { directory, folder, load, save, locked, event, publicPaper, getConfig, readPaper });
  const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 40 * 1024 * 1024, files: 1 } });
  router.get("/meta", wrap(async (req, res) => res.json({
    lenses, ...(await status()), fastTranslation: Boolean(translationModel && getConfig().provider !== "codex" && getConfig().apiKey), translationModel: translationModel || null,
    venue: "ICLR 2027", policyURL: "https://iclr.cc/Conferences/2027/AIPolicyForReviewers",
    rubricStatus: "ICLR 常用字段；2027 数字评分图例需以分配到的 OpenReview 表单核对。",
    sources: [
      { name: "ICLR Reviewer Guide", url: "https://iclr.cc/Conferences/2027/ReviewerGuidelines" },
      { name: "ICLR AI Policy", url: "https://iclr.cc/Conferences/2027/AIPolicyForReviewers" },
      { name: "CSPaper · Agentic Review API（参考，未接入）", url: "https://github.com/cspaper/platform-examples" },
      { name: "AI-paper-reviewer · MIT", url: "https://github.com/FanBroWell/AI-paper-reviewer" },
      { name: "Scientific Review · MIT", url: "https://github.com/chantsss/paper-pre-submission-review" },
    ],
  })));
  router.get("/papers", wrap(async (req, res) => {
    const result = [];
    for (const id of await readdir(directory)) {
      if (!uuid.safeParse(id).success) continue;
      const p = await load(id);
      result.push({ id, title: p.title, filename: p.filename, venue: p.venue, updated: p.updated, pageCount: p.pages.length,
        findings: p.findings.length, accepted: p.findings.filter(f => f.status === "accepted").length, completed: p.completed });
    }
    res.json(result.sort((a, b) => b.updated.localeCompare(a.updated)));
  }));
  router.post("/papers", upload.single("pdf"), wrap(async (req, res) => {
    if (!req.file) throw new Error("请选择 PDF 文件");
    const parsed = await extractPDF(req.file.buffer);
    const id = randomUUID();
    const filename = Buffer.from(req.file.originalname, "latin1").toString("utf8").replace(/[\x00-\x1f]/g, "").slice(0, 240);
    const p = { id, title: parsed.title || filename.replace(/\.pdf$/i, ""), filename, hash: parsed.hash, venue: "ICLR 2027 · Main Conference",
      pages: parsed.pages, created: now(), updated: now(), version: 1, completed: false, form: emptyForm(), findings: [], runs: [],
      history: [{ id: randomUUID(), time: now(), type: "import", detail: `导入 ${parsed.pages.length} 页 PDF` }], initialAssessment: null, aiStarted: false };
    await mkdir(folder(id), { recursive: true, mode: 0o700 });
    try { await writeFile(path.join(folder(id), "manuscript.pdf"), req.file.buffer, { mode: 0o600 }); await save(p); }
    catch (e) { await rm(folder(id), { recursive: true, force: true }); throw e; }
    res.status(201).json(await publicPaper(p));
  }));
  router.get("/papers/:id", wrap(async (req, res) => res.json(await publicPaper(await load(req.params.id)))));
  router.get("/papers/:id/pdf", wrap(async (req, res) => {
    await load(req.params.id);
    res.type("pdf").sendFile("manuscript.pdf",{root:folder(req.params.id)});
  }));
  router.post("/papers/:id/translate", wrap(async (req, res) => {
    const input = z.object({ text: z.string().trim().min(1).max(10000), engine: z.enum(["fast", "quality"]), consent: z.literal(true) }).strict().parse(req.body);
    const p = await load(req.params.id), config = { ...getConfig() };
    if (input.engine === "fast") {
      if (!translationModel || config.provider === "codex") throw new Error("尚未配置快速翻译模型，不会自动回退到审稿模型");
      config.model = translationModel;
    }
    const result = await translatePassage(input.text, config);
    await locked(p.id, async () => {
      const records = await translationLog(p.id);
      records.push({ id: randomUUID(), time: now(), engine: input.engine, model: config.model, provider: config.provider, text: input.text, translation: result.translation });
      await atomicJSON(path.join(folder(p.id), "translations.json"), records);
    });
    res.json(result);
  }));
  router.patch("/papers/:id", wrap(async (req, res) => locked(req.params.id, async () => {
    const input = z.object({ version: z.number().int(), form: formSchema.optional(), title: z.string().trim().min(1).max(500).optional(), completed: z.boolean().optional() }).strict().parse(req.body);
    const p = await load(req.params.id);
    if (p.version !== input.version) return res.status(409).json({ error: "审稿记录已更新，请刷新后再保存。你的本地文本仍保留。" });
    if (input.form) {
      await atomicJSON(path.join(folder(p.id), "snapshots", `${p.version}.json`), { time: now(), form: p.form, version: p.version });
      p.form = { ...input.form, organization: input.form.organization ?? p.form.organization ?? "" };
    }
    if (input.title) p.title = input.title;
    if (input.completed !== undefined) p.completed = input.completed;
    event(p, "save", input.completed ? "人工标记审稿完成" : input.form?.organization !== undefined ? "保存审稿表单与 AI 整理草稿" : "保存人工审稿表单");
    await save(p); res.json(await publicPaper(p));
  })));
  router.post("/papers/:id/initial", wrap(async (req, res) => locked(req.params.id, async () => {
    const input = z.object({ text: z.string().trim().min(30).max(60000), attestation: z.literal(true) }).strict().parse(req.body);
    const p = await load(req.params.id);
    if (p.aiStarted || p.initialAssessment) throw new Error("原始人工评估只能在本系统首次 AI 运行前封存一次，不能事后替换。");
    p.initialAssessment = { text: input.text, time: now(), attestation: true };
    event(p, "initial", "封存原始人工评估"); await save(p); res.json(await publicPaper(p));
  })));
  router.post("/papers/:id/findings", wrap(async (req, res) => locked(req.params.id, async () => {
    const input = noteSchema.parse(req.body), p = await load(req.params.id);
    if (input.page > p.pages.length) throw new Error("PDF 页码超出范围");
    p.findings.unshift({ ...input, id: randomUUID(), source: "human", status: "open", time: now(), certainty: "conditional",
      anchored: locateQuote(p.pages, input.page, input.quote), impact: "", request: "", counterevidence: "" });
    event(p, "annotation", `新增人工批注：${input.title}`); await save(p); res.json(await publicPaper(p));
  })));
  router.patch("/papers/:id/findings/:findingId", wrap(async (req, res) => locked(req.params.id, async () => {
    const input = z.object({ status: z.enum(["open", "accepted", "dismissed"]).optional(), body: z.string().trim().min(1).max(15000).optional(), reviewerNote: z.string().max(15000).optional() }).strict().parse(req.body);
    const p = await load(req.params.id), finding = p.findings.find(f => f.id === uuid.parse(req.params.findingId));
    if (!finding) return res.status(404).json({ error: "批注不存在" });
    const before = structuredClone(finding);
    Object.assign(finding, input, { reviewedAt: now() });
    event(p, "decision", `${finding.title}：${input.status || "人工补充"}`, { before, after: structuredClone(finding) }); await save(p); res.json(await publicPaper(p));
  })));
  router.post("/papers/:id/runs", wrap(async (req, res) => locked(req.params.id, async () => {
    const input = z.object({ mode: z.enum(["explore", "official"]), language: z.enum(["zh", "en"]),
      instructions: z.string().max(10000).default(""), skillIds: z.array(z.enum(["claims", "experiments", "logic", "synthesis"])).min(1), consent: z.literal(true),
    }).strict().parse(req.body);
    const p = await load(req.params.id);
    if (input.mode === "official" && !p.initialAssessment) throw new Error("正式辅助审稿须先封存你自己撰写的原始评估；AI 不能代写该内容。");
    const current = await jobs.get(p.id);
    if (["queued", "running", "cancelling"].includes(current?.status)) return res.status(409).json({ error: "已有审稿任务正在运行" });
    const config = { ...getConfig() };
    if (config.provider !== "codex" && !config.apiKey) throw new Error("请先在模型设置中配置 API Key");
    const prompt = await buildReviewRequest(p, input);
    const run = { id: randomUUID(), time: now(), status: "queued", model: config.model, provider: config.provider,
      apiOrigin: config.provider === "codex" ? "Codex cloud" : new URL(config.baseURL || "https://api.openai.com/v1").origin,
      request: input, prompt, manuscriptHash: p.hash, originalAssessment: p.initialAssessment, result: null };
    p.runs.unshift(run); p.aiStarted = true; event(p, "ai", `AI 审稿：${config.model}`); await save(p);
    const job = jobs.enqueue(p.id, async ({ signal, progress }) => {
      try {
        progress({ phase: "reading", message: `检查 ${p.pages.length} 页正文与附录` });
        const result = await generate(config, prompt, { signal, onProgress: progress });
        signal.throwIfAborted();
        if (result.findings.some(f => f.page > p.pages.length)) throw new Error("模型给出了超出 PDF 范围的页码，本轮输出未纳入审稿意见");
        await locked(p.id, async () => {
          const latest = await load(p.id);
          Object.assign(latest.runs.find(r => r.id === run.id), { status: "completed", completed: now(), result });
          latest.findings.push(...validateFindings(result.findings, latest.pages, run.id));
          event(latest, "ai-result", `完成审稿：${result.findings.length} 条待人工核对的问题`); await save(latest);
        });
        return { message: "AI 审稿完成，原始人工表单未被覆盖" };
      } catch (error) {
        await locked(p.id, async () => {
          const latest = await load(p.id), stored = latest.runs.find(r => r.id === run.id);
          Object.assign(stored, { status: signal.aborted ? "cancelled" : "failed", error: error.message, completed: now() });
          event(latest, "ai-error", "AI 审稿未完成，已保留请求与原始记录"); await save(latest);
        });
        throw error;
      }
    }, { title: "ICLR PDF 审稿" });
    res.status(202).json({ job });
  })));
  router.post("/papers/:id/cancel", wrap(async (req, res) => {
    await locked(req.params.id, async () => {
      const p = await load(req.params.id), job = jobs.cancel(req.params.id);
      if (job?.status === "cancelled") {
        for (const run of p.runs.filter(r => r.status === "queued")) Object.assign(run, { status: "cancelled", completed: now() });
        await save(p);
      }
      res.json({ job });
    });
  }));
  router.get("/papers/:id/export", wrap(async (req, res) => {
    const p = await load(req.params.id);
    const translations = await translationLog(p.id);
    const readings = await readingRecords(folder, p.id);
    if (req.query.format === "md") {
      res.attachment("iclr-review.md").type("text/markdown").send(reviewMarkdown({ ...p, translations, readings })); return;
    }
    const snapshots = [];
    const names = await readdir(path.join(folder(p.id), "snapshots")).catch(e => { if (e.code === "ENOENT") return []; throw e; });
    for (const name of names) snapshots.push(JSON.parse(await readFile(path.join(folder(p.id), "snapshots", name), "utf8")));
    res.attachment("iclr-review-record.json").json({ ...p, snapshots, translations, readings, exportedAt: now() });
  }));
  router.get("/papers/:id/snapshots/:version", wrap(async (req, res) => {
    await load(req.params.id);
    const v = z.coerce.number().int().positive().parse(req.params.version);
    res.json(JSON.parse(await readFile(path.join(folder(req.params.id), "snapshots", `${v}.json`), "utf8")));
  }));
  return router;
}
