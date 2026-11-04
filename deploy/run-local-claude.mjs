import {spawn} from "node:child_process";
import {readFile,mkdir} from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import {atomicJSON} from "../server/core.mjs";
import {skills,skillPrompt} from "../server/skills.mjs";

const root=path.resolve(process.env.DATA_DIR||"data");
await mkdir(root,{recursive:true,mode:0o700});
await skillPrompt(skills.map(skill=>skill.id));
const selectionFile=path.join(root,"local-claude-config.json");
const selection=await readFile(selectionFile,"utf8").then(JSON.parse).catch(error=>{if(error.code==="ENOENT")return null;throw error;});
const dual=selection?.teamMode==="dual";
const nativeOnly=!selection||selection.teamMode==="gpt-only";
const status=dual||nativeOnly?null:await new Promise((resolve,reject)=>{
  const child=spawn("claude",["auth","status"],{stdio:["ignore","pipe","ignore"]});let text="";
  child.stdout.on("data",data=>{text+=data;});child.on("error",reject);
  child.on("close",()=>{try{resolve(JSON.parse(text));}catch{reject(Error("Cannot read native Claude login status"));}});
});
if(!dual&&!nativeOnly&&!status.loggedIn)throw Error("请先完成本机 Claude Code 的登录或服务配置；不会读取或迁移登录凭据");
const model=nativeOnly?(selection?.model||"gpt-6.1-sol"):process.env.LOCAL_COWRITER_MODEL||selection?.model||"claude-opus-5-5";
if(nativeOnly&&!["gpt-6.1-sol","gpt-6-astra"].includes(model))throw Error("未授权的本机 GPT 模型；不会自动切换或调用付费备用模型");
const reviewer=nativeOnly?"":selection?.reviewer||"deepseek/deepseek-flash";
if(!nativeOnly&&!["claude-opus-5-5","claude-fable-5-1"].includes(model))throw Error("未授权的协作模型");
if(!nativeOnly&&!["deepseek/deepseek-flash","deepseek-v4.1-flash","deepseek-official:deepseek-flash"].includes(reviewer))throw Error("未授权的写作模型");
const reviewerId=nativeOnly?"":reviewer.startsWith("deepseek-official:")?reviewer:`tokenhub:${reviewer}`;
if(!selection || selection.model!==model)await atomicJSON(selectionFile,{...selection,teamMode:nativeOnly?"gpt-only":selection?.teamMode,model,reviewer,selectedAt:new Date().toISOString()});
// Inspect only the configured origin for provenance; authentication remains inside the native client.
const settings=dual||nativeOnly?{}:await readFile(path.join(process.env.CLAUDE_CONFIG_DIR||path.join(os.homedir(),".claude"),"settings.json"),"utf8").then(JSON.parse).catch(error=>{if(error.code==="ENOENT")return {};throw error;});
const configuredOrigin=settings.env?.ANTHROPIC_BASE_URL?new URL(settings.env.ANTHROPIC_BASE_URL).origin:"https://api.anthropic.com";
const child=spawn(process.execPath,["server/index.mjs"],{stdio:"inherit",env:{...process.env,NODE_ENV:"production",DATA_DIR:root,PORT:process.env.PORT||"4317",BIND_HOST:"127.0.0.1",SHARED_MODE:"0",SETTINGS_LOCKED:"1",
  AI_PROVIDER:"codex",OPENAI_MODEL:nativeOnly?model:"gpt-6.1-sol",LOCAL_REVISION_ONLY:"1",REVISION_REVIEWER:reviewerId,REVISION_COWRITER_MODEL:nativeOnly?"":model,REVISION_COWRITER_AUTH:nativeOnly?"":"local",REVISION_CROSSCHECK_MODEL:nativeOnly?"":"gpt-6.1-sol",REVISION_TEAM_MODE:nativeOnly?"":dual?"dual":"",ARCHIVE_APPLIED_COMMENTS:"1",CLAUDE_LOCAL_CONFIGURED_ORIGIN:nativeOnly?"":configuredOrigin,CLAUDE_LOCAL_ERROR_LOG:path.join(root,"local-claude-last-error.json")}});
for(const signal of ["SIGTERM","SIGINT"])process.on(signal,()=>child.kill(signal));
child.on("exit",code=>process.exit(code||0));
