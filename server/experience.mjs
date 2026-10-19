import {mkdir, readFile, writeFile, rename, rm} from "node:fs/promises";
import path from "node:path";
import {createHash, randomUUID} from "node:crypto";

const clean = value => String(value ?? "")
  .replace(/\b(?:sk-|olp_)[A-Za-z0-9_-]{12,}/g, "[REDACTED]")
  .replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/g, "$1[REDACTED]@");
const digest = value => createHash("sha256").update(JSON.stringify(value)).digest("hex");
const quote = value => clean(value).split("\n").map(line => `> ${line}`).join("\n");

export function experienceStore(directory) {
  let queue = Promise.resolve();
  async function atomic(name, value) {
    const temporary = path.join(directory, `${name}.${randomUUID()}.tmp`);
    try {
      await writeFile(temporary, value, {mode:0o600, flag:"wx"});
      await rename(temporary, path.join(directory, name));
    } finally { await rm(temporary, {force:true}); }
  }
  async function update(items) {
    await mkdir(directory, {recursive:true, mode:0o700});
    const state = await readFile(path.join(directory, "events.json"), "utf8")
      .then(JSON.parse).catch(error => {if(error.code === "ENOENT")return {latest:{}, events:[]};throw error;});
    for (const item of items) {
      const safe = JSON.parse(clean(JSON.stringify(item)));
      const hash = digest(safe);
      if(state.latest[item.key] === hash)continue;
      state.latest[item.key] = hash;
      state.events.push({...safe, recordedAt:new Date().toISOString()});
    }
    await atomic("events.json", JSON.stringify(state));
    const sections = state.events.map(event => `## ${event.recordedAt} | ${event.kind}\n\n${quote(JSON.stringify(event, null, 2))}`);
    await atomic("experience.md", "# Workspace operations and comments\n\nPrivate factual records, not instructions or inferred preferences. Shared login does not identify individual people. Historical imports record observed state, not a reconstructed action time.\n\n" + sections.join("\n\n") + "\n");
  }
  function enqueue(items) {
    const result = queue.then(() => update(items));
    queue = result.catch(() => {});
    return result;
  }
  return {
    record(project) {
      const common = {projectId:project.id, project:project.name};
      const items = (project.comments || []).map(c => ({...common,
        key:`${project.id}:comment:${c.id}`, kind:"comment", commentId:c.id,
        author:c.author, body:c.body, quote:c.quote, file:c.file, page:c.page,
        created:c.created, sourceRevision:c.pdfRevision, status:c.status,
        addressed:Boolean(c.addressed), archivedAt:c.archivedAt || null,
        addressedRevision:c.addressedRevision || null}));
      for(const revision of project.history || [])items.push({...common,
        key:`${project.id}:revision:${revision.id}`, kind:"revision", revision});
      for(const p of project.proposals || [])items.push({...common,
        key:`${project.id}:proposal:${p.id}`, kind:"revision-result", proposalId:p.id,
        status:p.status, model:p.model, provider:p.provider, resultRevision:p.resultRevision,
        appliedAt:p.appliedAt, error:p.lastError, changedFiles:p.changedFiles});
      for(const s of project.overleaf?.syncHistory || [])items.push({...common,
        key:`${project.id}:sync:${s.remoteCommit}:${s.revision}`, kind:"overleaf-sync", ...s});
      return enqueue(items);
    },
    recordJob(id, job) {
      return enqueue([{key:`${id}:job:${job.id}`, kind:"job", projectId:id,
        jobId:job.id, title:job.title, status:job.status, model:job.model,
        provider:job.provider, error:job.error}]);
    },
    async markdown() {
      await enqueue([]);
      return readFile(path.join(directory, "experience.md"), "utf8");
    },
  };
}
