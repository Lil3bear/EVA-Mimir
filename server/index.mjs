import express from "express";
import multer from "multer";
import AdmZip from "adm-zip";
import path from "node:path";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import { createServer as createHTTPServer } from "node:http";
import { readFile, readdir, mkdir, writeFile, rm, stat } from "node:fs/promises";
import { gzip } from "node:zlib";
import { promisify } from "node:util";
import { z } from "zod";
import {
  atomicJSON,
  importZip,
  detectMain,
  compileFiles,
  applyPatches,
  linkPatchComments,
  safePath,
  textExt,
  run,
} from "./core.mjs";
import { skills, effectiveSkillIds, skillManifest } from "./skills.mjs";
import { generate, revisionComments } from "./ai.mjs";
import { translate } from "./translate.mjs";
import { bibliography, verifyEntry } from "./bibliography.mjs";
import { codexStatus } from "./codex.mjs";
import { Jobs } from "./jobs.mjs";
import { experienceStore } from "./experience.mjs";
import { connectOverleaf, pushOverleaf, overleafURL } from "./overleaf.mjs";
import { overleafCredentials } from "./overleaf-credentials.mjs";
import {recordSourceCommit,sourceCommitDiff} from "./source-history.mjs";
import {commentSnapshot,archiveAppliedComments} from "./comment-log.mjs";
import { installAccess } from "./access.mjs";
import { createReviewerRouter } from "./reviewer.mjs";
import { installPeerReviewRoutes } from "./peer-review.mjs";
import { installFigureRoutes } from "./figure-routes.mjs";
import {revisionProvider,publicRevisionProvider,collaborativeRevision} from "./revision-provider.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dataRoot = process.env.DATA_DIR || path.join(root, "data");
const port = Number(process.env.PORT || 4317);
await mkdir(dataRoot, { recursive: true });
const app = express();
const httpServer = createHTTPServer(app);
app.disable("x-powered-by");
app.use(express.json({ limit: "4mb" }));
installAccess(app, {port, shared:process.env.SHARED_MODE === "1", origin:process.env.PUBLIC_ORIGIN,
  passwordHash:process.env.TEAM_PASSWORD_HASH, secret:process.env.SESSION_SECRET, username:process.env.TEAM_USERNAME});
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 30 * 1024 * 1024, files: 1 },
});
const config = {
  provider: process.env.AI_PROVIDER || "codex",
  apiKey: process.env.OPENAI_API_KEY || "",
  baseURL: process.env.OPENAI_BASE_URL || "https://api.openai.com/v1",
  apiFormat: process.env.AI_API_FORMAT || "responses",
  revisionTransport: process.env.REVISION_TRANSPORT || "api",
  localRevisionOnly: process.env.LOCAL_REVISION_ONLY === "1",
  model:
    process.env.OPENAI_MODEL ||
    (process.env.AI_PROVIDER === "openai" ? "gpt-4.1" : "gpt-6.1-sol"),
};
const savedSettings = await readFile(
  path.join(dataRoot, "settings.json"),
  "utf8",
)
  .then(JSON.parse)
  .catch(() => null);
if (savedSettings) {
  const saved = z
    .object({
      provider: z.enum(["codex", "openai"]),
      model: z.string().min(1).max(100),
    })
    .safeParse(savedSettings);
  if (saved.success && process.env.SETTINGS_LOCKED !== "1") Object.assign(config, saved.data);
}
const localClaudeAuth=process.env.REVISION_COWRITER_AUTH==="local";
if(localClaudeAuth && (process.env.SHARED_MODE==="1" || ![undefined,"127.0.0.1","::1","localhost"].includes(process.env.BIND_HOST)))
  throw Error("本机 Claude 登录模式只允许本机回环服务，不会开放给公网调用");
const revisionConfig=collaborativeRevision(await revisionProvider(config,process.env.REVISION_REVIEWER),config,process.env.REVISION_COWRITER_MODEL,{localAuth:localClaudeAuth,localOrigin:process.env.CLAUDE_LOCAL_CONFIGURED_ORIGIN,crosscheckModel:process.env.REVISION_CROSSCHECK_MODEL,teamMode:process.env.REVISION_TEAM_MODE});
const taskConfig=mode=>({... (mode === "revise" ? revisionConfig : config),manuscriptContext:true,archiveComments:mode==="revise"&&process.env.ARCHIVE_APPLIED_COMMENTS==="1"});
async function aiStatus() {
  if (config.provider === "codex") {
    const cli = await codexStatus();
    return {
      ai: cli.authenticated,
      hasApiKey: Boolean(config.apiKey),
      provider: "codex",
      model: config.model,
      revision:publicRevisionProvider(revisionConfig),
      localRevisionOnly: config.localRevisionOnly,
      cli,
    };
  }
  return {
    ai: Boolean(config.apiKey),
    hasApiKey: Boolean(config.apiKey),
    provider: "openai",
    apiOrigin: new URL(config.baseURL).origin,
    model: config.model,
    revision:publicRevisionProvider(revisionConfig),
    localRevisionOnly: config.localRevisionOnly,
  };
}
const locks = new Set();
const pid = (id) => path.join(dataRoot, z.string().uuid().parse(id));
const projectFile = (id) => path.join(pid(id), "project.json");
const getProject = async (id) =>
  JSON.parse(await readFile(projectFile(id), "utf8"));
const getRevision = async (id, rev) =>
  JSON.parse(
    await readFile(
      path.join(pid(id), "revisions", `${z.string().uuid().parse(rev)}.json`),
      "utf8",
    ),
  );
