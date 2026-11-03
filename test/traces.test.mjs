import {test} from "node:test";
import assert from "node:assert/strict";
import {mkdtemp, mkdir, writeFile, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {
  buildTrace,
  compactPatch,
  deriveTurns,
  parseRemoteLog,
  readPiUsage,
  summarizeTrace,
} from "../server/traces.mjs";

const project = () => ({
  id: "11111111-1111-4111-8111-111111111111",
  name: "示例论文",
  revision: "rev-2",
  comments: [{
    id: "comment-1", body: "把这句话改短一些。", quote: "A long sentence.", file: "main.tex",
    page: 2, severity: "minor", author: "you", actor: {id: "m1", name: "梁明健"}, status: "resolved",
  }],
  proposals: [{
    id: "proposal-1", revision: "rev-1", time: "2026-11-02T10:00:00.000Z", status: "applied",
    effectiveCommentIds: ["comment-1"], summary: "压缩了一句话。", coverage: "只检查 main.tex。",
    reportId: "report-1", provider: "openai", vendor: "DeepSeek via Pi", model: "deepseek-flash",
    modelName: "Pi / deepseek-flash", resultRevision: "rev-2", gitCommit: "abc1234",
    patches: [{
      file: "main.tex", reason: "只压缩目标句。", commentIds: ["comment-1"],
      before: ["\\documentclass{article}", "\\usepackage{amsmath}", "\\usepackage{graphicx}", "\\usepackage{booktabs}", "\\begin{document}", "A very long sentence.", "\\end{document}"].join("\n"),
      after: ["\\documentclass{article}", "\\usepackage{amsmath}", "\\usepackage{graphicx}", "\\usepackage{booktabs}", "\\begin{document}", "A short sentence.", "\\end{document}"].join("\n"),
    }],
  }],
  history: [
    {id: "rev-2", time: "2026-11-02T10:00:10.000Z", label: "接受 AI 修改（编译通过）", gitCommit: "abc1234",
      parent: "rev-1", provenance: {kind: "ai", proposalId: "proposal-1", model: "deepseek-flash"},
      initiatedBy: {id: "m1", name: "梁明健"}},
    {id: "rev-1", time: "2026-11-02T09:00:00.000Z", label: "导入项目", gitCommit: null, parent: null, provenance: {kind: "manual"}},
  ],
  reports: [{id: "report-1", coverage: "只检查 main.tex。"}],
  overleaf: {
    directory: "/data/project/overleaf-1.git",
    syncHistory: [{revision: "rev-2", remoteCommit: "def5678", time: "2026-11-02T10:00:20.000Z", model: "deepseek-flash", provider: "openai"}],
  },
});

const job = () => ({
  id: "job-1", title: "AI 修订", status: "completed",
  created: "2026-11-02T09:59:50.000Z", started: "2026-11-02T09:59:51.000Z", updated: "2026-11-02T10:00:12.000Z",
  model: "deepseek-flash", provider: "DeepSeek via Pi",
  request: {mode: "revise", instructions: "处理这批批注。", commentIds: ["comment-1"]},
  result: {outcome: "applied", proposal: "proposal-1", revision: "rev-2", message: "已保存"},
  events: [
    {phase: "queued", message: "已排队", time: "2026-11-02T09:59:50.000Z"},
    {phase: "reading", message: "读取正文", time: "2026-11-02T09:59:51.500Z"},
    {phase: "model", message: "模型请求", time: "2026-11-02T09:59:52.000Z", piSessionDirectory: "/data/pi-sessions/s1"},
    {phase: "validating", message: "校验补丁", time: "2026-11-02T10:00:05.000Z"},
    {phase: "saved", message: "已保存", time: "2026-11-02T10:00:11.000Z", revision: "rev-2"},
  ],
});

const remoteLog = [
  "abcdef1234567890\u001f梁明健\u001f2026-11-01T08:00:00Z\u001f2026-11-02T09:00:00Z\u001fUpdate on Overleaf.",
  "",
  " 3 files changed, 12 insertions(+), 4 deletions(-)",
  "",
].join("\n");

test("deriveTurns merges job, proposal and revision into one completed turn", () => {
  const turns = deriveTurns(project(), [job()]);
  assert.equal(turns.length, 1);
  assert.equal(turns[0].status, "completed");
  assert.equal(turns[0].durationMs, 21000);
  assert.equal(turns[0].comments.length, 1);
  assert.equal(turns[0].comments[0].author, "梁明健");
  assert.equal(turns[0].patches.length, 1);
  assert.equal(turns[0].revision, "rev-2");
  assert.equal(turns[0].baseRevision, "rev-1");
  assert.equal(turns[0].gitCommit, "abc1234");
  assert.equal(turns[0].model.id, "deepseek-flash");
});

test("buildTrace produces ordered events, compact patches and no internal or path fields", async () => {
  const dataRoot = await mkdtemp(path.join(os.tmpdir(), "trace-test-"));
  try {
    const value = project();
    value.overleaf.directory = path.join(dataRoot, "overleaf-1.git");
    const trace = await buildTrace(value, [job()], {
      dataRoot,
      sessionRoot: path.join(dataRoot, "pi-sessions"),
      gitFn: async () => Buffer.from(remoteLog),
    });
    assert.equal(trace.turns.length, 1);
    assert.equal(trace.remote.length, 1);
    assert.equal(trace.remote[0].data.author, "梁明健");
    assert.equal(trace.remote[0].data.files, 3);
    assert.equal(trace.remote[0].data.insertions, 12);
    const types = trace.events.map(event => event.type);
    for (const type of ["turn/start", "comment/attach", "tool/result", "assistant/message", "patch/proposed", "revision/created", "overleaf/push", "turn/end"]) {
      assert.ok(types.includes(type), `missing ${type}`);
    }
    assert.deepEqual(trace.events.map(event => event.seq), trace.events.map((_, index) => index + 1));
    assert.equal(trace.lastSeq, trace.events.length);
    const turn = trace.turns[0];
    assert.ok(turn.patches[0].before.includes("A very long sentence."));
    assert.ok(!turn.patches[0].before.includes("\\documentclass"), "common prefix should be trimmed");
    assert.equal(turn.patches[0].trimmed, true);
    const serialized = JSON.stringify(trace);
    assert.ok(!serialized.includes("overleaf-1.git"), "local mirror path must not leak");
    assert.ok(!serialized.includes("pi-sessions"), "session path must not leak");
    assert.ok(!serialized.includes("\"_job\""), "internal job object must not leak");
  } finally {
    await rm(dataRoot, {recursive: true, force: true});
  }
});

test("awaiting approval turn has no revision and keeps the pending patch", async () => {
  const pending = project();
  pending.proposals[0].status = "pending";
  delete pending.proposals[0].resultRevision;
  delete pending.proposals[0].gitCommit;
  pending.history = [];
  const pendingJob = job();
  pendingJob.status = "awaiting_approval";
  pendingJob.result = {outcome: "proposed", proposal: "proposal-1"};
  pendingJob.events = pendingJob.events.filter(event => !["saved"].includes(event.phase));
  const trace = await buildTrace(pending, [pendingJob], {
    dataRoot: os.tmpdir(), sessionRoot: null, includeRemote: false,
  });
  assert.equal(trace.turns[0].status, "awaiting_approval");
  assert.equal(trace.turns[0].revision, null);
  assert.equal(trace.turns[0].patches.length, 1);
  assert.ok(!trace.events.some(event => event.type === "revision/created"));
});

test("parseRemoteLog reads format lines, shortstat and reverses to ascending order", () => {
  const commits = parseRemoteLog(remoteLog);
  assert.equal(commits.length, 1);
  assert.equal(commits[0].short, "abcdef1");
  assert.equal(commits[0].files, 3);
  assert.equal(commits[0].deletions, 4);
});

test("readPiUsage only reads inside the configured session root", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "trace-pi-"));
  try {
    const directory = path.join(root, "s1");
    await mkdir(directory);
    const message = {
      type: "message",
      message: {role: "assistant", model: "deepseek-flash", provider: "deepseek",
        usage: {input: 100, output: 20, totalTokens: 120, cost: {total: 0.001}}},
    };
    await writeFile(path.join(directory, "session.jsonl"), `${JSON.stringify({type: "session"})}\n${JSON.stringify(message)}\n`);
    const usage = await readPiUsage(directory, root);
    assert.deepEqual(usage, {input: 100, output: 20, total: 120, cost: 0.001, model: "deepseek-flash", provider: "deepseek"});
    assert.equal(await readPiUsage(directory, path.join(root, "elsewhere")), null);
  } finally {
    await rm(root, {recursive: true, force: true});
  }
});

