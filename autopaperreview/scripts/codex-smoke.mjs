// Manual live check against the bundled public demo; consumes Codex usage.
import assert from "node:assert/strict";
const base = "http://localhost:4317/api";
async function api(url, body) {
  const response = await fetch(base + url, {
    method: body ? "POST" : "GET",
    headers:
      body instanceof FormData ? {} : { "Content-Type": "application/json" },
    body:
      body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  assert.ok(response.ok, data.error || `HTTP ${response.status}`);
  return data;
}
const health = await api("/health");
assert.equal(health.provider, "codex");
assert.equal(health.model, "gpt-6.1-sol");
assert.equal(health.ai, true);
const form = new FormData();
form.append("demo", "true");
form.append("trusted", "true");
let project = await api("/projects/import", form);
const url = `/projects/${project.id}`;
const before = "Each stage leaves an explicit record.";
const after = "Each stage retains an explicit record for the author.";
await api(`${url}/comments`, {
  body: `仅将这句话改为：${after}。保留其他内容。`,
  quote: before,
  pdfRevision: null,
});
const secondBefore =
  "Scientific decisions and final acceptance of changes remain with the author.";
const secondAfter =
  "The author retains responsibility for scientific decisions and final approval of revisions.";
project = await api(`${url}/comments`, {
  body: `仅将结论中的这句话改为：${secondAfter}。保留其他内容。`,
  quote: secondBefore,
  pdfRevision: null,
});
const expectedIds = project.comments.map((c) => c.id);
project = await api(`${url}/ai`, {
  mode: "revise",
  skillIds: health.skills.map((s) => s.id),
  consent: true,
  instructions: `这是公开示例的连接测试。只处理两条已有批注：在 main.tex 中精确把 ${before} 替换为 ${after}，再把 ${secondBefore} 替换为 ${secondAfter}。不要增加审稿问题或其他修改。commentIds 必须逐字复制对应现有批注的 id，不得使用 F1 或 C1 等审稿标签。`,
});
const proposal = project.proposals.find((p) => p.status === "pending");
assert.ok(proposal, "real Codex must return a proposal");
assert.equal(project.reports[0].provider, "codex");
assert.equal(project.reports[0].model, "gpt-6.1-sol");
const linkedIds = new Set(
  proposal.patches.flatMap((patch) => patch.commentIds),
);
assert.ok(
  expectedIds.every((id) => linkedIds.has(id)),
  "both real comment UUIDs must remain linked",
);
assert.ok(proposal.patches.every((patch) => !patch.unlinkedCommentIds?.length));
project = await api(`${url}/proposals/${proposal.id}/apply`, {});
assert.equal(project.pdfRevision, project.revision);
const source = await api(`${url}/source?file=main.tex`);
assert.ok(source.content.includes(after));
assert.ok(source.content.includes(secondAfter));
assert.equal(project.comments[0].status, "open");
assert.ok(project.comments.every((c) => c.addressed && c.status === "open"));
console.log(
  JSON.stringify(
    {
      success: true,
      project: project.id,
      provider: health.provider,
      model: health.model,
      compiled: true,
      patches: proposal.patches.length,
      commentsLinked: linkedIds.size,
      skills: health.skills.length,
      summary: proposal.summary,
    },
    null,
    2,
  ),
);
