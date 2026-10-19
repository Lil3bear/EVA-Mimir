import React, { useEffect, useRef, useState } from "react";
import { BookOpen, MessageCircle, ArrowUpRight, ChevronRight, LoaderCircle, Square, Send, Plus, AlertCircle } from "lucide-react";

const active = job => ["queued", "running", "cancelling"].includes(job?.status);
const stamp = value => new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
export default function ReadingPanel({ paper, meta, selection, request, beforeRun, onPaper, locate }) {
  const [state, setState] = useState({ records: [], job: null }), [selectedId, setSelectedId] = useState(null), [mode, setMode] = useState("guide");
  const [quote, setQuote] = useState(""), [quotePage, setQuotePage] = useState(null), [question, setQuestion] = useState(""), [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false), [error, setError] = useState(""), [ready, setReady] = useState(false);
  const live = useRef(true), answer = useRef(), selectionRef = useRef(selection);
  selectionRef.current = selection;
  const url = `/api/reviewer/papers/${paper.id}/readings`;
  const selected = state.records.find(r => r.id === selectedId), busy = active(state.job) || pending;
  useEffect(() => {
    live.current = true;
    request(url).then(data => {
      if (!live.current) return;
      data.records = data.records.filter(r => r.mode !== "organize");
      setState(data); setReady(true);
      if (!selectionRef.current && data.records.length) { setSelectedId(data.records[0].id); setMode(data.records[0].mode); setQuote(data.records[0].quote); setQuotePage(data.records[0].page); }
    }).catch(e => { if (live.current) { setError(e.message); setReady(true); } });
    return () => { live.current = false; };
  }, [paper.id]);
  useEffect(() => {
    if (!selection) return;
    setMode("explain"); setSelectedId(null); setQuote(selection.quote); setQuotePage(selection.page); setQuestion(""); setError("");
  }, [selection]);
  useEffect(() => {
    if (!active(state.job)) return;
    const timer = setInterval(() => request(url).then(data => { if (live.current) setState({ ...data, records: data.records.filter(r => r.mode !== "organize") }); }).catch(e => { if (live.current) setError(e.message); }), 2000);
    return () => clearInterval(timer);
  }, [state.job?.status, paper.id]);
  useEffect(() => { if (selected?.status === "completed") answer.current?.scrollIntoView({ block: "nearest" }); }, [selected?.status, selectedId]);
  async function start(e) {
    e.preventDefault(); setError(""); setPending(true);
    try {
      if (!(await beforeRun())) return;
      const parentId = selected?.status === "completed" ? selected.id : null;
      const fallback = mode === "guide" ? "用中文带我读懂这篇论文：问题是什么、方法怎么做、实验说明了什么，建议先看哪些页。" : "请用白话解释这段原文，拆开关键词，并举一个容易理解的例子。";
      const data = await request(url, { method: "POST", body: { mode, page: mode === "explain" ? quotePage : null, quote: mode === "explain" ? quote : "", question: question.trim() || fallback, parentId, consent } });
      if (!live.current) return;
      onPaper(data.paper); setState(s => ({ records: [data.record, ...s.records], job: data.job })); setSelectedId(data.record.id); setQuestion("");
    } catch (e) { if (live.current) setError(e.message); }
    finally { if (live.current) setPending(false); }
  }
  function chooseMode(value) { setMode(value); setSelectedId(null); setQuestion(""); setError(""); }
  return <>
    <div className="r-panel-heading"><div><h2>{mode === "guide" ? "AI 导读" : "AI 白话"}</h2><p>{mode === "guide" ? "问题 → 方法 → 实验 → 阅读顺序" : "这句话是什么意思，放在文中怎么理解"}</p></div><button className="r-icon" title="开始新提问" aria-label="开始新提问" onClick={() => chooseMode(mode)}><Plus size={17}/></button></div>
    <div className="r-reading-modes"><button className={mode === "guide" ? "selected" : ""} onClick={() => chooseMode("guide")}><BookOpen size={14}/>整篇导读</button><button className={mode === "explain" ? "selected" : ""} onClick={() => chooseMode("explain")}><MessageCircle size={14}/>选段白话</button></div>
    <div className="r-panel-scroll r-reading-scroll">
      {state.records.length > 0 && <label className="r-reading-history-label">阅读记录<select aria-label="阅读记录" value={selectedId || ""} onChange={e => {
        const r = state.records.find(r => r.id === e.target.value); setSelectedId(r?.id || null);
        if (r) { setMode(r.mode); setQuote(r.quote); setQuotePage(r.page); } setQuestion(""); setError("");
      }}><option value="">新提问</option>{state.records.map(r => <option key={r.id} value={r.id}>{stamp(r.time)} · {r.mode === "guide" ? "导读" : "白话"} · {r.status === "completed" ? r.question.slice(0, 32) : r.status}</option>)}</select></label>}
      {mode === "explain" && quote && <button className="r-quote" onClick={() => locate({ page: quotePage, quote })}><span>第 {quotePage} 页 · 待解释的原文</span><q>{quote}</q></button>}
      {mode === "explain" && !quote && <div className="r-panel-empty"><MessageCircle size={26}/><h3>选中不理解的原文</h3><p>PDF 划选浮窗中的「AI 白话」</p></div>}
      {error && <div className="r-reading-error" role="alert"><AlertCircle size={15}/>{error}</div>}
      {selected?.error && <div className="r-reading-error" role="alert">{selected.error}</div>}
      {active(state.job) && <div className="r-reading-progress" role="status"><LoaderCircle size={16} className="r-spin"/><span>{state.job.message}</span><button className="r-icon" title="停止导读或解释" aria-label="停止导读或解释" onClick={async () => {
        try { const data = await request(`${url}/cancel`, { method: "POST", body: {} }); if (live.current) { setState(s => ({ ...s, job: data.job })); setState(await request(url)); } }
        catch (e) { if (live.current) setError(e.message); }
      }}><Square size={14}/></button></div>}
      {!ready && <p className="r-muted">正在读取阅读记录…</p>}
      {selected?.result && <article ref={answer} className="r-reading-response">
        <div className="r-reading-question"><MessageCircle size={13}/><span>{selected.question}</span></div>
        <div className="r-reading-answer">{selected.result.answer}</div>
        {selected.result.references.length > 0 && <div className="r-reading-references"><h3>回到原文</h3>{selected.result.references.map((r, i) => <button key={i} title={r.quote} onClick={() => locate({ ...r, id: `${selected.id}-${i}` })}><span>p. {r.page}</span><q>{r.quote}</q><small>{r.anchored ? "已定位" : "待核对"}</small><ArrowUpRight size={13}/></button>)}</div>}
        <details className="r-reading-coverage"><summary>阅读边界与模型</summary><p>{selected.result.coverage}</p><small>{selected.model} · {stamp(selected.time)} · 最近 {selected.contextTurns} 轮上下文</small></details>
        <div className="r-reading-followups">{["再白话一点，尽量不用术语", "举一个具体例子", ...selected.result.followUps].slice(0, 6).map(q => <button key={q} onClick={() => setQuestion(q)}>{q}<ChevronRight size={12}/></button>)}</div>
      </article>}
      {ready && mode === "guide" && !selected && !busy && <div className="r-panel-empty r-reading-empty"><BookOpen size={29} strokeWidth={1.3}/><h3>先把论文读懂</h3><p>{paper.pages.length} 页 · {paper.venue}</p></div>}
    </div>
    <form className="r-reading-composer" onSubmit={start}>
      <textarea aria-label="导读或白话问题" rows={3} maxLength={3000} value={question} onChange={e => setQuestion(e.target.value)} placeholder={selected?.result ? "还有哪里没听懂？可以继续追问…" : mode === "guide" ? "例如：这篇文章到底在解决什么问题？" : "例如：这段话里的术语是什么意思？"}/>
      <p className="r-reading-disclosure">全文文本、选文与最近 6 轮对话发送至{meta?.provider === "codex" ? " Codex 云端" : "配置的模型服务"}，使用账户额度。结果仅供理解，不覆盖审稿意见。需封存独立评估时，请先完成人工记录。</p>
      <label className="r-check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/><span>同意云端辅助阅读并保存 AI 使用记录</span></label>
      <button className="r-primary r-full" disabled={!ready || busy || !meta?.ai || !consent || (mode === "explain" && !quote)}><Send size={14}/>{busy ? "正在解释…" : selected?.result ? "继续追问" : mode === "guide" ? "生成 AI 导读" : "用白话解释"}</button>
    </form>
  </>;
}
