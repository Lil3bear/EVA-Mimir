import test from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,rm,readFile} from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import express from "express";
import {randomUUID} from "node:crypto";
import {figureInventory,manuscript,validateDiagram,resolveChart,sceneFor,sceneSVG} from "../server/figures.mjs";
import {figureGate,installFigureRoutes,validateMethodAudit,updateFigureCaption,pendingFigureComments} from "../server/figure-routes.mjs";
import {Jobs} from "../server/jobs.mjs";

const encode=s=>Buffer.from(s).toString("base64");
const table=String.raw`\begin{table}\caption{Solve rate (\%)}\label{tab:rate}
\begin{tabular}{lrr}\toprule Method & Count & Rate (\%)\\
\midrule Baseline & 10 & 50.0\\
Ours & 15 & 75.0\\\bottomrule\end{tabular}\end{table}`;
const fixture=()=>({id:randomUUID(),files:{"main.tex":encode(String.raw`\input{method}\input{results}`),"method.tex":encode(String.raw`\section{Method} Our method uses a memory and a validator.
\begin{figure}\includegraphics{fig/old.pdf}\caption{Old caption}\label{fig:old}\end{figure}`),"results.tex":encode(table),"inactive.tex":encode(String.raw`\includegraphics{fig/unused.pdf}`),"fig/old.pdf":encode("old-pdf"),"fig/unused.pdf":encode("unused")}});
const diagram=()=>({title:"Evidence-grounded workflow",caption:"Memory informs a candidate which is checked by a validator.",takeaway:"突出已描述的方法，不补充反馈路径。",pattern:"architecture",nodes:[{id:"memory",label:"Memory",column:0,row:0,role:"context"},{id:"validator",label:"Validator",column:1,row:0,role:"novelty"}],edges:[{from:"memory",to:"validator",label:"candidate"}],evidence:[{file:"method.tex",quote:"Our method uses a memory and a validator.",supports:"modules"}],blockers:[]});
const chart=()=>({tableId:"tab:rate",title:"Source table comparison",caption:"Rates from Table rate; no uncertainty estimates are supplied.",takeaway:"重现已有表格，不声称统计显著性。",rows:[0,1],columns:[2],unit:"percent",blockers:[]});

test("inventory resolves the active TeX graph and preserves numeric cell provenance",()=>{
  const rev=fixture(),inv=figureInventory(rev,"main.tex");
  assert.equal(inv.assets.length,2);assert.equal(inv.assets.filter(a=>a.references.some(r=>r.active)).length,1);
  assert.equal(inv.tables.length,1);assert.equal(inv.tables[0].rows[1].values[1],75);
  const c=resolveChart(chart(),inv.tables);assert.deepEqual(c.data.map(r=>r.values),[[50],[75]]);assert.deepEqual(c.source.columns,[2]);
  assert.throws(()=>resolveChart({...chart(),columns:[1]},inv.tables),/单位/);
  assert.throws(()=>resolveChart({...chart(),rows:[99]},inv.tables),/行不存在/);
  assert.throws(()=>resolveChart({...chart(),numbers:[90]},inv.tables));
  const grouped=structuredClone(inv.tables);grouped[0].rows[0].group="published";grouped[0].rows[1].group="own";
  assert.throws(()=>resolveChart(chart(),grouped),/不同配置/);
});
test("untrusted scene data cannot introduce scripts, duplicate nodes, invalid edges or invented evidence",()=>{
  const docs=manuscript(fixture()),d=validateDiagram(diagram(),docs);
  const svg=sceneSVG(sceneFor(d));assert(svg.includes("Memory"));assert(!svg.includes("<script"));
  const escaped=structuredClone(d);escaped.nodes[0].label="<script>";
  assert(!sceneSVG(sceneFor(escaped)).includes("<script>"));
  const duplicate=structuredClone(d);duplicate.nodes[1].column=0;
  assert.throws(()=>validateDiagram(duplicate,docs),/重复/);
  assert.throws(()=>validateDiagram({...d,edges:[{from:"x",to:"validator",label:"input"}]},docs),/无效/);
  assert.throws(()=>validateDiagram({...d,evidence:[{file:"method.tex",quote:"imagined claim",supports:"module"}]},docs),/定位/);
});
test("Method gate is revision-bound and unresolved major or human Method comments prevent formal replacement",()=>{
  const rev=fixture(),inv=figureInventory(rev,"main.tex"),p={revision:rev.id,comments:[]};
  const audit={id:randomUUID(),revision:rev.id,result:{blockers:[]}};
  assert.equal(figureGate(null,p,inv).status,"unreviewed");
  assert.equal(figureGate(audit,p,inv).status,"passed");
  p.comments=[{id:"archived",author:"you",status:"open",file:"method.tex",body:"历史批注",archivedAt:"2026-10-18"}];
  assert.equal(pendingFigureComments(p).length,0);assert.equal(figureGate(audit,p,inv).status,"passed");
  p.comments=[{id:"c",author:"you",status:"open",file:"method.tex",body:"未验证的机制"}];
  assert.equal(figureGate(audit,p,inv).status,"blocked");
  p.revision=randomUUID();assert.equal(figureGate(audit,p,inv).status,"unreviewed");
  const uncertain={...audit,result:validateMethodAudit({summary:"存在不确定问题",blockers:[{file:"method.tex",quote:"unlocated quotation",reason:"Needs evidence"}]},manuscript(rev))};
  p.revision=rev.id;p.comments=[];assert.equal(uncertain.result.blockers[0].anchored,false);assert.equal(figureGate(uncertain,p,inv).status,"blocked");
});

