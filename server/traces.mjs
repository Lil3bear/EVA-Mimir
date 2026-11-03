import path from "node:path";
import {readdir, readFile, stat} from "node:fs/promises";
import {git} from "./overleaf.mjs";

// P0: read-only replay. Everything here is derived from existing artifacts;
// nothing is written back to the project, the job log or the Overleaf mirror.

export const TRACE_ID = "main";
const MAX_PATCH_LINES = 160;
const MAX_REASON = 2000;
const MAX_INSTRUCTION = 4000;
const MAX_REMOTE_COMMITS = 30;
const MAX_SESSION_BYTES = 4 * 1024 * 1024;

const STATUS_LABEL = {
  completed: "completed",
  no_changes: "no_changes",
  awaiting_approval: "awaiting_approval",
  failed: "failed",
  cancelled: "cancelled",
  interrupted: "interrupted",
  running: "running",
  queued: "queued",
};

const trim = (value, max) => {
  const text = String(value ?? "");
  return text.length > max ? `${text.slice(0, max)}…` : text;
};

const within = (root, target) => {
  if (!root || !target) return false;
  const rel = path.relative(path.resolve(root), path.resolve(target));
  return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
};

function actorView(actor) {
  if (!actor || !actor.name) return null;
  return {kind: "member", memberId: actor.id || null, name: String(actor.name).slice(0, 80)};
}

// Keep the changed region only: full-file before/after in a proposal is
// unreadable in a transcript and unnecessary for review.
export function compactPatch(patch) {
  const before = String(patch?.before ?? "").split("\n");
  const after = String(patch?.after ?? "").split("\n");
  let prefix = 0;
  while (prefix < before.length && prefix < after.length && before[prefix] === after[prefix]) prefix++;
  let suffix = 0;
  while (
    suffix < before.length - prefix &&
    suffix < after.length - prefix &&
    before[before.length - 1 - suffix] === after[after.length - 1 - suffix]
  ) suffix++;
  const context = 3;
  const from = Math.max(0, prefix - context);
  let to = Math.min(before.length, before.length - suffix + context);
  let afterTo = Math.min(after.length, after.length - suffix + context);
  let excerptBefore = before.slice(from, to);
  let excerptAfter = after.slice(from, afterTo);
  let trimmed = from > 0 || to < before.length || afterTo < after.length;
  if (excerptBefore.length > MAX_PATCH_LINES) {
    excerptBefore = [...excerptBefore.slice(0, MAX_PATCH_LINES - 20), "…", ...excerptBefore.slice(-19)];
    trimmed = true;
  }
  if (excerptAfter.length > MAX_PATCH_LINES) {
    excerptAfter = [...excerptAfter.slice(0, MAX_PATCH_LINES - 20), "…", ...excerptAfter.slice(-19)];
    trimmed = true;
  }
  return {
    file: String(patch?.file ?? ""),
    reason: trim(patch?.reason, MAX_REASON),
    commentIds: Array.isArray(patch?.commentIds) ? patch.commentIds.filter(id => typeof id === "string") : [],
    before: excerptBefore.join("\n"),
    after: excerptAfter.join("\n"),
    trimmed,
  };
}

function commentView(comment) {
  if (!comment) return null;
  return {
    id: String(comment.id ?? ""),
    body: trim(comment.body, 4000),
    quote: trim(comment.quote, 2000),
    file: comment.file ? String(comment.file) : "",
    page: Number.isInteger(comment.page) ? comment.page : null,
    severity: comment.severity || null,
    author: comment.author === "ai" ? "AI Reviewer" : (comment.actor?.name || "历史共享账号"),
  };
}

function pickComments(project, proposal, job) {
  const byId = new Map((project.comments || []).map(comment => [comment.id, comment]));
  const source = new Map((proposal?.sourceComments || []).map(comment => [comment.id, comment]));
  const ids = [
    ...(job?.request?.commentIds || []),
    ...(proposal?.effectiveCommentIds || []),
    ...(proposal?.sourceComments || []).map(comment => comment.id),
  ];
  const seen = new Set();
  const result = [];
  for (const id of ids) {
    if (typeof id !== "string" || seen.has(id)) continue;
    seen.add(id);
    const view = commentView(byId.get(id) || source.get(id));
    if (view) result.push(view);
  }
  return result;
}