test("summarizeTrace reports counts without exposing events", async () => {
  const trace = await buildTrace(project(), [job()], {
    dataRoot: os.tmpdir(), sessionRoot: null, includeRemote: false,
  });
  const summary = summarizeTrace(trace);
  assert.equal(summary.turnCount, 1);
  assert.equal(summary.remoteCount, 0);
  assert.ok(summary.eventCount > 0);
  assert.equal(summary.title, "示例论文");
});

test("compactPatch keeps context and marks long excerpts as trimmed", () => {
  const long = Array.from({length: 400}, (_, index) => `line ${index}`);
  const patch = compactPatch({file: "a.tex", before: long.join("\n"), after: [...long, "line 400"].join("\n"), reason: "r"});
  assert.ok(patch.before.split("\n").length <= 160);
  assert.equal(patch.trimmed, true);
});

test("collaboration stages become separate model rows with summaries", async () => {
  const value = project();
  value.proposals[0].collaboration = {
    workflow: "www-crosscheck-local-v1",
    stages: [
      {role: "draft", vendor: "DeepSeek 官方", model: "deepseek-flash", provider: "openai",
        summary: "起草阶段：只改目标句。", coverage: "覆盖 main.tex。", patches: [{file: "main.tex"}], findings: []},
      {role: "crosscheck", vendor: "本机 Codex", model: "gpt-6.1-sol", provider: "codex",
        summary: "复核阶段：保留一处，删除一处。", coverage: "复核全文一致性。", patches: [{file: "main.tex"}], findings: [{title: "x"}]},
    ],
  };
  const jobValue = job();
  jobValue.events.splice(3, 0,
    {phase: "model", message: "联合修订 1/2 · DeepSeek 官方 deepseek-flash · draft", time: "2026-11-02T09:59:52.000Z"},
    {phase: "model", message: "联合修订 2/2 · 本机 Codex gpt-6.1-sol · crosscheck", time: "2026-11-02T10:00:02.000Z"});
  const trace = await buildTrace(value, [jobValue], {dataRoot: os.tmpdir(), sessionRoot: null, includeRemote: false});
  const turn = trace.turns[0];
  assert.equal(turn.collaboration.stages.length, 2);
  assert.equal(turn.collaboration.stages[1].role, "crosscheck");
  const rows = trace.events.filter(event => event.kind === "model" && event.data?.stage);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].data.stage.role, "draft");
  assert.match(rows[0].data.stage.summary, /起草/);
  assert.ok(rows[0].data.durationMs >= 9000);
  assert.equal(rows[1].data.stage.patchCount, 1);
  assert.equal(rows[1].data.stage.findingCount, 1);
});
