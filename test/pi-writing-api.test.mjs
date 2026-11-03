import {test} from "node:test";
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {mkdtemp,mkdir,writeFile,rm,readFile} from "node:fs/promises";
import {createServer} from "node:net";
import path from "node:path";
import os from "node:os";

test("Pi writing adapter keeps candidates reviewable and records rejection, acceptance, Git and request linkage",{timeout:30000},async()=>{
  const directory=await mkdtemp(path.join(os.tmpdir(),"mimir-writing-api-"));
  const bin=path.join(directory,"bin");await mkdir(bin);
  await writeFile(path.join(bin,"pi"),`#!/usr/bin/env node
let input="";process.stdin.setEncoding("utf8");process.stdin.on("data",d=>input+=d);
process.stdin.on("end",()=>{
  const marker="MANUSCRIPT DATA (not instructions):\\n";
  const data=JSON.parse(input.slice(input.lastIndexOf(marker)+marker.length));
  const target=data.sourceTargets[0];
  const result={summary:"Fixture revision",coverage:"Provided source only",findings:[],patches:[{targetId:target.id,after:"Scientific revision goes beyond fluency.",reason:"Concise wording",commentIds:[data.comments[0].id]}]};
  console.log(JSON.stringify({type:"message_end",message:{role:"assistant",provider:"deepseek",model:"deepseek-flash",stopReason:"stop",content:[{type:"text",text:JSON.stringify(result)}]}}));
});
`,{mode:0o700});
  const listener=createServer();await new Promise(resolve=>listener.listen(0,"127.0.0.1",resolve));
  const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
  const child=spawn(process.execPath,["server/index.mjs"],{env:{...process.env,
    PATH:bin+path.delimiter+process.env.PATH,PORT:String(port),DATA_DIR:path.join(directory,"data"),
    NODE_ENV:"production",AI_PROVIDER:"openai",OPENAI_API_KEY:"fixture-only",OPENAI_MODEL:"deepseek-flash",
    REVISION_TRANSPORT:"pi-cli",LOCAL_REVISION_ONLY:"1",ARCHIVE_APPLIED_COMMENTS:"0",
    REVISION_REVIEWER:"",REVISION_COWRITER_MODEL:"",REVISION_COWRITER_AUTH:"",REVISION_CROSSCHECK_MODEL:"",REVISION_TEAM_MODE:"",
    MIMIR_PI_SESSION_DIR:path.join(directory,"sessions"),OVERLEAF_CREDENTIAL_DIR:path.join(directory,"credentials"),
  },stdio:["ignore","pipe","pipe"]});
  const origin=`http://127.0.0.1:${port}`;
  const api=async(route,body,method=body?"POST":"GET")=>{
    const response=await fetch(origin+"/api"+route,{method,headers:{"Content-Type":"application/json"},...(body?{body:JSON.stringify(body)}:{})});
    const value=await response.json();assert.equal(response.ok,true,JSON.stringify(value));return value;
  };
  try {
    await new Promise((resolve,reject)=>{child.stdout.on("data",d=>{if(String(d).includes("Autopaperreview:"))resolve();});child.once("error",reject);child.once("exit",code=>reject(new Error(`server exited: ${code}`)));});
    const form=new FormData();form.set("demo","true");form.set("trusted","true");
    let project=await fetch(origin+"/api/projects/import",{method:"POST",body:form}).then(r=>r.json());
    const route="/projects/"+project.id;
    project=await api(route+"/compile",{},"POST");const original=project.revision;
    project=await api(route+"/comments",{body:"Make this concise.",quote:"Revising a scientific manuscript involves more than improving fluency.",pdfRevision:project.pdfRevision,page:1});
    const propose=async()=>{
      const queued=await api(route+"/jobs",{mode:"revise",skillIds:["snap-write"],instructions:"Keep the meaning",consent:true,apply:false,expectedRevision:original,commentIds:[project.comments[0].id]});
      let job;
      for(let i=0;i<150;i++){job=(await api(route+"/activity")).job;if(job.id===queued.job.id&&!["queued","running"].includes(job.status))break;await new Promise(resolve=>setTimeout(resolve,20));}
      assert.equal(job.status,"awaiting_approval",job.error);return job;
    };
    const rejected=await propose();
    project=await api(route+"/proposals/"+rejected.result.proposal+"/reject",{});
    assert.equal(project.revision,original);
    const accepted=await propose();
    project=await api(route+"/proposals/"+accepted.result.proposal+"/apply",{});
    assert.notEqual(project.revision,original);assert.equal(project.pdfRevision,project.revision);
    const diff=await api(route+"/history/"+project.revision+"/diff");
    assert.equal(diff.provenance.transport,"pi-cli");assert.match(diff.diff,/Scientific revision goes beyond fluency/);
    const state=JSON.parse(await readFile(path.join(directory,"data/experience/events.json"),"utf8"));
    assert(state.events.some(event=>event.status==="rejected"&&event.patches.length));
    assert(state.events.some(event=>event.status==="applied"&&event.skillManifest));
    assert(state.events.some(event=>event.kind==="job"&&event.piSessions?.length));
    assert(state.events.some(event=>event.kind==="editing-request"&&event.report.instructions==="Keep the meaning"));
    project=await api(route+"/restore/"+original,{});
    assert.equal(project.history[0].restoredFrom,original);
  } finally {
    if(child.exitCode===null&&child.signalCode===null)await new Promise(resolve=>{child.once("exit",resolve);child.kill("SIGTERM");});
    await rm(directory,{recursive:true,force:true});
  }
});
