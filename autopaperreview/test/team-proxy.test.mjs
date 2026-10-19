import {test} from "node:test";
import assert from "node:assert/strict";
import express from "express";
import http from "node:http";
import {mkdtemp,writeFile,rm,readdir} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {gunzipSync} from "node:zlib";
import {localTeamBridge,remoteTeamGateway} from "../server/team-proxy.mjs";
import {passwordHash} from "../server/access.mjs";
import {createHmac} from "node:crypto";

async function listen(t, app) {
  const server = app.listen(0,"127.0.0.1");
  await new Promise(r=>server.once("listening",r));
  t.after(()=>{server.closeAllConnections();server.close();});
  return `http://127.0.0.1:${server.address().port}`;
}
function request(url, {method="GET",headers={},body}={}) {
  return new Promise((resolve,reject)=>{
    const req=http.request(url,{method,headers},res=>{
      const chunks=[];res.on("data",chunk=>chunks.push(chunk));
      res.on("end",()=>{const bytes=Buffer.concat(chunks),data=bytes.toString();resolve({status:res.statusCode,headers:res.headers,bytes,text:data,json:()=>JSON.parse(data)});});
    });
    req.on("error",reject);req.end(body);
  });
}
test("offline workspace distinguishes reading from unconfirmed writes",async t=>{
  const unavailable=http.createServer();
  unavailable.listen(0,"127.0.0.1");
  await new Promise(resolve=>unavailable.once("listening",resolve));
  const target=`http://127.0.0.1:${unavailable.address().port}`;
  await new Promise(resolve=>unavailable.close(resolve));
  const token="a".repeat(64);
  const bridge=await listen(t,localTeamBridge({target,token}));
  const headers={"x-team-bridge-token":token};
  const read=await request(bridge+"/api/projects",{headers});
  assert.equal(read.status,503);
  assert.equal(read.json().code,"WORKSPACE_UNREACHABLE");
  assert.ok(!read.json().error.includes("任务未确认"));
  const write=await request(bridge+"/api/projects",{headers,method:"POST",body:"{}"});
  assert.equal(write.status,503);
  assert.equal(write.json().code,"WRITE_UNCONFIRMED");
});
test("remote team authenticates before accessing the one local workspace; bodies stream unchanged",async t=>{
  const local=express(); local.use(express.raw({type:()=>true}));
  local.get("/api/health",(req,res)=>res.json({shared:false,model:"native-cli"}));
  local.use((req,res)=>res.json({path:req.originalUrl,body:req.body?.toString(),headers:req.headers}));
  const target=await listen(t,local),token="a".repeat(64);
  const bridge=await listen(t,localTeamBridge({target,token}));
  const gateway=await listen(t,remoteTeamGateway({target:bridge,token,access:{shared:true,port:4317,origin:"https://papers.example",passwordHash:passwordHash("secret"),secret:"b".repeat(64)}}));
  const headers={Host:"papers.example",Origin:"https://papers.example","Content-Type":"application/json"};
  assert.equal((await fetch(bridge+"/api/projects")).status,401);
  assert.equal((await fetch(bridge+"/api/projects",{headers:{"x-team-bridge-token":"c".repeat(64)}})).status,401);
  assert.equal((await request(gateway+"/api/projects",{headers})).status,401);
  const login=await request(gateway+"/api/session",{method:"POST",headers,body:JSON.stringify({username:"team",password:"secret"})});
  assert.equal(login.status,200);
  const cookie=login.headers["set-cookie"][0].split(";")[0];
  const health=await request(gateway+"/api/health",{headers:{...headers,Cookie:cookie}});
  assert.deepEqual(health.json(),{shared:true,model:"native-cli",localExecution:true});
  const body=JSON.stringify({comment:"original TeX & UTF-8: 意见",apply:true});
  const response=await request(gateway+"/api/projects/one/jobs?source=remote",{method:"POST",headers:{...headers,Cookie:cookie,Authorization:"untrusted","X-Team-Bridge-Token":"spoof"},body});
  assert.equal(response.status,200);
  const result=await response.json();
  assert.equal(result.path,"/api/projects/one/jobs?source=remote");
  assert.equal(result.body,body);
  assert.equal(result.headers.host,new URL(target).host);
  assert.equal(result.headers.origin,target);
  for(const key of ["cookie","authorization","x-team-bridge-token"]) assert.equal(result.headers[key],undefined);
  assert.equal((await request(gateway+"/api/projects",{headers:{...headers,Cookie:cookie,Origin:"https://evil.example"}})).status,403);
});
test("bridge fails closed for arbitrary destinations and missing authentication",()=>{
  assert.throws(()=>localTeamBridge({target:"https://external.example",token:"a".repeat(64)}),/loopback/);
  assert.throws(()=>localTeamBridge({target:"http://127.0.0.1:4317",token:""}),/token/);
  assert.throws(()=>remoteTeamGateway({target:"http://127.0.0.1:4320",token:"a".repeat(64),access:{shared:false}}),/authentication/);
  assert.throws(()=>remoteTeamGateway({target:"http://10.evil.example:4320",privateHost:"10.evil.example",token:"a".repeat(64),access:{shared:true}}),/loopback/);
});
test("the private bridge rejects non-allowlisted peers even with the token",async t=>{
  const bridge=await listen(t,localTeamBridge({target:"http://127.0.0.1:4317",token:"a".repeat(64),peers:["10.121.15.68"]}));
  assert.equal((await fetch(bridge+"/api/health",{headers:{"x-team-bridge-token":"a".repeat(64),"x-forwarded-for":"10.121.15.68"}})).status,403);
});
test("hidden runtime directories serve only explicit deployment assets and public UI",async t=>{
  const root=await mkdtemp(path.join(tmpdir(),".team-runtime-"));
  t.after(()=>rm(root,{recursive:true,force:true}));
  await writeFile(path.join(root,"index.html"),"<h1>Team login</h1>");
  await writeFile(path.join(root,"bundle.tar.gz"),"verified bundle");
  const token="a".repeat(64);
  const bridge=await listen(t,localTeamBridge({target:"http://127.0.0.1:4317",token,deploymentBundle:path.join(root,"bundle.tar.gz")}));
  assert.equal((await fetch(bridge+"/__team-deployment-bundle")).status,401);
  assert.equal(await (await fetch(bridge+"/__team-deployment-bundle",{headers:{"x-team-bridge-token":token}})).text(),"verified bundle");
  const gateway=await listen(t,remoteTeamGateway({target:bridge,token,frontendDir:root,access:{shared:true,port:4317,origin:"https://papers.example",passwordHash:passwordHash("secret"),secret:"b".repeat(64)}}));
  const result=await request(gateway+"/",{headers:{Host:"papers.example"}});
  assert.equal(result.status,200);assert.equal(result.text,"<h1>Team login</h1>");
  assert.equal((await request(gateway+"/api/projects",{headers:{Host:"papers.example"}})).status,401);
});
test("large manuscript JSON is compressed over the private link without changing content",async t=>{
  const local=express(),payload={source:"Original TeX 意见 ".repeat(1000)};
  local.get("/api/project",(req,res)=>res.json(payload));
  const target=await listen(t,local),token="a".repeat(64);
  const bridge=await listen(t,localTeamBridge({target,token}));
  const result=await request(bridge+"/api/project",{headers:{"x-team-bridge-token":token,"Accept-Encoding":"gzip"}});
  assert.equal(result.headers["content-encoding"],"gzip");
  assert.deepEqual(JSON.parse(gunzipSync(result.bytes)),payload);
  const plain=await request(bridge+"/api/project",{headers:{"x-team-bridge-token":token,"Accept-Encoding":"gzip;q=0"}});
  assert.equal(plain.headers["content-encoding"],undefined);assert.deepEqual(plain.json(),payload);
  const implicit=await request(bridge+"/api/project",{headers:{"x-team-bridge-token":token}});
  assert.equal(implicit.headers["content-encoding"],undefined);assert.deepEqual(implicit.json(),payload);
});