test("asset captions change together with the image, preserve labels and escape model TeX",()=>{
  const rev=fixture(),inv=figureInventory(rev,"main.tex"),files={...rev.files};
  updateFigureCaption(files,inv,"fig/old.pdf","Updated 50% & safe \\input{secret}",true);
  const tex=Buffer.from(files["method.tex"],"base64").toString();
  assert(tex.includes("\\begin{figure*}"));assert(tex.includes("width=\\textwidth"));assert(tex.includes("\\label{fig:old}"));
  assert(tex.includes("50\\% \\& safe \\textbackslash{}input\\{secret\\}"));assert(!tex.includes("\\input{secret}"));
  const duplicate=structuredClone(inv);duplicate.assets[0].references.push({file:"method.tex",active:true});
  assert.throws(()=>updateFigureCaption({...rev.files},duplicate,"fig/old.pdf","Caption"),/不唯一/);
});

test("figure routes stage drafts, preserve comments on failure, enforce cost and stale gates, then compile and log a real asset change",async t=>{
  const root=await mkdtemp(path.join(os.tmpdir(),"figure-test-"));t.after(()=>rm(root,{recursive:true,force:true}));
  let rev=fixture(),p={id:randomUUID(),revision:rev.id,main:"main.tex",comments:[],history:[]},state=null,calls=0,failCompile=false;
  const jobs=new Jobs({read:async()=>state,write:async(_,s)=>{state=s;}});
  const app=express();app.use(express.json());
  const wrap=fn=>async(req,res,next)=>{try{await fn(req,res);}catch(e){next(e);}};
  installFigureRoutes(app,{pid:()=>root,getProject:async()=>structuredClone(p),getRevision:async()=>structuredClone(rev),saveProject:async()=>{},getConfig:()=>({provider:"codex"}),jobs,wrap,withProjectLock:async(_,fn)=>fn(),
    invoke:async(_,schema,model)=>{calls++;assert.equal(model,"gpt-6.1-sol");return schema.properties.nodes?diagram():{summary:"Method 内容一致",blockers:[]};},
    renderPDF:async()=>Buffer.from("%PDF-1.4\nchanged-vector-asset"),
    compile:async(_,files)=>{if(failCompile)throw Error("compile failed");assert.notEqual(files["fig/old.pdf"],rev.files["fig/old.pdf"]);return {pdf:Buffer.from("compiled")};},
    snapshot:async(staged,files,_,compiled,{provenance})=>{assert(compiled.pdf);assert.equal(provenance.model,"gpt-6.1-sol");assert.equal(provenance.comment.status,"open");rev={id:randomUUID(),files};p={...staged,revision:rev.id};return {...rev,gitCommit:"abc123"};},
  });
  app.use((e,req,res,next)=>res.status(400).json({error:e.message}));
  const server=app.listen(0,"127.0.0.1");await new Promise(resolve=>server.on("listening",resolve));t.after(()=>new Promise(resolve=>server.close(resolve)));
  const url=`http://127.0.0.1:${server.address().port}/api/projects/${p.id}/figures`;
  const request=async(route="",body)=>{const r=await fetch(url+route,body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{});return {status:r.status,data:await r.json()};};
  const wait=async()=>{for(let i=0;i<200;i++){await new Promise(r=>setTimeout(r,5));const s=await jobs.get(p.id);if(s&&!['queued','running'].includes(s.status))return s;}throw Error("job timeout");};
  const payload={revision:p.revision,kind:"diagram",target:"fig/old.pdf",instructions:"突出验证器",consent:true};
  assert.equal((await request("",{...payload,model:"gpt-6-astra"})).status,400);assert.equal(calls,0);
  let r=await request("",payload);assert.equal(r.status,202);await wait();const draft=r.data.recordId;
  const before=rev.files["fig/old.pdf"];
  assert.equal((await request(`/${draft}/apply`,{revision:p.revision,visualConsent:true})).status,400);assert.equal(rev.files["fig/old.pdf"],before);
  await request("",{revision:p.revision,kind:"audit",instructions:"审查完整方法",consent:true});await wait();
  failCompile=true;assert.equal((await request(`/${draft}/apply`,{revision:p.revision,visualConsent:true})).status,400);
  let record=JSON.parse(await readFile(path.join(root,"figures",`${draft}.json`),"utf8"));assert.equal(record.comment.status,"open");assert.equal(record.status,"draft");assert.equal(rev.files["fig/old.pdf"],before);
  failCompile=false;assert.equal((await request(`/${draft}/apply`,{revision:p.revision,visualConsent:true})).status,200);
  record=JSON.parse(await readFile(path.join(root,"figures",`${draft}.json`),"utf8"));assert.equal(record.comment.status,"archived");assert.equal(record.gitCommit,"abc123");assert.equal(record.status,"applied");assert.notEqual(rev.files["fig/old.pdf"],before);
  assert.equal((await request(`/${draft}/apply`,{revision:p.revision,visualConsent:true})).status,400);assert.equal(calls,2);
});