const experience = experienceStore(path.join(dataRoot, "experience"));
const recordExperience = (p) => experience.record(p).catch(() => console.error("Experience log update failed; project data retained for rebuild"));
const saveProject = async (p) => {
  await atomicJSON(projectFile(p.id), p);
  await recordExperience(p);
};
const syncTokens = overleafCredentials(process.env.OVERLEAF_CREDENTIAL_DIR || path.join(homedir(), ".config", "autopaperreview", "overleaf-credentials"));
const jobs = new Jobs({
  read: (id) =>
    readFile(path.join(pid(id), "activity.json"), "utf8")
      .then(JSON.parse)
      .catch(() => null),
  write: async(id, state) => {
    await atomicJSON(path.join(pid(id),"jobs",`${z.string().uuid().parse(state.id)}.json`),state);
    await atomicJSON(path.join(pid(id), "activity.json"), state);
    await experience.recordJob(id,state).catch(() => console.error("Experience job log update failed"));
  },
});
async function withProjectLock(id, operation, signal) {
  while (locks.has(id)) {
    signal?.throwIfAborted();
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  signal?.throwIfAborted();
  locks.add(id);
  try {
    return await operation();
  } finally {
    locks.delete(id);
  }
}
const wrap = (fn) => async (req, res, next) => {
  try {
    await fn(req, res);
  } catch (e) {
    next(e);
  }
};
const locked = (fn) =>
  wrap(async (req, res) => {
    const id = req.params.id;
    if (locks.has(id))
      return res.status(409).json({ error: "该项目正在处理，请稍后重试" });
    locks.add(id);
    try {
      await fn(req, res);
    } finally {
      locks.delete(id);
    }
  });
const queued = (fn) =>
  wrap((req, res) => withProjectLock(req.params.id, () => fn(req, res)));
async function ensureGitHistory(p) {
  if(p.sourceGit?.head && p.history.every(item=>item.gitCommit) && p.sourceGit.head===p.history[0]?.gitCommit)return;
  let parent,parentRevision=null;
  for(const item of [...p.history].reverse()) {
    const rev=await getRevision(p.id,item.id);
    if(rev.parent===undefined)rev.parent=parentRevision;
    const commit=await recordSourceCommit(pid(p.id),rev,parent);
    if(rev.gitCommit!==commit){rev.gitCommit=commit;await atomicJSON(path.join(pid(p.id),"revisions",`${rev.id}.json`),rev);}
    Object.assign(item,{gitCommit:commit,provenance:rev.provenance||null,parent:rev.parent||null,restoredFrom:rev.restoredFrom||null});
    parent=commit;
    parentRevision=rev.id;
  }
  p.sourceGit={enabled:true,head:parent||null};
}
async function snapshot(p, files, label, compiled, metadata={}) {
  await ensureGitHistory(p);
  const rev = {
    id: metadata.id||randomUUID(),
    time: new Date().toISOString(),
    label,
    files,
    main: p.main,
    engine: p.engine,
    parent:p.revision||null,
    provenance:metadata.provenance||{kind:"manual"},
    restoredFrom:metadata.restoredFrom||null,
  };
  rev.gitCommit=await recordSourceCommit(pid(p.id),rev,p.sourceGit.head);
  if(metadata.provenance?.proposalId){const proposal=p.proposals.find(x=>x.id===metadata.provenance.proposalId);if(proposal)proposal.gitCommit=rev.gitCommit;}
  await atomicJSON(path.join(pid(p.id), "revisions", `${rev.id}.json`), rev);
  if (compiled) {
    await writeFile(path.join(pid(p.id), `${rev.id}.pdf`), compiled.pdf);
    p.pdfRevision = rev.id;
    p.log = compiled.log;
  }
  p.revision = rev.id;
  p.history.unshift({ id: rev.id, time: rev.time, label,gitCommit:rev.gitCommit,parent:rev.parent,provenance:rev.provenance,restoredFrom:rev.restoredFrom });
  p.sourceGit.head=rev.gitCommit;
  p.updated = rev.time;
  await saveProject(p);
  return rev;
}
async function compile(p, files, options) {
  const temp = path.join(pid(p.id), "build", randomUUID());
  try {
    return await compileFiles(files, p.main, p.engine, temp, options);
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
}
async function saveAIResult(p, rev, input, runConfig, result) {
  const appliedSkills = input.skillManifest || await skillManifest(input.skillIds);
  let patches = linkPatchComments(result.patches.filter(p=>p.before!==p.after), p.comments);
  if (patches.length){const next=applyPatches(rev.files, patches);if(Object.keys(next).every(file=>next[file]===rev.files[file]))patches=[];}
  const report = {
    id: randomUUID(),
    revision: rev.id,
    time: new Date().toISOString(),
    skills: appliedSkills.ids,
    skillManifest: appliedSkills,
    mode: input.mode,
    provider: runConfig.provider,
    model: runConfig.model,
    vendor:runConfig.vendor||null,
    modelName:runConfig.modelName||runConfig.model,
    collaboration:result.collaboration||null,
    transport:runConfig.provider === "codex" ? "codex-cli" : input.mode === "revise" && runConfig.revisionTransport === "claude-cli" ? "claude-cli" : runConfig.apiFormat,
    summary: result.summary,
    coverage: result.coverage,
    outcome:input.mode==="review"?"reviewed":patches.length?"proposed":"no_changes",
    instructions:input.instructions||"",
    candidateProposalId:input.candidateProposalId||null,
    commentScope:input.commentScope||"human",
    commentIds:input.sourceCommentIds||p.comments.filter(c=>input.mode!=="revise" || !runConfig.localRevisionOnly || (c.author==="you" && c.status==="open" && !c.addressed && c.quote?.trim())).map(c=>c.id),
  };
  for (const f of result.findings)
    if (f.file && !rev.files[f.file])
      throw new Error(`模型引用了不存在的文件: ${f.file}`);
  p.reports.unshift(report);
  for (const f of result.findings) {
    if (!p.comments.some((c) => c.body === f.body && c.quote === f.quote))
      p.comments.push({
        ...f,
        id: randomUUID(),
        author: "ai",
        status: "open",
        created: report.time,
        page: null,
        x: null,
        y: null,
        pdfRevision: null,
        sourceRevision: rev.id,
      });
  }
  let proposal;
  if (patches.length) {
    proposal = {
      id: randomUUID(),
      revision: rev.id,
      time: report.time,
      status: "pending",
      patches,
      effectiveCommentIds:result.effectiveCommentIds||[],
      archiveComments:Boolean(runConfig.archiveComments),
      sourceComments:input.sourceComments||p.comments.filter(c=>patches.some(patch=>patch.commentIds.includes(c.id))).map(commentSnapshot),
      summary: result.summary,
      reportId:report.id,
      candidateProposalId:report.candidateProposalId,
      provider:runConfig.provider,
      model:runConfig.model,
      vendor:report.vendor,
      modelName:report.modelName,
      collaboration:report.collaboration,
      transport:report.transport,
      skills:appliedSkills.ids,
      skillManifest:appliedSkills,
    };
    report.proposalId=proposal.id;
    p.proposals.unshift(proposal);
  }
  await saveProject(p);
  return proposal;
}
async function applyProposal(p, proposal, options = {}) {
  if((revisionConfig.finalReviewer||revisionConfig.teamMode==="dual")&&proposal.collaboration?.workflow!==revisionConfig.workflow)
    throw Error("此提案没有经过当前写作团队复核，未应用；请重新提交批注交叉复核");
  if (p.revision !== proposal.revision)
    throw new Error("建议基于旧版本，未覆盖新修改，请重新生成");
  if(proposal.sourceComments?.some(saved=>{
    const current=p.comments.find(c=>c.id===saved.id);
    return !current||JSON.stringify(commentSnapshot(current))!==JSON.stringify(saved);
  }))throw Error("批注在生成建议后已改变，未应用旧意见，也未归档批注；请重新提交");
  const rev = await getRevision(p.id, p.revision);
  const files = applyPatches(rev.files, proposal.patches);
  const effective=proposal.patches.filter(p=>p.before!==p.after);
  if(!effective.length || Object.keys(files).every(file=>files[file]===rev.files[file])){
    const message="本轮源码没有实际变化，未标记已应用，也未创建新版本";
    proposal.lastError=message;(proposal.applyAttempts||=[]).push({time:new Date().toISOString(),status:"no_changes"});await saveProject(p);throw Error(message);
  }
  options.onProgress?.({
    phase: "compiling",
    message: "修改已定位，先在临时目录编译，不覆盖当前 PDF",
    files: [...new Set(proposal.patches.map((p) => p.file))],
  });
  let result;
  try {result=await compile(p,files,options);}
  catch(error){proposal.lastError=error.message;proposal.lastAttemptAt=new Date().toISOString();(proposal.applyAttempts||=[]).push({time:proposal.lastAttemptAt,status:"failed",error:error.message});await saveProject(p);throw error;}
  options.signal?.throwIfAborted();
  const staged=structuredClone(p),applied=staged.proposals.find(x=>x.id===proposal.id);
  const historical=p.reports.find(r=>r.id===proposal.reportId || r.time===proposal.time);
  const nextId=randomUUID(),appliedAt=new Date().toISOString();
  Object.assign(applied,{status:"applied",resultRevision:nextId,appliedAt,provider:proposal.provider||historical?.provider||null,model:proposal.model||historical?.model||null,lastError:null,changedFiles:[...new Set(effective.map(p=>p.file))]});
  (applied.applyAttempts||=[]).push({time:appliedAt,status:"applied",revision:nextId});
  const report=staged.reports.find(r=>r.id===applied.reportId);if(report)Object.assign(report,{outcome:"applied",resultRevision:nextId,appliedAt});
  applied.keepOpenCommentIds=options.keepOpenCommentIds||[];
  const keepOpen=new Set(applied.keepOpenCommentIds);
  const addressed=new Set((applied.effectiveCommentIds??effective.flatMap(patch=>patch.commentIds)).filter(id=>!keepOpen.has(id)));
  for(const c of staged.comments)if(keepOpen.has(c.id))Object.assign(c,{addressed:false,partialRevision:nextId,partialProposalId:proposal.id});
  for (const c of staged.comments)
    if (addressed.has(c.id))Object.assign(c,{addressed:true,addressedBy:proposal.id,addressedRevision:nextId});
  archiveAppliedComments(staged,applied,nextId,appliedAt);
  try{await snapshot(
    staged,
    files,
    options.automatic
      ? "自动按批注修订（编译通过）"
      : "接受 AI 修改（编译通过）",
    result,
    {id:nextId,provenance:{kind:"ai",proposalId:applied.id,reportId:applied.reportId||null,provider:applied.provider,vendor:applied.vendor||null,model:applied.model,transport:applied.transport||null,collaboration:applied.collaboration ? {workflow:applied.collaboration.workflow,stages:applied.collaboration.stages.map(({role,provider,vendor,model,transport})=>({role,provider,vendor,model,transport}))} : null,skills:applied.skills||[],skillManifest:applied.skillManifest||null,commentIds:[...new Set(effective.flatMap(p=>p.commentIds))],keepOpenCommentIds:applied.keepOpenCommentIds}},
  );}catch(error){proposal.lastError=error.message;(proposal.applyAttempts||=[]).push({time:new Date().toISOString(),status:"failed",error:error.message});await saveProject(p);throw error;}
  Object.assign(p,staged);
}
async function syncProject(p, options = {}) {
  if (!p.overleaf) throw new Error("尚未连接 Overleaf Git");
  if (p.pdfRevision !== p.revision)
    throw new Error("请先成功编译当前版本，再同步至 Overleaf");
  const base = await getRevision(p.id, p.overleaf.baseRevision);
  const rev = await getRevision(p.id, p.revision);
  try {
    const result = await pushOverleaf(
      p.overleaf,
      base.files,
      rev.files,
      await syncTokens.get(p.id, p.overleaf.url),
      {...options,revisionMetadata:{revision:rev.id,sourceCommit:rev.gitCommit||null,provider:rev.provenance?.provider||null,model:rev.provenance?.model||null}},
    );
    Object.assign(p.overleaf, {
      baseRevision: rev.id,
      head: result.head,
      lastSynced: new Date().toISOString(),
      lastError: "",
    });
    p.overleaf.syncHistory ||= [];
    p.overleaf.syncHistory.push({revision:rev.id,sourceCommit:rev.gitCommit||null,remoteCommit:result.head,time:p.overleaf.lastSynced,model:rev.provenance?.model||null,provider:rev.provenance?.provider||null});
    await saveProject(p);
    return result;
  } catch (error) {
    p.overleaf.lastError = error.message;
    await saveProject(p);
    throw error;
  }
}
async function runAIJob(id, request, automatic, { signal, progress }) {
  const runConfig = taskConfig(automatic ? "revise" : request.mode);
  const p = await getProject(id),
    rev = await getRevision(id, p.revision);
  if(request?.expectedRevision&&request.expectedRevision!==p.revision)
    throw Error("排队期间论文版本已变化，未调用模型或应用修改；请刷新并核对批注后重新提交。");
  if (automatic) {
    if (!p.automation?.enabled) return { outcome:"no_changes",message: "自动修订已关闭，未修改" };
    if (
      p.automation.provider !== runConfig.provider ||
      (p.automation.workflow||null) !== (runConfig.workflow||null) ||
      p.automation.model !== runConfig.model
    )
      throw new Error("模型配置已改变，请重新开启自动修订以确认授权");
    p.comments = p.comments.filter(
      (c) => c.author === "you" && c.status === "open" && !c.addressed && !c.archivedAt,
    );
    if (!p.comments.length) return { outcome:"no_changes",message: "暂无新的待处理用户批注，未修改" };
    request = {
      mode: "revise",
      instructions:
        "只处理本轮提供的用户批注。每处修改必须关联对应现有 comment.id；不得顺带全面重写。无法处理的科学问题作为待确认问题，不要编造。",
      skillIds: p.automation.skillIds,
      consent: true,
    };
  }
  const submitted=revisionComments(p,request,runConfig);
  if(request.candidateProposalId){
    const candidate=p.proposals.find(x=>x.id===request.candidateProposalId&&x.status==="pending"&&x.revision===rev.id);
    if(request.mode!=="revise"||!candidate)throw Error("待复核草稿不存在、已处理或基于旧版本；未发送模型请求");
    request={...request,collaborationCandidate:{proposalId:candidate.id,revision:candidate.revision,summary:candidate.summary,patches:candidate.patches.map(({file,after,reason,commentIds})=>({file,after,reason,commentIds}))}};
  }
  request={...request,skillIds:effectiveSkillIds(request.skillIds),skillManifest:await skillManifest(request.skillIds),sourceCommentIds:submitted.map(c=>c.id),sourceComments:submitted.map(commentSnapshot)};
  progress({
    phase: "reading",
    provider:runConfig.vendor||runConfig.provider,model:runConfig.model,revision:rev.id,
    request:{mode:request.mode,skillIds:request.skillIds,instructions:request.instructions,commentScope:request.commentScope||"human",commentIds:request.sourceCommentIds},
    message: `本轮读取 ${submitted.length} 条批注，版本 ${rev.id.slice(0, 8)}`,
  });
  const result = await generate(p, rev, request, runConfig, {
    signal,
    onProgress: progress,
  });
  signal.throwIfAborted();
  return withProjectLock(
    id,
    async () => {
      const current = await getProject(id);
      progress({
        phase: "validating",
        message: `收到 ${result.patches.length} 处修改，核对原文及批注编号`,
        files: [...new Set(result.patches.map((p) => p.file))],
      });
      const proposal = await saveAIResult(
        current,
        rev,
        request,
        runConfig,
        result,
      );
      if (!proposal)
        return {
          outcome:request.mode==="review"?"reviewed":"no_changes",
          message:
            request.mode === "review"
              ? "审稿完成，意见已保存到批注"
              : "本轮没有可自动应用的修改，请查看审稿记录",
        };
      if (
        (!automatic && !request.apply) ||
        current.revision !== rev.id ||
        proposal.patches.some(
          (p) => p.unlinkedCommentIds.length || !p.commentIds.length,
        )
      )
        return {
          outcome:"proposed",
          message: "修改建议已保存，请查看差异并人工确认",
          proposal: proposal.id,
        };
      if (automatic && !current.automation?.enabled)
        return { outcome:"proposed",message: "自动修订已关闭，建议已保留，等待人工确认" };
      await applyProposal(current, proposal, {
        signal,
        onProgress: progress,
        automatic,
      });
      progress({
        phase: "saved",
        message: proposal.archiveComments?"编译成功，新版本与差异已保存；对应批注已移入修订日志，待你复核":"编译成功，新版本与差异已保存；批注待你复核",
      });
      if (current.overleaf?.autoPush) {
        try {
          const sync = await syncProject(current, { signal, progress });
          return {
            outcome:"applied",
            message: sync.message,
            proposal: proposal.id,
            revision: current.revision,
          };
        } catch (error) {
          return {
            outcome:"applied",
            message: "本地修订已保存，Overleaf 同步未完成",
            warning: error.message,
            proposal: proposal.id,
            revision: current.revision,
          };
        }
      }
      return {
        outcome:"applied",
        message: "本地修订与 PDF 已更新，可以查看差异或恢复旧版",
        proposal: proposal.id,
        revision: current.revision,
      };
    },
    signal,
  );
}
function queueAutomatic(id) {
  return jobs.enqueue(id, (context) => runAIJob(id, null, true, context), {
    automatic: true,
    delay: 1800,
    title: "自动按批注修订",
    model:revisionConfig.model,provider:revisionConfig.vendor||revisionConfig.provider,
  });
}
const compressJSON = promisify(gzip);
const fileManifests = new Map();
async function sendProject(res, p) {
  const key = `${p.id}:${p.revision}`;
  let files = fileManifests.get(key);
  if (!files) {
    const rev = await getRevision(p.id, p.revision);
    files = Object.keys(rev.files).map(name => ({name, editable:textExt.test(name), size:Buffer.byteLength(rev.files[name], "base64")}));
    if (fileManifests.size >= 32) fileManifests.delete(fileManifests.keys().next().value);
    fileManifests.set(key, files);
  }
  const body = {
    ...p,
    overleafCredentialSaved: Boolean(p.overleaf && await syncTokens.get(p.id,p.overleaf.url).catch(()=>undefined)),
    files,
  };
  if (res.req.get("X-Workspace-View") === "reader") {
    body.detailsLoaded = false;
    body.proposalCount = p.proposals.length;
    body.reportCount = p.reports.length;
    body.proposals = [];
    body.reports = [];
    body.history = p.history.map(({id,time,label,gitCommit,parent,restoredFrom,provenance}) => ({
      id,time,label,gitCommit,parent,restoredFrom,
      provenance:provenance ? {kind:provenance.kind,model:provenance.model,provider:provenance.provider} : null,
    }));
  } else body.detailsLoaded = true;
  // Compress before the private network hop, not only at the public gateway.
  res.vary("Accept-Encoding");
  if (res.req.acceptsEncodings("gzip")) {
    const bytes = await compressJSON(Buffer.from(JSON.stringify(body)));
    res.type("json").set("Content-Encoding", "gzip").send(bytes);
  } else res.json(body);
}
app.get(
  "/api/health",
  wrap(async (req, res) => {
    const latex = await run("pdflatex", ["--version"])
      .then((r) => r.code === 0)
      .catch(() => false);
    res.json({
      shared: process.env.SHARED_MODE === "1",
      settingsLocked: process.env.SETTINGS_LOCKED === "1",
      defaultProjectId:process.env.DEFAULT_PROJECT_ID||null,
      fastTranslation: Boolean(process.env.TRANSLATION_MODEL && config.provider !== "codex" && config.apiKey),
      translationModel: process.env.TRANSLATION_MODEL || null,
      latex,
      ...(await aiStatus()),
      skills: skills.map(({ files, ...s }) => s),
    });
  }),
);
app.post(
  "/api/settings",
  wrap(async (req, res) => {
    if (process.env.SETTINGS_LOCKED === "1") return res.status(403).json({error:"共享服务的模型配置由管理员管理"});
    const input = z
      .object({
        apiKey: z.string().max(500).optional(),
        provider: z.enum(["codex", "openai"]).default("codex"),
        model: z.string().min(1).max(100),
      })
      .parse(req.body);
    if (input.apiKey) config.apiKey = input.apiKey;
    config.model = input.model;
    config.provider = input.provider;
    await atomicJSON(path.join(dataRoot, "settings.json"), {
      provider: config.provider,
      model: config.model,
    });
    res.json(await aiStatus());
  }),
);
app.get(
  "/api/projects",
  wrap(async (req, res) => {
    const projects = [];
    for (const dir of await readdir(dataRoot)) {
      if (!z.string().uuid().safeParse(dir).success) continue;
      const p = await getProject(dir).catch(() => null);
      if (p) projects.push({ id: p.id, name: p.name, updated: p.updated });
    }
    res.json(projects.sort((a, b) => b.updated.localeCompare(a.updated)));
  }),
);
const demo = String.raw`\documentclass[10pt,twocolumn]{article}
\usepackage[margin=0.8in]{geometry}
\usepackage{graphicx}
\title{Evidence Before Eloquence:\\A Human-in-the-Loop Workflow for Scientific Writing}
\author{Anonymous Authors}
\date{}
\begin{document}
\maketitle
\begin{abstract}
Scientific manuscripts require a clear relationship between claims and supporting evidence. We describe a human-in-the-loop workflow that connects document annotations, source-level revisions, and compilation checks. The workflow preserves author control through explicit patch approval and versioned source snapshots. This paper is a demonstration manuscript; no empirical performance is claimed.
\end{abstract}
\section{Introduction}
Revising a scientific manuscript involves more than improving fluency. A sentence may read naturally while overstating an experimental result or hiding an assumption. A useful revision process must therefore track both the language and the evidence behind each claim.

Our approach places the author at the center of an iterative review cycle. The author annotates a compiled document, a reviewer proposes localized edits, and the author inspects those edits before a new version is compiled. Each stage leaves an explicit record.
\section{Workflow}
\subsection{Annotation and Evidence}
An annotation records a page, a location, and an optional text quotation. Its document version is retained so that a comment is not silently attached to unrelated text after pagination changes. Claims requiring additional experiments remain open rather than being replaced with invented results.
\subsection{Controlled Revision}
The editor produces exact source replacements. A proposed change is applied only when its original passage occurs once in the current file. The revised source is compiled before the new version becomes active. A failed build leaves the accepted manuscript unchanged.
\begin{figure}[h]
\centering
\includegraphics[width=0.95\linewidth]{workflow.png}
\caption{The author controls the revision cycle. Each accepted revision retains a source snapshot.}
\label{fig:workflow}
\end{figure}
\section{Review Principles}
Review findings separate severity from certainty. A missing citation may be a confirmed textual omission, while the identity of a potentially relevant work remains unverified without access to its primary source. Submission requirements depend on the target venue and year, not on a universal checklist.
\section{Limitations}
Compilation checks do not establish scientific validity. Source-level review does not replace visual inspection of figures, external citation verification, or expert assessment. The demonstration does not provide a benchmark or evidence of improved publication outcomes.
\section{Conclusion}
Versioned annotations and explicit patch approval make the revision process inspectable. Scientific decisions and final acceptance of changes remain with the author.
\end{document}`;
app.post(
  "/api/projects/import",
  upload.single("file"),
  wrap(async (req, res) => {
    if (req.body.trusted !== "true")
      throw new Error(
        "仅导入你信任的 LaTeX 项目。原生 TeX 编译不是强隔离沙箱。",
      );
    const isDemo = req.body.demo === "true";
    let files;
    if (isDemo) {
      files = { "main.tex": Buffer.from(demo).toString("base64") };
      files["workflow.png"] = (
        await readFile(path.join(root, "public/workflow.png"))
      ).toString("base64");
    } else {
      if (!req.file) throw new Error("请选择 Overleaf 导出的 ZIP");
      files = importZip(req.file.buffer);
    }
    const p = {
      id: randomUUID(),
      name: isDemo
        ? "Evidence Before Eloquence"
        : path.basename(req.file.originalname, ".zip"),
      main: detectMain(files),
      engine: "pdflatex",
      venue: "",
      revision: null,
      pdfRevision: null,
      comments: [],
      history: [],
      proposals: [],
      reports: [],
      log: "",
      trusted: true,
    };
    await snapshot(p, files, "导入项目");
    await sendProject(res, p);
  }),
);
app.get(
  "/api/projects/:id",
  wrap(async (req, res) => sendProject(res, await getProject(req.params.id))),
);
app.patch(
  "/api/projects/:id",
  locked(async (req, res) => {
    const p = await getProject(req.params.id);
    const changes = z
      .object({
        main: z.string().optional(),
        engine: z.enum(["pdflatex", "xelatex"]).optional(),
        venue: z.string().max(10000).optional(),
      })
      .parse(req.body);
    const rev = await getRevision(p.id, p.revision);
    if (
      changes.main &&
      (!rev.files[changes.main] || !/\.tex$/i.test(changes.main))
    )
      throw new Error("主文件不存在");
    const changedBuild =
      (changes.main && changes.main !== p.main) ||
      (changes.engine && changes.engine !== p.engine);
    Object.assign(p, changes);
    if (changedBuild) await snapshot(p, rev.files, "修改编译配置");
    else await saveProject(p);
    await sendProject(res, p);
  }),
);
app.get(
  "/api/projects/:id/source",
  wrap(async (req, res) => {
    const p = await getProject(req.params.id);
    const rev = await getRevision(p.id, p.revision);
    const name = safePath(req.query.file);
    if (!textExt.test(name) || !rev.files[name])
      throw new Error("文件不可编辑");
    res.json({
      content: Buffer.from(rev.files[name], "base64").toString("utf8"),
      revision: rev.id,
    });
  }),
);
app.put(
  "/api/projects/:id/source",
  locked(async (req, res) => {
    const input = z
      .object({
        file: z.string(),
        content: z.string().max(2000000),
        revision: z.string().uuid(),
      })
      .parse(req.body);
    const p = await getProject(req.params.id);
    if (p.revision !== input.revision)
      return res.status(409).json({ error: "文件版本已改变，请重新打开" });
    const rev = await getRevision(p.id, p.revision);
    safePath(input.file);
    if (!textExt.test(input.file) || !rev.files[input.file])
      throw new Error("文件不可编辑");
    if(Buffer.from(input.content).toString("base64")===rev.files[input.file])return sendProject(res,p);
    for(const c of p.comments)if(c.addressed && p.proposals.some(proposal=>proposal.status==="applied" && proposal.patches.some(patch=>patch.file===input.file && patch.commentIds.includes(c.id)))){c.addressed=false;c.archivedAt=null;c.archiveProposalId=null;c.addressedInvalidatedAt=new Date().toISOString();}
    await snapshot(
      p,
      {
        ...rev.files,
        [input.file]: Buffer.from(input.content).toString("base64"),
      },
      `编辑 ${input.file}`,
    );
    await sendProject(res, p);
  }),
);
app.post(
  "/api/projects/:id/compile",
  locked(async (req, res) => {
    const p = await getProject(req.params.id);
    const rev = await getRevision(p.id, p.revision);
    try {
      const result = await compile(p, rev.files);
      await writeFile(path.join(pid(p.id), `${rev.id}.pdf`), result.pdf);
      p.pdfRevision = rev.id;
      p.log = result.log;
      await saveProject(p);
      await sendProject(res, p);
    } catch (e) {
      p.log = e.log || e.message;
      await saveProject(p);
      throw e;
    }
  }),
);
app.get(
  "/api/projects/:id/pdf/:rev",
  wrap(async (req, res) => {
    const file = path.join(
      pid(req.params.id),
      `${z.string().uuid().parse(req.params.rev)}.pdf`,
    );
    res
      .type("pdf")
      .set("Cache-Control", "no-store")
      .sendFile(path.basename(file),{root:path.dirname(file)});
  }),
);
app.get("/api/experience", wrap(async (req,res) => {
  for(const entry of await readdir(dataRoot)) {
    if(!z.string().uuid().safeParse(entry).success)continue;
    await experience.record(await getProject(entry));
  }
  res.type("text/markdown").attachment("experience.md").send(await experience.markdown());
}));
app.get(
  "/api/projects/:id/export",
  wrap(async (req, res) => {
    const p = await getProject(req.params.id);
    const rev = await getRevision(p.id, p.revision);
    const zip = new AdmZip();
    for (const [name, content] of Object.entries(rev.files))
      zip.addFile(name, Buffer.from(content, "base64"));
    res
      .type("zip")
      .attachment("autopaperreview-source.zip")
      .send(zip.toBuffer());
  }),
);
app.get(
  "/api/projects/:id/report",
  wrap(async (req, res) => {
    const p = await getProject(req.params.id);
    res
      .type("json")
      .attachment("autopaperreview-review.json")
      .send(
        JSON.stringify(
          {
            project: p.name,
            revision: p.revision,
            comments: p.comments,
            reports: p.reports,
            proposals: p.proposals,
            history:p.history,
            sourceGit:p.sourceGit||null,
            overleafSyncHistory:p.overleaf?.syncHistory||[],
            jobs:await projectJobHistory(p.id),
          },
          null,
          2,
        ),
      );
  }),
);
app.post(
  "/api/projects/:id/comments",
  queued(async (req, res) => {
    const input = z
      .object({
        requestId: z.string().uuid().optional(),
        body: z.string().trim().min(1).max(10000),
        quote: z.string().max(10000).default(""),
        page: z.number().int().min(1).nullable().default(null),
        x: z.number().min(0).max(1).nullable().default(null),
        y: z.number().min(0).max(1).nullable().default(null),
        pdfRevision: z.string().uuid().nullable(),
        file: z.string().default(""),
        severity: z.enum(["critical", "major", "minor"]).default("minor"),
      })
      .parse(req.body);
    const p = await getProject(req.params.id);
    if (input.requestId) {
      const previous = p.comments.find(c => c.requestId === input.requestId);
      if (previous) {
        if (Object.keys(input).some(key => previous[key] !== input[key]))
          return res.status(409).json({error:"这次提交编号已用于不同批注，请重新提交。"});
        return sendProject(res, p);
      }
    }
    if (input.pdfRevision) await getRevision(p.id, input.pdfRevision);
    p.comments.push({
      ...input,
      id: randomUUID(),
      author: "you",
      status: "open",
      created: new Date().toISOString(),
    });
    await saveProject(p);
    if (p.automation?.enabled) queueAutomatic(p.id);
    await sendProject(res, p);
  }),
);
app.patch(
  "/api/projects/:id/comments/:comment",
  locked(async (req, res) => {
    const p = await getProject(req.params.id);
    const c = p.comments.find((c) => c.id === req.params.comment);
    if (!c) throw new Error("批注不存在");
    const input=z.object({status:z.enum(["open","resolved"]),retry:z.boolean().default(false),archived:z.literal(false).optional()}).parse(req.body);
    c.status=input.status;
    if(input.status==="open")c.addressed=false;
    if(input.archived===false){c.archivedAt=null;c.archiveProposalId=null;c.archiveRestoredAt=new Date().toISOString();}
    c.resolvedAt=input.status==="resolved"?new Date().toISOString():null;
    await saveProject(p);
    if(input.retry && c.author==="you" && c.status==="open" && p.automation?.enabled)queueAutomatic(p.id);
    await sendProject(res, p);
  }),
);
app.post("/api/projects/:id/translate", async (req, res, next) => {
  try {
    const input = z.object({ text: z.string().trim().min(1), consent: z.literal(true), engine:z.enum(["fast","quality"]).default("quality") }).parse(req.body);
    await stat(projectFile(req.params.id));
    if (input.engine === "fast" && (!process.env.TRANSLATION_MODEL || config.provider === "codex")) throw new Error("管理员尚未配置快速翻译模型，不会回退到论文模型");
    res.json(await translate(input.text, { ...config, model:input.engine === "fast" ? process.env.TRANSLATION_MODEL : config.model }));
  } catch (error) { next(error); }
});
app.get("/api/projects/:id/bibliography", wrap(async (req, res) => {
  const p = await getProject(req.params.id);
  const revision = req.query.revision || p.revision;
  const rev = await getRevision(p.id, revision);
  res.json({ revision, ...bibliography(rev.files), audit: p.bibAudit?.revision === revision ? p.bibAudit : null });
}));
app.post("/api/projects/:id/bibliography/audit", wrap(async (req, res) => {
  z.object({consent: z.literal(true)}).parse(req.body);
  const p = await getProject(req.params.id), rev = await getRevision(p.id, p.revision);
  const job = jobs.enqueue(p.id, async ({ signal, progress }) => {
    const report = { revision: rev.id, ...bibliography(rev.files), checked: new Date().toISOString() };
    for (let i = 0; i < report.entries.length; i++) {
      signal.throwIfAborted();
      const entry = report.entries[i];
      progress({phase: "checking", message: `核查文献 ${i+1}/${report.entries.length} · ${entry.key}`});
      entry.verification = await verifyEntry(entry, {signal});
    }
    await withProjectLock(p.id, async () => {
      const fresh = await getProject(p.id);
      fresh.bibAudit = report;
      await saveProject(fresh);
    }, signal);
    return { message: "Bib 核查完成，未改写文献数据库", revision: rev.id };
  }, {title: "核查 Bib 文献"});
  res.status(202).json({job});
}));
app.post(
  "/api/projects/:id/ai",
  locked(async (req, res) => {
    const input = z
      .object({
        mode: z.enum(["review", "revise"]),
        skillIds: z.array(z.string()).min(1).max(skills.length),
        instructions: z.string().max(12000),
        consent: z.literal(true),
      })
      .parse(req.body);
    const p = await getProject(req.params.id);
    const rev = await getRevision(p.id, p.revision);
    const runConfig = taskConfig(input.mode);
    input.skillIds=effectiveSkillIds(input.skillIds);
    input.skillManifest=await skillManifest(input.skillIds);
    const result = await generate(p, rev, input, runConfig);
    await saveAIResult(p, rev, input, runConfig, result);
    await sendProject(res, p);
  }),
);
app.post(
  "/api/projects/:id/proposals/:proposal/:action",
  locked(async (req, res) => {
    const p = await getProject(req.params.id);
    const proposal = p.proposals.find((x) => x.id === req.params.proposal);
    if (!proposal || proposal.status !== "pending")
      throw new Error("该建议不存在或已处理");
    if (req.params.action === "reject") {
      proposal.status = "rejected";
      await saveProject(p);
      return sendProject(res, p);
    }
    if (req.params.action !== "apply") throw new Error("未知操作");
    const approval=z.object({keepOpenCommentIds:z.array(z.string().uuid()).max(100).default([])}).strict().parse(req.body||{});
    const linked=new Set(proposal.effectiveCommentIds||proposal.patches.flatMap(patch=>patch.commentIds));
    if(new Set(approval.keepOpenCommentIds).size!==approval.keepOpenCommentIds.length||approval.keepOpenCommentIds.some(id=>!linked.has(id)))
      throw Error("保留待处理的批注必须属于本次实际修改");
    await applyProposal(p, proposal,approval);
    await jobs.markApplied(p.id,proposal.id,p.revision);
    await sendProject(res, p);
  }),
);
app.get(
  "/api/projects/:id/activity",
  wrap(async (req, res) => {
    const version = await stat(projectFile(req.params.id));
    res
      .set("Cache-Control", "no-store")
      .json({ job: await jobs.get(req.params.id), projectVersion: `${version.mtimeMs}:${version.size}` });
  }),
);
async function projectJobHistory(id) {
  const folder=path.join(pid(id),"jobs"),names=await readdir(folder).catch(e=>{if(e.code==="ENOENT")return [];throw e;});
  const records=[];
  for(const name of names)if(/^[a-f0-9-]{36}\.json$/.test(name))records.push(JSON.parse(await readFile(path.join(folder,name),"utf8")));
  return records.sort((a,b)=>b.created.localeCompare(a.created));
}
app.get("/api/projects/:id/jobs/history",wrap(async(req,res)=>{await getProject(req.params.id);res.json(await projectJobHistory(req.params.id));}));
app.post("/api/projects/:id/history/git",locked(async(req,res)=>{
  const p=await getProject(req.params.id);await ensureGitHistory(p);
  const previous=await jobs.get(p.id);
  if(previous && !["queued","running","cancelling"].includes(previous.status)){
    const file=path.join(pid(p.id),"jobs",`${z.string().uuid().parse(previous.id)}.json`);
    if(!await readFile(file).then(()=>true).catch(e=>{if(e.code==="ENOENT")return false;throw e;}))await atomicJSON(file,previous);
  }
  await saveProject(p);await sendProject(res,p);
}));
app.get("/api/projects/:id/history/:rev/diff",wrap(async(req,res)=>{
  const p=await getProject(req.params.id),rev=await getRevision(p.id,req.params.rev);
  if(!rev.gitCommit)throw Error("此旧版本尚未建立 Git 历史索引");
  res.json({revision:rev.id,commit:rev.gitCommit,parent:rev.parent||null,provenance:rev.provenance||null,diff:await sourceCommitDiff(pid(p.id),rev.id)});
}));
app.post(
  "/api/projects/:id/jobs",
  wrap(async (req, res) => {
    await getProject(req.params.id);
    const input = z
      .object({
        mode: z.enum(["review", "revise"]),
        skillIds: z
          .array(z.enum(skills.map((s) => s.id)))
          .min(1)
          .max(skills.length),
        instructions: z.string().max(12000),
        consent: z.literal(true),
        apply: z.boolean().default(false),
        commentScope: z.enum(["human","allPending"]).default("human"),
        commentIds: z.array(z.string().uuid()).min(1).max(100).optional(),
        candidateProposalId:z.string().uuid().optional(),
        expectedRevision:z.string().uuid().optional(),
      })
      .parse(req.body);
    if(input.apply&&input.mode!=="revise")throw Error("审稿模式不允许自动改写源码");
    if(input.candidateProposalId&&input.mode!=="revise")throw Error("仅修订模式允许复核已有草稿");
    if(input.commentIds) {
      const project=await getProject(req.params.id);
      const eligible=new Set(revisionComments(project,input,taskConfig(input.mode)).map(c=>c.id));
      if(input.mode!=="revise"||new Set(input.commentIds).size!==input.commentIds.length||input.commentIds.some(id=>!eligible.has(id)))
        throw Error("所选批注已处理、不可用或重复；未发送模型请求");
    }
    const job = jobs.enqueue(
      req.params.id,
      (context) => runAIJob(req.params.id, input, false, context),
      { title: input.mode === "review" ? "全面审稿" : "按批注修订",model:taskConfig(input.mode).model,provider:taskConfig(input.mode).vendor||config.provider },
    );
    res.status(202).json({ job });
  }),
);
app.post(
  "/api/projects/:id/jobs/cancel",
  wrap(async (req, res) => {
    await getProject(req.params.id);
    res.json({ job: jobs.cancel(req.params.id) });
  }),
);
app.post(
  "/api/projects/:id/automation",
  locked(async (req, res) => {
    const input = z
      .object({
        enabled: z.boolean(),
        consent: z.boolean().optional(),
        startNow: z.boolean().default(false),
        skillIds: z
          .array(z.enum(skills.map((s) => s.id)))
          .min(1)
          .max(skills.length)
          .optional(),
      })
      .parse(req.body);
    if (input.enabled && (input.consent !== true || !input.skillIds))
      throw new Error("开启自动修订需要明确确认云端处理及所选 Skills");
    const p = await getProject(req.params.id);
    p.automation = {
      enabled: input.enabled,
      skillIds: input.skillIds || p.automation?.skillIds || [],
      provider: revisionConfig.provider,
      model: revisionConfig.model,
      workflow:revisionConfig.workflow||null,
      grantedAt: new Date().toISOString(),
    };
    await saveProject(p);
    if (input.enabled && input.startNow) queueAutomatic(p.id);
    if (!input.enabled && (await jobs.get(p.id))?.automatic) jobs.cancel(p.id);
    await sendProject(res, p);
  }),
);
app.post(
  "/api/projects/:id/overleaf/connect",
  locked(async (req, res) => {
    const input = z
      .object({
        url: z.string().max(300),
        token: z.string().max(500).optional(),
        autoPush: z.boolean().default(false),
        consent: z.literal(true),
      })
      .parse(req.body);
    const p = await getProject(req.params.id);
    const url = overleafURL(input.url);
    const repository = await connectOverleaf(pid(p.id), url, input.token || (p.overleaf?.url === url ? await syncTokens.get(p.id, url) : undefined));
    if (input.token) await syncTokens.set(p.id, url, input.token);
    else if (p.overleaf?.url !== url) await syncTokens.delete(p.id);
    const previous = p.overleaf?.directory;
    p.overleaf = {
      ...repository,
      baseRevision:
        p.overleaf?.url === repository.url
          ? p.overleaf.baseRevision
          : p.history[p.history.length - 1].id,
      autoPush: input.autoPush,
      lastSynced:
        p.overleaf?.url === repository.url ? p.overleaf.lastSynced : null,
      lastError: "",
    };
    await saveProject(p);
    if (
      previous &&
      previous !== repository.directory &&
      path.dirname(previous) === pid(p.id)
    )
      await rm(previous, { recursive: true, force: true });
    await sendProject(res, p);
  }),
);
app.delete("/api/projects/:id/overleaf/credentials", locked(async (req,res) => {
  const p = await getProject(req.params.id);
  await syncTokens.delete(p.id);
  if(p.overleaf) {p.overleaf.autoPush=false;await saveProject(p);}
  await sendProject(res,p);
}));
app.post(
  "/api/projects/:id/overleaf/push",
  wrap(async (req, res) => {
    z.object({ consent: z.literal(true) }).parse(req.body);
    await getProject(req.params.id);
    const job = jobs.enqueue(
      req.params.id,
      ({ signal, progress }) =>
        withProjectLock(
          req.params.id,
          async () =>
            syncProject(await getProject(req.params.id), { signal, progress }),
          signal,
        ),
      { title: "同步至 Overleaf" },
    );
    res.status(202).json({ job });
  }),
);
app.post(
  "/api/projects/:id/restore/:rev",
  locked(async (req, res) => {
    const p = await getProject(req.params.id);
    const rev = await getRevision(p.id, req.params.rev);
    p.main = rev.main;
    p.engine = rev.engine;
    for(const c of p.comments)if(c.addressed && c.status==="open"){c.addressed=false;c.archivedAt=null;c.archiveProposalId=null;c.addressedInvalidatedAt=new Date().toISOString();}
    const savedPDF = await readFile(path.join(pid(p.id), `${rev.id}.pdf`)).catch(error => {
      if (error.code === "ENOENT") return null;
      throw error;
    });
    const restoredPDF = savedPDF ? {pdf:savedPDF,log:`恢复已编译版本 ${rev.id}`} : await compile(p, rev.files);
    await snapshot(p, rev.files, "恢复历史版本",restoredPDF,{restoredFrom:rev.id,provenance:{kind:"restore"}});
    await sendProject(res, p);
  }),
);
installPeerReviewRoutes(app,{pid,getProject,getRevision,getConfig:()=>config,jobs,wrap});
installFigureRoutes(app,{pid,getProject,getRevision,saveProject,snapshot,compile,withProjectLock,getConfig:()=>config,jobs,wrap});
app.use("/api/reviewer", await createReviewerRouter({
  directory: path.join(dataRoot, "reviewer"), getConfig: () => config, status: aiStatus,
}));
app.use("/api", (req, res) => res.status(404).json({ error: "API 不存在" }));
app.get(["/review", "/review/"], (req, res, next) => {
  if (process.env.NODE_ENV !== "production") return next();
  res.sendFile("index.html",{root:path.join(root,"dist")});
});
if (process.env.NODE_ENV === "production")
  app.use(express.static(path.join(root, "dist")));
else {
  const { createServer } = await import("vite");
  const vite = await createServer({
    root,
    server: { middlewareMode: true, hmr: { server: httpServer } },
    appType: "spa",
  });
  app.use(vite.middlewares);
}
app.use((err, req, res, next) => {
  const message =
    err instanceof z.ZodError
      ? "请求参数不合法"
      : err.code === "ENOENT"
        ? "文件不存在"
        : err.message;
  res
    .status(err.code === "ENOENT" ? 404 : err.status === 409 ? 409 : 400)
    .json({ error: message, log: err.log });
});
httpServer.listen(port, process.env.BIND_HOST || "127.0.0.1", () =>
  console.log(`Autopaperreview: http://localhost:${port}`),
);
