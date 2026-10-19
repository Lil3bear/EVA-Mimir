import {test} from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,rm,writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {randomUUID,createHmac} from "node:crypto";
import http from "node:http";
import {PullQueue} from "../server/pull-queue.mjs";
import {executeDelivery} from "../server/pull-worker.mjs";
import {remoteTeamGateway} from "../server/team-proxy.mjs";
import {passwordHash} from "../server/access.mjs";

async function directory(t){const d=await mkdtemp(path.join(tmpdir(),"pull-test-"));t.after(()=>rm(d,{recursive:true,force:true}));return d;}
const input=()=>({method:"POST",url:"/api/projects/example/jobs",headers:{"content-type":"application/json"},body:Buffer.from('{"consent":true}').toString("base64")});
function fetchHTTP(url,{method="GET",headers={},body}={}) {
  return new Promise((resolve,reject)=>{const req=http.request(url,{method,headers},res=>{const chunks=[];res.on("data",c=>chunks.push(c));res.on("end",()=>resolve({status:res.statusCode,json:async()=>JSON.parse(Buffer.concat(chunks))}));});req.on("error",reject);req.end(body);});
}
test("ten submissions survive restart, claims do not collide, duplicates cannot change content",async t=>{
  const dir=await directory(t);let queue=new PullQueue(dir);
  const rows=Array.from({length:10},()=>queue.enqueue(input()));
  queue=new PullQueue(dir);assert.equal(queue.entries.size,10);
  assert.equal(queue.enqueue(input(),rows[0].id).id,rows[0].id);
  assert.throws(()=>queue.enqueue({...input(),body:"e30="},rows[0].id),/不同内容/);
  const a=queue.claim("a"),b=queue.claim("b");assert.notEqual(a.id,b.id);
  assert.equal(a.id,rows[0].id);assert.equal(b.id,rows[1].id);
  assert.equal(queue.claim("a").id,a.id);
  assert.throws(()=>queue.complete(a.id,"b",{}),/不属于/);
  queue.complete(a.id,"a",{status:202,headers:{},body:"e30="});
  queue=new PullQueue(dir);assert.equal(queue.entries.get(a.id).state,"done");
  queue.cancel(rows[9].id);assert.equal(queue.entries.get(rows[9].id).state,"cancelled");
  assert.throws(()=>queue.cancel(b.id),/已被领取/);
});
test("lost delivery acknowledgement reuses local receipt without a second model dispatch",async t=>{
  const dir=await directory(t),request={id:randomUUID(),...input()};let calls=0;
  const fetcher=async()=>{calls++;return new Response('{"job":{"id":"one"}}',{status:202});};
  const options={directory:dir,target:"http://127.0.0.1:4317",fetcher};
  const first=await executeDelivery(request,options),second=await executeDelivery(request,options);
  assert.deepEqual(first,second);assert.equal(calls,1);
});
test("uncertain crash is never replayed, invalid destinations are rejected",async t=>{
  const dir=await directory(t),request={id:randomUUID(),...input()};
  await writeFile(path.join(dir,request.id+".json"),JSON.stringify({started:1}));
  const result=await executeDelivery(request,{directory:dir,target:"http://127.0.0.1:4317",fetcher:()=>{throw Error("must not run");}});
  assert.equal(result.status,409);
  await assert.rejects(executeDelivery({...request,url:"//evil/api"},{directory:dir,target:"http://127.0.0.1:4317"}),/Invalid/);
  await assert.rejects(executeDelivery({...request,id:randomUUID()},{directory:dir,target:"https://external.example"}),/loopback/);
});
test("gateway authenticates browser and worker separately and delivers through outbound polling",async t=>{
  const queueDir=await directory(t),secret="b".repeat(64),token="a".repeat(64);
  const app=remoteTeamGateway({target:"http://127.0.0.1:4320",token,queueDir,access:{shared:true,port:4317,origin:"https://papers.example",passwordHash:passwordHash("secret"),secret}});
  const server=app.listen(0,"127.0.0.1");await new Promise(r=>server.once("listening",r));
  t.after(()=>{server.closeAllConnections();server.close();});
  const base=`http://127.0.0.1:${server.address().port}`;
  const expiry=String(Date.now()+60000),cookie=`autopaperreview_session=${expiry}.${createHmac("sha256",secret).update(expiry).digest("hex")}`;
  const headers={Host:"papers.example",Cookie:cookie,"content-type":"application/json"};
  assert.equal((await fetchHTTP(base+"/api/execution-queue",{headers:{Host:"papers.example"}})).status,401);
  assert.equal((await fetch(base+"/__executor/claim",{method:"POST",headers,body:'{"worker":"one"}'})).status,401);
  const pending=fetchHTTP(base+"/api/projects/demo/jobs",{method:"POST",headers,body:'{"consent":true}'});
  const workerHeaders={"x-team-bridge-token":token,"content-type":"application/json"};
  let request;
  for(let i=0;i<30&&!request;i++) {
    ({request}=await(await fetch(base+"/__executor/claim",{method:"POST",headers:workerHeaders,body:'{"worker":"one"}'})).json());
    if(!request)await new Promise(r=>setTimeout(r,10));
  }
  assert.ok(request);assert.equal(request.headers.cookie,undefined);
  await fetch(base+"/__executor/result/"+request.id,{method:"POST",headers:workerHeaders,body:JSON.stringify({worker:"one",response:{status:202,headers:{"content-type":"application/json"},body:Buffer.from('{"job":{"id":"ok"}}').toString("base64")}})});
  const result=await pending;assert.equal(result.status,202);assert.equal((await result.json()).job.id,"ok");
});
