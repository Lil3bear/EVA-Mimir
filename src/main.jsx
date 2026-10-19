import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as pdfjs from "pdfjs-dist";
import worker from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import {
  BookOpen,
  Upload,
  Settings2,
  Play,
  Download,
  ChevronLeft,
  ChevronRight,
  FileText,
  FolderOpen,
  MessageSquare,
  Sparkles,
  History,
  X,
  Plus,
  Check,
  RotateCcw,
  AlertCircle,
  ArrowUpRight,
  MousePointer2,
  MapPin,
  SlidersHorizontal,
  GitCompareArrows,
  LoaderCircle,
  PanelLeftClose,
  Save,
  ExternalLink,
  ZoomIn,
  ZoomOut,
  Activity,
  Square,
  CloudUpload,
  Languages,
  LogOut,
  Users,
  Image,
} from "lucide-react";
import "./style.css";
import { citationEntry } from "./citation-links.mjs";
import { createTranslationClient } from "./translation-client.mjs";
import { placeReaderPopup } from "./reader-popup.mjs";
import { PeerReviewPanel } from "./peer-review.jsx";
import { FigurePanel } from "./figure-panel.jsx";
import {loadPDF,pdfErrorMessage} from "./pdf-load.mjs";
import {pageAtReadingLine} from "./pdf-scroll.mjs";
pdfjs.GlobalWorkerOptions.workerSrc = worker;

async function api(url, options = {}) {
  const {fullProject = false, ...requestOptions} = options;
  let submissionKey=null,executionId;
  if(options.method&&options.method!=="GET") {
    executionId=options.body?.requestId||crypto.randomUUID();
    if(!(options.body instanceof FormData)&&!["/session","/logout"].includes(url)) {
      const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(JSON.stringify([options.method,url,options.body])));
      submissionKey="autopaperreview-submission:"+Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,"0")).join("");
      try {
        const previous=JSON.parse(localStorage.getItem(submissionKey)||"null");
        const reuse=previous&&Date.now()-previous.created<86400000;
        if(reuse)executionId=previous.id;
        localStorage.setItem(submissionKey,JSON.stringify({id:executionId,created:reuse?previous.created:Date.now()}));
      } catch {}
    }
  }
  const executionHeaders=executionId?{"X-Execution-Request-Id":executionId}:{};
  let res = await fetch(`/api${url}`, {
    ...requestOptions,
    headers:
      options.body instanceof FormData
        ? {"X-Workspace-View":"reader",...executionHeaders}
        : { "Content-Type": "application/json", "X-Workspace-View":fullProject ? "full" : "reader",...executionHeaders },
    body:
      options.body instanceof FormData
        ? options.body
        : options.body
          ? JSON.stringify(options.body)
          : undefined,
  });
  let data = await res.json();
  const deadline=Date.now()+300000;
  while(data.executionQueued) {
    if(Date.now()>deadline)throw new Error(`请求 ${data.requestId} 已保存在远端队列，尚未确认执行结果。请查看顶部执行队列，不要重复提交。`);
    await new Promise(resolve=>setTimeout(resolve,2000));
    res=await fetch(`/api/execution-queue/${data.requestId}`);
    data=await res.json();
  }
  if(submissionKey&&res.status<500&&res.status!==401&&data.code!=="EXECUTION_UNCONFIRMED")try{localStorage.removeItem(submissionKey);}catch{}
  if (res.status === 401) window.dispatchEvent(new Event("autopaperreview-session-expired"));
  if (!res.ok)
    throw Object.assign(new Error(data.error || "请求失败"), { log: data.log });
  return data;
}
function MemberPresence() {
  const [state,setState]=useState(null);
  useEffect(()=>{
    let active=true;
    const beat=async()=>{try {const res=await fetch("/api/session/presence",{method:"POST"});if(!res.ok)throw Error();const data=await res.json();if(active)setState(data);}catch{if(active)setState(null);}};
    beat();const timer=setInterval(beat,20000);
    return()=>{active=false;clearInterval(timer);};
  },[]);
  return <span className="member-presence" title={state?.members.map(m=>m.name).join("、") || "连接中"}>{state?`在线 ${state.count} 人`:"在线人数连接中"}</span>;
}

