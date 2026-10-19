import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as pdfjs from "pdfjs-dist";
import worker from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { BookOpen, Upload, Search, FileText, ChevronLeft, ChevronRight, Plus, X, Check, Sparkles, MessageSquare,
  ClipboardCheck, History, Download, Settings2, ArrowUpRight, PanelLeftClose, PanelLeftOpen, ZoomIn, ZoomOut,
  LoaderCircle, AlertCircle, CircleCheck, ShieldCheck, Ban, Square, Save, ExternalLink, Languages, Copy, RotateCcw, CornerDownRight, MessageCircle } from "lucide-react";
import ReadingPanel from "./reviewer-reading.jsx";
import OrganizationPanel from "./reviewer-organization.jsx";
import { createTranslationClient } from "./translation-client.mjs";
import { placeReaderPopup } from "./reader-popup.mjs";
import {loadPDF,pdfErrorMessage} from "./pdf-load.mjs";
import "pdfjs-dist/web/pdf_viewer.css";
import "./reviewer.css";

pdfjs.GlobalWorkerOptions.workerSrc = worker;
document.title = "Redline · ICLR 审稿工作台";
const base = "/api/reviewer";
const labels = { summary: "Summary", strengths: "Strengths", weaknesses: "Weaknesses", questions: "Questions", limitations: "Limitations", ethics: "Ethical Concerns", justification: "Rating Justification" };
const cn = { summary: "论文概述", strengths: "主要优点", weaknesses: "主要问题", questions: "给作者的问题", limitations: "局限性", ethics: "伦理问题", justification: "评分理由" };
const categories = { claims: "论断与证据", experiments: "实验设计", logic: "逻辑与理论", evaluation: "评价有效性", novelty: "贡献与新颖性" };
const severities = { critical: "关键问题", major: "主要问题", moderate: "需澄清" };
const certainties = { confirmed: "原文可确认", conditional: "有条件的疑虑", unverified: "待核验" };
const stamp = value => new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
const norm = s => s.normalize("NFKC").replace(/\s+/g, "").toLowerCase();
async function api(url, options = {}) {
  const response = await fetch(url, { ...options, headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    body: options.body instanceof FormData ? options.body : options.body ? JSON.stringify(options.body) : undefined });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}
