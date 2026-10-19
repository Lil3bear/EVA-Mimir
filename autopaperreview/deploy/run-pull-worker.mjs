import {readFile,mkdir,writeFile,rm} from "node:fs/promises";
import {homedir} from "node:os";
import path from "node:path";
import {runPullWorker} from "../server/pull-worker.mjs";

const dir=path.join(homedir(),".config/autopaperreview");
const config=JSON.parse(await readFile(path.join(dir,"team-bridge.json"),"utf8"));
const lock=path.join(dir,"pull-worker.lock");
try {await mkdir(lock,{mode:0o700});}
catch(error) {
  if(error.code!=="EEXIST")throw error;
  const pid=Number(await readFile(path.join(lock,"pid"),"utf8"));
  let alive=true;try{process.kill(pid,0);}catch(e){if(e.code==="ESRCH")alive=false;else throw e;}
  if(alive)throw Error("Another pull executor is running");
  await rm(lock,{recursive:true});await mkdir(lock,{mode:0o700});
}
await writeFile(path.join(lock,"pid"),String(process.pid),{mode:0o600});
const controller=new AbortController();
for(const sig of ["SIGTERM","SIGINT"])process.on(sig,()=>controller.abort());
try {
  await Promise.all(Array.from({length:4},(_,slot)=>runPullWorker({origin:config.access.origin,token:config.token,target:config.localTarget,directory:path.join(dir,"execution-receipts"),worker:`workspace-${slot}`,signal:controller.signal})));
} finally {await rm(lock,{recursive:true,force:true});}
