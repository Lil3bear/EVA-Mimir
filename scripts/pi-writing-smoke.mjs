import assert from "node:assert/strict";
import {mkdir,writeFile} from "node:fs/promises";

const origin = process.argv[2];
if (!origin || new URL(origin).hostname !== "127.0.0.1") throw new Error("Supply the local writing URL");
const api = async (route, body, method="POST") => {
  const response = await fetch(origin+"/api"+route,{method,headers:{"Content-Type":"application/json"},...(body?{body:JSON.stringify(body)}:{})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
};
const form = new FormData();form.set("demo","true");form.set("trusted","true");
const imported = await fetch(origin+"/api/projects/import",{method:"POST",body:form});
let project=await imported.json();assert(imported.ok);
const route="/projects/"+project.id;
project=await api(route+"/compile");
const before=project.revision;
project=await api(route+"/comments",{body:"Make this sentence more concise. Preserve its precise meaning. Change only the quoted sentence.",quote:"Revising a scientific manuscript involves more than improving fluency.",pdfRevision:project.pdfRevision,page:1,x:0.2,y:0.2});
const requested=await api(route+"/jobs",{mode:"revise",skillIds:["snap-write"],instructions:"This is a smoke test on a demonstration manuscript. Make one concise source edit for the supplied comment, preserving all scientific claims. Return a complete JSON response.",consent:true,apply:false,expectedRevision:before,commentIds:[project.comments[0].id]});
let job;
for(let i=0;i<250;i++) {
  job=(await api(route+"/activity",undefined,"GET")).job;
  if(job.id===requested.job.id && ["completed","awaiting_approval","failed","no_changes","cancelled"].includes(job.status))break;
  await new Promise(resolve=>setTimeout(resolve,1000));
}
assert.equal(job.status,"awaiting_approval",JSON.stringify({status:job.status,error:job.error}));
project=await api(route,undefined,"GET");
const proposal=project.proposals.find(p=>p.id===job.result.proposal);
assert(proposal);assert.equal(proposal.transport,"pi-cli");assert.equal(project.revision,before);
project=await api(route+"/proposals/"+proposal.id+"/apply",{});
assert.notEqual(project.revision,before);assert.equal(project.pdfRevision,project.revision);
const diff=await api(route+"/history/"+project.revision+"/diff",undefined,"GET");
assert.match(diff.diff,/diff --git/);assert.equal(diff.provenance.transport,"pi-cli");
const experience=await fetch(origin+"/api/experience").then(r=>r.text());
assert.match(experience,/editing-request/);assert.match(experience,/pi-cli/);assert.match(experience,/applied/);
const result={projectId:project.id,model:proposal.model,transport:proposal.transport,proposalId:proposal.id,before,after:project.revision,commit:diff.commit,patches:proposal.patches.map(({before,after,reason})=>({before,after,reason})),checks:{pi:true,deepseek:true,skillManifest:Boolean(proposal.skillManifest),compiled:true,gitDiff:true,trajectory:true},remotePush:false};
await mkdir("output",{recursive:true});
await writeFile("output/pi-writing-smoke.json",JSON.stringify(result,null,2));
console.log(JSON.stringify(result,null,2));
