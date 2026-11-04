import {mkdirSync, readFileSync, writeFileSync, renameSync, readdirSync, unlinkSync, openSync, fsyncSync, closeSync} from "node:fs";
import path from "node:path";
import {randomUUID, createHash, timingSafeEqual} from "node:crypto";
import express from "express";
import {gzipSync} from "node:zlib";

const uuid=/^[a-f0-9-]{36}$/;
const terminal=new Set(["done","expired","cancelled"]);
// One gateway process owns this directory. Atomic receipts survive gateway restarts.
export class PullQueue {
  constructor(directory) {
    this.directory=directory;mkdirSync(directory,{recursive:true,mode:0o700});
    this.entries=new Map();this.lastPoll=0;
    for(const name of readdirSync(directory)) if (/^[a-f0-9-]{36}\.json$/.test(name)) {
      const row=JSON.parse(readFileSync(path.join(directory,name),"utf8"));this.entries.set(row.id,row);
    }
    this.entries=new Map([...this.entries.values()].sort((a,b)=>a.created-b.created||(a.order||0)-(b.order||0)).map(row=>[row.id,row]));
    this.clean();
  }
  save(row) {
    const file=path.join(this.directory,row.id+".json"),temp=file+".tmp";
    writeFileSync(temp,JSON.stringify(row),{mode:0o600});
    const fd=openSync(temp,"r");try{fsyncSync(fd);}finally{closeSync(fd);}
    renameSync(temp,file);
    const directory=openSync(this.directory,"r");try{fsyncSync(directory);}finally{closeSync(directory);}
    this.entries.set(row.id,row);return row;
  }
  clean() {
    const now=Date.now();
    for(const row of this.entries.values()) {
      if(terminal.has(row.state)&&now-row.updated>(row.readOnly?15000:86400000)) {unlinkSync(path.join(this.directory,row.id+".json"));this.entries.delete(row.id);}
      else if(row.state==="queued"&&now-row.created>(row.readOnly?90000:86400000))
        this.save({...row,state:"expired",updated:now,response:{status:409,headers:{"content-type":"application/json"},body:Buffer.from(JSON.stringify({error:"排队请求已过期，未执行；请核对当前版本后重新提交。"})).toString("base64")}});
    }
  }
  enqueue(input,id=randomUUID()) {
    if(!uuid.test(id))throw Object.assign(Error("无效请求编号"),{status:400});
    this.clean();
    const digest=createHash("sha256").update(JSON.stringify(input)).digest("hex");
    const existing=this.entries.get(id);
    if(existing) {
      if(existing.digest!==digest)throw Object.assign(Error("请求编号已用于不同内容"),{status:409});
      return existing;
    }
    if(["GET","HEAD"].includes(input.method)) {
      const shared=[...this.entries.values()].find(r=>r.readOnly&&!terminal.has(r.state)&&r.digest===digest);
      if(shared)return shared;
    }
    if(this.entries.size>=1000)throw Object.assign(Error("队列已满，请稍后重试"),{status:429});
    const order=Math.max(0,...[...this.entries.values()].map(row=>row.order||0))+1;
    return this.save({id,...input,digest,order,readOnly:["GET","HEAD"].includes(input.method),state:"queued",created:Date.now(),updated:Date.now()});
  }
  claim(worker) {
    this.lastPoll=Date.now();this.clean();
    // Reoffer an outstanding delivery to the same slot. Local receipts prevent replay.
    const own=[...this.entries.values()].find(r=>r.state==="claimed"&&r.worker===worker);
    if(own)return own;
    const row=[...this.entries.values()].find(r=>r.state==="queued");
    if(!row)return null;
    return this.save({...row,state:"claimed",worker,updated:Date.now()});
  }
  complete(id,worker,response) {
    const row=this.entries.get(id);
    if(!row||row.worker!==worker)throw Object.assign(Error("请求不属于此执行端"),{status:409});
    if(row.state==="done")return row;
    return this.save({...row,state:"done",updated:Date.now(),response});
  }
  cancel(id) {
    const row=this.entries.get(id);
    if(!row||row.state!=="queued"||row.readOnly)throw Object.assign(Error("请求已被领取或已结束，不能撤销排队；请查看任务日志。"),{status:409});
    return this.save({...row,state:"cancelled",updated:Date.now(),response:{status:409,headers:{"content-type":"application/json"},body:Buffer.from(JSON.stringify({error:"排队提交已取消，未执行。"})).toString("base64")}});
  }
}