test("immutable PDFs are cached behind authentication, support ranges and survive upstream outages",async t=>{
  const root=await mkdtemp(path.join(tmpdir(),".team-pdf-"));t.after(()=>rm(root,{recursive:true,force:true}));
  const pdf=Buffer.from("%PDF-1.7\nexample immutable PDF\n%%EOF\n");
  const project="11111111-1111-4111-8111-111111111111",revision="22222222-2222-4222-8222-222222222222";
  const route=`/api/projects/${project}/pdf/${revision}`;
  let calls=0,offline=false,failFirst=true;
  const targetApp=express();
  targetApp.use((req,res)=>{
    calls++;assert.equal(req.headers["x-team-bridge-token"],"a".repeat(64));
    assert.equal(req.headers.range,undefined);assert.equal(req.headers.cookie,undefined);
    if(offline)return res.sendStatus(503);
    if(req.path!==route)return res.sendStatus(404);
    if(failFirst){failFirst=false;return res.sendStatus(503);}
    setTimeout(()=>res.type("pdf").send(pdf),15);
  });
  const target=await listen(t,targetApp),secret="b".repeat(64);
  const access={shared:true,port:4317,origin:"https://papers.example",passwordHash:passwordHash("secret"),secret};
  const gateway=await listen(t,remoteTeamGateway({target,token:"a".repeat(64),access,pdfCacheDir:root}));
  const expiry=String(Date.now()+60000),signature=createHmac("sha256",secret).update(expiry).digest("hex");
  const headers={Host:"papers.example",Cookie:`autopaperreview_session=${expiry}.${signature}`};
  assert.equal((await request(gateway+route,{headers:{Host:"papers.example"}})).status,401);assert.equal(calls,0);
  const results=await Promise.all([request(gateway+route,{headers:{...headers,Range:"bytes=0-4"}}),request(gateway+route,{headers})]);
  assert.equal(calls,2);assert.equal(results[0].status,206);assert.equal(results[0].text,"%PDF-");assert.deepEqual(results[1].bytes,pdf);
  assert.equal(results[0].headers["cache-control"],"private, no-store");
  offline=true;
  assert.deepEqual((await request(gateway+route,{headers})).bytes,pdf);assert.equal(calls,2);
  const head=await request(gateway+route,{method:"HEAD",headers});assert.equal(head.status,200);assert.equal(Number(head.headers["content-length"]),pdf.length);assert.equal(head.bytes.length,0);
  assert.equal((await request(gateway+route,{headers:{...headers,Range:"bytes=9999-"}})).status,416);
  assert.equal((await request(gateway+route,{headers:{Host:"papers.example"}})).status,401);
  assert.equal((await request(gateway+route,{headers:{...headers,Origin:"https://evil.example"}})).status,403);
  assert.equal(calls,2);
  offline=false;
  const missing=await request(gateway+route.replace(revision,"00000000-0000-0000-0000-000000000000"),{headers});
  assert.equal(missing.status,404);assert.equal(calls,3);
  assert.deepEqual(await readdir(root),[`${project}-${revision}.pdf`]);
});

