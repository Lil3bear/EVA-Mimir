import React, {useEffect, useState} from "react";
import {AlertCircle, Check, Layers, Play, RefreshCw} from "lucide-react";

const severityLabel = {critical: "必须修", major: "建议修", minor: "文字优化"};
const certaintyLabel = {confirmed: "已确认", conditional: "有条件", unverified: "待核验"};

export function SectionPanel({project, api, activity, onStarted}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState([]);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const base = `/projects/${project.id}/sections`;
  const active = activity && ["queued", "running", "cancelling"].includes(activity.status);

  const load = async () => {
    const next = await api(base);
    setData(next);
    setSelected(next.sections.map(section => section.id));
  };
  useEffect(() => {
    let stopped = false;
    setData(null);
    setError("");
    setConsent(false);
    api(base).then(next => {
      if (stopped) return;
      setData(next);
      setSelected(next.sections.map(section => section.id));
    }).catch(reason => { if (!stopped) setError(reason.message); });
    return () => { stopped = true; };
  }, [project.id, project.revision]);
  useEffect(() => {
    if (activity && !active) load().catch(reason => setError(reason.message));
  }, [activity?.id, activity?.status]);

  const choose = ids => { setSelected(ids); setConsent(false); };
  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api(`${base}/review`, {
        method: "POST",
        body: { revision: project.revision, sectionIds: selected, consent },
      });
      onStarted(result.job);
      await load();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  const latest = data?.latest;
  const results = new Map((latest?.results || []).map(result => [result.section, result]));
  return (
    <div className="section-panel">
      <div className="section-label"><span><Layers size={14}/> 章节对齐</span>
        <button title="刷新" aria-label="刷新章节" disabled={busy} onClick={() => load().catch(reason => setError(reason.message))}><RefreshCw size={15}/></button>
      </div>
      {error && <p role="alert" className="inline-error">{error}</p>}
      {!data ? <p role="status">正在读取章节…</p> : <>
        <p className="section-hint">
          {data.sections.length} 个章节 · {data.provider} {data.model} · 每个章节由独立 sub-agent 按自己的 skill 检查对齐
        </p>
        <div className="section-actions">
          <button type="button" onClick={() => choose(data.sections.map(section => section.id))}>全选</button>
          <button type="button" onClick={() => choose([])}>清空</button>
        </div>
        <div className="section-list">
          {data.sections.map(section => (
            <label className={`section-item${results.has(section.id) ? " done" : ""}`} key={section.id}>
              <input type="checkbox" checked={selected.includes(section.id)} onChange={event => choose(event.target.checked ? [...selected, section.id] : selected.filter(id => id !== section.id))}/>
              <span>
                <strong>{section.title}</strong>
                <small>{section.files.join(" · ")} · {section.chars.toLocaleString("zh-CN")} 字符</small>
              </span>
              {results.has(section.id) && <Check size={14}/>}
            </label>
          ))}
        </div>
        <label className="consent"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)}/>
          同意将全文与本轮章节选择发送至 {data.provider} {data.model}
        </label>
        <button className="primary" disabled={busy || active || !consent || !selected.length || !data.enabled} onClick={run}>
          <Play size={15}/>{active ? "章节对齐运行中…" : `运行 ${selected.length} 个章节`}
        </button>
        {!data.enabled && <p className="warning-text">尚未配置模型，无法运行章节对齐。</p>}
        {latest && <div className="section-latest">
          <div className="section-label"><span>
            {latest.status === "running" ? "最新一轮运行中" : latest.status === "failed" ? "最新一轮失败" : "最新一轮结果"}
          </span><small>{new Date(latest.created).toLocaleString("zh-CN")} · {latest.model}</small></div>
          {latest.error && <p className="warning-text">{latest.error}</p>}
          {[...results.values()].map(result => {
            const section = data.sections.find(item => item.id === result.section);
            return <article className="section-result" key={result.section}>
              <header><strong>{section?.title || result.section}</strong><span>{result.findings.length} 条</span></header>
              <p>{result.alignment}</p>
              {result.summary && <p className="muted">{result.summary}</p>}
              {result.findings.map((finding, index) => <div className="section-finding" key={index}>
                <div className="section-finding-head">
                  <span className={`severity ${finding.severity}`}>{severityLabel[finding.severity] || finding.severity}</span>
                  <strong>{finding.title}</strong>
                  <span className="muted">{certaintyLabel[finding.certainty] || finding.certainty}{finding.anchored === false ? " · 原文未定位" : ""}</span>
                </div>
                <p>{finding.body}</p>
                {finding.quote && <blockquote>{finding.quote}</blockquote>}
                {finding.suggestion && <p className="muted">建议：{finding.suggestion}</p>}
                <small>{finding.file}{finding.relatedSection ? ` · 关联 ${finding.relatedSection}` : ""}</small>
              </div>)}
              {result.crossRefs?.length > 0 && <div className="section-cross">
                <strong>跨章节</strong>
                {result.crossRefs.map((ref, index) => <p key={index}><code>{ref.from} → {ref.to}</code> {ref.issue}</p>)}
              </div>}
              {result.blockers?.length > 0 && <div className="section-blockers">
                {result.blockers.map((blocker, index) => <p key={index}><AlertCircle size={12}/> {blocker}</p>)}
              </div>}
            </article>;
          })}
          {latest.status === "running" && <p className="muted">{activity?.message || "正在运行章节 sub-agent…"}</p>}
        </div>}
      </>}
    </div>
  );
}
