import React,{useEffect,useState} from "react";
import {Image,Play,Download,RefreshCw,Check,FileSearch,ExternalLink} from "lucide-react";

const names={comparison:"前后对照",layers:"分层框架","pipeline-inset":"流程与细节",architecture:"模块架构","decision-tree":"决策树","worked-example":"实例引导"};
export function FigurePanel({project,api,activity,onStarted,onApplied}) {
  const [data,setData]=useState(null),[error,setError]=useState(""),[busy,setBusy]=useState(false),[target,setTarget]=useState(""),[kind,setKind]=useState("diagram"),[model,setModel]=useState("gpt-6.1-sol"),[comment,setComment]=useState(""),[consent,setConsent]=useState(false),[astra,setAstra]=useState(false),[selected,setSelected]=useState(""),[visual,setVisual]=useState(false);
  const base=`/projects/${project.id}/figures`,active=["queued","running","cancelling"].includes(activity?.status);
  const load=async()=>{const next=await api(base);setData(next);};
  useEffect(()=>{let stopped=false;setData(null);setSelected("");setComment("");setTarget("");setVisual(false);api(base).then(d=>{if(!stopped)setData(d);}).catch(e=>{if(!stopped)setError(e.message);});return()=>{stopped=true;};},[project.id,project.revision]);
  useEffect(()=>{if(activity&&!active)load().catch(e=>setError(e.message));},[activity?.id,activity?.status]);
  const task=async(fn)=>{setBusy(true);setError("");try{await fn();}catch(e){setError(e.message);}finally{setBusy(false);}};
  const record=data?.records.find(r=>r.id===selected),stale=record&&record.revision!==project.revision;
  const choices=kind==="diagram"?data?.assets.filter(a=>a.references.some(r=>r.active)).map(a=>({id:a.file,label:a.file})):data?.tables.filter(t=>t.active).map(t=>({id:t.id,label:t.id}));
  const submit=type=>task(async()=>{
    const result=await api(base,{method:"POST",body:{revision:project.revision,kind:type,target:type==="audit"?"":target,model,instructions:type==="audit"?"检查完整 Method 与全文证据、尚未解决的作者批注，明确是否仍有阻止正式绘图的问题。":comment,consent:true,astraConsent:astra,...(type!=="audit"&&record?.status==="draft"&&!stale&&record.target===target&&record.kind===kind?{previous:record.id}:{})}});
    setSelected(result.recordId);onStarted(result.job);await load();
  });
  return <section className="figure-workbench">
    <div className="section-label"><span><Image size={14}/> 图示工作区</span><button title="刷新图稿" aria-label="刷新图稿" disabled={busy} onClick={()=>task(load)}><RefreshCw size={15}/></button></div>
    {error&&<p role="alert" className="inline-error">{error}</p>}
    {data&&<>
      <div className={`figure-gate ${data.gate.status}`}><strong>Method：{{unreviewed:"待审查",blocked:"有待解决问题",passed:"当前版本审查通过"}[data.gate.status]}</strong><span>{data.assets.filter(a=>a.references.some(r=>r.active)).length} 张正文图 · {data.tables.filter(t=>t.active).length} 个数字表格</span>
        {data.gate.blockers.length>0&&<details><summary>{data.gate.blockers.length} 项阻塞</summary>{data.gate.blockers.map((b,i)=><p key={i}><b>{b.file}</b> {b.reason}</p>)}</details>}
      </div>
      <label>本轮模型<select value={model} onChange={e=>{setModel(e.target.value);setAstra(false);}}>{data.models.map(m=><option key={m}>{m}</option>)}</select></label>
      {model==="gpt-6-astra"&&<label className="consent"><input type="checkbox" checked={astra} onChange={e=>setAstra(e.target.checked)}/>本轮使用 Astra，可能消耗更多账户额度</label>}
      <label className="consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>同意本机 Codex 读取全文和本轮图示批注</label>
      <button className="secondary" disabled={busy||active||!consent||!data.enabled||(model==="gpt-6-astra"&&!astra)} onClick={()=>submit("audit")}><FileSearch size={15}/>检查 Method</button>
      <div className="figure-target-mode"><label><input type="radio" name="figure-kind" checked={kind==="diagram"} onChange={()=>{setKind("diagram");setTarget("");setSelected("");}}/>现有图</label><label><input type="radio" name="figure-kind" checked={kind==="chart"} onChange={()=>{setKind("chart");setTarget("");setSelected("");}}/>实验表制图</label></div>
      <label>图示目标<select value={target} onChange={e=>{setTarget(e.target.value);setSelected("");}}><option value="">选择图或表格</option>{choices?.map(c=><option key={c.id} value={c.id}>{c.label}</option>)}</select></label>
      <label>图示批注<textarea value={comment} onChange={e=>setComment(e.target.value)} rows={4} placeholder="本图修改意见"/></label>
      <button className="primary" disabled={busy||active||!target||!comment.trim()||!consent||!data.enabled||(model==="gpt-6-astra"&&!astra)} onClick={()=>submit(kind)}><Play size={15}/>提交图示批注</button>
      <div className="figure-records">{data.records.map(r=><button key={r.id} className={selected===r.id?"active":""} onClick={()=>{setSelected(r.id);setVisual(false);if(r.kind!=="audit"){setKind(r.kind);setTarget(r.target);setComment("");}}}><span>{r.kind==="audit"?"Method 审查":r.target}</span><small>{r.model} · {{queued:"排队",running:"执行中",reviewed:"已审查",draft:"待确认草稿",applied:"已写入论文",failed:"失败",cancelled:"已取消"}[r.status]||r.status}</small></button>)}</div>
      {record&&<div className="figure-draft">
        <strong>{record.kind==="audit"?"Method 审查结果":"图稿记录"}</strong>
        <p>{record.spec?.takeaway||record.result?.summary||record.error||"等待模型结果"}</p>
        {record.scene&&<><a href={`/api${base}/${record.id}/preview`} target="_blank" rel="noreferrer" title="打开完整图稿"><img src={`/api${base}/${record.id}/preview`} alt={record.spec.title}/></a><p>{record.spec.caption}</p><small>{names[record.spec.pattern]||record.spec.source?.tableId} · {stale?"旧版原文":"当前原文"} · {record.comment.status==="archived"?"批注已归档":"批注未完成"}</small><div className="figure-downloads"><a href={`/api${base}/${record.id}/export`}><Download size={14}/>PDF</a><a href={`/api${base}/${record.id}/export?format=json`}><Download size={14}/>可编辑源数据</a><a href={`/api${base}/${record.id}/preview`} target="_blank" rel="noreferrer"><ExternalLink size={14}/>SVG</a></div></>}
        <blockquote>{record.comment.body}</blockquote>
        {(record.spec?.blockers||record.result?.blockers||[]).map((b,i)=><p key={i} className="inline-error">{typeof b==="string"?b:`${b.anchored===false?"待核验原文引句 · ":""}${b.file}：${b.reason}`}</p>)}
        {record.status==="draft"&&<><label className="consent"><input type="checkbox" checked={visual} onChange={e=>setVisual(e.target.checked)}/>已检查图稿及图注，确认替换或插入正式稿</label><button className="primary" disabled={busy||active||stale||!visual||data.gate.status!=="passed"||record.spec.blockers.length>0} onClick={()=>task(async()=>{await api(`${base}/${record.id}/apply`,{method:"POST",body:{revision:project.revision,visualConsent:true}});await onApplied();await load();})}><Check size={15}/>写入 TeX 并编译</button></>}
        {record.gitCommit&&<small>Git {record.gitCommit.slice(0,12)}</small>}
      </div>}
    </>}
  </section>;
}
