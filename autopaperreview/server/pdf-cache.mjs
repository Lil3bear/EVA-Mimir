import http from "node:http";
import {randomUUID} from "node:crypto";
import {createWriteStream} from "node:fs";
import {mkdir,open,rename,rm} from "node:fs/promises";
import {pipeline} from "node:stream/promises";
import path from "node:path";

const uuid="[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}";
const route=new RegExp(`^/api/projects/(${uuid})/pdf/(${uuid})$`);
const transient=status=>[502,503,504].includes(status);

async function validPDF(file) {
  const handle=await open(file,"r");
  try {
    const head=Buffer.alloc(5),stat=await handle.stat();
    await handle.read(head,0,5,0);
    return stat.isFile() && stat.size>5 && head.toString()==="%PDF-";
  } finally {await handle.close();}
}

function download(target,pathname,token,file) {
  return new Promise((resolve,reject)=>{
    const request=http.get(new URL(pathname,target),{
      headers:{"x-team-bridge-token":token,Accept:"application/pdf","Accept-Encoding":"identity"},
      signal:AbortSignal.timeout(80000),
    },response=>{
      if(response.statusCode!==200) {
        response.resume();
        reject(Object.assign(Error("PDF upstream unavailable"),{status:response.statusCode}));
        return;
      }
      if(!/^application\/pdf(?:;|$)/i.test(response.headers["content-type"]||"")) {
        response.resume();reject(Object.assign(Error("Invalid PDF response"),{status:502}));return;
      }
      pipeline(response,createWriteStream(file,{flags:"wx",mode:0o600}))
        .then(resolve,reject);
    });
    request.on("error",reject);
  });
}

// Immutable revision PDFs only. Never cache mutable workspace data or replay a write.
export function revisionPDFCache({directory,target,token}) {
  const root=path.resolve(directory),fills=new Map();
  async function fill(filename,pathname) {
    const destination=path.join(root,filename);
    try {if(await validPDF(destination))return "hit";}
    catch(error){if(error.code!=="ENOENT")throw error;}
    await mkdir(root,{recursive:true,mode:0o700});
    for(let attempt=0;attempt<2;attempt++) {
      const temporary=path.join(root,`.${filename}.${randomUUID()}.part`);
      try {
        await download(target,pathname,token,temporary);
        if(!await validPDF(temporary))throw Object.assign(Error("Invalid PDF file"),{status:502});
        await rename(temporary,destination);
        return "filled";
      } catch(error) {
        if(attempt || (error.status && !transient(error.status)))throw error;
      } finally {await rm(temporary,{force:true});}
    }
  }
  return async (req,res,next)=>{
    const match=route.exec(req.path);
    if(!match || !["GET","HEAD"].includes(req.method))return next();
    const filename=`${match[1]}-${match[2]}.pdf`;
    let pending=fills.get(filename);
    if(!pending) {
      pending=fill(filename,req.path).finally(()=>fills.delete(filename));
      fills.set(filename,pending);
    }
    try {
      const state=await pending;
      if(res.destroyed)return;
      res.set({"Cache-Control":"private, no-store","X-PDF-Cache":state});
      res.sendFile(filename,{root,dotfiles:"allow",cacheControl:false},error=>{
        if(!error)return;
        if(res.headersSent)res.destroy();
        else if(!res.destroyed)res.status(error.statusCode||503).json({error:"PDF 暂时无法读取，请重新加载；论文与批注未改变。"});
      });
    } catch(error) {
      if(res.destroyed)return;
      const status=[401,403,404].includes(error.status)?error.status:503;
      res.set("Cache-Control","no-store").status(status).json({error:status===404?"此版本 PDF 不存在，请先编译。":"PDF 执行端暂时不可用，请稍后重新加载；论文与批注未改变。"});
    }
  };
}