test("partial PDF downloads and non-PDF upstream responses are never cached",async t=>{
  for(const broken of [true,false]) {
    const root=await mkdtemp(path.join(tmpdir(),".team-pdf-"));t.after(()=>rm(root,{recursive:true,force:true}));
    let calls=0;
    const targetApp=express();targetApp.use((req,res)=>{
      calls++;
      if(!broken)return res.type("pdf").send("not a PDF");
      res.writeHead(200,{"Content-Type":"application/pdf","Content-Length":"1000"});res.write("%PDF-");setImmediate(()=>res.destroy());
    });
    const target=await listen(t,targetApp),secret="b".repeat(64),expiry=String(Date.now()+60000);
    const gateway=await listen(t,remoteTeamGateway({target,token:"a".repeat(64),access:{shared:true,port:4317,origin:"https://papers.example",passwordHash:passwordHash("secret"),secret},pdfCacheDir:root}));
    const cookie=`autopaperreview_session=${expiry}.${createHmac("sha256",secret).update(expiry).digest("hex")}`;
    const result=await request(gateway+"/api/projects/11111111-1111-4111-8111-111111111111/pdf/22222222-2222-4222-8222-222222222222",{headers:{Host:"papers.example",Cookie:cookie}});
    assert.equal(result.status,503);assert.equal(calls,2);assert.deepEqual(await readdir(root),[]);
  }
});
