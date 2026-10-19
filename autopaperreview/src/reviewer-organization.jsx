import React, { useEffect, useState } from "react";
import { Sparkles, Save, Copy, Square, LoaderCircle, CornerDownRight } from "lucide-react";

const active = job => ["queued", "running", "cancelling"].includes(job?.status);
export default function OrganizationPanel({ paper, meta, value, change, request, beforeRun, onPaper, save, saving, dirty }) {
  const [state, setState] = useState({ records: [], job: null }), [consent, setConsent] = useState(false);
  const [error, setError] = useState(""), [pending, setPending] = useState(false), [ready, setReady] = useState(false), [copied, setCopied] = useState(false);
  const url = `/api/reviewer/papers/${paper.id}/readings`;
  const records = state.records.filter(r => r.mode === "organize");
  const latest = records[0], busy = active(state.job) || pending;
  useEffect(() => {
    let live = true;
    async function refresh() {
      try { const data = await request(url); if (live) { setState(data); setReady(true); } }
      catch (e) { if (live) { setError(e.message); setReady(true); } }
    }
    refresh();
    const timer = setInterval(refresh, 2500);
    return () => { live = false; clearInterval(timer); };
  }, [paper.id]);
  async function generate() {
    setPending(true); setError("");
    try {
      if (!(await beforeRun())) return;
      const data = await request(url, { method: "POST", body: { mode: "organize", question: "根据我的人工批注和已采纳意见，核对论文后按 ICLR 2027 Official Review 全部字段整理英文草稿。评分标为建议，Confidence 和人工 AI 披露由本人确认。", consent } });
      onPaper(data.paper); setState(s => ({ records: [data.record, ...s.records], job: data.job }));
    } catch (e) { setError(e.message); }
    finally { setPending(false); }
  }
  return <>
    <div className="r-panel-heading"><div><h2>AI 整理</h2><p>Official Review · 未提交 OpenReview</p></div><button className="r-icon" title="保存 AI 整理" aria-label="保存 AI 整理" disabled={saving || !dirty} onClick={save}><Save size={17}/></button></div>
    <div className="r-panel-scroll r-form r-organization">
      <div className="r-form-policy">AI 辅助草稿；评分和 AI 使用披露须由本人确认。</div>
      <div className="r-organization-actions"><button className="r-secondary" onClick={async () => {
        try { await navigator.clipboard.writeText(value || ""); setCopied(true); } catch (e) { setError(e.message); }
      }} disabled={!value}><Copy size={14}/>{copied ? "已复制" : "复制全文"}</button><span className="r-muted">{saving ? "保存中" : dirty ? "待保存" : "已保存"}</span></div>
      <label className="r-form-field"><span>New Official Review</span><textarea className="r-organization-editor" aria-label="AI 整理草稿" value={value || ""} onChange={e => { change(e.target.value); setCopied(false); }} maxLength={60000} rows={32}/></label>
      {error && <div className="r-reading-error" role="alert">{error}</div>}
      {latest?.error && <div className="r-reading-error" role="alert">{latest.error}</div>}
      {active(state.job) && <div className="r-reading-progress" role="status"><LoaderCircle size={15} className="r-spin"/><span>{state.job.message}</span><button className="r-icon" aria-label="停止 AI 整理" title="停止当前任务" onClick={async () => {
        try { await request(`${url}/cancel`, { method: "POST", body: {} }); setState(await request(url)); } catch (e) { setError(e.message); }
      }}><Square size={14}/></button></div>}
      {latest?.result && <details className="r-summary"><summary>最近生成结果 · {new Date(latest.time).toLocaleString("zh-CN")}</summary><pre className="r-organization-preview">{latest.result.answer}</pre><button className="r-secondary" onClick={() => {
        if (value?.trim() && !window.confirm("用这次生成结果替换当前整理草稿？已保存的旧稿保留在历史快照中。")) return;
        change(latest.result.answer);
      }}><CornerDownRight size={14}/>采用为编辑草稿</button><p className="r-muted">{latest.result.coverage}</p></details>}
    </div>
    <div className="r-reading-composer"><label className="r-check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/><span>同意将全文、批注及草稿发送至模型服务并保存交互记录</span></label><button className="r-primary r-full" disabled={!ready || busy || !consent || !meta?.ai} onClick={generate}><Sparkles size={14}/>{busy ? "生成中…" : "根据审稿记录整理"}</button></div>
  </>;
}
