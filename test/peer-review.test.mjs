import {test} from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,rm,writeFile,mkdir,readFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {reviewerRegistry,publicReviewers,reviewSnapshot,runPeerReviewer,validatePeerReport,installPeerReviewRoutes,peerReviewGuidance} from "../server/peer-review.mjs";
import {Jobs} from "../server/jobs.mjs";
import express from "express";
import {randomUUID} from "node:crypto";
const revision={id:randomUUID(),files:{"main.tex":Buffer.from("Evidence first.\nA supported claim.").toString("base64")}};
const snapshot=reviewSnapshot({venue:"WWW"},revision);
const map={question:"What is supported?",contributions:["Evidence"],logicChain:"question to evidence",sections:[{file:"main.tex",role:"intro",claim:"A supported claim.",evidence:"Evidence first."}],uncertainties:[]};
const wireMap=m=>({...m,sections:Object.fromEntries(m.sections.map(({file,...section})=>[file,section]))});
const report={summary:"review",alignment:"aligned",coverage:"source only",findings:[{title:"question",body:"Check support",suggestion:"Clarify the claim",file:"main.tex",quote:"A supported claim.",relatedEvidence:[{file:"main.tex",quote:"Evidence first.",reason:"support"}],severity:"minor",certainty:"confirmed"}]};
test("WWW profile ports the four reviewer lenses without transplanting ICLR policy or inventing faults",async()=>{
  const guidance=await peerReviewGuidance(["claims"],"www-strict");
  for(const text of ["Four lenses", "Skeptical adjudication", "WWW 2027", "strongest author defense", "not a preselected rejection verdict", "2026-10-17", "www2027.thewebconf.org"]) assert.ok(guidance.includes(text),text);
  assert.ok(!guidance.includes("ICLR 2027 permits"));
  const calls=[];
  await runPeerReviewer({vendor:"test",model:"test",config:{}},snapshot,{profile:"www-strict"},{invoke:async(config,req)=>{calls.push(req);return req.name==="paper_structure"?wireMap(map):structuredClone(report);}});
  assert.ok(calls.every(call=>call.instructions.includes("WWW 2027")));
});
test("peer models read the entire same revision before reviewing, including long sources",async()=>{
  const content="Full text. ".repeat(30000)+"END";
  const snap=reviewSnapshot({}, {...revision,files:{...revision.files,"appendix.tex":Buffer.from(content).toString("base64")}});
  const calls=[],fullMap={...map,sections:[...map.sections,{file:"appendix.tex",role:"appendix",claim:"context",evidence:"text"}]};
  const result=await runPeerReviewer({vendor:"TokenHub",model:"test",config:{}},snap,{quote:"selected"},{invoke:async(config,req)=>{calls.push(req);return calls.length===1?wireMap(fullMap):structuredClone(report);}});
  assert.equal(calls.length,2);
  assert.equal(JSON.parse(calls[0].input).documents.find(d=>d.file==="appendix.tex").content,content);
  assert.deepEqual(JSON.parse(calls[1].input).paperMap,fullMap);
  assert.equal(JSON.parse(calls[1].input).revision,revision.id);
  assert.equal(result.findings[0].anchored,true);
  assert.notEqual(snap.sourceHash,snapshot.sourceHash);
});
test("nonexistent evidence files are rejected; invented quotes cannot become confirmed findings",()=>{
  const raw=structuredClone(report);raw.findings[0].relatedEvidence[0].quote="not in source";
  assert.equal(validatePeerReport(raw,snapshot).findings[0].certainty,"unverified");
  raw.findings[0].file="invented.tex";
  assert.throws(()=>validatePeerReport(raw,snapshot),/不存在/);
});
test("malformed read-only review results retain the raw draft but never become a valid report",async()=>{
  const malformed=structuredClone(report);delete malformed.findings[0].suggestion;
  await assert.rejects(runPeerReviewer({vendor:"test",model:"test",config:{}},snapshot,{}, {invoke:async(config,req)=>req.name==="paper_structure"?wireMap(map):malformed}),error=>{
    assert.equal(error.unvalidatedResult.stage,"global_peer_review");
    assert.deepEqual(error.unvalidatedResult.data,malformed);return true;
  });
});
test("model registry exposes all configured text models but no keys or configuration",async()=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),"peer-registry-"));
  try{const filename=path.join(dir,"tokenhub.json");await writeFile(filename,JSON.stringify({baseURL:"https://tokenhub.tencentmaas.com/v1",apiKey:"SECRET_TOKENHUB",models:[{id:"deepseek-v4-pro",name:"DeepSeek"},{id:"glm-5.3",name:"GLM"}]}));
    const entries=await reviewerRegistry({provider:"openai",baseURL:"https://uuapi.io/v1",apiKey:"SECRET_UUAPI",model:"claude-opus-5-5"},filename);
    assert.equal(entries.find(e=>e.model==="glm-5.3").config.reasoningEffort,"low");
    const visible=JSON.stringify(publicReviewers(entries));assert.ok(!visible.includes("SECRET"));assert.ok(!visible.includes("apiKey"));assert.equal(entries.filter(e=>e.vendor==="TokenHub").length,2);
  }finally{await rm(dir,{recursive:true,force:true});}
});
test("peer review cancellation between stages prevents the findings call",async()=>{
  const controller=new AbortController();let calls=0;
  await assert.rejects(runPeerReviewer({vendor:"test",model:"test",config:{}},snapshot,{}, {signal:controller.signal,invoke:async()=>{calls++;controller.abort();return wireMap(map);}}));assert.equal(calls,1);
});
test("an incomplete global map cannot proceed to paragraph advice",async()=>{
  const partial={...map,sections:[{...map.sections[0],file:"unknown.tex"}]};let calls=0;
  await assert.rejects(runPeerReviewer({vendor:"test",model:"test",config:{}},snapshot,{}, {invoke:async()=>{calls++;return wireMap(partial);}}),/完整覆盖/);
  assert.equal(calls,1);
  const larger=reviewSnapshot({}, {...revision,files:{...revision.files,"appendix.tex":Buffer.from("Appendix").toString("base64")}});
  await assert.rejects(runPeerReviewer({vendor:"test",model:"test",config:{}},larger,{}, {invoke:async()=>wireMap(map)}),/完整覆盖/);
});
test("HTTP peer reviews require consent and current revision, preserve successful reviews when another model fails, never edit source",async()=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),"peer-http-")),p={id:randomUUID(),revision:revision.id,venue:"WWW"};
  const providerFile=path.join(dir,"providers.json");await writeFile(providerFile,JSON.stringify({baseURL:"https://tokenhub.tencentmaas.com/v1",apiKey:"test",models:[{id:"deepseek-v4-pro"},{id:"glm-5.3"}]}));
  const previous=process.env.REVIEW_PROVIDER_FILE;process.env.REVIEW_PROVIDER_FILE=providerFile;
  const states=new Map(),jobs=new Jobs({read:async id=>states.get(id),write:async(id,state)=>states.set(id,state)});
  const app=express();app.use(express.json());let calls=0;
  installPeerReviewRoutes(app,{pid:id=>{assert.equal(id,p.id);return path.join(dir,id);},getProject:async()=>p,getRevision:async()=>revision,getConfig:()=>({provider:"codex"}),jobs,wrap:fn=>(req,res,next)=>Promise.resolve(fn(req,res)).catch(next),invoke:async(config,req)=>{calls++;if(config.model==="deepseek-v4-pro")throw Error("test upstream failure");return req.name==="paper_structure"?wireMap(map):report;}});
  app.use((e,req,res,next)=>res.status(400).json({error:e.message}));const server=app.listen(0,"127.0.0.1");await new Promise(resolve=>server.once("listening",resolve));
  const base=`http://127.0.0.1:${server.address().port}`;
  const payload={revision:revision.id,reviewerIds:["tokenhub:deepseek-v4-pro","tokenhub:glm-5.3"],skillIds:["writing"],profile:"www-strict",consent:true};
  const post=body=>fetch(`${base}/api/projects/${p.id}/peer-reviews`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  try{
    assert.equal((await post({...payload,consent:false})).status,400);
    assert.equal((await post({...payload,revision:randomUUID()})).status,400);
    assert.equal((await post({...payload,reviewerIds:["fake"]})).status,400);
    assert.equal((await post({...payload,quote:"old selection",pdfRevision:randomUUID()})).status,400);
    assert.equal(calls,0);
    assert.equal((await post(payload)).status,202);
    for(let i=0;i<100;i++){if((await jobs.get(p.id))?.status==="completed")break;await new Promise(resolve=>setTimeout(resolve,10));}
    assert.equal((await jobs.get(p.id)).status,"completed");
    const runs=await(await fetch(`${base}/api/projects/${p.id}/peer-reviews`)).json();
    assert.equal(runs[0].status,"partial");assert.equal(runs[0].reviewers[0].status,"failed");assert.equal(runs[0].reviewers[1].status,"completed");assert.equal(calls,3);
    assert.equal(runs[0].profile,"www-strict");assert.match(runs[0].guidanceHash,/^[a-f0-9]{64}$/);
    assert.equal(Buffer.from(revision.files["main.tex"],"base64").toString(),"Evidence first.\nA supported claim.");
    p.revision=randomUUID();const stale=await(await fetch(`${base}/api/projects/${p.id}/peer-reviews`)).json();assert.equal(stale[0].stale,true);
  }finally{if(previous===undefined)delete process.env.REVIEW_PROVIDER_FILE;else process.env.REVIEW_PROVIDER_FILE=previous;await new Promise(resolve=>server.close(resolve));await rm(dir,{recursive:true,force:true});}
});
test("all-model reviews are durable before 202 and concurrency is bounded at two",async()=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),"peer-workers-")),p={id:randomUUID(),revision:revision.id};
  const providerFile=path.join(dir,"providers.json");
  const models=["one","two","three","four"].map(id=>({id}));
  await writeFile(providerFile,JSON.stringify({baseURL:"https://tokenhub.tencentmaas.com/v1",apiKey:"test",models}));
  const previous=process.env.REVIEW_PROVIDER_FILE;process.env.REVIEW_PROVIDER_FILE=providerFile;
  const states=new Map(),jobs=new Jobs({read:async id=>states.get(id),write:async(id,state)=>states.set(id,state)});
  let concurrent=0,maximum=0;const attempted=new Set();
  const app=express();app.use(express.json());
  installPeerReviewRoutes(app,{pid:id=>path.join(dir,id),getProject:async()=>p,getRevision:async()=>revision,getConfig:()=>({provider:"codex"}),jobs,wrap:fn=>(req,res,next)=>Promise.resolve(fn(req,res)).catch(next),invoke:async(config,req)=>{
    concurrent++;maximum=Math.max(maximum,concurrent);attempted.add(config.model);
    try {await new Promise(resolve=>setTimeout(resolve,30));if(config.model==="one")return {};return req.name==="paper_structure"?wireMap(map):structuredClone(report);}
    finally {concurrent--;}
  }});
  const server=app.listen(0,"127.0.0.1");await new Promise(resolve=>server.once("listening",resolve));
  try {
    const response=await fetch(`http://127.0.0.1:${server.address().port}/api/projects/${p.id}/peer-reviews`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision:revision.id,reviewerIds:models.map(m=>`tokenhub:${m.id}`),skillIds:["review"],consent:true})});
    assert.equal(response.status,202);const created=await response.json();
    const filename=path.join(dir,p.id,"peer-reviews",`${created.reviewId}.json`);
    assert.equal(JSON.parse(await readFile(filename,"utf8")).jobId,created.job.id);
    for(let i=0;i<100;i++){if((await jobs.get(p.id)).status==="completed")break;await new Promise(resolve=>setTimeout(resolve,10));}
    assert.equal((await jobs.get(p.id)).status,"completed");
    const saved=JSON.parse(await readFile(filename,"utf8"));
    assert.equal(saved.status,"partial");assert.ok(saved.reviewers.every(r=>r.started && r.completed));
    assert.equal(saved.reviewers[0].status,"failed");assert.equal(saved.reviewers[0].unvalidatedResult.stage,"paper_structure");
    assert.ok(saved.reviewers.slice(1).every(r=>r.status==="completed"));
    assert.equal(maximum,2);assert.equal(attempted.size,4);
  }finally{if(previous===undefined)delete process.env.REVIEW_PROVIDER_FILE;else process.env.REVIEW_PROVIDER_FILE=previous;await new Promise(resolve=>server.close(resolve));await rm(dir,{recursive:true,force:true});}
});
test("a GET racing with job completion never overwrites the final report as interrupted",async()=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),"peer-race-")),id=randomUUID(),runId=randomUUID(),jobId=randomUUID();
  const folder=path.join(dir,id,"peer-reviews"),filename=path.join(folder,runId+".json");await mkdir(folder,{recursive:true});
  const run={id:runId,jobId,revision:revision.id,mainFile:null,created:new Date().toISOString(),status:"running",reviewers:[{id:"test",status:"running"}]};await writeFile(filename,JSON.stringify(run));
  const app=express();
  installPeerReviewRoutes(app,{pid:id=>path.join(dir,id),getProject:async()=>({id,revision:revision.id}),getRevision:async()=>revision,getConfig:()=>({}),jobs:{get:async()=>{await writeFile(filename,JSON.stringify({...run,status:"completed",reviewers:[{id:"test",status:"completed",result:report}]}));return {id:jobId,status:"completed"};}},wrap:fn=>(req,res,next)=>Promise.resolve(fn(req,res)).catch(next)});
  const server=app.listen(0,"127.0.0.1");await new Promise(resolve=>server.once("listening",resolve));
  try{const result=await(await fetch(`http://127.0.0.1:${server.address().port}/api/projects/${id}/peer-reviews`)).json();assert.equal(result[0].status,"completed");assert.equal(JSON.parse(await readFile(filename,"utf8")).status,"completed");}
  finally{await new Promise(resolve=>server.close(resolve));await rm(dir,{recursive:true,force:true});}
});
