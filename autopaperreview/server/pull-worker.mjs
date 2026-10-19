import {readFile,writeFile,rename,mkdir,open,rm,readdir,stat} from "node:fs/promises";
import path from "node:path";
import {gzipSync} from "node:zlib";

async function save(file,value) {
  await writeFile(file+".tmp",JSON.stringify(value),{mode:0o600});
  const fd=await open(file+".tmp","r");try{await fd.sync();}finally{await fd.close();}
  await rename(file+".tmp",file);
  const folder=await open(path.dirname(file),"r");try{await folder.sync();}finally{await folder.close();}
}
export async function executeDelivery(request,{directory,target,fetcher=fetch}) {
  if(!/^[a-f0-9-]{36}$/.test(request.id)||!/^\/api\//.test(request.url)||request.url.includes("\\")||request.url.startsWith("//")||/^\/api\/(session|logout)(?:[/?]|$)/.test(request.url))throw Error("Invalid execution request");
  const origin=new URL(target);
  if(origin.protocol!=="http:"||!["localhost","127.0.0.1","[::1]"].includes(origin.hostname))throw Error("Local executor target must be loopback");
  await mkdir(directory,{recursive:true,mode:0o700});
  const file=path.join(directory,request.id+".json");
  let receipt=await readFile(file,"utf8").then(JSON.parse).catch(e=>{if(e.code==="ENOENT")return null;throw e;});
  if(receipt?.response)return receipt.response;
  if(receipt) {
    // A crash after dispatch is ambiguous. Never repeat a potentially billable write.
    const response={status:409,headers:{"content-type":"application/json"},body:Buffer.from(JSON.stringify({error:"本机在处理此提交时中断，未自动重放。请检查批注、任务和版本历史后再操作。",code:"EXECUTION_UNCONFIRMED"})).toString("base64")};
    await save(file,{...receipt,response});return response;
  }
  await save(file,{id:request.id,started:Date.now()});
  let response;
  try {
    const headers={};for(const key of ["content-type","range","x-workspace-view","if-none-match"])if(request.headers?.[key])headers[key]=request.headers[key];
    const result=await fetcher(new URL(request.url,origin),{method:request.method,headers,body:["GET","HEAD"].includes(request.method)?undefined:Buffer.from(request.body,"base64"),signal:AbortSignal.timeout(600000),redirect:"error"});
    let bytes=Buffer.from(await result.arrayBuffer());
    if(request.url==="/api/health"&&result.status===200)bytes=Buffer.from(JSON.stringify({...JSON.parse(bytes),shared:true,localExecution:true,pullExecution:true}));
    response={status:result.status,headers:Object.fromEntries(result.headers),body:bytes.toString("base64")};
  } catch {
    response={status:503,headers:{"content-type":"application/json"},body:Buffer.from(JSON.stringify({error:"本机执行请求中断；未自动重复执行，请核对任务与版本历史。",code:"EXECUTION_UNCONFIRMED"})).toString("base64")};
  }
  await save(file,{id:request.id,response,finished:Date.now()});return response;
}
export async function runPullWorker({origin,token,target,directory,worker="workspace",signal}) {
  if(!origin.startsWith("https://"))throw Error("Executor requires HTTPS gateway");
  const post=async(route,body)=>{
    const payload=JSON.stringify(body),compress=payload.length>1024;
    const res=await fetch(new URL(route,origin),{method:"POST",headers:{"content-type":"application/json","x-team-bridge-token":token,...(compress?{"content-encoding":"gzip"}:{})},body:compress?gzipSync(payload):payload,signal:AbortSignal.timeout(30000),redirect:"error"});
    if(!res.ok)throw Error(`Gateway HTTP ${res.status}`);
    return res.json();
  };
  await mkdir(directory,{recursive:true,mode:0o700});
  for(const name of await readdir(directory))if(/^[a-f0-9-]{36}\.json$/.test(name)) {
    const file=path.join(directory,name);
    const info=await stat(file).catch(()=>null);
    if(info&&Date.now()-info.mtimeMs>7*86400000) {
      const receipt=await readFile(file,"utf8").then(JSON.parse).catch(()=>null);
      if(receipt?.acknowledged)await rm(file,{force:true});
    }
  }
  const heartbeat=worker.endsWith("-0")?setInterval(()=>post("/__executor/heartbeat",{}).catch(()=>{}),10000):null;
  signal?.addEventListener("abort",()=>clearInterval(heartbeat),{once:true});
  while(!signal?.aborted) {
    try {
      const {request}=await post("/__executor/claim",{worker});
      if(request) {
        const response=await executeDelivery(request,{directory,target});
        await post("/__executor/result/"+request.id,{worker,response});
        if(request.readOnly)await rm(path.join(directory,request.id+".json"),{force:true});
        else await save(path.join(directory,request.id+".json"),{id:request.id,response,acknowledged:Date.now()});
        continue;
      }
    } catch(error) {console.error(new Date().toISOString(),error.message);}
    await new Promise(resolve=>setTimeout(resolve,1500));
  }
  clearInterval(heartbeat);
}