const wrap=fn=>(req,res,next)=>Promise.resolve(fn(req,res)).catch(next);
function reply(res,row) {
  for(const [key,value] of Object.entries(row.response.headers||{}))
    if(["content-type","content-disposition","content-range","accept-ranges","etag","last-modified"].includes(key))res.setHeader(key,value);
  res.setHeader("Cache-Control","no-store");
  let bytes=Buffer.from(row.response.body,"base64");
  if(bytes.length>1024&&res.req.acceptsEncodings("gzip")&&row.response.status!==206) {
    bytes=gzipSync(bytes);res.setHeader("Content-Encoding","gzip");res.setHeader("Vary","Accept-Encoding");
  }
  res.status(row.response.status).send(bytes);
}
export function installPullWorker(app,queue,token) {
  app.use("/__executor",(req,res,next)=>{
    const supplied=req.headers["x-team-bridge-token"];
    if(typeof supplied!=="string"||supplied.length!==token.length||!timingSafeEqual(Buffer.from(supplied),Buffer.from(token)))return res.sendStatus(401);
    next();
  },express.json({limit:"192mb"}));
  app.post("/__executor/claim",wrap(async(req,res)=>{
    const worker=req.body?.worker;
    if(!/^[a-z0-9-]{1,80}$/.test(worker||""))return res.sendStatus(400);
    res.json({request:queue.claim(worker)});
  }));
  app.post("/__executor/heartbeat",(req,res)=>{queue.lastPoll=Date.now();res.json({online:true});});
  app.post("/__executor/result/:id",wrap(async(req,res)=>{
    const {worker,response}=req.body||{};
    if(!response||!Number.isInteger(response.status)||response.status<200||response.status>599||typeof response.body!=="string")return res.sendStatus(400);
    queue.complete(req.params.id,worker,response);res.json({saved:true});
  }));
}
export function installPullBrowser(app,queue) {
  app.post("/api/execution-queue/:id/cancel",wrap(async(req,res)=>{queue.cancel(req.params.id);res.json({cancelled:true});}));
  app.get("/api/execution-queue",(req,res)=>res.json({online:Date.now()-queue.lastPoll<20000,requests:[...queue.entries.values()].filter(r=>!r.readOnly).slice(-100).map(({id,state,created,updated,url})=>({id,state,created,updated,url}))}));
  app.get("/api/execution-queue/:id",(req,res)=>{
    const row=queue.entries.get(req.params.id);
    if(!row)return res.status(404).json({error:"请求不存在或回执已过期，请检查批注和修订日志。"});
    if(terminal.has(row.state))return reply(res,row);
    res.status(202).json({executionQueued:true,requestId:row.id,state:row.state,message:"已保存在远端队列，等待你的工作区执行端处理，请勿重复提交。"});
  });
  app.use("/api",express.raw({type:()=>true,limit:"128mb"}),wrap(async(req,res)=>{
    if(!["GET","HEAD","POST","PUT","PATCH","DELETE"].includes(req.method))return res.sendStatus(405);
    const headers={};
    for(const key of ["content-type","range","x-workspace-view","if-none-match"])if(req.headers[key])headers[key]=req.headers[key];
    const row=queue.enqueue({method:req.method,url:req.originalUrl,actor:req.actor,headers,body:Buffer.isBuffer(req.body)?req.body.toString("base64"):""},req.headers["x-execution-request-id"]);
    const deadline=Date.now()+35000;
    while(!res.destroyed&&Date.now()<deadline) {
      const current=queue.entries.get(row.id);
      if(terminal.has(current.state))return reply(res,current);
      await new Promise(resolve=>setTimeout(resolve,150));
    }
    if(res.destroyed)return;
    if(row.readOnly)return res.status(503).json({error:"工作区执行端暂未响应，稍后刷新即可；本次只是读取，没有提交修改。"});
    res.status(202).json({executionQueued:true,requestId:row.id,state:queue.entries.get(row.id).state,message:"提交已安全排队，等待本机执行端；请勿重复提交。"});
  }));
}