function modelView(project, proposal, job) {
  const provider = proposal?.vendor || proposal?.provider || job?.provider || null;
  const id = proposal?.model || job?.model || null;
  const name = proposal?.modelName || proposal?.model || job?.model || null;
  if (!provider && !id) return null;
  return {provider, id, name};
}

function durationBetween(start, end) {
  if (!start || !end) return null;
  const value = Date.parse(end) - Date.parse(start);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

function jobProposal(proposalList, job) {
  const wanted = job?.result?.proposal;
  if (wanted) {
    const match = proposalList.find(proposal => proposal.id === wanted);
    if (match) return match;
  }
  return proposalList.find(proposal => proposal.revision === job.revision) || null;
}

function historyFor(history, proposal, job) {
  const revision = job?.result?.revision || proposal?.resultRevision;
  if (revision) {
    const match = history.find(entry => entry.id === revision);
    if (match) return match;
  }
  if (proposal) {
    const match = history.find(entry => entry.provenance?.proposalId === proposal.id);
    if (match) return match;
  }
  return null;
}

function buildRun(project, {job = null, proposal = null, history = null, startedAt, endedAt, status, title, instruction}) {
  const model = modelView(project, proposal, job);
  const comments = pickComments(project, proposal, job);
  const revision = history?.id || job?.result?.revision || proposal?.resultRevision || null;
  const gitCommit = history?.gitCommit || proposal?.gitCommit || null;
  const error =
    (job?.status === "failed" || job?.status === "cancelled" || job?.status === "interrupted" ? job.error : null) ||
    proposal?.lastError ||
    null;
  return {
    id: job ? `job-${job.id}` : proposal ? `proposal-${proposal.id}` : `revision-${history?.id}`,
    startedAt: startedAt || null,
    endedAt: endedAt || null,
    durationMs: durationBetween(startedAt, endedAt),
    status,
    title: title || job?.title || "修订",
    instruction: trim(instruction ?? job?.request?.instructions ?? "", MAX_INSTRUCTION),
    comments,
    baseRevision: proposal?.revision || job?.events?.find(event => event.revision)?.revision || history?.parent || null,
    revision,
    gitCommit,
    model,
    summary: trim(proposal?.summary || job?.result?.message || job?.message || "", 8000),
    coverage: trim(project.reports?.find(report => report.id === proposal?.reportId)?.coverage, 4000),
    patches: (proposal?.patches || []).map(compactPatch),
    collaboration: proposal?.collaboration ? {
      workflow: proposal.collaboration.workflow || null,
      teamMode: proposal.collaboration.teamMode || null,
      stages: (proposal.collaboration.stages || []).map(stage => ({
        role: stage.role || "stage",
        provider: stage.provider || null,
        vendor: stage.vendor || null,
        model: stage.model || null,
        transport: stage.transport || null,
        summary: trim(stage.summary, 6000),
        coverage: trim(stage.coverage, 3000),
        patchCount: Array.isArray(stage.patches) ? stage.patches.length : 0,
        findingCount: Array.isArray(stage.findings) ? stage.findings.length : 0,
      })),
    } : null,
    error: error ? trim(error, 4000) : null,
    usage: null,
    actor: actorView(history?.initiatedBy),
    _job: job,
    _proposal: proposal,
    _history: history,
    events: [],
    order: 0,
  };
}

export function deriveTurns(project, jobHistory = []) {
  const proposals = Array.isArray(project.proposals) ? project.proposals : [];
  const history = Array.isArray(project.history) ? project.history : [];
  const runs = [];
  const usedProposals = new Set();
  const usedHistory = new Set();

  for (const job of [...jobHistory].sort((a, b) => String(a.created).localeCompare(String(b.created)))) {
    const proposal = jobProposal(proposals, job);
    if (proposal) usedProposals.add(proposal.id);
    const entry = historyFor(history, proposal, job);
    if (entry) usedHistory.add(entry.id);
    const startedAt = job.started || job.created;
    const terminal = ["completed", "no_changes", "awaiting_approval", "failed", "cancelled", "interrupted"].includes(job.status);
    runs.push(buildRun(project, {
      job,
      proposal,
      history: entry,
      startedAt,
      endedAt: terminal ? job.updated : null,
      status: STATUS_LABEL[job.status] || "completed",
      title: job.title,
      instruction: job.request?.instructions,
    }));
  }

  for (const proposal of proposals) {
    if (usedProposals.has(proposal.id)) continue;
    const entry = historyFor(history, proposal, null);
    if (entry) usedHistory.add(entry.id);
    const startedAt = proposal.time || entry?.time || null;
    const endedAt = proposal.status === "applied" ? (entry?.time || proposal.appliedAt || null) : null;
    runs.push(buildRun(project, {
      proposal,
      history: entry,
      startedAt,
      endedAt,
      status: proposal.status === "applied" ? "completed" : proposal.status === "pending" ? "awaiting_approval" : proposal.status === "rejected" ? "rejected" : "completed",
      title: "AI 修订",
    }));
  }

  for (const entry of history) {
    if (usedHistory.has(entry.id)) continue;
    const kind = entry.provenance?.kind || "manual";
    if (kind === "ai") continue;
    // The initial import is the baseline, not a review turn.
    if (/^导入/.test(String(entry.label || ""))) continue;
    runs.push(buildRun(project, {
      history: entry,
      startedAt: entry.time,
      endedAt: entry.time,
      status: kind === "restore" ? "restored" : "manual",
      title: entry.label || (kind === "restore" ? "恢复版本" : "手动编辑"),
    }));
  }

  runs.sort((a, b) => String(a.startedAt || "").localeCompare(String(b.startedAt || "")));
  runs.forEach((run, index) => {
    run.index = index + 1;
    run.id = `turn-${run.index}`;
  });
  return runs;
}

export async function readPiUsage(directory, sessionRoot) {
  if (!within(sessionRoot, directory)) return null;
  try {
    const info = await stat(directory);
    if (!info.isDirectory()) return null;
    const names = (await readdir(directory)).filter(name => name.endsWith(".jsonl")).sort();
    if (!names.length) return null;
    const file = path.join(directory, names[names.length - 1]);
    const fileInfo = await stat(file);
    if (!fileInfo.isFile() || fileInfo.size > MAX_SESSION_BYTES) return null;
    const text = await readFile(file, "utf8");
    let usage = null;
    for (const line of text.split("\n")) {
      if (!line.trim()) continue;
      let entry;
      try { entry = JSON.parse(line); } catch { continue; }
      const message = entry?.type === "message" ? entry.message : null;
      if (!message || message.role !== "assistant" || !message.usage) continue;
      const value = message.usage;
      usage = {
        input: Number(value.input) || 0,
        output: Number(value.output) || 0,
        total: Number(value.totalTokens) || (Number(value.input) || 0) + (Number(value.output) || 0),
        cost: Number(value.cost?.total) || 0,
        model: message.model || null,
        provider: message.provider || null,
      };
    }
    return usage;
  } catch {
    return null;
  }
}

export function parseRemoteLog(text) {
  const commits = [];
  let current = null;
  for (const line of String(text || "").split("\n")) {
    if (line.includes("\u001f")) {
      const [commit, author, authorTime, commitTime, ...rest] = line.split("\u001f");
      if (!/^[a-f0-9]{7,40}$/.test(commit || "")) continue;
      current = {
        commit,
        short: commit.slice(0, 7),
        author: trim(author, 80),
        authorTime: authorTime || null,
        commitTime: commitTime || null,
        message: trim(rest.join("\u001f"), 300),
        files: null,
        insertions: 0,
        deletions: 0,
      };
      commits.push(current);
      continue;
    }
    const stat = /(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?/.exec(line);
    if (stat && current) {
      current.files = Number(stat[1]);
      current.insertions = Number(stat[2] || 0);
      current.deletions = Number(stat[3] || 0);
    }
  }
  return commits.reverse();
}

export async function readRemoteCommits(project, {dataRoot, gitFn = git, limit = MAX_REMOTE_COMMITS} = {}) {
  const directory = project?.overleaf?.directory;
  if (!directory || !within(dataRoot, directory)) return [];
  try {
    const output = await gitFn([
      "--git-dir", directory, "log", "--all", `-n`, String(limit),
      "--format=%H%x1f%an%x1f%aI%x1f%cI%x1f%s", "--shortstat",
    ], {cwd: dataRoot});
    return parseRemoteLog(output.toString("utf8"));
  } catch {
    return [];
  }
}

function pushEvent(turn, event) {
  turn.events.push({...event, id: `${turn.id}:${event.type}:${turn.events.length}`, turn: turn.index});
}

function buildTurnEvents(turn) {
  const jobEvents = Array.isArray(turn._job?.events) ? turn._job.events : [];
  const firstOf = phase => jobEvents.find(event => event.phase === phase);
  const timeOf = event => event?.time || null;
  const reading = firstOf("reading");
  const model = firstOf("model");
  const validating = firstOf("validating");
  const saved = firstOf("saved");
  const startedAt = turn.startedAt;
  const proposalTime = turn._proposal?.time || turn._job?.updated || startedAt;

  pushEvent(turn, {
    type: "turn/start", step: 0, time: startedAt, kind: "user", visibility: ["chat", "trajectory"],
    data: {instruction: turn.instruction, commentIds: turn.comments.map(comment => comment.id), baseRevision: turn.baseRevision, title: turn.title},
  });
  turn.comments.forEach((comment, index) => {
    pushEvent(turn, {
      type: "comment/attach", step: 0, time: startedAt, kind: "comment", visibility: ["chat"],
      data: {comment, index},
    });
  });

  if (reading) {
    pushEvent(turn, {
      type: "tool/result", step: 1, time: timeOf(reading), kind: "tool", visibility: ["trajectory"],
      data: {
        tool: "source.read", status: "ok",
        durationMs: model ? durationBetween(timeOf(reading), timeOf(model)) : null,
        detail: {comments: turn.comments.length},
      },
    });
  }
  const stages = turn.collaboration?.stages || [];
  if (stages.length) {
    const progress = jobEvents.filter(event => event.phase === "model" && /联合修订/.test(event.message || ""));
    const source = progress.length ? progress : jobEvents.filter(event => event.phase === "model");
    stages.forEach((stage, index) => {
      const start = source[index]?.time || timeOf(model) || proposalTime;
      const next = source[index + 1]?.time || timeOf(validating) || proposalTime;
      pushEvent(turn, {
        type: "tool/result", step: 2, time: start, kind: "model", visibility: ["trajectory"],
        data: {
          tool: "model.request", status: "ok",
          durationMs: durationBetween(start, next),
          model: {provider: stage.vendor || stage.provider, id: stage.model, name: stage.model},
          stage,
        },
      });
    });
  } else if (model) {
    const seconds = validating ? durationBetween(timeOf(model), timeOf(validating)) : null;
    pushEvent(turn, {
      type: "tool/result", step: 2, time: timeOf(model), kind: "tool", visibility: ["trajectory"],
      data: {tool: "model.request", status: "ok", durationMs: seconds, model: turn.model, usage: turn.usage},
    });
  }
  if (validating) {
    pushEvent(turn, {
      type: "tool/result", step: 3, time: timeOf(validating), kind: "tool", visibility: ["trajectory"],
      data: {
        tool: "patch.validate", status: turn.patches.length ? "ok" : "empty",
        durationMs: proposalTime ? durationBetween(timeOf(validating), proposalTime) : null,
        detail: {patches: turn.patches.length, files: [...new Set(turn.patches.map(patch => patch.file).filter(Boolean))]},
      },
    });
  }
  if (turn.summary) {
    pushEvent(turn, {
      type: "assistant/message", step: 3, time: proposalTime, kind: "model", visibility: ["chat", "trajectory"],
      data: {summary: turn.summary, coverage: turn.coverage, model: turn.model, usage: turn.usage},
    });
  }
  turn.patches.forEach((patch, index) => {
    pushEvent(turn, {
      type: "patch/proposed", step: 4, time: proposalTime, kind: "patch", visibility: ["chat", "trajectory"],
      data: {patch, index},
    });
  });
  if (turn.revision) {
    pushEvent(turn, {
      type: "revision/created", step: 5, time: turn._history?.time || turn.endedAt || saved?.time || proposalTime,
      kind: "revision", visibility: ["chat", "trajectory"],
      data: {revision: turn.revision, label: turn._history?.label || "已保存版本", gitCommit: turn.gitCommit},
    });
  }
  for (const sync of turn._project?.overleaf?.syncHistory || []) {
    if (sync.revision !== turn.revision) continue;
    pushEvent(turn, {
      type: "overleaf/push", step: 6, time: sync.time, kind: "remote", visibility: ["chat", "trajectory"],
      data: {remoteCommit: sync.remoteCommit, model: sync.model, provider: sync.provider, status: "ok"},
    });
  }
  if (turn.error) {
    pushEvent(turn, {
      type: "error", step: 6, time: turn.endedAt || proposalTime, kind: "error", visibility: ["chat", "trajectory"],
      data: {message: turn.error, status: turn.status},
    });
  }
  if (!["running", "queued"].includes(turn.status)) {
    pushEvent(turn, {
      type: "turn/end", step: 7, time: turn.endedAt || proposalTime, kind: "system", visibility: ["trajectory"],
      data: {status: turn.status, durationMs: turn.durationMs, outcome: turn._job?.result?.outcome || null},
    });
  }

  turn.events.forEach((event, index) => { event._order = index; });
  for (const key of ["_job", "_proposal", "_history", "_project", "order"]) delete turn[key];
}

function remoteEvents(commits) {
  return commits.map(commit => ({
    id: `remote-${commit.commit}`,
    turn: null,
    item: 0,
    time: commit.authorTime || commit.commitTime,
    type: "overleaf/flush",
    kind: "remote",
    visibility: ["chat", "trajectory"],
    actor: {kind: "remote", name: commit.author},
    data: {
      commit: commit.commit,
      short: commit.short,
      message: commit.message,
      author: commit.author,
      authorTime: commit.authorTime,
      commitTime: commit.commitTime,
      files: commit.files,
      insertions: commit.insertions,
      deletions: commit.deletions,
      attribution: "version-author",
      note: "版本级批量提交；同一窗口多人编辑只保留最后编辑者",
    },
  }));
}

export async function buildTrace(project, jobHistory = [], options = {}) {
  const {dataRoot = process.cwd(), sessionRoot = null, gitFn = git, includeRemote = true} = options;
  const turns = deriveTurns(project, jobHistory);
  const used = new Set();

  for (const turn of turns) {
    turn._project = project;
    const directory = (turn._job?.events || []).map(event => event.piSessionDirectory).filter(Boolean).at(-1);
    if (directory && sessionRoot && !used.has(directory)) {
      used.add(directory);
      turn.usage = await readPiUsage(directory, sessionRoot);
    }
    if (!turn.usage && turn._job?.events) {
      const inline = turn._job.events.find(event => event.usage)?.usage;
      if (inline) turn.usage = inline;
    }
    buildTurnEvents(turn);
  }

  const commits = includeRemote ? await readRemoteCommits(project, {dataRoot, gitFn}) : [];
  const remote = remoteEvents(commits);
  const events = [...turns.flatMap(turn => turn.events), ...remote];

  events.sort((left, right) => {
    const byTime = String(left.time || "").localeCompare(String(right.time || ""));
    if (byTime) return byTime;
    const byTurn = (left.turn ?? 1e9) - (right.turn ?? 1e9);
    if (byTurn) return byTurn;
    const byStep = (left.step ?? 0) - (right.step ?? 0);
    if (byStep) return byStep;
    return (left._order ?? 0) - (right._order ?? 0);
  });
  events.forEach((event, index) => {
    event.seq = index + 1;
    delete event._order;
  });

  return {
    id: TRACE_ID,
    title: project.name || "当前项目",
    turns: turns.map(turn => ({
      index: turn.index,
      id: turn.id,
      startedAt: turn.startedAt,
      endedAt: turn.endedAt,
      durationMs: turn.durationMs,
      status: turn.status,
      title: turn.title,
      instruction: turn.instruction,
      comments: turn.comments,
      baseRevision: turn.baseRevision,
      revision: turn.revision,
      gitCommit: turn.gitCommit,
      model: turn.model,
      summary: turn.summary,
      coverage: turn.coverage,
      patches: turn.patches,
      error: turn.error,
      usage: turn.usage,
      collaboration: turn.collaboration,
      actor: turn.actor,
      eventCount: turn.events.length,
    })),
    events,
    remote,
    lastSeq: events.length,
  };
}

export function summarizeTrace(trace) {
  const first = trace.turns[0]?.startedAt || null;
  const last = trace.turns.at(-1)?.endedAt || trace.turns.at(-1)?.startedAt || null;
  return {
    id: trace.id,
    title: trace.title,
    turnCount: trace.turns.length,
    eventCount: trace.events.length,
    remoteCount: trace.remote.length,
    startedAt: first,
    endedAt: last,
  };
}