function Icon({ icon: Component, label, ...props }) {
  return <button type="button" className="r-icon" title={label} aria-label={label} {...props}><Component size={17}/></button>;
}
function Modal({ title, close, children, wide = false }) {
  const ref = useRef();
  useEffect(() => {
    const previous = document.activeElement;
    ref.current?.focus();
    const key = e => {
      if (e.key === "Escape") close();
      if (e.key !== "Tab") return;
      const nodes = [...ref.current.querySelectorAll("button:not(:disabled),input:not(:disabled),select,textarea,a[href]")];
      const first = nodes[0], last = nodes.at(-1);
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("keydown", key); previous?.focus(); };
  }, []);
  return <div className="r-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) close(); }}><section ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className={`r-modal ${wide ? "wide" : ""}`}>
    <header><h2>{title}</h2><Icon icon={X} label="关闭" onClick={close}/></header>{children}
  </section></div>;
}
function Reader({ paper, page, setPage, target, onQuote }) {
  const [doc, setDoc] = useState(null), [error, setError] = useState(""), [zoom, setZoom] = useState(1), [width, setWidth] = useState(600), [rendering, setRendering] = useState(false);
  const holder = useRef(), surface = useRef(), canvas = useRef(), layer = useRef();
  const [reload,setReload]=useState(0),[loadingMessage,setLoadingMessage]=useState("正在加载 PDF");
  useEffect(() => {
    setDoc(null); setError("");setLoadingMessage("正在加载 PDF");
    const loading = loadPDF(pdfjs.getDocument,{ url: `${base}/papers/${paper.id}/pdf`, disableStream:true, disableAutoFetch:true, isEvalSupported: false },{onRetry:(n,total)=>setLoadingMessage(`正在重新加载 PDF（${n}/${total}）`)});
    let alive = true;
    loading.promise.then(d => { if (alive) setDoc(d); }).catch(e => { if (alive) setError(pdfErrorMessage(e)); });
    return () => { alive = false; loading.destroy(); };
  }, [paper.id,reload]);
  useEffect(() => {
    const observer = new ResizeObserver(entries => setWidth(Math.max(240, entries[0].contentRect.width - 48)));
    observer.observe(holder.current); return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!doc) return;
    let alive = true, task, textLayer;
    setRendering(true);
    (async () => {
      const p = await doc.getPage(page);
      if (!alive) return;
      const original = p.getViewport({ scale: 1 }), scale = width / original.width * zoom, viewport = p.getViewport({ scale });
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      surface.current.style.width = `${viewport.width}px`; surface.current.style.height = `${viewport.height}px`;
      surface.current.style.setProperty("--scale-factor", scale);
      canvas.current.width = Math.floor(viewport.width * ratio); canvas.current.height = Math.floor(viewport.height * ratio);
      canvas.current.style.width = `${viewport.width}px`; canvas.current.style.height = `${viewport.height}px`;
      task = p.render({ canvasContext: canvas.current.getContext("2d"), viewport, transform: [ratio, 0, 0, ratio, 0, 0] });
      await task.promise;
      if (!alive) return;
      layer.current.replaceChildren();
      textLayer = new pdfjs.TextLayer({ textContentSource: await p.getTextContent(), container: layer.current, viewport });
      await textLayer.render();
      if (!alive) return;
      if (target?.page === page && target.quote) {
        const spans = [...layer.current.querySelectorAll("span")].filter(s => s.textContent);
        const text = spans.map(s => norm(s.textContent)).join("");
        const needle = norm(target.quote), start = text.indexOf(needle);
        let cursor = 0;
        for (const span of spans) {
          const length = norm(span.textContent).length;
          if (start >= 0 && cursor < start + needle.length && cursor + length > start) span.classList.add("r-quote-highlight");
          cursor += length;
        }
        layer.current.querySelector(".r-quote-highlight")?.scrollIntoView({ block: "center", behavior: "smooth" });
      }
      setRendering(false);
    })().catch(e => { if (alive && e.name !== "RenderingCancelledException" && e.name !== "AbortException") { setError(pdfErrorMessage(e)); setRendering(false); } });
    return () => { alive = false; task?.cancel(); textLayer?.cancel(); };
  }, [doc, page, width, zoom, target]);
  return <section className="r-reader">
    <div className="r-reader-toolbar"><span><FileText size={15}/><span className="r-reader-filename" title={paper.filename}>{paper.filename}</span></span>
      <div className="r-page-control"><Icon icon={ChevronLeft} label="上一页" disabled={page <= 1} onClick={() => setPage(page - 1)}/>
        <select aria-label="PDF 页码" value={page} onChange={e => setPage(Number(e.target.value))}>{paper.pages.map(p => <option key={p.number} value={p.number}>{p.number} / {paper.pages.length}</option>)}</select>
        <Icon icon={ChevronRight} label="下一页" disabled={page >= paper.pages.length} onClick={() => setPage(page + 1)}/></div>
      <div className="r-zoom"><Icon icon={ZoomOut} label="缩小" disabled={zoom <= .6} onClick={() => setZoom(z => Math.max(.6, z - .15))}/><button className="r-zoom-value" title="适合页面宽度" onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button><Icon icon={ZoomIn} label="放大" disabled={zoom >= 2} onClick={() => setZoom(z => Math.min(2, z + .15))}/></div>
    </div>
    <div ref={holder} className="r-paper-scroll" onScroll={() => onQuote(null)} onMouseUp={() => {
      const selection = window.getSelection();
      if (selection?.toString().trim() && layer.current?.contains(selection.anchorNode) && layer.current?.contains(selection.focusNode)) {
        const rect = selection.getRangeAt(0).getBoundingClientRect();
        onQuote({ page, quote: selection.toString().trim().slice(0, 10000), anchor: { x: rect.left, top: rect.top, bottom: rect.bottom } });
      }
    }}>
      {error ? <div className="r-reader-error" role="alert"><AlertCircle/><p>{error}</p><Icon icon={RotateCcw} label="重新加载 PDF" onClick={()=>setReload(n=>n+1)}/><a href={`${base}/papers/${paper.id}/pdf`} target="_blank" rel="noreferrer">打开原 PDF</a></div> : <>
        {(!doc || rendering) && <span className="r-rendering" role="status"><LoaderCircle size={14} className="r-spin"/>{!doc?loadingMessage:"正在渲染"}</span>}
        <div ref={surface} className="r-pdf-surface"><canvas ref={canvas}/><div className="textLayer" ref={layer}/></div>
        <p className="r-page-footer">第 {page} 页，共 {paper.pages.length} 页<span>原始 PDF · SHA-256 {paper.hash.slice(0, 10)}</span></p>
      </>}
    </div>
  </section>;
}
function SelectionTranslation({ selection, client, meta, engine, setEngine, autoCloud, setAutoCloud, close, annotate, explain }) {
  const [text, setText] = useState(""), [pending, setPending] = useState(false), [error, setError] = useState(""), [progress, setProgress] = useState(""), [copied, setCopied] = useState(false);
  const panel = useRef(), generation = useRef(0), [position, setPosition] = useState({ left: 12, top: 12 });
  useLayoutEffect(() => {
    const place = () => {
      const rect = panel.current.getBoundingClientRect();
      setPosition(placeReaderPopup(selection.anchor, { width: rect.width, height: rect.height }, { width: innerWidth, height: innerHeight }));
    };
    const observer = new ResizeObserver(place); observer.observe(panel.current);
    window.addEventListener("resize", place); place();
    return () => { observer.disconnect(); window.removeEventListener("resize", place); };
  }, [selection]);
  useEffect(() => {
    const key = e => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", key);
    return () => { generation.current++; document.removeEventListener("keydown", key); };
  }, []);
  async function run() {
    const id = ++generation.current;
    setPending(true); setError(""); setCopied(false);
    try {
      const translation = await client({ text: selection.quote, engine, model: engine === "fast" ? meta?.translationModel : meta?.model,
        onProgress: message => { if (generation.current === id) setProgress(message); } });
      if (generation.current === id) setText(translation);
    } catch (e) { if (generation.current === id) setError(e.message); }
    finally { if (generation.current === id) setPending(false); }
  }
  useEffect(() => {
    generation.current++; setText(""); setError(""); setProgress(""); setPending(false); setCopied(false);
    if (engine === "browser" || autoCloud) run();
    return () => { generation.current++; };
  }, [engine, autoCloud]);
  return <section ref={panel} className="r-translation-popup" style={position} role="region" aria-label="划选翻译" onMouseDown={e => e.stopPropagation()}>
    <header><strong><Languages size={16}/>中文译文 <small>p. {selection.page}</small></strong><Icon icon={X} label="关闭翻译" onClick={close}/></header>
    <div className="r-translation-engine"><select aria-label="翻译引擎" value={engine} onChange={e => setEngine(e.target.value)}>
      <option value="browser">浏览器本地翻译 · 不用模型额度</option><option value="fast" disabled={!meta?.fastTranslation}>快速云翻译 · {meta?.translationModel || "未配置"}</option><option value="quality" disabled={!meta?.ai}>审稿模型精译 · 使用账户额度</option>
    </select><Icon icon={pending ? LoaderCircle : RotateCcw} label="重新翻译" disabled={pending || (engine !== "browser" && !meta?.ai)} onClick={run}/></div>
    <details className="r-translation-source"><summary>查看原文</summary><p>{selection.quote}</p></details>
    <div className={`r-translation-result ${error ? "r-warning" : ""}`} aria-live="polite">{error || (pending ? <span><LoaderCircle size={14} className="r-spin"/>{progress || "正在翻译选文…"}</span> : text || "点击翻译，将仅发送这段选文。")}</div>
    {engine !== "browser" && <><p className="r-translation-disclosure">仅选文发送至{meta?.provider === "codex" ? " Codex 云端" : ` ${meta?.apiOrigin || "已配置的模型服务"}`}，使用账户额度；译文和交互保存在完整 JSON 档案。</p>
      {!autoCloud && <button className="r-primary r-full" disabled={pending || !meta?.ai} onClick={run}><Languages size={14}/>同意发送选文并翻译</button>}
      <label className="r-check r-translation-auto"><input type="checkbox" checked={autoCloud} onChange={e => setAutoCloud(e.target.checked)}/><span>本篇后续划选自动云端翻译（使用额度）</span></label></>}
    <footer><button onClick={explain}><MessageCircle size={14}/>AI 白话</button><button onClick={annotate}><MessageSquare size={14}/>添加批注</button><button disabled={!text} onClick={async () => {
      try { await navigator.clipboard.writeText(text); setCopied(true); } catch { setError("无法访问剪贴板，请选中译文手动复制。"); }
    }}><Copy size={14}/>{copied ? "已复制" : "复制译文"}</button></footer>
  </section>;
}
function Finding({ finding: f, active, locate, update, append, run }) {
  const [note, setNote] = useState(f.reviewerNote || ""), [expanded, setExpanded] = useState(false);
  return <article className={`r-finding ${active ? "active" : ""} ${f.status === "dismissed" ? "dismissed" : ""}`}>
    <div className="r-finding-meta"><span className={`r-severity ${f.severity}`}>{severities[f.severity]}</span><span>{categories[f.category]}</span><span className="r-origin">{f.source === "ai" ? "AI" : "人工"}</span></div>
    <button className="r-finding-title" onClick={locate}>{f.title}<ArrowUpRight size={15}/></button>
    <button className="r-quote" onClick={locate} title="跳转到 PDF 原文"><span>p. {f.page} · {f.anchored ? "原文已定位" : "未验证原文位置"}</span><q>{f.quote || "整页批注"}</q></button>
    <p className="r-finding-body">{f.body}</p>
    <div className="r-certainty"><span className={f.certainty === "unverified" ? "warn" : ""}>{certainties[f.certainty]}</span>{f.status === "accepted" && <span className="r-green"><Check size={12}/>人工采纳</span>}{f.status === "dismissed" && <span>已排除</span>}</div>
    {(f.impact || f.request || f.counterevidence) && <><button className="r-text-button" onClick={() => setExpanded(!expanded)}>{expanded ? "收起依据" : "影响、反证与澄清要求"}<ChevronRight size={13} className={expanded ? "r-rotate" : ""}/></button>
      {expanded && <div className="r-evidence">{f.impact && <p><strong>决策影响</strong>{f.impact}</p>}{f.counterevidence && <p><strong>作者可能的解释 / 附录证据</strong>{f.counterevidence}</p>}{f.request && <p><strong>最小澄清要求</strong>{f.request}</p>}{run && <small>{run.model} · {stamp(run.time)}</small>}</div>}</>}
    <div className="r-finding-actions"><button disabled={f.status === "accepted"} onClick={() => update({ status: "accepted" })}><Check size={14}/>采纳</button><button onClick={() => update({ status: f.status === "dismissed" ? "open" : "dismissed" })}><Ban size={14}/>{f.status === "dismissed" ? "重新打开" : "排除"}</button><button onClick={append}><CornerDownRight size={14}/>写入意见</button></div>
    <details className="r-note"><summary>人工复核备注{f.reviewerNote ? " · 已记录" : ""}</summary><textarea aria-label="人工复核备注" value={note} onChange={e => setNote(e.target.value)} placeholder="你的判断、作者可能的回应或其他证据"/><button className="r-secondary" onClick={() => update({ reviewerNote: note })}><Save size={13}/>保存备注</button></details>
  </article>;
}
function App() {
  const [papers, setPapers] = useState([]), [paper, setPaper] = useState(null), [meta, setMeta] = useState(null), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [tab, setTab] = useState("ai"), [page, setPage] = useState(1), [target, setTarget] = useState(null), [search, setSearch] = useState(""), [filter, setFilter] = useState("open"), [library, setLibrary] = useState(true);
  const [modal, setModal] = useState(""), [form, setForm] = useState(null), [dirty, setDirty] = useState(false), [saving, setSaving] = useState(false), [selection, setSelection] = useState(null);
  const [note, setNote] = useState({ title: "", body: "", page: 1, quote: "", severity: "major", category: "logic" });
  const [initial, setInitial] = useState(""), [attest, setAttest] = useState(false), [mode, setMode] = useState("explore"), [language, setLanguage] = useState("en"), [instructions, setInstructions] = useState(""), [consent, setConsent] = useState(false), [skillIds, setSkillIds] = useState(["claims", "experiments", "logic", "synthesis"]);
  const [provider, setProvider] = useState("codex"), [model, setModel] = useState(""), [key, setKey] = useState(""), [draftRun, setDraftRun] = useState("");
  const uploadRef = useRef(), current = useRef(null), formRef = useRef(null), dirtyRef = useRef(false), savingRef = useRef(false);
  const [translationEngine, setTranslationEngine] = useState(() => globalThis.Translator ? "browser" : "quality"), [autoCloud, setAutoCloud] = useState(false);
  const [readingSelection, setReadingSelection] = useState(null);
  const translationClient = useRef(null);
  useEffect(() => {
    setAutoCloud(false);
    translationClient.current = createTranslationClient({ request: (engine, text) => api(`${base}/papers/${paper.id}/translate`, { method: "POST", body: { text, engine, consent: true } }) });
  }, [paper?.id]);
  current.current = paper; formRef.current = form; dirtyRef.current = dirty;
  const activeJob = ["queued", "running", "cancelling"].includes(paper?.job?.status);
  async function refreshList() { setPapers(await api(`${base}/papers`)); }
  async function refreshMeta() { const m = await api(`${base}/meta`); setMeta(m); setProvider(m.provider); setModel(m.model); }
  async function act(fn) { setError(""); setLoading(true); try { await fn(); } catch (e) { setError(e.message); } finally { setLoading(false); } }
  function applyPaper(p, replaceForm = false) { current.current = p; setPaper(p); if (replaceForm) { formRef.current = p.form; dirtyRef.current = false; setForm(p.form); setDirty(false); } }
  async function persist() {
    if (!current.current || !dirtyRef.current || savingRef.current) return true;
    savingRef.current = true; setSaving(true);
    const submitted = formRef.current, p = current.current;
    try {
      const fresh = await api(`${base}/papers/${p.id}`, { method: "PATCH", body: { version: p.version, form: submitted } });
      if (current.current?.id === p.id) {
        current.current = fresh;
        setPaper(fresh);
        if (formRef.current === submitted) { setDirty(false); dirtyRef.current = false; }
      }
      refreshList().catch(() => {}); return true;
    } catch (e) { setError(e.message); return false; }
    finally { savingRef.current = false; setSaving(false); }
  }
  async function openPaper(id) {
    if (savingRef.current) throw new Error("正在保存，请稍后切换论文");
    if (!(await persist())) return;
    const p = await api(`${base}/papers/${id}`);
    applyPaper(p, true); setPage(1); setTarget(null); setSelection(null); setReadingSelection(null);
    localStorage.setItem("redline-paper", id);
    const url = new URL(location.href); url.searchParams.set("paper", id); history.replaceState(null, "", url);
  }
  useEffect(() => {
    act(async () => {
      await refreshList();
      const id = new URLSearchParams(location.search).get("paper") || localStorage.getItem("redline-paper");
      if (id) await openPaper(id).catch(() => { localStorage.removeItem("redline-paper"); });
    });
    refreshMeta().catch(e => setError(e.message));
  }, []);
  useEffect(() => {
    if (!dirty) return;
    const timeout = setTimeout(persist, 1200); return () => clearTimeout(timeout);
  }, [dirty, form, paper?.version]);
  useEffect(() => {
    const listener = e => { if (dirtyRef.current || savingRef.current) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", listener); return () => window.removeEventListener("beforeunload", listener);
  }, []);
  useEffect(() => {
    if (!activeJob || !paper) return;
    const id = paper.id;
    const interval = setInterval(async () => {
      if (savingRef.current) return;
      try {
        const fresh = await api(`${base}/papers/${id}`);
        if (current.current?.id !== id) return;
        setPaper(fresh);
        if (!["queued", "running", "cancelling"].includes(fresh.job?.status)) refreshList().catch(() => {});
      } catch (e) { setError(e.message); }
    }, 2500);
    return () => clearInterval(interval);
  }, [activeJob, paper?.id]);
  async function upload(files) {
    if (savingRef.current) throw new Error("请等待当前记录保存完成");
    if (!(await persist())) return;
    let last;
    for (const file of files) {
      const data = new FormData(); data.append("pdf", file);
      last = await api(`${base}/papers`, { method: "POST", body: data });
      await refreshList();
    }
    if (last) await openPaper(last.id);
  }
  function newNote(value = { page, quote: "" }) { setNote({ title: "", body: "", severity: "major", category: "logic", page: value.page, quote: value.quote }); setModal("note"); setSelection(null); }
  async function updateFinding(f, patch) {
    await act(async () => {
      if (!(await persist())) return;
      const fresh = await api(`${base}/papers/${paper.id}/findings/${f.id}`, { method: "PATCH", body: patch });
      applyPaper(fresh); await refreshList();
    });
  }
  function changeForm(k, value) { setForm(f => ({ ...f, [k]: value })); setDirty(true); }
  const filtered = paper?.findings.filter(f => (tab === "human" ? f.source === "human" : true) && (filter === "all" || f.status === filter)) || [];
  const latestRun = paper?.runs.find(r => r.status === "completed");
  const selectedRun = paper?.runs.find(r => r.id === draftRun && r.result) || latestRun;
  return <div className="r-app">
    <header className="r-topbar"><a className="r-brand" href="/review"><span className="r-logo"><BookOpen size={20}/></span><strong>redline<span> / </span></strong><span className="r-brand-caption">审稿工作台</span></a>
      <div className="r-top-right"><span className="r-workspace"><span/>本机工作区</span><span className="r-venue">ICLR 2027</span><Icon icon={Settings2} label="模型设置" onClick={() => setModal("settings")}/><a className="r-icon" href="/" title="论文写作工作台" aria-label="论文写作工作台"><ExternalLink size={17}/></a></div>
    </header>
    <input hidden ref={uploadRef} type="file" multiple accept="application/pdf,.pdf" onChange={e => { const files = [...e.target.files]; e.target.value = ""; act(() => upload(files)); }}/>
    {error && <div className="r-error" role="alert"><AlertCircle size={16}/><span>{error}</span><Icon icon={X} label="关闭提示" onClick={() => setError("")}/></div>}
    <div className={`r-workbench ${library ? "" : "collapsed"}`}>
      {library && <aside className="r-library"><div className="r-library-heading"><span>论文库 <b>{papers.length.toString().padStart(2, "0")}</b></span><Icon icon={PanelLeftClose} label="收起论文库" onClick={() => setLibrary(false)}/></div>
        <button className="r-primary r-import" disabled={loading} onClick={() => uploadRef.current.click()}>{loading ? <LoaderCircle className="r-spin" size={16}/> : <Plus size={16}/>}导入 PDF</button>
        <label className="r-search"><Search size={15}/><input value={search} onChange={e => setSearch(e.target.value)} aria-label="搜索论文" placeholder="搜索论文…"/></label>
        <div className="r-library-items">{papers.filter(p => `${p.title} ${p.filename}`.toLowerCase().includes(search.toLowerCase())).map((p, i) => <button className={`r-paper-item ${paper?.id === p.id ? "selected" : ""}`} key={p.id} disabled={loading || saving} onClick={() => act(() => openPaper(p.id))}>
          <span className="r-paper-number">{String(i + 1).padStart(2, "0")}</span><div><strong>{p.title}</strong><span>{p.pageCount} 页<span className="r-dot">·</span>{p.completed ? "已完成" : p.findings ? `${p.accepted} / ${p.findings} 已采纳` : "待审稿"}</span><small>{stamp(p.updated)}</small></div>{p.completed && <CircleCheck className="r-green" size={14}/>}</button>)}
          {papers.length > 0 && !papers.some(p => `${p.title} ${p.filename}`.toLowerCase().includes(search.toLowerCase())) && <p className="r-muted r-library-empty">没有匹配的论文</p>}
        </div>
        <footer className="r-library-footer"><ShieldCheck size={16}/><div><strong>审稿记录保存在本机</strong><span>PDF / 批注 / 版本 / AI 交互</span></div></footer>
      </aside>}
      <main className="r-main">
        <div className="r-document-heading"><div className="r-document-title">{!library && <Icon icon={PanelLeftOpen} label="展开论文库" onClick={() => setLibrary(true)}/>}<span className="r-section-label">REVIEW DESK</span><h1 title={paper?.title}>{paper?.title || "论文审稿"}</h1></div>
          {paper && <div className="r-document-actions"><span className="r-save-state">{saving ? <LoaderCircle size={13} className="r-spin"/> : dirty ? <span className="r-unsaved"/> : <CircleCheck size={13}/>} {saving ? "保存中" : dirty ? "待保存" : "已保存"}</span><Icon icon={Download} label="导出审稿记录" onClick={() => setModal("export")}/><button className="r-primary" disabled={activeJob || loading} onClick={() => { setConsent(false); setModal("ai"); }}><Sparkles size={15}/>{activeJob ? "审稿中" : "AI 审稿"}</button></div>}
        </div>
        {!paper ? <div className="r-empty" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); act(() => upload([...e.dataTransfer.files])); }}>
          <div className="r-empty-document"><FileText size={45} strokeWidth={1.2}/><span><Plus size={15}/></span></div><h2>开始一篇新的审稿</h2><p>ICLR 2027 · Main Conference</p><button disabled={loading} className="r-primary" onClick={() => uploadRef.current.click()}>{loading ? <LoaderCircle size={16} className="r-spin"/> : <Upload size={16}/>}选择 PDF</button><span className="r-muted">或将 PDF 拖入这里 · 单文件不超过 40 MB</span><a href="https://iclr.cc/Conferences/2027/AIPolicyForReviewers" target="_blank" rel="noreferrer">ICLR AI 使用与披露政策<ArrowUpRight size={13}/></a>
        </div> : <div className="r-split"><div className="r-reader-column"><Reader paper={paper} page={page} setPage={p => { setPage(p); setSelection(null); }} target={target} onQuote={setSelection}/>
          {selection && <SelectionTranslation key={`${paper.id}:${selection.page}:${selection.quote}`} selection={selection} client={translationClient.current} meta={meta} engine={translationEngine} setEngine={setTranslationEngine} autoCloud={autoCloud} setAutoCloud={setAutoCloud} annotate={() => newNote(selection)} explain={() => { setReadingSelection({ page: selection.page, quote: selection.quote }); setTab("reading"); setSelection(null); }} close={() => { setSelection(null); window.getSelection()?.removeAllRanges(); }}/>}</div>
          <aside className="r-review-panel"><nav className="r-tabs" aria-label="审稿视图">{[["reading", BookOpen, "AI 导读"], ["ai", Sparkles, "AI 审稿"], ["human", MessageSquare, "人工审稿"], ["form", ClipboardCheck, "ICLR 意见"], ["history", History, "记录"], ["organization", FileText, "AI 整理"]].map(([id, Comp, label]) => <button key={id} className={tab === id ? "active" : ""} onClick={() => { setTab(id); setReadingSelection(null); }}><Comp size={15}/>{label}</button>)}</nav>
            {tab === "organization" && <OrganizationPanel key={paper.id} paper={paper} meta={meta} value={form?.organization} change={value => changeForm("organization", value)} request={api} beforeRun={async () => { if (savingRef.current) throw new Error("正在保存，请稍后重试"); return persist(); }} onPaper={p => applyPaper(p)} save={persist} saving={saving} dirty={dirty}/>}
            {tab === "reading" && <ReadingPanel key={paper.id} paper={paper} meta={meta} selection={readingSelection} request={api} beforeRun={async () => { if (savingRef.current) throw new Error("正在保存审稿草稿，请稍后提问"); return persist(); }} onPaper={p => { applyPaper(p); refreshList().catch(() => {}); }} locate={r => { setPage(r.page); setTarget(r); }}/>}
            {activeJob && <div className="r-job" role="status"><LoaderCircle size={16} className="r-spin"/><div><strong>正在交叉审查</strong><span>{paper.job.message}</span></div><Icon icon={Square} label="停止 AI 审稿" onClick={() => act(async () => { const r = await api(`${base}/papers/${paper.id}/cancel`, { method: "POST", body: {} }); setPaper(p => ({ ...p, job: r.job })); })}/></div>}
            {!activeJob && ["failed", "cancelled", "interrupted"].includes(paper.job?.status) && <div className="r-job-error"><AlertCircle size={14}/>{paper.job.error || paper.job.message}</div>}
            {(tab === "ai" || tab === "human") && <>
              <div className="r-panel-heading"><div><h2>{tab === "human" ? "我的批注" : "问题与证据"}<span>{filtered.length}</span></h2><p>{tab === "human" ? "独立判断 · 原文批注" : "只保留影响核心结论的问题"}</p></div><Icon icon={Plus} label="添加人工批注" onClick={() => newNote()}/></div>
              <div className="r-filters">{[["open", "待复核"], ["accepted", "已采纳"], ["dismissed", "已排除"], ["all", "全部"]].map(([value, title]) => <button className={filter === value ? "selected" : ""} key={value} onClick={() => setFilter(value)}>{title}</button>)}</div>
              <div className="r-panel-scroll">
                {tab === "ai" && latestRun && <details className="r-summary"><summary><Sparkles size={14}/>AI 总评与覆盖范围</summary><p>{latestRun.result.summary}</p><strong>覆盖范围</strong><p>{latestRun.result.coverage}</p><small>{latestRun.model} · {stamp(latestRun.time)}</small></details>}
                {filtered.map(f => <Finding key={f.id} finding={f} active={target?.id === f.id} run={paper.runs.find(r => r.id === f.runId)} locate={() => { setPage(f.page); setTarget(f); }} update={patch => updateFinding(f, patch)} append={() => {
                  if (!window.confirm("将此问题写入 Weaknesses 草稿？仍需你核实并自行决定最终措辞。")) return;
                  changeForm("weaknesses", `${form.weaknesses}${form.weaknesses ? "\n\n" : ""}${f.title}（p. ${f.page}${f.section ? `，${f.section}` : ""}）\n${f.body}${f.request ? `\n${f.request}` : ""}`); setTab("form");
                }}/>) }
                {!filtered.length && <div className="r-panel-empty">{tab === "ai" ? <Sparkles size={28} strokeWidth={1.3}/> : <MessageSquare size={28} strokeWidth={1.3}/>}<h3>{paper.findings.length ? "这里还没有问题" : tab === "ai" ? "等待第一轮审稿" : "写下你的独立判断"}</h3>{tab === "ai" ? <><p>{latestRun ? "本轮没有提出可支持的问题。" : "论断与证据、逻辑与理论、实验严谨性"}</p><button className="r-primary" disabled={activeJob || loading} onClick={() => { setConsent(false); setModal("ai"); }}><Sparkles size={15}/>开始 AI 审稿</button></> : <><p>第 {page} 页</p><button className="r-secondary" onClick={() => newNote()}><Plus size={14}/>添加批注</button></>}</div>}
              </div><footer className="r-panel-footer"><span className="r-status-dot"/>人工作出最终判断<button onClick={() => setModal("skills")}>审稿 Skills<ArrowUpRight size={12}/></button></footer>
            </>}
            {tab === "form" && <><div className="r-panel-heading"><div><h2>ICLR 审稿意见</h2><p>人工草稿 · 尚未提交 OpenReview</p></div><Icon icon={Save} label="保存审稿意见" disabled={saving || !dirty} onClick={persist}/></div><div className="r-panel-scroll r-form">
              <div className="r-form-policy"><ShieldCheck size={16}/><div>数字评分图例以你的 OpenReview 表单为准。<a href="https://iclr.cc/Conferences/2027/ReviewerGuidelines" target="_blank" rel="noreferrer">官方指南 <ArrowUpRight size={11}/></a></div></div>
              {latestRun && <div className="r-ai-draft"><select aria-label="选择 AI 审稿轮次" value={selectedRun?.id || ""} onChange={e => setDraftRun(e.target.value)}>{paper.runs.filter(r => r.result).map((r, i) => <option key={r.id} value={r.id}>AI 草稿 · {stamp(r.time)} · {r.model}</option>)}</select><button className="r-secondary" onClick={() => {
                if (!window.confirm("用所选 AI 草稿替换文字字段？数字评分和原始人工评估不会改变，已有表单历史会保留。")) return;
                setForm(f => ({ ...f, ...Object.fromEntries(Object.keys(labels).map(k => [k, selectedRun.result[k]])) })); setDirty(true);
              }}><CornerDownRight size={14}/>采用 AI 草稿</button></div>}
              {Object.entries(labels).map(([k, label]) => <label className="r-form-field" key={k}><span>{label}<small>{cn[k]}</small></span><textarea aria-label={label} value={form?.[k] || ""} onChange={e => changeForm(k, e.target.value)} rows={k === "weaknesses" ? 7 : 4}/></label>)}
              <h3 className="r-subheading">人工评分</h3><div className="r-ratings">{["soundness", "presentation", "contribution", "rating", "confidence"].map(k => <label key={k}>{k[0].toUpperCase() + k.slice(1)}<input aria-label={k} placeholder="未评分" value={form?.[k] || ""} onChange={e => changeForm(k, e.target.value)} maxLength={100}/></label>)}</div>
              <button className="r-secondary r-full" onClick={() => setModal("initial")}><ShieldCheck size={15}/>{paper.initialAssessment ? "查看原始人工评估" : "原始人工评估与 AI 披露"}</button>
              <label className="r-check"><input type="checkbox" checked={paper.completed} onChange={e => {
                const completed = e.target.checked;
                act(async () => { if (!(await persist())) return; const p = current.current; applyPaper(await api(`${base}/papers/${p.id}`, { method: "PATCH", body: { version: p.version, completed } })); await refreshList(); });
              }}/><span>我已人工核对并完成这份审稿</span></label>
            </div></>}
            {tab === "history" && <><div className="r-panel-heading"><div><h2>审稿记录</h2><p>{paper.history.length} 条事件 · {paper.runs.length} 轮 AI 交互</p></div><Icon icon={Download} label="导出完整记录" onClick={() => setModal("export")}/></div><div className="r-panel-scroll r-history">
              <div className="r-history-policy"><ShieldCheck size={18}/><strong>{paper.initialAssessment ? "原始人工评估已封存" : "尚未封存原始人工评估"}</strong><button className="r-text-button" onClick={() => setModal("initial")}>查看<ArrowUpRight size={12}/></button></div>
              {paper.runs.map(r => <details className="r-run-record" key={r.id}><summary><Sparkles size={14}/><span>{r.model}<small>{stamp(r.time)} · {r.status === "completed" ? "已完成" : r.status}</small></span></summary><p>{r.request.mode === "official" ? "正式辅助审稿" : "AI 预审 / 探索"} · {r.request.language}</p><strong>本轮要求</strong><p>{r.request.instructions || "无额外要求"}</p>{r.error && <p role="alert">{r.error}</p>}<details><summary>完整模型输入</summary><pre>{r.prompt.instructions}{"\n\n"}{r.prompt.input}</pre></details>{r.result && <details><summary>完整模型输出</summary><pre>{JSON.stringify(r.result, null, 2)}</pre></details>}</details>)}
              <h3 className="r-subheading">时间线</h3>{paper.history.map(h => <div className="r-history-row" key={h.id}><span/><div><strong>{h.detail}</strong><small>{stamp(h.time)}</small></div></div>)}
            </div></>}
          </aside>
        </div>}
      </main>
    </div>
    {modal === "note" && <Modal title="添加人工批注" close={() => setModal("")}><form onSubmit={e => { e.preventDefault(); act(async () => {
      if (!(await persist())) return;
      const fresh = await api(`${base}/papers/${paper.id}/findings`, { method: "POST", body: note });
      applyPaper(fresh); setModal(""); setTab("human"); setFilter("open"); await refreshList();
    }); }}><div className="r-inline-fields"><label>PDF 页码<input required type="number" min={1} max={paper.pages.length} value={note.page} onChange={e => setNote(n => ({ ...n, page: Number(e.target.value) }))}/></label><label>影响程度<select value={note.severity} onChange={e => setNote(n => ({ ...n, severity: e.target.value }))}>{Object.entries(severities).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><label>问题类型<select value={note.category} onChange={e => setNote(n => ({ ...n, category: e.target.value }))}>{Object.entries(categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label></div>
      <label>原文<textarea aria-label="原文" value={note.quote} onChange={e => setNote(n => ({ ...n, quote: e.target.value }))} rows={3}/></label><label>问题标题<input aria-label="问题标题" required value={note.title} onChange={e => setNote(n => ({ ...n, title: e.target.value }))} maxLength={300}/></label><label>你的审稿判断<textarea aria-label="你的审稿判断" required rows={5} value={note.body} onChange={e => setNote(n => ({ ...n, body: e.target.value }))}/></label><div className="r-modal-actions"><button className="r-primary" disabled={loading}><Save size={15}/>保存批注</button></div></form></Modal>}
    {modal === "ai" && <Modal title="AI 辅助审稿" close={() => setModal("")}><form onSubmit={e => { e.preventDefault(); act(async () => {
      if (!(await persist())) return;
      const result = await api(`${base}/papers/${paper.id}/runs`, { method: "POST", body: { mode, language, instructions, skillIds, consent } });
      setPaper(p => ({ ...p, job: result.job })); setTab("ai"); setFilter("open"); setModal("");
    }); }}><div className="r-mode-switch"><button type="button" className={mode === "explore" ? "selected" : ""} onClick={() => setMode("explore")}>AI 预审</button><button type="button" className={mode === "official" ? "selected" : ""} onClick={() => setMode("official")}>正式审稿辅助</button></div>
      <div className="r-policy-notice"><ShieldCheck size={18}/><p>ICLR 2027 要求披露原始人工评估与 AI 交互。AI 预审不等同于独立人工评估，不能事后补写为“未经 AI 辅助”。<a href="https://iclr.cc/Conferences/2027/AIPolicyForReviewers" target="_blank" rel="noreferrer">官方政策 <ArrowUpRight size={12}/></a></p></div>
      {mode === "official" && !paper.initialAssessment && <button type="button" className="r-secondary r-full" onClick={() => setModal("initial")} disabled={paper.aiStarted}><ShieldCheck size={14}/>{paper.aiStarted ? "已有 AI 交互，无法事后补录原始评估" : "先封存原始人工评估"}</button>}
      <div className="r-lens-list">{meta?.lenses.map(s => <label className="r-check" key={s.id}><input type="checkbox" checked={skillIds.includes(s.id)} onChange={e => setSkillIds(ids => e.target.checked ? [...ids, s.id] : ids.filter(id => id !== s.id))}/><span><strong>{s.name}</strong><small>{s.detail}</small></span></label>)}</div>
      <label>正式意见语言<select value={language} onChange={e => setLanguage(e.target.value)}><option value="en">English · 原文问题解释为中文</option><option value="zh">中文</option></select></label><label>本轮重点<textarea value={instructions} onChange={e => setInstructions(e.target.value)} rows={3} placeholder="例如：重点检查核心论断、实验归因，不抓小问题。"/></label>
      <div className="r-run-meta"><span>{paper.pages.length} 页 PDF</span><span>{meta?.model || "模型未连接"}</span></div><p className="r-disclosure">AI 接收 PDF 提取的全文及附录文本，不含图像像素，不运行实验或联网验证引用。PDF 仍在本机；提取文本、人工意见会发送至{meta?.provider === "codex" ? " Codex 云端" : ` ${meta?.apiOrigin || "模型提供商"}`}。运行会使用你的账户额度。</p>
      <label className="r-check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/><span>我有权处理此论文，同意本轮云端传输，并将人工核实与披露 AI 使用。</span></label>
      {!meta?.ai && <p className="r-warning">{meta?.cli?.message || "请先配置模型连接"}</p>}
      <div className="r-modal-actions"><button type="button" className="r-secondary" onClick={() => setModal("settings")}><Settings2 size={15}/>模型设置</button><button className="r-primary" disabled={loading || !consent || !meta?.ai || !skillIds.length || (mode === "official" && !paper.initialAssessment)}><Sparkles size={15}/>开始本轮审稿</button></div>
    </form></Modal>}
    {modal === "initial" && <Modal title="原始人工评估" close={() => setModal("")}>
      {paper.initialAssessment ? <><div className="r-policy-notice"><ShieldCheck size={18}/><p>已于 {stamp(paper.initialAssessment.time)} 封存。本系统不会修改这份原始记录。</p></div><pre className="r-initial-record">{paper.initialAssessment.text}</pre></> : <form onSubmit={e => { e.preventDefault(); act(async () => {
        if (!(await persist())) return;
        applyPaper(await api(`${base}/papers/${paper.id}/initial`, { method: "POST", body: { text: initial, attestation: attest } })); setInitial(""); setModal("ai");
      }); }}><p className="r-disclosure">仅记录你自己撰写、未经 AI 生成或修改的原始判断。此记录只能在本系统首次 AI 运行前封存一次；你仍需自行披露其他工具中的交互。</p>{paper.aiStarted ? <div className="r-policy-notice"><AlertCircle size={18}/><p>本论文已经运行过 AI 预审，不能在本系统事后创建“原始人工评估”。已有 AI 记录会如实保留。</p></div> : <><label>你的原始评估<textarea required minLength={30} rows={9} value={initial} onChange={e => setInitial(e.target.value)} placeholder="独立概述贡献、主要优点、影响判断的问题与初步结论。"/></label><label className="r-check"><input type="checkbox" checked={attest} onChange={e => setAttest(e.target.checked)}/><span>我确认上述内容为本人独立撰写，未使用 AI 生成或润色。</span></label><div className="r-modal-actions"><button className="r-primary" disabled={loading || !attest || initial.trim().length < 30}><ShieldCheck size={15}/>封存原始评估</button></div></>}</form>}
    </Modal>}
    {modal === "settings" && <Modal title="模型连接" close={() => setModal("")}><form onSubmit={e => { e.preventDefault(); act(async () => {
      await api("/api/settings", { method: "POST", body: { provider, model, apiKey: key || undefined } }); setKey(""); await refreshMeta(); setModal("");
    }); }}><label>连接方式<select value={provider} onChange={e => { setProvider(e.target.value); setModel(e.target.value === "codex" ? "gpt-6.1-sol" : "gpt-4.1"); }}><option value="codex">本机 Codex · ChatGPT 登录</option><option value="openai">OpenAI / 服务端配置的兼容 API</option></select></label><label>模型 ID<input required value={model} onChange={e => setModel(e.target.value)}/></label>{provider === "openai" && <label>API Key<input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} placeholder="留空保持当前 Key"/></label>}<p className="r-disclosure">与原论文工作台共用模型配置。API Key 仅保存在服务器进程内存中，不会写入审稿记录或返回浏览器。Codex 模式仍在云端推理。</p><div className="r-modal-actions"><button className="r-primary" disabled={loading}><Check size={15}/>保存连接</button></div></form></Modal>}
    {modal === "skills" && <Modal title="审稿 Skills 与依据" close={() => setModal("")}><div className="r-skills-overview">{meta?.lenses.map((l, i) => <div key={l.id}><b>{String(i + 1).padStart(2, "0")}</b><span><strong>{l.name}</strong><small>{l.detail}</small></span></div>)}</div><p className="r-disclosure">本系统使用原创 ICLR 审稿适配规则，以及项目已有的 MIT 授权科学审查、数学核查参考。CSPaper 公开的是服务 API 示例，并非可直接安装的完整审稿 Skill；本系统未调用其服务，也不冒充其结果。</p><div className="r-source-list">{meta?.sources.map(s => <a key={s.url} href={s.url} target="_blank" rel="noreferrer">{s.name}<ArrowUpRight size={14}/></a>)}</div></Modal>}
    {modal === "export" && <Modal title="导出审稿" close={() => setModal("")}><div className="r-export-options"><button onClick={() => act(async () => { if (await persist()) location.assign(`${base}/papers/${paper.id}/export?format=md`); })}><FileText size={22}/><span><strong>ICLR 审稿意见</strong><small>Markdown · 人工表单、评分与披露</small></span><Download size={17}/></button><button onClick={() => act(async () => { if (await persist()) location.assign(`${base}/papers/${paper.id}/export`); })}><History size={22}/><span><strong>完整审稿档案</strong><small>JSON · 原始评估、AI 输入输出、批注、历史版本</small></span><Download size={17}/></button><a href={`${base}/papers/${paper.id}/pdf`} download={paper.filename}><BookOpen size={22}/><span><strong>原始论文</strong><small>导入时的原始 PDF</small></span><Download size={17}/></a></div><p className="r-disclosure">系统不会向 OpenReview 自动提交。导出文件包含论文内容和个人审稿记录，请妥善保管。</p></Modal>}
  </div>;
}
createRoot(document.getElementById("root")).render(<App/>);
