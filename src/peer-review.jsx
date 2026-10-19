import React,{useEffect,useState} from "react";
import {Users,Play,RefreshCw,Check,AlertCircle} from "lucide-react";

export function PeerReviewPanel({project,anchor,api,activity,onStarted,skillIds}) {
  const [models,setModels]=useState([]),[selected,setSelected]=useState([]),[runs,setRuns]=useState([]);
  const [error,setError]=useState(""),[consent,setConsent]=useState(false),[instructions,setInstructions]=useState(""),[starting,setStarting]=useState(false);
  const [scope,setScope]=useState(anchor?.quote?"selection":"paper");
  const [profile,setProfile]=useState("standard");
  const [profiles,setProfiles]=useState([]);
  useEffect(()=>{setScope(anchor?.quote?"selection":"paper");},[anchor?.quote,project.id]);
  const quote=scope==="selection"?anchor?.quote||"":"";
  const active=activity && ["queued","running","cancelling"].includes(activity.status);
  useEffect(()=>{let stopped=false;api("/peer-reviewers").then(data=>{if(stopped)return;setModels(data.reviewers);setProfiles(data.profiles||[]);setSelected(data.reviewers.filter(m=>m.vendor==="TokenHub" && m.model==="deepseek-v4-pro").map(m=>m.id));}).catch(e=>{if(!stopped)setError(e.message);});return()=>{stopped=true;};},[]);
  useEffect(()=>{
    let stopped=false,timer;
    setRuns([]);setConsent(false);
    const update=async()=>{try{const data=await api(`/projects/${project.id}/peer-reviews`);if(!stopped)setRuns(data);}catch(e){if(!stopped)setError(e.message);}finally{if(!stopped)timer=setTimeout(update,3000);}};
    update();
    return()=>{stopped=true;clearTimeout(timer);};
  },[project.id,project.revision]);
  function choose(ids){setSelected(ids);setConsent(false);}
  async function start(e){e.preventDefault();setStarting(true);setError("");try{const result=await api(`/projects/${project.id}/peer-reviews`,{method:"POST",body:{revision:project.revision,reviewerIds:selected,quote,pdfRevision:quote?anchor?.pdfRevision||null:null,instructions,...(profiles.includes(profile)?{profile}:{}),skillIds,consent}});onStarted(result.job);}catch(e){setError(e.message);}finally{setStarting(false);}}
  const statusName={pending:"待运行",queued:"排队中",running:"审稿中",completed:"完成",partial:"部分完成",failed:"失败",cancelled:"已停止",interrupted:"已中断"};
  return <div className="peer-panel">
    <form onSubmit={start}>
      <div className="peer-heading"><strong><Users size={15}/> 全局审稿人</strong><button type="button" title="选中全部模型" onClick={()=>choose(models.map(m=>m.id))}><Check size={13}/> 全选</button><button type="button" onClick={()=>choose([])}>清空</button></div>
      <fieldset className="peer-models"><legend>参与模型 · {selected.length} 个</legend>
        {[...new Set(models.map(m=>m.vendor))].map(vendor=><div key={vendor}><h4>{vendor}</h4>{models.filter(m=>m.vendor===vendor).map(m=><label key={m.id}><input type="checkbox" checked={selected.includes(m.id)} onChange={e=>choose(e.target.checked?[...selected,m.id]:selected.filter(id=>id!==m.id))}/><span>{m.model}</span></label>)}</div>)}
        {!models.length && <span className="muted">暂无已配置的审稿模型</span>}
      </fieldset>
      <label className="peer-scope">审稿范围<select aria-label="联合审稿范围" value={scope} onChange={e=>setScope(e.target.value)}><option value="paper">全文审稿</option><option value="selection" disabled={!anchor?.quote}>选中段落 · 结合全文</option></select></label>
      {profiles.includes("www-strict") && <label className="peer-scope">审稿标准<select aria-label="联合审稿标准" value={profile} onChange={e=>{setProfile(e.target.value);setConsent(false);}}><option value="standard">通用 · 证据与四视角复核</option><option value="www-strict">WWW 2027 · 严苛审稿人</option></select></label>}
      {quote && <blockquote className="popup-quote">{quote}</blockquote>}
      <label className="peer-instructions">审稿重点<textarea aria-label="联合审稿重点" value={instructions} onChange={e=>setInstructions(e.target.value)} placeholder="逻辑衔接、贡献与实验是否对齐…"/></label>
      <label className="peer-consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>同意向所选服务发送当前完整论文，每个模型先理解全文再审稿，共 {selected.length*2} 次模型请求，使用团队额度。</label>
      {error && <p role="alert" className="warning-text">{error}</p>}
      <button className="primary peer-start" type="submit" disabled={!selected.length||!consent||active||starting}><Play size={14}/>{starting?"正在排队":quote?"联合审查选中段落":"开始联合审稿"}</button>
    </form>
    <div className="peer-history-heading"><strong>审稿记录</strong><button title="刷新审稿记录" onClick={()=>api(`/projects/${project.id}/peer-reviews`).then(setRuns).catch(e=>setError(e.message))}><RefreshCw size={14}/></button></div>
    {!runs.length && <div className="empty-comments"><Users size={24}/><strong>暂无联合审稿记录</strong></div>}
    {runs.map(run=><section className="peer-run" key={run.id}>
      <div className="peer-run-heading"><time>{new Date(run.created).toLocaleString("zh-CN")}</time><span>{statusName[run.status]}</span></div>
      <small>版本 {run.revision.slice(0,8)} · {run.stale?"旧版意见":"当前版本"} · {run.profile==="www-strict"?"WWW 2027 严苛审稿":"通用审稿"} · {run.reviewers.filter(r=>r.status==="completed").length}/{run.reviewers.length} 成功</small>
      {run.quote && <blockquote className="popup-quote">{run.quote}</blockquote>}
      {run.reviewers.map(reviewer=><details className="peer-reviewer" key={reviewer.id} open={reviewer.status==="completed" && run.reviewers.length<=3}>
        <summary>{reviewer.vendor} · {reviewer.model}<span>{statusName[reviewer.status]}</span></summary>
        {reviewer.error && <p className="warning-text"><AlertCircle size={13}/> {reviewer.error}</p>}
        {reviewer.unvalidatedResult && <details><summary>未通过校验的原始返回 · 仅供人工核对</summary><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",maxHeight:280,overflow:"auto",fontSize:11}}>{JSON.stringify(reviewer.unvalidatedResult,null,2)}</pre></details>}
        {reviewer.status==="completed" && reviewer.result && <>
          <p>{reviewer.result.summary}</p><p><strong>全文对齐：</strong>{reviewer.result.alignment}</p>
          <details className="peer-map"><summary>论文结构与证据链</summary><p>{reviewer.result.paperMap.question}</p><p>{reviewer.result.paperMap.logicChain}</p>{reviewer.result.paperMap.sections.map((s,i)=><p key={i}><strong>{s.file}</strong><br/>{s.role}<br/>{s.claim}<br/>{s.evidence}</p>)}{reviewer.result.paperMap.uncertainties.map((u,i)=><p className="muted" key={i}>{u}</p>)}</details>
          {reviewer.result.findings.map((f,i)=><div className="peer-finding" key={i}><strong>{f.title}</strong><small>{f.file} · {{critical:"严重",major:"重要",minor:"次要"}[f.severity]} · {{confirmed:"模型判断：确定",conditional:"模型判断：有条件",unverified:"待人工核实"}[f.certainty]}</small><blockquote className="popup-quote">{f.quote}</blockquote><p>{f.body}</p><p><strong>建议：</strong>{f.suggestion}</p>{f.relatedEvidence.map((e,j)=><details key={j}><summary>{e.file} · {e.anchored?"原文已定位":"原文待核实"}</summary><blockquote className="popup-quote">{e.quote}</blockquote><p>{e.reason}</p></details>)}</div>)}
          {!reviewer.result.findings.length && <p className="muted">本轮未提出有依据的问题</p>}
          <p className="muted">{reviewer.result.coverage}</p>
        </>}
      </details>)}
    </section>)}
  </div>;
}