function ExecutionQueueStatus() {
  const [state,setState]=useState(null);
  const [error,setError]=useState("");
  useEffect(()=>{
    let stopped=false,timer;
    const poll=async()=>{
      try {const res=await fetch("/api/execution-queue");if(res.ok){const value=await res.json();if(!stopped&&Array.isArray(value.requests))setState(value);}}
      catch {}
      if(!stopped)timer=setTimeout(poll,5000);
    };
    poll();return()=>{stopped=true;clearTimeout(timer);};
  },[]);
  if(!state)return null;
  const pending=state.requests.filter(r=>["queued","claimed"].includes(r.state));
  return <details className="execution-status"><summary>{state.online?"本机执行端在线":"本机执行端离线"}{pending.length?` · ${pending.length} 个排队请求`:""}</summary><div className="execution-requests">
    <strong>远端提交队列</strong>
    {error&&<p role="alert">{error}</p>}
    {!state.requests.length&&<p>暂无提交</p>}
    {state.requests.slice(-10).reverse().map(row=><div key={row.id}><small>{row.id.slice(0,8)} · {new Date(row.created).toLocaleTimeString()} · {{queued:"待本机领取",claimed:"正在交付",done:"交付已结束，请核对修订日志",expired:"过期，未执行",cancelled:"已取消"}[row.state]}</small><p>{row.url}</p>{row.state==="queued"&&<button onClick={async()=>{try{const res=await fetch(`/api/execution-queue/${row.id}/cancel`,{method:"POST"});const data=await res.json();if(!res.ok)throw Error(data.error);setState(s=>({...s,requests:s.requests.map(r=>r.id===row.id?{...r,state:"cancelled"}:r)}));}catch(e){setError(e.message);}}}>取消排队</button>}</div>)}
  </div></details>;
}
function IconButton({ icon: Icon, label, ...props }) {
  return (
    <button className="icon-button" title={label} aria-label={label} {...props}>
      <Icon size={17} />
    </button>
  );
}
function Modal({ title, children, close, wide }) {
  const ref = useRef(),
    closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const previous = document.activeElement;
    ref.current?.querySelector("button")?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") closeRef.current();
      if (e.key !== "Tab") return;
      const focusable = [
        ...ref.current.querySelectorAll(
          "button:not(:disabled),a[href],input:not(:disabled),textarea:not(:disabled),select:not(:disabled)",
        ),
      ];
      const first = focusable[0],
        last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      }
      if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, []);
  return (
    <div
      className="modal-shade"
      onMouseDown={(e) => e.target === e.currentTarget && close()}
    >
      <section
        ref={ref}
        className={`modal ${wide ? "wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <h2>{title}</h2>
          <IconButton icon={X} label="关闭" onClick={close} />
        </header>
        {children}
      </section>
    </div>
  );
}

function ReaderPopup({ placement, mode, close, children }) {
  const ref = useRef();
  const [position, setPosition] = useState({left:12, top:12});
  useLayoutEffect(() => {
    const update = () => setPosition(placeReaderPopup(placement, ref.current.getBoundingClientRect(), {width:window.innerWidth,height:window.innerHeight}));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(ref.current);
    window.addEventListener("resize", update);
    return () => {observer.disconnect(); window.removeEventListener("resize", update);};
  }, [placement]);
  useEffect(() => {
    const outside = e => {if (!e.target.closest(".reader-popup,.paper")) close();};
    const escape = e => {if(e.key === "Escape") {e.preventDefault(); close();}};
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {document.removeEventListener("pointerdown",outside); document.removeEventListener("keydown",escape);};
  }, [close]);
  return <section ref={ref} className={`reader-popup ${mode}`} role="dialog" aria-label={mode === "comment" ? "添加批注" : "选文翻译"} style={position}>{children}</section>;
}

function PDFPage({doc,page,size,renderWidth,scrollRoot,pinMode,onAnchor,onDismiss,comments,pdfRevision,selected,onSelect,references,onReferenceMissing}) {
  const paper=useRef(),canvas=useRef(),layer=useRef(),lastAnchor=useRef(null);
  const [near,setNear]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState("");
  const [links,setLinks]=useState([]),[retry,setRetry]=useState(0);
  useEffect(()=>{
    const observer=new IntersectionObserver(([entry])=>setNear(entry.isIntersecting),{root:scrollRoot.current,rootMargin:"900px 0px"});
    observer.observe(paper.current);return()=>observer.disconnect();
  },[scrollRoot]);
  useEffect(()=>{
    if(!near){canvas.current.width=0;canvas.current.height=0;layer.current.replaceChildren();setLinks([]);return;}
    let stopped=false,rendering,textLayer;
    setLoading(true);setError("");setLinks([]);
    (async()=>{
      const p=await doc.getPage(page);if(stopped)return;
      const viewport=p.getViewport({scale:renderWidth/size.width});
      const c=canvas.current,ratio=window.devicePixelRatio||1;
      c.width=viewport.width*ratio;c.height=viewport.height*ratio;c.style.width=`${viewport.width}px`;c.style.height=`${viewport.height}px`;
      layer.current.replaceChildren();layer.current.style.setProperty("--scale-factor",viewport.scale);
      rendering=p.render({canvasContext:c.getContext("2d"),viewport,transform:[ratio,0,0,ratio,0,0]});await rendering.promise;
      if(stopped)return;const content=await p.getTextContent();if(stopped)return;
      textLayer=new pdfjs.TextLayer({textContentSource:content,container:layer.current,viewport});await textLayer.render();
      const annotations=await p.getAnnotations();if(stopped)return;
      setLinks(annotations.filter(a=>typeof a.dest==="string"&&a.dest.startsWith("cite.")).map(a=>{
        const [x1,y1,x2,y2]=viewport.convertToViewportRectangle(a.rect);
        return {id:a.id,entry:citationEntry(a.dest,references||[]),key:a.dest,left:Math.min(x1,x2),top:Math.min(y1,y2),width:Math.abs(x2-x1),height:Math.abs(y2-y1)};
      }));
    })().catch(e=>{if(!stopped&&!["RenderingCancelledException","AbortException"].includes(e.name))setError(pdfErrorMessage(e));}).finally(()=>{if(!stopped)setLoading(false);});
    return()=>{stopped=true;rendering?.cancel();textLayer?.cancel();};
  },[doc,page,near,renderWidth,size.width,references,retry]);
  useEffect(()=>{lastAnchor.current=null;},[pdfRevision,renderWidth]);
  function anchor(e,context=false){
    if(loading||error||e.target.closest("button,a")||(!context&&e.button===2))return;
    const selection=window.getSelection(),range=selection?.rangeCount?selection.getRangeAt(0):null;
    const inside=range&&layer.current.contains(range.startContainer)&&layer.current.contains(range.endContainer);
    const quote=inside?selection.toString().trim():"";
    if(!context&&!pinMode&&!quote){lastAnchor.current=null;onDismiss();return;}
    if(context)e.preventDefault();
    const rect=paper.current.getBoundingClientRect(),textRect=quote?range.getBoundingClientRect():null;
    const point={x:e.clientX??textRect?.left??rect.left,y:e.clientY??textRect?.bottom??rect.top};
    const a=context&&!quote&&lastAnchor.current?lastAnchor.current:{page,x:Math.max(0,Math.min(1,(point.x-rect.left)/rect.width)),y:Math.max(0,Math.min(1,(point.y-rect.top)/rect.height)),quote,pdfRevision};
    lastAnchor.current=a;
    onAnchor(a,{x:textRect?.left??point.x,top:textRect?.top??point.y,bottom:textRect?.bottom??point.y},context||pinMode?"comment":"translate");
  }
  return <div className="paper" ref={paper} data-pdf-page={page} aria-label={`PDF 第 ${page} 页`} onMouseUp={anchor} onContextMenu={e=>anchor(e,true)} onKeyUp={e=>{if(e.key==="Shift")anchor(e);}} style={{width:renderWidth,height:renderWidth*size.height/size.width}}>
    <canvas ref={canvas}/><div className="textLayer" ref={layer}/>
    {near&&loading&&<span className="pdf-page-status" role="status"><LoaderCircle size={14} className="spin"/> {page}</span>}
    {error&&<div className="pdf-page-status" role="alert">{error}<IconButton icon={RotateCcw} label={`重试第 ${page} 页`} onClick={()=>setRetry(n=>n+1)}/></div>}
    {!pinMode&&links.map(link=>{
      const props={className:"citation-link",key:link.id,style:{left:link.left,top:link.top,width:link.width,height:link.height},title:link.entry?`${link.entry.title} · ${link.entry.url?"打开文章（链接来源于 Bib，未必已核实）":"暂无文章链接"}`:"引用键尚未匹配，查看 Bib","aria-label":`打开引用 ${link.entry?.key||link.key}`};
      return link.entry?.url?<a {...props} href={link.entry.url} target="_blank" rel="noopener noreferrer"/>:<button {...props} onClick={onReferenceMissing}/>;
    })}
    {comments.filter(c=>c.page===page&&c.pdfRevision===pdfRevision&&c.x!==null).map((c,index)=><button key={c.id} className={`pin ${selected===c.id?"selected":""} ${c.status==="resolved"?"resolved":""}`} style={{left:`${c.x*100}%`,top:`${c.y*100}%`}} title={c.body} onClick={()=>onSelect(c)}>{index+1}</button>)}
  </div>;
}

function PDFView({
  url,
  page,
  setPage,
  pinMode,
  onAnchor,
  onDismiss,
  comments,
  pdfRevision,
  selected,
  onSelect,
  references,
  onReferenceMissing,
}) {
  const [doc, setDoc] = useState(null),
    [width, setWidth] = useState(650),
    [error, setError] = useState("");
  const [sizes,setSizes]=useState([]);
  const [reload,setReload]=useState(0),[loadingMessage,setLoadingMessage]=useState("");
  const loadedURL=useRef();
  const [zoom, setZoom] = useState("fit"),
    [baseWidth, setBaseWidth] = useState(612);
  const renderWidth = zoom === "fit" ? width : baseWidth * Number(zoom);
  const host = useRef(),scrollRoot=useRef(),observedPage=useRef(1),previousWidth=useRef(renderWidth);
  useEffect(() => {
    const observer = new ResizeObserver((entries) =>
      setWidth(Math.min(790, Math.max(240, entries[0].contentRect.width - 60))),
    );
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    setDoc(null);
    setSizes([]);
    setError("");
    setLoadingMessage("正在加载 PDF");
    if (!url) return;
    const task = loadPDF(pdfjs.getDocument,{url,disableStream:true,disableAutoFetch:true,isEvalSupported:false},{onRetry:(n,total)=>setLoadingMessage(`连接暂时中断，正在重新加载 PDF（${n}/${total}）`)});
    let canceled = false;
    task.promise
      .then(async(d) => {
        const dimensions=await Promise.all(Array.from({length:d.numPages},async(_,i)=>{
          const p=await d.getPage(i+1),v=p.getViewport({scale:1});return {width:v.width,height:v.height};
        }));
        if (!canceled) {
          setSizes(dimensions);setBaseWidth(dimensions[0].width);
          setDoc(d);
          const initial=loadedURL.current===url?Math.min(page,d.numPages):1;
          observedPage.current=0;setPage(initial);
          loadedURL.current=url;
        }
      })
      .catch((e) => {
        if (!canceled) setError(pdfErrorMessage(e));
      });
    return () => {
      canceled = true;
      task.destroy();
    };
  }, [url,reload]);
  useLayoutEffect(()=>{
    if(!doc||(observedPage.current===page&&previousWidth.current===renderWidth))return;
    previousWidth.current=renderWidth;
    const target=scrollRoot.current?.querySelector(`[data-pdf-page="${page}"]`);
    if(target){observedPage.current=page;scrollRoot.current.scrollTop+=target.getBoundingClientRect().top-scrollRoot.current.getBoundingClientRect().top-12;}
  },[doc,page,renderWidth]);
  useEffect(()=>{onDismiss();},[url,page,renderWidth]);
  function scroll(){
    onDismiss();if(!doc)return;
    const root=scrollRoot.current,rect=root.getBoundingClientRect();
    const next=pageAtReadingLine([...root.querySelectorAll('[data-pdf-page]')].map(el=>({page:Number(el.dataset.pdfPage),top:el.getBoundingClientRect().top,bottom:el.getBoundingClientRect().bottom})),rect.top,rect.height);
    if(next!==observedPage.current){observedPage.current=next;setPage(next);}
  }
  return (
    <section className="document-workspace" ref={host}>
      <div className="pdf-toolbar">
        <span className="preview-label" role="status">
          <FileText size={14} />编译预览
        </span>
        <div className="page-controls">
          <IconButton
            icon={ChevronLeft}
            label="上一页"
            disabled={!doc || page === 1}
            onClick={() => setPage(page - 1)}
          />
          <span>{doc ? `${page} / ${doc.numPages}` : "-- / --"}</span>
          <IconButton
            icon={ChevronRight}
            label="下一页"
            disabled={!doc || page === doc.numPages}
            onClick={() => setPage(page + 1)}
          />
        </div>
        <div className="zoom-controls">
          <IconButton
            icon={ZoomOut}
            label="缩小 PDF"
            disabled={!doc}
            onClick={() =>
              setZoom(
                Math.max(
                  0.5,
                  (zoom === "fit" ? width / baseWidth : Number(zoom)) - 0.25,
                ).toFixed(2),
              )
            }
          />
          <select
            aria-label="PDF 缩放"
            value={zoom}
            onChange={(e) => setZoom(e.target.value)}
          >
            <option value="fit">适合宽度</option>
            {["0.5", "0.75", "1", "1.25", "1.5", "2", "2.5"].map((value) => (
              <option key={value} value={value}>
                {Number(value) * 100}%
              </option>
            ))}
            {zoom !== "fit" &&
              !["0.5", "0.75", "1", "1.25", "1.5", "2", "2.5"].includes(
                zoom,
              ) && (
                <option value={zoom}>{Math.round(Number(zoom) * 100)}%</option>
              )}
          </select>
          <IconButton
            icon={ZoomIn}
            label="放大 PDF"
            disabled={!doc}
            onClick={() =>
              setZoom(
                Math.min(
                  2.5,
                  (zoom === "fit" ? width / baseWidth : Number(zoom)) + 0.25,
                ).toFixed(2),
              )
            }
          />
        </div>
      </div>
      <div className={`pdf-scroll ${pinMode ? "pin-mode" : ""}`} ref={scrollRoot} onScroll={scroll}>
        {error ? (
          <div className="empty">
            <AlertCircle />
            <p role="alert">{error}</p>
            <IconButton icon={RotateCcw} label="重新加载 PDF" onClick={()=>setReload(n=>n+1)}/>
          </div>
        ) : !doc ? (
          <div className="empty">
            <BookOpen size={34} />
            <p role="status">{url ? loadingMessage : "等待编译"}</p>
          </div>
        ) : (
          <div className="pdf-page-wrap continuous">
            {sizes.map((size,i)=><PDFPage key={`${url}:${reload}:${i}`} doc={doc} page={i+1} size={size} renderWidth={renderWidth} scrollRoot={scrollRoot} pinMode={pinMode} onAnchor={onAnchor} onDismiss={onDismiss} comments={comments} pdfRevision={pdfRevision} selected={selected} onSelect={onSelect} references={references} onReferenceMissing={onReferenceMissing}/>)}
          </div>
        )}
      </div>
    </section>
  );
}

function App({member}) {
  const commentSubmission = useRef(null);
  const [detailsError,setDetailsError] = useState("");
  const [health, setHealth] = useState(null),
    [projects, setProjects] = useState([]),
    [project, setProject] = useState(null);
  const [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [failureLog, setFailureLog] = useState(""),
    [modal, setModal] = useState(""),
    [tab, setTab] = useState("comments");
  useEffect(() => {
    if (tab !== "changes" || !project || project.detailsLoaded !== false) return;
    let stopped=false;
    setDetailsError("");
    api(`/projects/${project.id}`,{fullProject:true}).then(p=>{if(!stopped)setProject(p);}).catch(e=>{if(!stopped)setDetailsError(e.message);});
    return ()=>{stopped=true;};
  },[tab,project?.id,project?.detailsLoaded,project?.revision]);
  const [page, setPage] = useState(1),
    [pinMode, setPinMode] = useState(false),
    [anchor, setAnchor] = useState(null),
    [body, setBody] = useState(""),
    [draftAnchor, setDraftAnchor] = useState(null),
    [filter, setFilter] = useState("open"),
    [selected, setSelected] = useState("");
  const [skillIds, setSkillIds] = useState([]);
  const [instructions, setInstructions] = useState(""),
    [consent, setConsent] = useState(false),
    [key, setKey] = useState(""),
    [provider, setProvider] = useState("codex"),
    [model, setModel] = useState("gpt-6.1-sol");
  const [venue, setVenue] = useState(""),
    [source, setSource] = useState(null),
    [sourceContent, setSourceContent] = useState(""),
    [mobileFiles, setMobileFiles] = useState(false);
  const [uploadFile, setUploadFile] = useState(null),
    [trusted, setTrusted] = useState(false),
    [aiMode, setAiMode] = useState("review");
  const [revisionCommentIds,setRevisionCommentIds]=useState(null);
  const [activity, setActivity] = useState(null),
    [activityError, setActivityError] = useState(""),
    [now, setNow] = useState(Date.now());
  const [jobHistory,setJobHistory]=useState([]),[historyDiff,setHistoryDiff]=useState(null),[historyError,setHistoryError]=useState("");
  useEffect(()=>{
    if(modal!=="history" || !project?.id)return;
    let stopped=false;setHistoryDiff(null);setHistoryError("");
    api(`/projects/${project.id}/jobs/history`).then(rows=>{if(!stopped)setJobHistory(rows);}).catch(e=>{if(!stopped)setHistoryError(e.message);});
    return()=>{stopped=true;};
  },[modal,project?.id]);
  const [autoConsent, setAutoConsent] = useState(false),
    [startExisting, setStartExisting] = useState(false);
  const [syncURL, setSyncURL] = useState(""),
    [syncToken, setSyncToken] = useState(""),
    [syncConsent, setSyncConsent] = useState(false),
    [autoPush, setAutoPush] = useState(false);
  const [translation, setTranslation] = useState(null),
    [translating, setTranslating] = useState(false),
    [translationError, setTranslationError] = useState("");
  const translationRequest = useRef(0);
  const [readerPopup, setReaderPopup] = useState(null);
  const [translationEngine,setTranslationEngine] = useState("browser"), [translationProgress,setTranslationProgress] = useState("");
  const translationClient = useRef(null);
  useEffect(() => { translationClient.current = createTranslationClient({request: (engine,text) => api(`/projects/${project.id}/translate`,{method:"POST",body:{text,engine,consent:true}})}); },[project?.id]);
  const [bibData, setBibData] = useState(null), [pdfReferences, setPdfReferences] = useState([]),
    [bibError, setBibError] = useState(""), [bibConsent, setBibConsent] = useState(false);
  useEffect(() => {
    setBibData(null); setPdfReferences([]); setBibError("");
    if (!project) return;
    let cancelled = false;
    const current = `/projects/${project.id}/bibliography`;
    Promise.all([api(current), project.pdfRevision && project.pdfRevision !== project.revision ? api(`${current}?revision=${project.pdfRevision}`) : null]).then(([data,pdf]) => {
      if (!cancelled) {
        setBibData(data);
        const source = pdf || data;
        setPdfReferences(source.entries.map((e,i) => {
          const v = source.audit?.entries[i]?.verification;
          return {...e, url: e.url || (v?.status === "verified" ? v.url : null)};
        }));
      }
    }).catch(e => { if (!cancelled) setBibError(e.message); });
    return () => {cancelled = true;};
  }, [project?.id, project?.revision, project?.pdfRevision, project?.bibAudit?.checked]);
  const passage = anchor?.quote || project?.comments.find(c => c.id === selected)?.quote || "";
  const commentAnchor = body.trim() ? draftAnchor : anchor;
  useEffect(() => {
    translationRequest.current++;
    setTranslation(null);
    setTranslationError("");
    setTranslationProgress("");
    setTranslating(false);
  }, [project?.id, project?.revision, passage, translationEngine]);
  async function translateSelection() {
    const request = ++translationRequest.current;
    setTranslating(true);
    setTranslationError("");
    try {
      const result = await translationClient.current({text:passage,engine:translationEngine,model:translationEngine === "fast" ? health?.translationModel : health?.model,onProgress:message => {
        if (request === translationRequest.current) setTranslationProgress(message);
      }});
      if (request === translationRequest.current) setTranslation(result);
    } catch (e) {
      if (request === translationRequest.current) setTranslationError(e.message);
    } finally {
      if (request === translationRequest.current) setTranslating(false);
    }
  }
  useEffect(() => {
    if (readerPopup?.mode === "translate" && passage) translateSelection();
  }, [readerPopup?.mode, passage, translationEngine, project?.revision]);
  useEffect(() => {setReaderPopup(null);}, [project?.id, project?.pdfRevision]);
  const backgroundActive =
    activity && ["queued", "running", "cancelling"].includes(activity.status);
  const historicalActivity = !backgroundActive && activity &&
    project?.automation?.grantedAt && activity.updated < project.automation.grantedAt;
  const fileInput = useRef(),
    noteInput = useRef();
  async function act(label, fn) {
    setBusy(label);
    setError("");
    if (label.includes("编译")) setFailureLog("");
    try {
      return await fn();
    } catch (e) {
      setError(e.message);
      if (e.log) {
        setFailureLog(e.log);
        setModal("log");
      }
    } finally {
      setBusy("");
    }
  }
  async function refreshProjects() {
    setProjects(await api("/projects"));
  }
  async function openProject(id) {
    setProject(await api(`/projects/${id}`));
    localStorage.setItem("autopaperreview-project", id);
    setFailureLog("");
    setAnchor(null);
    setSelected("");
    setPage(1);
  }
  async function compile(p = project) {
    const updated = await api(`/projects/${p.id}/compile`, { method: "POST" });
    setProject(updated);
  }
  useEffect(() => {
    act("载入工作区", async () => {
      const h = await api("/health");
      setHealth(h);
      setSkillIds(h.skills.filter(s=>s.default!==false).map(s=>s.id));
      setModel(h.model);
      setProvider(h.provider);
      const list = await api("/projects");
      setProjects(list);
      if (list.length)
        await openProject(
          list.find(
            (p) => p.id === localStorage.getItem("autopaperreview-project"),
          )?.id || list.find(p=>p.id===h.defaultProjectId)?.id || list[0].id,
        );
    });
  }, []);
  useEffect(() => {
    if (readerPopup?.mode === "comment") noteInput.current?.focus();
  }, [readerPopup?.mode]);
  useEffect(() => {
    if (!project?.id) return;
    let observedRunning=false;
    let stopped = false,
      timer,
      seenTerminal = "",
      seenProjectVersion = "";
    const id = project.id;
    setActivity(null);
    setActivityError("");
    try {
      const draft = JSON.parse(
        localStorage.getItem(`autopaperreview-draft:${id}`) || "null",
      );
      setBody(draft?.body || "");
      setAnchor(draft?.anchor || null);
      setDraftAnchor(draft?.anchor || null);
    } catch {}
    async function poll() {
      try {
        const { job, projectVersion } = await api(`/projects/${id}/activity`);
        if (stopped) return;
        setActivity(job);
        if(job&&["queued","running","cancelling"].includes(job.status))observedRunning=true;
        setActivityError("");
        if (
          (projectVersion && projectVersion !== seenProjectVersion) || (job &&
          !["queued", "running", "cancelling"].includes(job.status) &&
          `${job.id}:${job.status}` !== seenTerminal)
        ) {
          const fresh = await api(`/projects/${id}`);
          if (!stopped){setProject(fresh);seenProjectVersion=projectVersion;if(job)seenTerminal=`${job.id}:${job.status}`;if(observedRunning&&job?.result?.outcome==="applied")setTab("changes");}
        }
      } catch {
        if (!stopped)
          setActivityError("后台连接暂时中断，正在重新连接；任务状态尚未确认");
      }
      if (!stopped) timer = setTimeout(poll, 2000 + Math.random() * 1000);
    }
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [project?.id]);
  useEffect(() => {
    if (!backgroundActive) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [backgroundActive]);
  const base = project ? `/projects/${project.id}` : "";
  const revisionProvider=health?.revision || health;
  const revisionAI=revisionProvider?.collaborator ? {...revisionProvider,
    displayName:`${revisionProvider.displayName} → ${revisionProvider.collaborator.vendor} ${revisionProvider.collaborator.displayName} → ${revisionProvider.finalReviewer?`${revisionProvider.finalReviewer.vendor} ${revisionProvider.finalReviewer.displayName}`:"交叉复核"}`,
    apiOrigin:[revisionProvider.apiOrigin,revisionProvider.collaborator.provider==="codex"?"本机 Codex（ChatGPT 账户）":revisionProvider.collaborator.localAuth?`本机 Claude Code（${revisionProvider.collaborator.apiOrigin||"沿用本机服务配置"}）`:revisionProvider.collaborator.apiOrigin,revisionProvider.finalReviewer?"本机 Codex（ChatGPT 账户）":null].filter(Boolean).join(" 和 "),
  } : revisionProvider;
  const revisionLimits=revisionProvider?.collaborator?.model==="claude-opus-5-5"?"八分钟，客户端费用估算上限为 4 美元":revisionProvider?.collaborator?.model==="claude-fable-5-1"?"八分钟，客户端费用估算上限为 6 美元":"四分钟，客户端费用估算上限为 2 美元";
  const revisionLocalNotice=revisionProvider?.collaborator?.localAuth?"协作阶段沿用本机 Claude Code 的认证和服务配置；如果本机配置了 UUAPI，仍会经过该网关。不把登录凭据发往云端，但论文内容会发送给所选模型服务。":"";
  const revisionDisclosure=revisionProvider?.teamMode==="dual"
    ? "双模型修订发送完整正文与 Bib：官方 DeepSeek 起草，本机 GPT 6.1 经 Codex 独立复核；Claude 因额度不足未参与。GPT 单次最多十分钟。"
    : `联合修订发送完整正文与 Bib，不截断正文；类文件和 BST 只用于编译。共三个阶段，Claude 单次调用最多三轮推理、${revisionLimits}（非实际账单或订阅用量保证）。${revisionLocalNotice}${revisionProvider?.finalReviewer?"GPT 6.1 经本机 Codex 交叉复核，单次最多十分钟。":""}`;
  const dialogAI=aiMode === "revise" ? revisionAI : health;
  const openCount =
    project?.comments.filter((c) => c.status === "open"&&!c.archivedAt).length || 0;
  const visibleComments =
    project?.comments.filter((c) => !c.archivedAt&&(filter === "all" || c.status === filter)) ||
    [];
  async function importProject(demo = false) {
    const data = new FormData();
    data.append("trusted", "true");
    if (demo) data.append("demo", "true");
    else data.append("file", uploadFile);
    const p = await api("/projects/import", { method: "POST", body: data });
    setProject(p);
    localStorage.setItem("autopaperreview-project", p.id);
    setModal("");
    setUploadFile(null);
    await refreshProjects();
    await compile(p);
  }
  async function addComment() {
    const input = {
      body, quote:commentAnchor?.quote || "", page:commentAnchor?.page || null,
      x:commentAnchor?.x ?? null, y:commentAnchor?.y ?? null,
      pdfRevision:commentAnchor?.pdfRevision || null, file:"",
    };
    const signature = JSON.stringify([project.id, input]);
    if (commentSubmission.current?.signature !== signature)
      commentSubmission.current = {signature,requestId:crypto.randomUUID()};
    setProject(
      await api(`${base}/comments`, {
        method: "POST",
        body: {...input, requestId:commentSubmission.current.requestId},
      }),
    );
    commentSubmission.current = null;
    setBody("");
    setAnchor(null);
    setDraftAnchor(null);
    setReaderPopup(null);
    localStorage.removeItem(`autopaperreview-draft:${project.id}`);
    if (!project.automation?.enabled) {
      setAutoConsent(false);
      setStartExisting(true);
      setModal("automation");
    }
  }
  async function startBackground(mode, options = {}) {
    const { job } = await api(`${base}/jobs`, {
      method: "POST",
      body: { mode, skillIds, instructions, consent, apply:mode==="revise", expectedRevision:project.revision, ...options },
    });
    setActivity(job);
    setModal("");
  }
  function openSync() {
    setSyncURL(project?.overleaf?.url || "");
    setSyncToken("");
    setSyncConsent(false);
    setAutoPush(project?.overleaf?.autoPush || false);
    setModal("overleaf");
  }
  function selectComment(c) {
    setSelected(c.id);
    if (c.pdfRevision === project.pdfRevision && c.page) setPage(c.page);
    setTab("comments");
  }
  async function readSource(file) {
    const s = await api(`${base}/source?file=${encodeURIComponent(file)}`);
    setSource({ file, revision: s.revision });
    setSourceContent(s.content);
    setModal("source");
  }
  const sources = [
    [
      "awesome-ai-research-writing",
      "https://github.com/Leey21/awesome-ai-research-writing",
    ],
    ["AI-paper-reviewer", "https://github.com/FanBroWell/AI-paper-reviewer"],
    [
      "paper-pre-submission-review",
      "https://github.com/chantsss/paper-pre-submission-review",
    ],
  ];
  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">
            <BookOpen size={21} />
          </span>
          <strong>Autopaperreview</strong>
          <span className="local-tag">{health?.shared ? "TEAM" : "LOCAL"}</span>
        </div>
        <div className="header-actions">
          <ExecutionQueueStatus />
          <MemberPresence />
          <a className="icon-button" href="/guide/index.html" target="_blank" rel="noreferrer" aria-label="图文使用指南" title="图文使用指南"><BookOpen size={17}/></a>
          <button
            className="quiet"
            aria-label="审稿 Skills"
            title="审稿 Skills"
            onClick={() => setModal("skills")}
          >
            <SlidersHorizontal size={15} />
            <span>审稿 Skills</span>
            <span className="small-count">{skillIds.length}</span>
          </button>
          <IconButton
            icon={Settings2}
            label="模型设置"
            onClick={() => setModal("settings")}
          />
          <span className="avatar" title={member?.name || "本机使用者"}>{member?.name?.slice(0,1) || "L"}</span>
          {health?.shared && <IconButton icon={LogOut} label="退出登录" onClick={async()=>{await api("/logout",{method:"POST"}); location.reload();}}/>}
        </div>
      </header>
      <div className="project-bar">
        <div className="project-identity">
          <IconButton
            icon={FolderOpen}
            label="切换项目"
            onClick={() => {
              setModal("projects");
              act("载入项目", refreshProjects);
            }}
          />
          <div>
            <strong>{project?.name || "未打开项目"}</strong>
            <span>
              {project
                ? `${project.files.length} 个文件 · ${project.history.length} 个版本`
                : "Autopaperreview 工作区"}
            </span>
          </div>
          <span className="version-tag">
            {project ? `源码 v${project.history.length}` : "源码 v0"}
          </span>
        </div>
        <div className="project-actions">
          <button
            className="secondary"
            disabled={!!busy}
            onClick={() => {
              setTrusted(false);
              fileInput.current.click();
            }}
          >
            <Upload size={15} />
            <span>导入 Overleaf</span>
          </button>
          <button
            className="primary"
            disabled={!project || !!busy}
            onClick={() => act("编译 PDF", () => compile())}
          >
            {busy === "编译 PDF" ? (
              <LoaderCircle size={15} className="spin" />
            ) : (
              <Play size={14} />
            )}
            <span>编译 PDF</span>
          </button>
          <IconButton
            icon={Download}
            label="导出项目"
            disabled={!project}
            onClick={() => setModal("export")}
          />
          <IconButton
            icon={CloudUpload}
            label="Overleaf 同步"
            disabled={!project || !!busy}
            onClick={openSync}
          />
        </div>
      </div>
      <input
        ref={fileInput}
        type="file"
        accept=".zip"
        hidden
        onChange={(e) => {
          if (e.target.files[0]) {
            setUploadFile(e.target.files[0]);
            setModal("import");
          }
          e.target.value = "";
        }}
      />
      {error && (
        <div className="error-banner" role="alert">
          <AlertCircle size={16} />
          <span>{error}</span>
          <IconButton icon={X} label="关闭错误" onClick={() => setError("")} />
        </div>
      )}
      <main className="workspace">
        <aside className={`file-sidebar ${mobileFiles ? "mobile-open" : ""}`}>
          <div className="section-label">
            <span>项目文件</span>
            <IconButton
              icon={PanelLeftClose}
              label="收起文件"
              onClick={() => setMobileFiles(false)}
            />
          </div>
          <div className="file-tree">
            {project ? (
              project.files.map((f) => (
                <button
                  key={f.name}
                  className={`file-row ${f.name === project.main ? "active" : ""}`}
                  title={f.name}
                  onClick={() =>
                    f.editable
                      ? act("读取源文件", () => readSource(f.name))
                      : setModal("assets")
                  }
                >
                  <FileText size={15} />
                  <span>{f.name}</span>
                  {f.name === project.main && <span className="main-dot" />}
                </button>
              ))
            ) : (
              <p className="muted file-empty">暂无项目文件</p>
            )}
          </div>
          <div className="compile-settings">
            <div className="section-label">编译配置</div>
            <label>
              主文件
              <select
                aria-label="主文件"
                value={project?.main || ""}
                disabled={!project || !!busy}
                onChange={(e) =>
                  act("更新配置", async () =>
                    setProject(
                      await api(base, {
                        method: "PATCH",
                        body: { main: e.target.value },
                      }),
                    ),
                  )
                }
              >
                {project?.files
                  .filter((f) => /\.tex$/i.test(f.name))
                  .map((f) => (
                    <option key={f.name}>{f.name}</option>
                  ))}
              </select>
            </label>
            <label>
              编译引擎
              <select
                aria-label="编译引擎"
                value={project?.engine || "pdflatex"}
                disabled={!project || !!busy}
                onChange={(e) =>
                  act("更新配置", async () =>
                    setProject(
                      await api(base, {
                        method: "PATCH",
                        body: { engine: e.target.value },
                      }),
                    ),
                  )
                }
              >
                <option value="pdflatex">pdfLaTeX</option>
                <option value="xelatex">XeLaTeX</option>
              </select>
            </label>
            <button
              className="text-button"
              disabled={!project}
              onClick={() => setModal("log")}
            >
              <FileText size={13} /> 编译日志 <ArrowUpRight size={13} />
            </button>
          </div>
          <div className="sidebar-bottom">
            <span className={`status-dot ${health?.latex ? "green" : ""}`} />
            <span>{health?.latex ? "本地 TeX 就绪" : "本地 TeX 未就绪"}</span>
            <small>0.1</small>
          </div>
        </aside>
        <div className="center-pane">
          <div className="document-tabs">
            <div>
              <button
                className="mobile-file-toggle"
                title="项目文件"
                onClick={() => setMobileFiles(!mobileFiles)}
              >
                <FolderOpen size={16} />
              </button>
              <span className="doc-tab">
                <FileText size={15} />
                {project?.main.replace(/\.tex$/, ".pdf") || "Manuscript.pdf"}
              </span>
              {project?.pdfRevision && (
                <span
                  className={`build-state ${project.pdfRevision === project.revision ? "" : "stale"}`}
                >
                  {project.pdfRevision === project.revision ? (
                    <>
                      <Check size={12} /> 已同步
                    </>
                  ) : (
                    "源文件已更新"
                  )}
                </span>
              )}
            </div>
            <div className="tool-modes">
              <IconButton
                icon={MousePointer2}
                label="选择文字"
                className={`icon-button ${!pinMode ? "tool-active" : ""}`}
                onClick={() => setPinMode(false)}
              />
              <IconButton
                icon={MapPin}
                label="添加位置批注"
                className={`icon-button ${pinMode ? "tool-active" : ""}`}
                onClick={() => setPinMode(true)}
              />
              <IconButton icon={BookOpen} label="文献与 Bib 核查" disabled={!project} onClick={() => {setBibConsent(false); setModal("bibliography");}} />
              {project?.pdfRevision && (
                <a
                  className="icon-button"
                  title="下载 PDF"
                  aria-label="下载 PDF"
                  href={`/api${base}/pdf/${project.pdfRevision}`}
                  download="manuscript.pdf"
                >
                  <Download size={16} />
                </a>
              )}
            </div>
          </div>
          {!project ? (
            <div className="welcome">
              <div className="welcome-emblem">
                <BookOpen size={40} strokeWidth={1.4} />
              </div>
              <h1>Autopaperreview</h1>
              <p className="welcome-sub">论文审阅工作区</p>
              <div className="welcome-buttons">
                <button
                  className="primary"
                  disabled={!!busy}
                  onClick={() => {
                    setTrusted(false);
                    fileInput.current.click();
                  }}
                >
                  <Upload size={16} />
                  导入 Overleaf ZIP
                </button>
                <button
                  className="secondary"
                  disabled={!!busy}
                  onClick={() =>
                    act("创建并编译示例", () => importProject(true))
                  }
                >
                  <FileText size={16} />
                  打开示例论文
                </button>
              </div>
              <div className="workflow-labels">
                <span>01 原稿</span>
                <span>02 批注</span>
                <span>03 修订</span>
                <span>04 复核</span>
              </div>
            </div>
          ) : (
            <PDFView
              url={
                project.pdfRevision
                  ? `/api${base}/pdf/${project.pdfRevision}`
                  : null
              }
              page={page}
              setPage={setPage}
              pinMode={pinMode}
              onAnchor={(a, placement, mode) => {
                setAnchor(a);
                setReaderPopup({placement,mode});
                if(mode === "comment") setTab("comments");
              }}
              onDismiss={() => setReaderPopup(null)}
              comments={project.comments.filter(c=>!c.archivedAt)}
              pdfRevision={project.pdfRevision}
              selected={selected}
              onSelect={selectComment}
              references={pdfReferences}
              onReferenceMissing={() => {setBibConsent(false); setModal("bibliography");}}
            />
          )}
        </div>
        <aside className="review-sidebar">
          {historicalActivity && (
            <section className="activity-strip">
              <button className="activity-message" onClick={() => setModal("activity")}>
                历史任务记录 · {new Date(activity.updated).toLocaleString("zh-CN")} · {{failed:"失败",completed:"完成",cancelled:"已停止",interrupted:"已中断",no_changes:"未修改",awaiting_approval:"待确认"}[activity.status] || activity.status}
                <ChevronRight size={13} />
              </button>
              <small>旧任务未重新运行。当前修订：{health?.revision?.vendor} {health?.revision?.model} → {health?.revision?.collaborator?.displayName} → {health?.revision?.finalReviewer?.displayName}</small>
              {activityError && <p role="status">{activityError}</p>}
            </section>
          )}
          {!historicalActivity && (activity || activityError) && (
            <section
              className={`activity-strip ${activity?.status || ""}`}
              aria-live="polite"
            >
              <div className="activity-heading">
                <Activity size={14} />
                <strong>{activity?.title || "后台任务"}</strong>
                <span>
                  {backgroundActive
                    ? `${Math.max(0, Math.floor((now - Date.parse(activity.started || activity.created)) / 1000))}s`
                    : {
                        completed: activity?.result?.outcome==="applied"?"已修改":"完成",
                        no_changes:"未修改",
                        awaiting_approval:"待确认，未应用",
                        failed: "失败",
                        cancelled: "已停止",
                        interrupted: "已中断",
                      }[activity?.status]}
                </span>
                {backgroundActive && (
                  <IconButton
                    icon={Square}
                    label="停止后台任务"
                    disabled={activity.status === "cancelling"}
                    onClick={() =>
                      act("停止任务", async () =>
                        setActivity(
                          (await api(`${base}/jobs/cancel`, { method: "POST" }))
                            .job,
                        ),
                      )
                    }
                  />
                )}
              </div>
              <button
                className="activity-message"
                onClick={() => setModal("activity")}
              >
                {activityError || activity?.message}
                <ChevronRight size={13} />
              </button>
              {activity?.pendingComments && (
                <small>新批注已进入下一轮队列</small>
              )}
              {activity?.result?.warning && (
                <p className="warning-text">{activity.result.warning}</p>
              )}
              <ol>
                {activity?.events.slice(-3).map((event, index) => (
                  <li key={index}>
                    <time>
                      {new Date(event.time).toLocaleTimeString("zh-CN", {
                        hour12: false,
                      })}
                    </time>
                    <span>{event.message}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}
          <div className="review-tabs">
            <button
              className={tab === "comments" ? "active" : ""}
              onClick={() => setTab("comments")}
            >
              <MessageSquare size={15} />
              批注<span>{openCount}</span>
            </button>
            <button
              className={tab === "changes" ? "active" : ""}
              onClick={() => setTab("changes")}
            >
              <GitCompareArrows size={15} />
              修订日志
            </button>
            <IconButton
              icon={History}
              label="版本历史"
              onClick={() => setModal("history")}
            />
            <button className={tab === "reviewers" ? "active" : ""} onClick={()=>setTab("reviewers")}><Users size={15}/>审稿人</button>
            <IconButton icon={Image} label="图示工作区" className={`icon-button ${tab==="figures"?"active":""}`} onClick={()=>setTab("figures")}/>
          </div>
          {tab === "comments" ? (
            <>
              <div className="comments-filter">
                <select
                  aria-label="批注筛选"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="open">待处理批注</option>
                  <option value="resolved">已解决批注</option>
                  <option value="all">全部批注</option>
                </select>
                <IconButton
                  icon={Plus}
                  label={body.trim() ? "继续编辑批注" : "添加全文批注"}
                  disabled={!project}
                  onClick={(e) => {
                    const rect = e.currentTarget.getBoundingClientRect();
                    if (!body.trim()) setAnchor({ quote: "", pdfRevision: null });
                    setReaderPopup({mode:"comment",placement:{x:rect.left,top:rect.top,bottom:rect.bottom}});
                  }}
                />
              </div>
              <div className="comment-list">
                {visibleComments.length ? (
                  visibleComments.map((c) => (
                    <article
                      key={c.id}
                      className={`comment ${selected === c.id ? "selected" : ""}`}
                      onClick={() => selectComment(c)}
                    >
                      <div className="comment-meta">
                        <span
                          className={`comment-avatar ${c.author === "ai" ? "ai" : ""}`}
                        >
                          {c.author === "ai" ? <Sparkles size={13} /> : c.actor?.name?.slice(0,1) || "?"}
                        </span>
                        <strong>
                          {c.author === "ai" ? "AI Reviewer" : c.actor?.name || "历史共享账号"}
                        </strong>
                        <span className={`severity ${c.severity}`}>
                          {
                            {
                              critical: "必须修",
                              major: "建议修",
                              minor: "文字优化",
                            }[c.severity]
                          }
                        </span>
                      </div>
                      <div className="comment-location">
                        {c.page ? `第 ${c.page} 页` : c.file || "全文"}
                        {c.pdfRevision &&
                          c.pdfRevision !== project.pdfRevision && (
                            <span> · 旧版定位</span>
                          )}
                        {c.certainty && (
                          <span>
                            {" "}
                            ·{" "}
                            {
                              {
                                confirmed: "已确认",
                                conditional: "有条件",
                                unverified: "待核验",
                              }[c.certainty]
                            }
                          </span>
                        )}
                      </div>
                      {c.quote && <blockquote>{c.quote}</blockquote>}
                      {c.title && (
                        <strong className="finding-title">{c.title}</strong>
                      )}
                      <p>{c.body}</p>
                      {c.addressed && (
                        <small className="addressed">有修改记录，待你核实；尚未解决</small>
                      )}
                      {c.status==="open"&&!c.addressed&&<IconButton icon={Sparkles} label="仅修改此批注" disabled={!!busy||!!backgroundActive} onClick={e=>{e.stopPropagation();setRevisionCommentIds([c.id]);setAiMode("revise");setInstructions("");setConsent(false);setModal("ai");}}/>}
                      {c.addressed && c.status==="open" && c.author==="you" && <IconButton icon={RotateCcw} label="继续修改此批注" disabled={!!busy || !!backgroundActive} onClick={e=>{e.stopPropagation();act("继续修改",async()=>setProject(await api(`${base}/comments/${c.id}`,{method:"PATCH",body:{status:"open",retry:true}})));}}/>}
                      <button
                        className="resolve-button"
                        disabled={!!busy}
                        onClick={(e) => {
                          e.stopPropagation();
                          act("更新批注", async () =>
                            setProject(
                              await api(`${base}/comments/${c.id}`, {
                                method: "PATCH",
                                body: {
                                  status:
                                    c.status === "resolved"
                                      ? "open"
                                      : "resolved",
                                },
                              }),
                            ),
                          );
                        }}
                      >
                        {c.status === "resolved" ? (
                          <RotateCcw size={13} />
                        ) : (
                          <Check size={13} />
                        )}
                        {c.status === "resolved" ? "重新打开" : "标记已解决"}
                      </button>
                    </article>
                  ))
                ) : (
                  <div className="empty-comments">
                    <MessageSquare size={27} strokeWidth={1.3} />
                    <strong>
                      {filter === "resolved"
                        ? "暂无已解决批注"
                        : "暂无待处理批注"}
                    </strong>
                  </div>
                )}
              </div>
            </>
          ) : tab === "figures" ? (
            project && <FigurePanel project={project} api={api} activity={activity} onStarted={setActivity} onApplied={()=>openProject(project.id)}/>
          ) : tab === "reviewers" ? (
            project && <PeerReviewPanel project={project} anchor={anchor} api={api} activity={activity} onStarted={setActivity} skillIds={skillIds}/>
          ) : (
            <div className="changes-list">
              {project?.detailsLoaded === false ? <p role="status">{detailsError || "正在读取修订详情…"}</p> : <>
              {project?.proposals.length ? (
                project.proposals.map((proposal) => (
                  <article className="proposal" key={proposal.id}>
                    <div className="section-label">
                      <span>
                        {proposal.status === "pending"
                          ? "待确认修改"
                          : proposal.status === "applied"
                            ? "已应用 · 编译通过"
                            : "已拒绝"}
                      </span>
                      <span>{proposal.patches.length} 处</span>
                    </div>
                    <p>
                      {proposal.status === "applied"
                        ? `本轮 ${proposal.patches.length} 处修改已保存为新版本，PDF 编译通过。`
                        : proposal.summary}
                    </p>
                    <small className="muted">{proposal.model||"旧记录未保存模型"} · {proposal.vendor||proposal.provider||"提供商未记录"} · {new Date(proposal.appliedAt||proposal.time).toLocaleString("zh-CN")}{proposal.gitCommit?` · Git ${proposal.gitCommit.slice(0,10)}`:""}{proposal.resultRevision && proposal.resultRevision!==project.revision?" · 历史修改":""}</small>
                    {proposal.collaboration && <details><summary>联合写作与交叉复核记录</summary>{proposal.collaboration.stages.map((stage,index)=><details className="collaboration-stage" key={index}><summary>{index+1}. {stage.vendor} · {stage.model} · {stage.role}</summary><p>{stage.summary}</p></details>)}</details>}
                    {proposal.commentLog?.length>0&&<details open><summary>已归档批注 · {proposal.commentLog.length}</summary>{proposal.commentLog.map(comment=><div className="archived-comment" key={comment.id}><small className="muted">{new Date(comment.archivedAt).toLocaleString("zh-CN")} · 已修改，待核实</small>{comment.quote&&<blockquote>{comment.quote}</blockquote>}<p>{comment.body}</p>{project.comments.some(c=>c.id===comment.id&&c.archivedAt&&c.archiveProposalId===proposal.id)&&<IconButton icon={RotateCcw} label="恢复到批注" disabled={!!busy||!!backgroundActive} onClick={()=>act("恢复批注",async()=>{setProject(await api(`${base}/comments/${comment.id}`,{method:"PATCH",body:{status:"open",archived:false}}));setTab("comments");})}/>}</div>)}</details>}
                    {proposal.lastError && <p className="warning-text">未应用：{proposal.lastError}</p>}
                    {proposal.status==="pending"&&revisionProvider?.finalReviewer&&proposal.collaboration?.workflow!==revisionProvider.workflow&&<p className="warning-text">此历史提案未经过当前三方复核，需重新提交批注。</p>}
                    {proposal.patches.map((patch, i) => (
                      <details className="patch" key={i}>
                        <summary>{patch.file}</summary>
                        {patch.unlinkedCommentIds?.length > 0 && (
                          <p className="warning-text">
                            有批注编号无法关联，本处修改需人工核对；未自动关联其他批注。
                          </p>
                        )}
                        <pre className="removed">{patch.before}</pre>
                        <pre className="added">{patch.after}</pre>
                        <p>{patch.reason}</p>
                      </details>
                    ))}
                    {proposal.status === "pending" && (
                      <div className="proposal-actions">
                        <button
                          className="secondary"
                          disabled={!!busy}
                          onClick={() =>
                            act("拒绝修改", async () =>
                              setProject(
                                await api(
                                  `${base}/proposals/${proposal.id}/reject`,
                                  { method: "POST" },
                                ),
                              ),
                            )
                          }
                        >
                          拒绝
                        </button>
                        <button
                          className="primary"
                          disabled={
                            !!busy || proposal.revision !== project.revision || (revisionProvider?.finalReviewer&&proposal.collaboration?.workflow!==revisionProvider.workflow)
                          }
                          onClick={() =>
                            act("应用修改并编译", async () =>
                              setProject(
                                await api(
                                  `${base}/proposals/${proposal.id}/apply`,
                                  { method: "POST" },
                                ),
                              ),
                            )
                          }
                        >
                          <Check size={14} />
                          接受并编译
                        </button>
                      </div>
                    )}
                    {proposal.status === "pending" &&
                      proposal.revision !== project.revision && (
                        <p className="muted">建议已过期，请重新生成。</p>
                      )}
                  </article>
                ))
              ) : (
                <div className="empty-comments">
                  <GitCompareArrows size={28} />
                  <strong>暂无修改建议</strong>
                </div>
              )}
              {project?.reports.map((r) => (
                <article className="review-report" key={r.id}>
                  <div className="section-label">
                    {{ applied: "已应用", proposed: "待确认", no_changes: "未修改", reviewed: "审稿" }[r.outcome] || "审稿记录"} · {new Date(r.time).toLocaleString("zh-CN")}
                  </div>
                  <details>
                    <summary>模型生成时的原始输出</summary>
                    <p>{r.summary}</p>
                    <small>{r.coverage}</small>
                  </details>
                </article>
              ))}
              </>}
            </div>
          )}
          {!["reviewers","figures"].includes(tab) && <div className="review-bottom">
            <label className="auto-toggle">
              <span>保存批注后自动修订</span>
              <input
                type="checkbox"
                role="switch"
                aria-label="保存批注后自动修订"
                checked={!!project?.automation?.enabled}
                disabled={!project || !!busy}
                onChange={(e) => {
                  if (e.target.checked) {
                    setAutoConsent(false);
                    setStartExisting(false);
                    setModal("automation");
                  } else
                    act("关闭自动修订", async () =>
                      setProject(
                        await api(`${base}/automation`, {
                          method: "POST",
                          body: { enabled: false },
                        }),
                      ),
                    );
                }}
              />
            </label>
            <div className="skill-summary">
              <span>
                <span className="status-dot green" />
                {skillIds.length} 个 Skills 已启用
              </span>
              <button
                className="text-button"
                onClick={() => setModal("skills")}
              >
                管理
                <ChevronRight size={12} />
              </button>
            </div>
            <div className="ai-buttons">
              <button
                className="secondary"
                disabled={
                  !project || !!busy || !!backgroundActive || !skillIds.length
                }
                onClick={() => {
                  setAiMode("review");
                  setConsent(false);
                  setVenue(project.venue);
                  setModal("ai");
                }}
              >
                <Sparkles size={14} />
                全面审稿
              </button>
              <button
                className="primary"
                disabled={
                  !project || !!busy || !!backgroundActive || !skillIds.length
                }
                onClick={() => {
                  setAiMode("revise");
                  setRevisionCommentIds(null);
                  setConsent(false);
                  setVenue(project.venue);
                  setModal("ai");
                }}
              >
                <GitCompareArrows size={14} />
                局部批注修改
              </button>
            </div>
          </div>}
        </aside>
      </main>
      {project && readerPopup && <ReaderPopup placement={readerPopup.placement} mode={readerPopup.mode} close={() => setReaderPopup(null)}>
        <header className="reader-popup-heading">
          <strong>{readerPopup.mode === "translate" ? <><Languages size={15}/> 中文译文</> : <><MessageSquare size={15}/> 修改意见</>}</strong>
          <IconButton icon={X} label="关闭浮窗" onClick={() => setReaderPopup(null)}/>
        </header>
        {readerPopup.mode === "translate" ? <>
          <div className="translation-heading">
            <select aria-label="翻译引擎" value={translationEngine} onChange={e=>setTranslationEngine(e.target.value)}>
              <option value="browser">本地翻译 · 不用模型额度</option>
              <option value="fast" disabled={!health?.fastTranslation}>快速云翻译 · {health?.translationModel || "未配置"}</option>
              <option value="quality">论文模型精译 · 使用额度</option>
            </select>
            <IconButton icon={translating ? LoaderCircle : RotateCcw} label="重新翻译" disabled={!passage || translating} onClick={translateSelection}/>
          </div>
          <p className={translationError ? "warning-text" : "translation-text"} aria-live="polite">
            {translationError || (translating ? translationProgress || "正在翻译…" : translation) || "待翻译"}
          </p>
          <button className="popup-comment-action" onClick={() => setReaderPopup({...readerPopup,mode:"comment"})}><MessageSquare size={14}/> 添加修改意见</button>
          <button className="popup-comment-action" onClick={() => {setTab("reviewers");setReaderPopup(null);}}><Users size={14}/> 请审稿人看这段</button>
        </> : <div className="composer">
          {commentAnchor && <div className="anchor-label"><MapPin size={12}/><span>{commentAnchor.page ? `第 ${commentAnchor.page} 页` : "全文批注"}</span><IconButton icon={X} label="取消定位" onClick={() => {
            setAnchor(null); setDraftAnchor(null);
            localStorage.setItem(`autopaperreview-draft:${project.id}`,JSON.stringify({body,anchor:null}));
          }}/></div>}
          {commentAnchor?.quote && <blockquote className="popup-quote">{commentAnchor.quote}</blockquote>}
          <textarea ref={noteInput} aria-label="批注意见" placeholder="写下你的修改意见…" value={body} onChange={e => {
            setBody(e.target.value);
            setDraftAnchor(commentAnchor);
            localStorage.setItem(`autopaperreview-draft:${project.id}`,JSON.stringify({body:e.target.value,anchor:commentAnchor}));
          }}/>
          <div className="composer-bottom">
            <span>{project.automation?.enabled ? "保存后自动修订" : "保存后确认自动修订"}</span>
            <button className="send-note" disabled={!body.trim() || !!busy} onClick={() => act("保存批注",addComment)}><Plus size={14}/> 提交并修改</button>
          </div>
        </div>}
      </ReaderPopup>}
      <footer className="status-bar">
        <span>
          {busy ? (
            <>
              <LoaderCircle size={12} className="spin" />
              {busy}…
            </>
          ) : backgroundActive ? (
            <>
              <LoaderCircle size={12} className="spin" />
              {activity.title} · 后台运行中
            </>
          ) : (
            <>
              <span className="status-dot green" />
              工作区就绪
            </>
          )}
        </span>
        <span>{project?.venue || "目标会议未设置"}</span>
        <span className="footer-ai" title={revisionAI?.displayName||revisionAI?.model}>
          <span className={`status-dot ${health?.ai ? "green" : ""}`} />
          {health?.ai
            ? revisionProvider?.collaborator ? `${revisionProvider.finalReviewer?"三方写作":"联合修订"} · ${revisionProvider.displayName||revisionProvider.model} + ${revisionProvider.collaborator.displayName}${revisionProvider.finalReviewer?` + ${revisionProvider.finalReviewer.displayName}`:revisionProvider.collaborator.localAuth?" · 本机 Claude":""}` : revisionAI?.backup ? `备用修订 · ${revisionAI.vendor} · ${revisionAI.displayName||revisionAI.model}` : `${health.provider === "codex" ? "Codex · " : ""}${health.model}`
            : "AI 未连接"}
        </span>
      </footer>
      {modal === "activity" && (
        <Modal title="后台修订记录" close={() => setModal("")} wide>
          {activity && (
            <>
              <p className="muted">
                {activity.title} · {activity.status} · {activity.id.slice(0, 8)}
              </p>
              <ol className="activity-log">
                {activity.events.map((event, index) => (
                  <li key={index}>
                    <time>{new Date(event.time).toLocaleString("zh-CN")}</time>
                    <strong>{event.message}</strong>
                    {event.files?.map((file) => (
                      <code key={file}>{file}</code>
                    ))}
                  </li>
                ))}
              </ol>
            {activity.log && <pre className="log">{activity.log}</pre>}
            {activity.result?.warning && (
                <p className="warning-text">{activity.result.warning}</p>
              )}
              <div className="modal-actions">
                <button
                  className="secondary"
                  onClick={() => {
                    setTab("changes");
                    setModal("");
                  }}
                >
                  <GitCompareArrows size={14} />
                  查看修改差异
                </button>
              </div>
            </>
          )}
        </Modal>
      )}
      {modal === "bibliography" && (
        <Modal title="文献与 Bib 核查" close={() => setModal("")} wide>
          <p className="disclosure">本地检查随稿件版本自动更新。联网核查仅向 Crossref 发送 Bib 标题、作者和 DOI，不发送论文正文；不会自动改写 Bib。未收录、网络失败或候选匹配均不代表文献虚假。</p>
          {bibError && <p className="warning-text">{bibError}</p>}
          {!bibData ? <p>正在读取文献数据库…</p> : <>
            <div className="bib-summary"><strong>{bibData.entries.length} 条文献</strong><span>{bibData.issues.length} 项源码问题</span><span>{bibData.audit ? `上次联网核查：${new Date(bibData.audit.checked).toLocaleString("zh-CN")}` : "尚未联网核查"}</span></div>
            {bibData.issues.map((issue,i) => <p className="warning-text" key={i}><code>{issue.file}</code> · {issue.message}</p>)}
            <div className="bib-list">{bibData.entries.map((entry,i) => {
              const verification = bibData.audit?.entries[i]?.verification;
              return <article className="bib-entry" key={`${entry.file}:${entry.key}:${i}`}>
                <div className="bib-entry-heading"><code>{entry.key}</code><span>{entry.year}</span>{entry.url && <a href={entry.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={13}/>打开文章</a>}</div>
                <strong>{entry.title || "无标题"}</strong>
                <p>{entry.authors.join("、")}</p>
                {entry.problems.map((problem,j) => <p className="warning-text" key={j}>{problem}</p>)}
                <p className={verification?.status === "verified" ? "bib-verified" : "bib-unverified"}>{verification ? ({verified:"元数据一致", mismatch:"元数据冲突", candidate:"仅候选，未确认", unverified:"未核实"}[verification.status]) : "未联网核实"}{verification ? ` · ${verification.detail}` : ""}</p>
                {verification?.url && <a href={verification.url} target="_blank" rel="noopener noreferrer">{verification.status === "verified" ? "Crossref 记录" : "查看候选记录"}</a>}
              </article>;
            })}</div>
            <label className="consent"><input type="checkbox" checked={bibConsent} onChange={e => setBibConsent(e.target.checked)}/>同意发送文献元数据至 Crossref 进行核查</label>
            <div className="modal-actions"><button className="primary" disabled={!bibConsent || !!busy || !!backgroundActive || !bibData.entries.length} onClick={() => act("开始 Bib 核查", async () => {
              setActivity((await api(`${base}/bibliography/audit`, {method:"POST", body:{consent:true}})).job);
              setModal("");
            })}><BookOpen size={14}/>后台核查全部 Bib</button></div>
          </>}
        </Modal>
      )}
      {modal === "automation" && (
        <Modal title="自动按批注修订" close={() => setModal("")}>
          <p className="disclosure">
            开启后，新保存的用户批注会在后台合并处理。源码、批注及日志将发送到{" "}
            {revisionAI?.provider === "codex" ? "Codex 云端模型" : revisionAI?.apiOrigin || "兼容 API"}
            ，使用当前账户额度。{revisionProvider?.collaborator ? `${revisionDisclosure}任一阶段失败均不应用修改，格式校验失败各阶段最多追加一次纠正调用。` : "格式或原文定位失败时最多额外请求一次模型。"}仅修改当前 TeX 源码，可能增加费用。修改在临时目录编译成功后自动生成本地新版本，保留差异和回退记录；已修改批注移入修订日志，未处理意见仍留在批注栏，不等于科学问题已解决。
          </p>
          <div className="run-summary">
            <span>{revisionAI?.backup ? `备用 · ${revisionAI.vendor} · ` : ""}{revisionAI?.displayName||revisionAI?.model}</span>
            <span>{skillIds.length} 个 Skills</span>
            <span>
              {project?.overleaf?.autoPush
                ? "已开启 Overleaf 自动同步"
                : "仅修改本地副本"}
            </span>
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={startExisting}
              onChange={(e) => setStartExisting(e.target.checked)}
            />
            <span>同时处理现有未完成的用户批注</span>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={autoConsent}
              onChange={(e) => setAutoConsent(e.target.checked)}
            />
            <span>
              同意为此项目持续处理新批注并自动应用编译通过的修改，直到我关闭此开关。
            </span>
          </label>
          <div className="modal-actions">
            <button
              className="primary"
              disabled={
                !autoConsent || !health?.ai || !skillIds.length || !!busy
              }
              onClick={() =>
                act("开启自动修订", async () => {
                  setProject(
                    await api(`${base}/automation`, {
                      method: "POST",
                      body: {
                        enabled: true,
                        consent: true,
                        startNow: startExisting,
                        skillIds,
                      },
                    }),
                  );
                  setModal("");
                })
              }
            >
              <Check size={14} />
              开启自动修订
            </button>
          </div>
        </Modal>
      )}
      {modal === "overleaf" && (
        <Modal
          title="Overleaf Git 同步"
          close={() => {
            setSyncToken("");
            setModal("");
          }}
        >
          {project?.overleaf && (
            <p className="sync-status">
              <Check size={14} />
              已连接 · {project.overleaf.branch.replace("refs/heads/", "")}
              <small>
                {project.overleaf.lastSynced
                  ? `上次同步：${new Date(project.overleaf.lastSynced).toLocaleString("zh-CN")}`
                  : "尚未推送本地修改"}
              </small>
            </p>
          )}
          <label>
            Git 地址
            <input
              aria-label="Overleaf Git 地址"
              value={syncURL}
              onChange={(e) => setSyncURL(e.target.value)}
              placeholder="https://git@git.overleaf.com/项目ID"
            />
          </label>
          <label>
            Git token（首次填写，服务端加密保存）
            <input
              type="password"
              aria-label="Overleaf Git token"
              autoComplete="off"
              value={syncToken}
              onChange={(e) => setSyncToken(e.target.value)}
              placeholder="已认证可留空；更换 token 时重新填写"
            />
          </label>
          <p className="disclosure">
            仅向这个 Overleaf
            项目同步已成功编译的源文件，不同步批注和登录信息。检测到同一文件在两端都有修改时停止同步，不强制覆盖。token
            经认证后加密保存在服务器独立凭据目录，不写入项目、不发送给模型；退出登录或服务重启后仍可复用。团队成员可复用本项目凭据进行同步。凭据失效或撤销后需重新认证。
          </p>
          {project?.overleaf && <p className="disclosure">{project.overleafCredentialSaved ? "已加密保存 Git token，无需重复填写。" : "尚未保存 Git token；若系统 Git 凭据不可用，请填写一次并连接。"}</p>}
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={autoPush}
              onChange={(e) => setAutoPush(e.target.checked)}
            />
            <span>每次自动修订并编译成功后，自动同步至此 Overleaf 项目</span>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={syncConsent}
              onChange={(e) => setSyncConsent(e.target.checked)}
            />
            <span>确认该地址属于本论文，允许连接并按上述设置传输源码。</span>
          </label>
          {project?.overleaf?.lastError && (
            <p className="warning-text">{project.overleaf.lastError}</p>
          )}
          <div className="modal-actions" style={{flexWrap:"wrap"}}>
            {project?.overleaf && <button className="secondary" disabled={!!busy || !!backgroundActive} onClick={() => {
              if(!confirm("忘记此项目在服务器保存的 Git token，并关闭自动同步？不会撤销 Overleaf 端 token，也不会删除源码。")) return;
              act("忘记 Git 凭据",async()=>{setProject(await api(`${base}/overleaf/credentials`,{method:"DELETE"}));setSyncToken("");});
            }}>忘记 Git 凭据</button>}
            <button
              className="secondary"
              disabled={
                !syncConsent || !syncURL || !!busy || !!backgroundActive
              }
              onClick={() =>
                act("连接 Overleaf", async () => {
                  setProject(
                    await api(`${base}/overleaf/connect`, {
                      method: "POST",
                      body: {
                        url: syncURL,
                        token: syncToken || undefined,
                        autoPush,
                        consent: true,
                      },
                    }),
                  );
                  setSyncToken("");
                })
              }
            >
              <ExternalLink size={14} />
              连接 / 保存设置
            </button>
            <button
              className="primary"
              disabled={
                !project?.overleaf ||
                !syncConsent ||
                !!busy ||
                !!backgroundActive ||
                project.pdfRevision !== project.revision
              }
              onClick={() =>
                act("开始同步", async () => {
                  setActivity(
                    (
                      await api(`${base}/overleaf/push`, {
                        method: "POST",
                        body: { consent: true },
                      })
                    ).job,
                  );
                  setModal("");
                })
              }
            >
              <CloudUpload size={14} />
              同步已编译版本
            </button>
          </div>
        </Modal>
      )}
      {modal === "skills" && (
        <Modal title="审稿 Skills" close={() => setModal("")} wide>
          <div className="modal-intro">
            <span className="eyebrow">REVIEW TOOLKIT</span>
            <h3>严谨性先于润色</h3>
          </div>
          <div className="skills-grid">
            {health?.skills.map((s) => (
              <div
                className={`skill-card ${skillIds.includes(s.id) ? "enabled" : ""}`}
                key={s.id}
              >
                <div className="skill-top">
                  <span className="skill-icon">
                    <BookOpen size={18} />
                  </span>
                  <input
                    type="checkbox"
                    checked={skillIds.includes(s.id)}
                    disabled={s.required || health.skills.some(parent=>skillIds.includes(parent.id)&&parent.requires?.includes(s.id))}
                    aria-label={s.name}
                    onChange={(e) =>
                      setSkillIds(
                        e.target.checked
                          ? [...new Set([...skillIds, s.id,...(s.requires||[])])]
                          : skillIds.filter((id) => id !== s.id),
                      )
                    }
                  />
                </div>
                <strong>{s.name}</strong>
                <p>{s.description}</p>
                <small>{s.source}{s.required ? " · 始终启用" : ""}</small>
                {s.sourceURL&&<a href={s.sourceURL} target="_blank" rel="noreferrer">原文出处 <ExternalLink size={11}/></a>}
              </div>
            ))}
          </div>
          <div className="source-links">
            {sources.map(([name, url]) => (
              <a key={name} href={url} target="_blank" rel="noreferrer">
                {name}
                <ExternalLink size={11} />
              </a>
            ))}
          </div>
        </Modal>
      )}
      {modal === "settings" && (
        <Modal title="模型设置" close={() => setModal("")}>
          {health?.settingsLocked ? <div><p>模型由团队管理员配置。</p><p>{health.apiOrigin} · {health.model}</p>{revisionAI?.backup && <p>备用修订：{revisionAI.vendor} · {revisionAI.displayName||revisionAI.model}（{revisionAI.model}）</p>}<p>快速翻译：{health.translationModel || "未配置"}</p><p className="disclosure">云端请求会将选定内容发送至上述第三方服务，并使用团队额度。API Key 不会返回浏览器。</p></div> : <form
            onSubmit={(e) => {
              e.preventDefault();
              act("保存模型设置", async () => {
                const h = await api("/settings", {
                  method: "POST",
                  body: {
                    provider,
                    apiKey: provider === "openai" ? key : undefined,
                    model,
                  },
                });
                setHealth({ ...health, ...h });
                setKey("");
                setModal("");
              });
            }}
          >
            <label>
              连接方式
              <select
                aria-label="连接方式"
                value={provider}
                onChange={(e) => {
                  setProvider(e.target.value);
                  setModel(
                    e.target.value === "codex" ? "gpt-6.1-sol" : "gpt-4.1",
                  );
                  setConsent(false);
                }}
              >
                <option value="codex">
                  本机 Codex · ChatGPT 登录（无需 API Key）
                </option>
                <option value="openai">OpenAI API</option>
              </select>
            </label>
            {provider === "openai" && (
              <label>
                OpenAI API Key
                <input
                  type="password"
                  autoComplete="off"
                  placeholder={
                    health?.hasApiKey ? "已配置，留空保持不变" : "sk-…"
                  }
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                />
              </label>
            )}
            <label>
              模型 ID
              <input
                required
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
            </label>
            <p className="disclosure">
              {provider === "codex"
                ? "复用本机 Codex CLI 的 ChatGPT 登录，无需填写 API Key。GPT-6.1 仍在云端推理，并非离线本地模型；会消耗你的 Codex 账户额度。模型仅生成建议，不直接改写项目文件。"
                : "Key 仅保存在本机服务进程内存中。审稿和修订将把论文源码、批注和编译日志发送至 OpenAI；每次运行前需确认。"}
            </p>
            <div className="modal-actions">
              <button className="primary" disabled={!!busy}>
                <Save size={14} />
                保存设置
              </button>
            </div>
          </form>}
        </Modal>
      )}
      {modal === "import" && (
        <Modal title="导入 Overleaf 项目" close={() => setModal("")}>
          <div className="upload-summary">
            <FileText size={28} />
            <strong>{uploadFile?.name}</strong>
            <span>{((uploadFile?.size || 0) / 1024 / 1024).toFixed(2)} MB</span>
          </div>
          <p className="disclosure">
            使用 Overleaf 的 Download Source 导出的
            ZIP。当前为文件导入，不会自动连接或同步你的 Overleaf 账户。
          </p>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={trusted}
              onChange={(e) => setTrusted(e.target.checked)}
            />
            <span>
              我信任此项目源码。同意在{health?.shared && !health?.localExecution ? "服务器" : "本机"}运行 TeX（已禁用 shell
              escape，但不是强隔离沙箱）。
            </span>
          </label>
          <div className="modal-actions">
            <button
              className="primary"
              disabled={!trusted || !!busy}
              onClick={() => act("导入并编译", () => importProject())}
            >
              <Upload size={14} />
              导入并编译
            </button>
          </div>
        </Modal>
      )}
      {modal === "ai" && (
        <Modal
          title={aiMode === "review" ? "全面审稿" : "按批注修改"}
          close={() => setModal("")}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(
                aiMode === "review" ? "AI 审稿" : "生成修改建议",
                async () => {
                  await api(base, { method: "PATCH", body: { venue } });
                  await startBackground(aiMode,aiMode==="revise"&&revisionCommentIds?{commentScope:"allPending",commentIds:revisionCommentIds}:{});
                },
              );
            }}
          >
            <label>
              目标会议 / 年份 / Track
              <input
                value={venue}
                onChange={(e) => setVenue(e.target.value)}
                placeholder="例如 ICLR 2027 · Main Conference"
              />
            </label>
            <label>
              本轮要求
              <textarea
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                placeholder={
                  aiMode === "review"
                    ? "特别关注的问题、官方投稿要求或证据材料…"
                    : "本轮优先处理哪些意见…"
                }
              />
            </label>
            <div className="run-summary">
              <span>{skillIds.length} 个 Skills</span>
              <span>{aiMode==="revise"&&revisionCommentIds?revisionCommentIds.length:openCount} 条待处理意见</span>
              <span>{dialogAI?.backup ? `${dialogAI.vendor} · ` : ""}{dialogAI?.displayName||dialogAI?.model}</span>
            </div>
            {aiMode === "revise" && health?.localRevisionOnly && <p className="disclosure">{revisionCommentIds?"本轮仅处理选定批注，其余意见保持待处理。":"全局修改已暂停。仅处理选中句子的用户批注，不调整全文结构。"}</p>}
            <p className="disclosure">
              仅源码审查，不包含 PDF
              视觉审稿和联网文献核验。修改对象是当前 TeX 源码，PDF 选文仅用于定位。{aiMode === "revise" && revisionProvider?.collaborator ? `${revisionDisclosure}各阶段格式校验失败最多追加一次纠正调用；任一阶段失败都不应用。` : "格式或定位失败最多额外请求一次模型。"}可能增加费用。{aiMode==="revise"?"提交后在后台应用通过校验的 TeX 修改，编译成功后保存版本和日志，并归档有实际修改的批注；失败或未修改的批注不会归档。":"审稿仅保存意见，不改写正文。"}
            </p>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
              />
              <span>
                {dialogAI?.provider === "codex"
                  ? "同意通过本机 Codex 将本轮项目源码、批注和日志发送至云端模型，使用我的 Codex 账户额度。"
                  : `同意本轮将项目源码、批注与编译日志发送至 ${dialogAI?.apiOrigin || "兼容 API"}。`}
              </span>
            </label>
            {!health?.ai && (
              <p className="warning-text">
                {health?.provider === "codex"
                  ? health.cli?.message ||
                    "请在终端运行 codex login 后刷新页面。"
                  : "请先在模型设置中配置 API Key。"}
              </p>
            )}
            <div className="modal-actions">
              <button
                type="submit"
                className="primary"
                disabled={!consent || !health?.ai || !!busy}
              >
                <Sparkles size={14} />
                {busy ? "处理中…" : "开始本轮"}
              </button>
            </div>
          </form>
        </Modal>
      )}
      {modal === "source" && source && (
        <Modal
          title={source.file}
          close={() => {
            if (window.confirm("关闭源码编辑器？未保存的修改将丢失。")) {
              setModal("");
              setSource(null);
            }
          }}
          wide
        >
          <textarea
            className="source-editor"
            aria-label="LaTeX 源码"
            spellCheck="false"
            value={sourceContent}
            onChange={(e) => setSourceContent(e.target.value)}
          />
          <div className="modal-actions">
            <button
              className="primary"
              disabled={!!busy}
              onClick={() =>
                act("保存源码", async () => {
                  setProject(
                    await api(`${base}/source`, {
                      method: "PUT",
                      body: { ...source, content: sourceContent },
                    }),
                  );
                  setModal("");
                  setSource(null);
                })
              }
            >
              <Save size={14} />
              保存新版本
            </button>
          </div>
        </Modal>
      )}
      {modal === "log" && (
        <Modal title="编译日志" close={() => setModal("")} wide>
          <pre className="log">
            {failureLog || project?.log || "暂无编译日志"}
          </pre>
          <button
            className="secondary"
            onClick={() => act("刷新日志", () => openProject(project.id))}
          >
            刷新日志
          </button>
        </Modal>
      )}
      {modal === "assets" && (
        <Modal title="项目资源" close={() => setModal("")}>
          <p className="disclosure">
            图片、字体和 PDF
            等二进制资源已随项目保存，编译时按原路径加载。可通过导出源码 ZIP
            获取原文件。
          </p>
        </Modal>
      )}
      {modal === "history" && (
        <Modal title="版本历史" close={() => setModal("")}>
          <p className="muted">{project?.sourceGit?.enabled?"本地 Git 历史已启用":"尚未建立本地 Git 历史"} · {project?.overleaf?.lastSynced?`Overleaf 最近同步 ${new Date(project.overleaf.lastSynced).toLocaleString("zh-CN")}`:project?.overleaf?"Overleaf 已连接，尚未同步":"Overleaf 未连接"}</p>
          {!project?.sourceGit?.enabled && <button className="secondary" disabled={!!busy || !!backgroundActive} onClick={()=>act("建立 Git 历史",async()=>setProject(await api(`${base}/history/git`,{method:"POST"})))}><GitCompareArrows size={14}/>建立 Git 历史</button>}
          <div className="history-list">
            {project?.history.map((r, i) => (
              <div className="history-row" key={r.id}>
                <span className="history-node" />
                <div>
                  <strong>
                    v{project.history.length - i} · {r.label}
                  </strong>
                  <small>{new Date(r.time).toLocaleString("zh-CN")} · {r.initiatedBy?.name || "历史共享账号 / 系统"}</small>
                  <small>{r.provenance?.model|| (r.provenance?.kind==="manual"?"手动编辑":r.provenance?.kind==="restore"?"恢复版本":"旧记录，模型未记录")}{r.gitCommit?` · Git ${r.gitCommit.slice(0,10)}`:""}</small>
                </div>
                {r.gitCommit && <IconButton icon={GitCompareArrows} label="查看此版本 Git 差异" disabled={!!busy} onClick={()=>act("读取 Git 差异",async()=>setHistoryDiff(await api(`${base}/history/${r.id}/diff`)))}/>}
                {i === 0 ? (
                  <span className="current-label">当前</span>
                ) : (
                  <IconButton
                    icon={RotateCcw}
                    label="恢复此版本"
                    disabled={!!busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          "恢复为一个新版本？现有历史和批注都会保留。",
                        )
                      )
                        act("恢复版本", async () => {
                          setProject(
                            await api(`${base}/restore/${r.id}`, {
                              method: "POST",
                            }),
                          );
                          setModal("");
                        });
                    }}
                  />
                )}
              </div>
            )) || <p className="muted">暂无版本</p>}
          </div>
          {historyDiff && <section><strong>Git {historyDiff.commit.slice(0,10)}</strong><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",maxHeight:360,overflow:"auto",fontSize:12}}>{historyDiff.diff}</pre></section>}
          <details><summary>任务记录 · {jobHistory.length}</summary>{historyError && <p className="warning-text">{historyError}</p>}{jobHistory.map(job=><div className="history-row" key={job.id}><div><strong>{job.title} · {job.status==="no_changes"?"未修改":job.status==="awaiting_approval"?"待确认，未应用":job.status==="failed"?"失败，未完成":job.status==="completed"?(job.result?.outcome==="applied"?"已修改":"任务结束"):job.status}</strong><small>{job.model||"模型未记录"} · {new Date(job.created).toLocaleString("zh-CN")}</small><small>{job.message}</small></div></div>)}</details>
        </Modal>
      )}
      {modal === "projects" && (
        <Modal title="项目" close={() => setModal("")}>
          <div className="project-list">
            {projects.map((p) => (
              <button
                key={p.id}
                onClick={() =>
                  act("打开项目", async () => {
                    await openProject(p.id);
                    setModal("");
                  })
                }
              >
                <FolderOpen size={19} />
                <span>
                  <strong>{p.name}</strong>
                  <small>{new Date(p.updated).toLocaleString("zh-CN")}</small>
                </span>
                <ChevronRight size={16} />
              </button>
            ))}
          </div>
          <div className="modal-actions">
            <button
              className="secondary"
              disabled={!!busy}
              onClick={() => act("创建并编译示例", () => importProject(true))}
            >
              <Plus size={14} />
              示例项目
            </button>
          </div>
        </Modal>
      )}
      {modal === "export" && (
        <Modal title="导出" close={() => setModal("")}>
          <div className="export-list">
            <a href={`/api${base}/export`}>
              <FolderOpen />
              LaTeX 源码 ZIP
              <Download size={16} />
            </a>
            {project?.pdfRevision && (
              <a
                href={`/api${base}/pdf/${project.pdfRevision}`}
                download="manuscript.pdf"
              >
                <FileText />
                PDF{project.pdfRevision !== project.revision && "（旧版）"}
                <Download size={16} />
              </a>
            )}
            <a href={`/api${base}/report`}>
              <MessageSquare />
              批注与审稿记录 JSON
              <Download size={16} />
            </a>
          </div>
        </Modal>
      )}
    </div>
  );
}

function SessionGate() {
  const [session,setSession] = useState(null), [username,setUsername] = useState(""), [password,setPassword] = useState(""), [error,setError] = useState(""), [pending,setPending] = useState(false);
  const [register,setRegister]=useState(false),[displayName,setDisplayName]=useState(""),[invitePassword,setInvitePassword]=useState("");
  useEffect(()=>{api("/session").then(setSession).catch(e=>setError(e.message));},[]);
  useEffect(()=>{const expired=()=>setSession(s=>({...s,authenticated:false,shared:true}));window.addEventListener("autopaperreview-session-expired",expired);return()=>window.removeEventListener("autopaperreview-session-expired",expired);},[]);
  if (!session || !session.authenticated) return <main className="login-page"><BookOpen size={32}/><h1>Autopaperreview</h1><form onSubmit={async e=>{
    e.preventDefault(); setPending(true); setError("");
    try {const result=await api("/session",{method:"POST",body:{username,password,register,displayName,invitePassword}}); setPassword("");setInvitePassword("");setSession(result);} catch(e) {setError(e.message);} finally {setPending(false);}
  }}><label>个人用户名<input autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)} required/></label>{register&&<label>显示姓名<input value={displayName} maxLength={40} onChange={e=>setDisplayName(e.target.value)} required/></label>}<label>个人密码<input type="password" autoComplete={register?"new-password":"current-password"} minLength={register?12:undefined} value={password} onChange={e=>setPassword(e.target.value)} required/></label>{register&&<label>团队邀请密码<input type="password" autoComplete="off" value={invitePassword} onChange={e=>setInvitePassword(e.target.value)} required/></label>}{error && <p className="warning-text" role="alert">{error}</p>}<button className="primary" disabled={pending || !session}>{pending ? "正在处理" : register?"创建个人账号":"登录"}</button>{session?.memberAccounts&&<button type="button" className="quiet" onClick={()=>{setRegister(!register);setError("");}}>{register?"返回登录":"首次使用：创建个人账号"}</button>}</form><p>私有团队工作区 · 成员共享项目与模型额度</p></main>;
  return <App member={session.member}/>;
}
createRoot(document.getElementById("root")).render(<SessionGate />);
