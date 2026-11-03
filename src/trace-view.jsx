import React, {useEffect, useMemo, useRef, useState} from "react";
import {
  Activity,
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  Cloud,
  GitCompareArrows,
  LoaderCircle,
  MessageSquare,
  Search,
  Sparkles,
  X,
} from "lucide-react";

const KIND_LABEL = {
  user: "用户", comment: "批注", model: "模型", tool: "工具",
  patch: "补丁", revision: "版本", remote: "远端", system: "状态", error: "错误",
};

const STATUS_LABEL = {
  completed: "Completed", failed: "Failed", cancelled: "Stopped",
  interrupted: "Interrupted", awaiting_approval: "待确认", no_changes: "No changes",
  running: "Running", manual: "手动编辑", restored: "恢复版本", rejected: "已拒绝",
};

const TOOL_LABEL = {
  "source.read": "读取源码",
  "model.request": "模型请求",
  "patch.validate": "校验补丁",
  "compile": "编译",
  "revision.write": "保存版本",
  "git.commit": "Git commit",
  "overleaf.fetch": "拉取 Overleaf",
  "overleaf.push": "推送 Overleaf",
};

const fmtDuration = ms => {
  if (!Number.isFinite(ms) || ms <= 0) return "";
  if (ms < 1000) return `${Math.max(1, Math.round(ms))}ms`;
  if (ms < 60000) return `${Math.round(ms / 100) / 10}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.round((ms % 60000) / 1000);
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
};

const fmtTime = value => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  return date.toLocaleString("zh-CN", sameDay
    ? {hour: "2-digit", minute: "2-digit", hour12: false}
    : {month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false});
};

const fmtTokens = value => (Number.isFinite(value) ? value.toLocaleString("zh-CN") : "—");
const fmtCost = value => (Number.isFinite(value) && value > 0 ? `$${value.toFixed(4)}` : "—");
const shortId = (value, length = 8) => (value ? String(value).slice(0, length) : "");

function eventSummary(event) {
  const data = event.data || {};
  switch (event.type) {
    case "turn/start": return data.instruction || "提交本轮修订";
    case "comment/attach": return `批注 · ${String(data.comment?.body || "").slice(0, 60)}`;
    case "tool/result":
      if (data.stage) return `阶段 ${data.stage.role} · ${data.stage.model || ""}`;
      return `${TOOL_LABEL[data.tool] || data.tool}${data.detail?.patches !== undefined ? ` · ${data.detail.patches} 处` : ""}`;
    case "assistant/message": return `助手回复 · ${String(data.summary || "").slice(0, 60)}`;
    case "patch/proposed": return `${data.patch?.file || "源码"} · ${String(data.patch?.reason || "").slice(0, 40)}`;
    case "revision/created": return `保存版本 ${shortId(data.revision)}${data.gitCommit ? ` · Git ${shortId(data.gitCommit, 7)}` : ""}`;
    case "overleaf/push": return `推送 Overleaf · ${shortId(data.remoteCommit, 7)}`;
    case "overleaf/flush": return `远端版本 · ${data.author || "未知作者"} · ${data.files ?? "?"} 个文件`;
    case "error": return data.message || "执行失败";
    case "turn/end": return `本轮结束 · ${STATUS_LABEL[data.status] || data.status}`;
    default: return event.type;
  }
}

function lineDiff(before, after) {
  const left = String(before ?? "").split("\n");
  const right = String(after ?? "").split("\n");
  const rows = left.length;
  const cols = right.length;
  const table = Array.from({length: rows + 1}, () => new Uint16Array(cols + 1));
  for (let i = rows - 1; i >= 0; i--) {
    for (let j = cols - 1; j >= 0; j--) {
      table[i][j] = left[i] === right[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const lines = [];
  let i = 0;
  let j = 0;
  while (i < rows && j < cols) {
    if (left[i] === right[j]) {
      lines.push({type: "same", text: left[i]});
      i++; j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      lines.push({type: "del", text: left[i++]});
    } else {
      lines.push({type: "add", text: right[j++]});
    }
  }
  while (i < rows) lines.push({type: "del", text: left[i++]});
  while (j < cols) lines.push({type: "add", text: right[j++]});
  return lines;
}

function laneOf(event) {
  if (event.data?.tool === "model.request") return 1;
  const kind = event.kind;
  if (kind === "user" || kind === "comment" || kind === "system") return 0;
  if (kind === "model" || kind === "patch") return 1;
  return 2;
}

function Timeline({events}) {
  const timed = events.filter(event => event.time && !Number.isNaN(Date.parse(event.time)));
  if (timed.length < 2) return null;
  const times = timed.map(event => Date.parse(event.time));
  const min = Math.min(...times);
  const max = Math.max(...times);
  const span = Math.max(max - min, 1000);
  // Remote history can span days; a duration strip would be meaningless.
  if (span > 6 * 60 * 60 * 1000) return null;
  return (
    <div className="trace-timeline" aria-hidden="true">
      <div className="trace-lane-label" style={{top: 2}}>用户 / 系统</div>
      <div className="trace-lane-label" style={{top: 16}}>模型</div>
      <div className="trace-lane-label" style={{top: 30}}>工具 / 远端</div>
      <div className="trace-lanes">
        {[4, 18, 32].map(top => <div className="trace-lane" key={top} style={{top}}/>)}
        {timed.map(event => {
          const start = Date.parse(event.time);
          const left = ((start - min) / span) * 100;
          const duration = Number(event.data?.durationMs);
          const width = Number.isFinite(duration) && duration > 0 ? Math.max((duration / span) * 100, 0.35) : 0.35;
          return (
            <span
              key={event.id}
              className={`trace-span trace-span-${laneOf(event)}${event.kind === "error" ? " error" : ""}`}
              style={{left: `${left}%`, width: `${Math.min(width, 100 - left)}%`, top: laneOf(event) * 14}}
              title={`${fmtTime(event.time)} · ${eventSummary(event)}`}
            />
          );
        })}
      </div>
    </div>
  );
}

function PatchView({patch}) {
  const lines = useMemo(() => (patch ? lineDiff(patch.before, patch.after) : []), [patch]);
  if (!patch) return null;
  const added = lines.filter(line => line.type === "add").length;
  const removed = lines.filter(line => line.type === "del").length;
  return (
    <div className="trace-patch">
      <div className="trace-patch-head">
        <code>{patch.file}</code>
        <span className="trace-diff-stat"><b>+{added}</b> <i>−{removed}</i></span>
        <span>{patch.commentIds?.length ? `关联 ${patch.commentIds.length} 条批注` : "未关联批注"}</span>
      </div>
      {patch.reason && <p className="trace-patch-reason">{patch.reason}</p>}
      <div className="trace-diff">
        <div className="trace-diff-label">差异{patch.trimmed ? "（截取变更附近）" : ""}</div>
        <pre className="trace-diff-lines">
          {lines.map((line, index) => (
            <div className={`trace-line ${line.type}`} key={index}>
              <span className="trace-sign">{line.type === "add" ? "+" : line.type === "del" ? "−" : " "}</span>
              {line.text || " "}
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}

function Inspector({event, onClose}) {
  const [tab, setTab] = useState("overview");
  useEffect(() => setTab("overview"), [event?.id]);
  if (!event) return (
    <aside className="trace-inspector empty">
      <div className="trace-inspector-empty">
        <Activity size={22} strokeWidth={1.4}/>
        <strong>选择一条记录</strong>
        <p>查看模型、用量、耗时、补丁与原始事件。</p>
      </div>
    </aside>
  );
  const data = event.data || {};
  const usage = data.usage || null;
  return (
    <aside className="trace-inspector">
      <header className="trace-insp-head">
        <span className={`trace-kind ${event.kind}`}>{KIND_LABEL[event.kind] || event.kind}</span>
        <strong>{eventSummary(event).slice(0, 48)}</strong>
        <button className="trace-icon" onClick={onClose} aria-label="关闭检视器"><X size={14}/></button>
      </header>
      <div className="trace-insp-tabs">
        <button className={tab === "overview" ? "active" : ""} onClick={() => setTab("overview")}>概览</button>
        <button className={tab === "raw" ? "active" : ""} onClick={() => setTab("raw")}>原始</button>
      </div>
      <div className="trace-insp-body">
        {tab === "raw" ? (
          <pre className="trace-json">{JSON.stringify(event, null, 2)}</pre>
        ) : (
          <>
            <dl className="trace-kv">
              <dt>类型</dt><dd><code>{event.type}</code></dd>
              <dt>时间</dt><dd>{fmtTime(event.time)}</dd>
              <dt>轮次</dt><dd>{event.turn == null ? "远端" : `第 ${event.turn} 轮`}</dd>
              {Number(event.data?.durationMs) > 0 && <><dt>耗时</dt><dd>{fmtDuration(event.data.durationMs)}</dd></>}
              {event.actor && event.actor.kind !== "remote" && <><dt>发起</dt><dd>{event.actor.name}</dd></>}
              {(data.model?.id || data.model?.name) && <><dt>模型</dt><dd>{data.model.name || data.model.id}</dd></>}
              {usage && <>
                <dt>输入</dt><dd>{fmtTokens(usage.input)} tokens</dd>
                <dt>输出</dt><dd>{fmtTokens(usage.output)} tokens</dd>
                <dt>费用</dt><dd>{fmtCost(usage.cost)}</dd>
              </>}
              {data.gitCommit && <><dt>Git</dt><dd><code>{shortId(data.gitCommit, 10)}</code></dd></>}
              {data.revision && <><dt>版本</dt><dd><code>{shortId(data.revision, 10)}</code></dd></>}
              {data.remoteCommit && <><dt>远端提交</dt><dd><code>{shortId(data.remoteCommit, 10)}</code></dd></>}
            </dl>
            {data.stage && (
              <div className="trace-stage-detail">
                <dl className="trace-kv">
                  <dt>阶段</dt><dd>{data.stage.role}</dd>
                  <dt>模型</dt><dd>{data.stage.vendor || data.stage.provider} · {data.stage.model}</dd>
                  <dt>补丁</dt><dd>{data.stage.patchCount}</dd>
                  <dt>发现</dt><dd>{data.stage.findingCount}</dd>
                </dl>
                {data.stage.summary && <p>{data.stage.summary}</p>}
                {data.stage.coverage && <p className="trace-note">覆盖：{data.stage.coverage}</p>}
                <p className="trace-note">阶段摘要由模型输出，不是隐藏思维链。</p>
              </div>
            )}
            {data.patch && <PatchView patch={data.patch}/>}
            {event.type === "overleaf/flush" && (
              <div className="trace-remote-detail">
                <dl className="trace-kv">
                  <dt>作者</dt><dd>{data.author}</dd>
                  <dt>版本时间</dt><dd>{fmtTime(data.authorTime)}</dd>
                  <dt>补造时间</dt><dd>{fmtTime(data.commitTime)}</dd>
                  <dt>改动</dt><dd>{data.files ?? "?"} 个文件 · +{data.insertions ?? 0} / −{data.deletions ?? 0}</dd>
                  <dt>粒度</dt><dd>版本级</dd>
                </dl>
                <p className="trace-note">{data.note}</p>
              </div>
            )}
            {data.summary && <p className="trace-note">{data.summary}</p>}
            {data.message && event.kind === "error" && <p className="trace-error-text">{data.message}</p>}
          </>
        )}
      </div>
    </aside>
  );
}

function TurnProcess({events, onSelect}) {
  const rows = events.filter(event => ["tool/result", "revision/created", "overleaf/push", "error"].includes(event.type));
  return (
    <div className="trace-process">
      {rows.map(event => (
        <button className={`trace-prow${event.kind === "error" ? " error" : ""}`} key={event.id} onClick={() => onSelect(event)}>
          <span className="trace-pico">
            {event.data?.stage ? <Sparkles size={12}/> : event.type === "tool/result" ? <Activity size={12}/> : event.type === "revision/created" ? <Check size={12}/> : event.type === "overleaf/push" ? <Cloud size={12}/> : <AlertCircle size={12}/>}
          </span>
          <span className="trace-ptext">{eventSummary(event)}</span>
          <span className="trace-pdur">{Number.isFinite(event.data?.durationMs) ? fmtDuration(event.data.durationMs) : ""}</span>
        </button>
      ))}
    </div>
  );
}

function StageChain({collaboration}) {
  const stages = collaboration?.stages || [];
  if (stages.length < 2) return null;
  return (
    <div className="trace-stages">
      <div className="trace-stages-head">阶段链路 · {stages.length} 个模型</div>
      {stages.map((stage, index) => (
        <details className="trace-stage" key={`${stage.role}-${index}`} open={index === 0}>
          <summary>
            <span>{index + 1}. {stage.role}</span>
            <span className="trace-stage-model">{stage.vendor || stage.provider} · {stage.model}</span>
            <span className="trace-stage-count">+{stage.patchCount} 补丁</span>
          </summary>
          {stage.summary && <p>{stage.summary}</p>}
          {stage.coverage && <p className="trace-note">覆盖：{stage.coverage}</p>}
        </details>
      ))}
      <p className="trace-note">阶段摘要由模型输出，不是隐藏思维链。</p>
    </div>
  );
}

function TurnCard({turn, events, open, onToggle, onSelect}) {
  return (
    <article className="trace-turn">
      <div className="trace-turn-meta">
        <b>第 {turn.index} 轮</b>
        <span>{fmtTime(turn.startedAt)}</span>
        <span>{turn.actor?.name || "本机使用者"}</span>
        {turn.baseRevision && <span>基于 {shortId(turn.baseRevision)}</span>}
      </div>
      <div className="trace-user-row">
        <div className="trace-bubble">
          {turn.instruction || "处理本轮批注"}
          {turn.comments.length > 0 && (
            <div className="trace-chips">
              {turn.comments.map(comment => (
                <span className="trace-chip" key={comment.id} title={comment.quote || comment.body}>
                  #{shortId(comment.id, 4)} · {String(comment.body || "").slice(0, 18)}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="trace-user-meta">
          <span>{fmtTime(turn.startedAt)}</span>
          <span>只读回放</span>
        </div>
      </div>
      <button className="trace-fold" aria-expanded={open} onClick={onToggle}>
        <span className={`trace-caret${open ? "" : " closed"}`}><ChevronDown size={14}/></span>
        <span>{STATUS_LABEL[turn.status] || turn.status}{turn.durationMs ? ` in ${fmtDuration(turn.durationMs)}` : ""}</span>
        <span className="trace-fold-counts">
          {events.filter(event => ["tool/result", "revision/created", "overleaf/push", "error"].includes(event.type)).length} 步 · {turn.comments.length} 条批注 · {turn.patches.length} 处修改
        </span>
      </button>
      {open && <TurnProcess events={events} onSelect={onSelect}/>}
      {open && <StageChain collaboration={turn.collaboration}/>}
      {turn.summary && <p className="trace-answer">{turn.summary}</p>}
      {turn.error && <p className="trace-error-text">{turn.error}</p>}
      {turn.patches.map((patch, index) => <PatchView key={index} patch={patch}/>)}
      {turn.usage && (
        <div className="trace-turn-foot">
          <span>输入 {fmtTokens(turn.usage.input)} · 输出 {fmtTokens(turn.usage.output)} tokens</span>
          <span>{fmtCost(turn.usage.cost)}</span>
          {turn.revision && <span>版本 {shortId(turn.revision)}</span>}
          <span className="spacer"/>
          <span>{fmtTime(turn.endedAt)}</span>
        </div>
      )}
    </article>
  );
}

function RemoteCard({commits, onSelect}) {
  if (!commits.length) return null;
  return (
    <article className="trace-turn trace-remote-card">
      <div className="trace-turn-meta"><b>Overleaf 远端</b><span>{commits.length} 个版本</span><span>只读</span></div>
      <p className="trace-note">
        远端 commit 是按需补造的：版本时间来自 Overleaf，提交时间来自 Git 桥。一次提交只保留窗口内最后编辑者。
      </p>
      <div className="trace-process">
        {commits.map(event => (
          <button className="trace-prow" key={event.id} onClick={() => onSelect(event)}>
            <span className="trace-pico"><Cloud size={12}/></span>
            <span className="trace-ptext">
              {shortId(event.data.commit, 7)} · {event.data.author} · {event.data.files ?? "?"} 个文件 · +{event.data.insertions ?? 0} / −{event.data.deletions ?? 0}
            </span>
            <span className="trace-pdur">{fmtTime(event.time)}</span>
          </button>
        ))}
      </div>
    </article>
  );
}

export function TraceView({projectId, api, onClose}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("chat");
  const [openTurns, setOpenTurns] = useState(() => new Set());
  const [selectedId, setSelectedId] = useState(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, []);

  useEffect(() => {
    const onKey = event => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const list = await api(`/projects/${projectId}/traces`);
        const trace = list.traces?.[0];
        if (!trace) {
          if (alive) setData({turns: [], events: [], remote: []});
          return;
        }
        const detail = await api(`/projects/${projectId}/traces/${trace.id}`);
        if (!alive) return;
        setData(detail);
        const latest = detail.turns?.at(-1);
        setOpenTurns(new Set(latest ? [latest.index] : []));
      } catch (reason) {
        if (alive) setError(reason.message || "无法读取过程记录");
      }
    })();
    return () => { alive = false; };
  }, [api, projectId]);

  const events = data?.events || [];
  const selected = useMemo(() => events.find(event => event.id === selectedId) || null, [events, selectedId]);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const visible = needle
      ? events.filter(event => JSON.stringify(event).toLowerCase().includes(needle))
      : events;
    const grouped = [];
    let currentTurn = undefined;
    for (const event of visible.filter(item => item.turn != null)) {
      if (event.turn !== currentTurn) {
        currentTurn = event.turn;
        grouped.push({type: "turn", turn: event.turn, id: `turn-head-${event.turn}`});
      }
      grouped.push({type: "event", event, id: event.id});
    }
    const remote = visible.filter(item => item.turn == null);
    if (remote.length) {
      grouped.push({type: "turn", turn: null, id: "remote-head"});
      remote.forEach(event => grouped.push({type: "event", event, id: event.id}));
    }
    return grouped;
  }, [events, query]);

  const select = event => {
    setSelectedId(event.id);
    setTab("trajectory");
  };

  const toggleTurn = index => {
    setOpenTurns(previous => {
      const next = new Set(previous);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  return (
    <div className="trace-overlay" role="dialog" aria-modal="true" aria-label="对话与轨迹">
      <div className="trace-shell">
        <header className="trace-top">
          <div className="trace-title">
            <Activity size={16}/>
            <strong>对话与轨迹</strong>
            <span className="trace-sub">{data?.title || "当前项目"}</span>
            <span className="trace-badge">只读回放</span>
          </div>
          <div className="trace-viewtabs" role="tablist">
            <button role="tab" aria-selected={tab === "chat"} className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")}>
              <MessageSquare size={14}/> 对话
            </button>
            <button role="tab" aria-selected={tab === "trajectory"} className={tab === "trajectory" ? "active" : ""} onClick={() => setTab("trajectory")}>
              <GitCompareArrows size={14}/> 轨迹
            </button>
          </div>
          <button className="trace-close" onClick={onClose} aria-label="关闭"><X size={16}/></button>
        </header>

        {error ? (
          <div className="trace-state error">
            <AlertCircle size={22}/>
            <strong>读取失败</strong>
            <p>{error}</p>
            <button className="trace-retry" onClick={() => window.location.reload()}>重新加载</button>
          </div>
        ) : !data ? (
          <div className="trace-state"><LoaderCircle size={22} className="spin"/><p>正在整理本轮记录…</p></div>
        ) : !data.turns?.length && !data.remote?.length ? (
          <div className="trace-state">
            <Activity size={22} strokeWidth={1.4}/>
            <strong>还没有可回放的过程</strong>
            <p>提交第一条批注后，这里会出现本次修订的对话与步骤。</p>
          </div>
        ) : tab === "chat" ? (
          <div className="trace-chat">
            <div className="trace-chat-col">
              {(data.turns || []).map(turn => (
                <TurnCard
                  key={turn.id}
                  turn={turn}
                  events={events.filter(event => event.turn === turn.index)}
                  open={openTurns.has(turn.index)}
                  onToggle={() => toggleTurn(turn.index)}
                  onSelect={select}
                />
              ))}
              <RemoteCard commits={data.remote || []} onSelect={select}/>
            </div>
          </div>
        ) : (
          <div className="trace-trajectory">
            <div className="trace-traj-main">
              <div className="trace-toolbar">
                <div className="trace-search">
                  <Search size={13}/>
                  <input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索记录、文件或模型…" aria-label="搜索轨迹"/>
                </div>
                <span className="trace-count">{rows.filter(row => row.type === "event").length} 条记录</span>
                <span className="spacer"/>
                <span className="trace-hint">点击记录查看详情</span>
              </div>
              <Timeline events={events}/>
              <div className="trace-table-wrap">
                <table className="trace-table">
                  <thead><tr><th className="trace-ev">事件</th><th>内容</th><th className="trace-when">时间</th></tr></thead>
                  <tbody>
                    {rows.map(row => row.type === "turn" ? (
                      <tr className="trace-turn-row" key={row.id}>
                        <td className="trace-ev">
                          <span className={`trace-turn-tab${row.turn == null ? " remote" : ""}`}/>
                          <span className="trace-turnno">{row.turn == null ? "远端" : `第 ${row.turn} 轮`}</span>
                        </td>
                        <td colSpan={2}>{row.turn == null ? "Overleaf 版本（按需补造）" : ""}</td>
                      </tr>
                    ) : (
                      <tr
                        key={row.id}
                        className={`trace-row${selectedId === row.event.id ? " selected" : ""}${row.event.kind === "error" ? " error" : ""}`}
                        onClick={() => setSelectedId(row.event.id)}
                        tabIndex={0}
                        onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedId(row.event.id); } }}
                      >
                        <td className="trace-ev">
                          {row.event.type === "tool/result" && row.event.data?.tool === "model.request" && <span className="trace-reqdot"/>}
                          <span className={`trace-kind ${row.event.kind}`}>{KIND_LABEL[row.event.kind] || row.event.kind}</span>
                          {row.event.type === "turn/start" && row.event.turn != null && <span className="trace-turnno small">第 {row.event.turn} 轮</span>}
                        </td>
                        <td className="trace-summary">{eventSummary(row.event)}</td>
                        <td className="trace-when">
                          {fmtTime(row.event.time)}
                          {Number(row.event.data?.durationMs) > 0 && <span className="trace-dur">{fmtDuration(row.event.data.durationMs)}</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <Inspector event={selected} onClose={() => setSelectedId(null)}/>
          </div>
        )}
      </div>
    </div>
  );
}
