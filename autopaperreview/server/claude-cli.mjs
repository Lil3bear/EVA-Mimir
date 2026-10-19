import childProcess from "node:child_process";
import {mkdtemp, writeFile, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {parseModelJSON} from "./model-api.mjs";

export function claudeRevisionInput(input) {
  let data;try{data=JSON.parse(input);}catch{return input;}
  if(!Array.isArray(data.documents)||!Array.isArray(data.sourceTargets))return input;
  // Send each TeX character once, with editable target IDs attached to lossless source segments.
  const grouped=new Map();
  for(const target of data.sourceTargets) {
    if(!grouped.has(target.file))grouped.set(target.file,[]);
    grouped.get(target.file).push(target);
  }
  data.documents=data.documents.map(document=>{
    const targets=grouped.get(document.file);
    if(!targets?.length)return document;
    const source=document.content,segments=[];let offset=0;
    for(const target of [...targets].sort((a,b)=>a.start-b.start)) {
      if(!Number.isSafeInteger(target.start)||!Number.isSafeInteger(target.end)||target.start<offset||target.end<target.start||source.slice(target.start,target.end)!==target.text)
        throw Error("Claude 源码分段与当前 TeX 不一致，未发送请求");
      if(target.start>offset)segments.push({text:source.slice(offset,target.start)});
      segments.push({targetId:target.id,text:target.text});offset=target.end;
    }
    if(offset<source.length)segments.push({text:source.slice(offset)});
    const {content,...metadata}=document;
    return {...metadata,sourceSegments:segments};
  });
  data.sourceTargets=data.sourceTargets.map(({text,...target})=>target);
  data.editingContract={...data.editingContract,before:"LOSSLESS SOURCE SEGMENTS: For each TeX document, concatenate sourceSegments[].text to recover its exact complete source, including whitespace. Segments with targetId are editable; return that targetId and its replacement text. Segments without targetId are read-only context. The sourceTargets catalogue contains location metadata only. Never count offsets or edit PDF text."};
  if(typeof data.compilationLog==="string") {
    const lines=data.compilationLog.split("\n"),blocks=new Set();
    for(let i=0;i<lines.length;i++)if(/warning|error|^!|undefined|overfull|underfull|missing|rerun|output written/i.test(lines[i]))
      blocks.add(lines.slice(i,Math.min(lines.length,i+3)).join("\n"));
    data.compilationLog=[...blocks].join("\n\n");
    data.compilationLogScope="Distinct diagnostic blocks and PDF output lines only; repeated diagnostics and package/font load traces omitted. The complete build log remains saved on the server. No manuscript source is omitted.";
  }
  return JSON.stringify(data);
}

export async function executeClaude(config, {instructions, input, schema, signal, timeoutMs=["claude-opus-5-5","claude-fable-5-1"].includes(config.model)?480000:240000}) {
  signal?.throwIfAborted();
  if(!config.localAuth && !config.apiKey)throw Error("Claude Code 未配置 API 密钥，未修改源码");
  const modelInput=claudeRevisionInput(input);
  const directory = await mkdtemp(path.join(os.tmpdir(), "autopaper-claude-"));
  try {
    const outputSchema=structuredClone(schema);
    // Target membership is enforced against immutable source ranges after generation, not by duplicating their catalogue in the tool schema.
    const target=outputSchema.properties?.patches?.items?.properties?.targetId;
    if(target)delete target.enum;
    const promptFile = path.join(directory, "instructions.txt");
    // Native structured output avoids relying on the model to serialize JSON in prose.
    await writeFile(promptFile, `${instructions}\n\nOUTPUT CONTRACT: Return the required structured output matching the following schema. Copy targetId only from the supplied sourceTargets; the server rejects unknown IDs. Do not output the schema itself or claim any external action. No filesystem, shell, or network tools are available.\n${JSON.stringify(outputSchema)}`, {mode:0o600});
    const env = config.localAuth ? {
      PATH:process.env.PATH || "/usr/local/bin:/usr/bin:/bin", HOME:os.homedir(), TMPDIR:directory,
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC:"1", DISABLE_AUTOUPDATER:"1",
    } : {
      PATH:process.env.PATH || "/usr/local/bin:/usr/bin:/bin", HOME:directory, TMPDIR:directory,
      ANTHROPIC_API_KEY:config.apiKey, ANTHROPIC_BASE_URL:config.baseURL.replace(/\/v1\/?$/, ""),
      CLAUDE_CODE_ATTRIBUTION_HEADER:"1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC:"1", DISABLE_AUTOUPDATER:"1",
    };
    for(const name of ["HTTP_PROXY","HTTPS_PROXY","NO_PROXY","SSL_CERT_FILE","SSL_CERT_DIR"])
      if(process.env[name])env[name]=process.env[name];
    if(config.localAuth && process.env.CLAUDE_CONFIG_DIR)env.CLAUDE_CONFIG_DIR=process.env.CLAUDE_CONFIG_DIR;
    const args = [config.localAuth?"--safe-mode":"--bare", "-p", "--output-format", "json",
      "--model", config.model, "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
      ...(!config.localAuth?["--setting-sources", ""]:[]), "--no-session-persistence", "--max-turns", "3", "--max-budget-usd", config.model==="claude-opus-5-5"?"4":config.model==="claude-fable-5-1"?"6":"2",
      ...(config.nativeStructuredOutput===false?[]:["--json-schema", JSON.stringify(outputSchema)]),
      ...(config.model==="claude-fable-5-1"?["--effort",config.reasoningEffort||"medium"]:[]),
      "--append-system-prompt-file", promptFile];
    const response = await new Promise((resolve,reject) => {
      const child = childProcess.spawn(process.env.CLAUDE_CLI_BINARY || "claude", args, {
        cwd:directory, env, detached:true, stdio:["pipe","pipe","pipe"],
      });
      let stdout="", overflow=false, timedOut=false;
      const stop = () => {try {process.kill(-child.pid,"SIGKILL");}catch {}};
      const timer = setTimeout(() => {timedOut=true;stop();}, timeoutMs);
      signal?.addEventListener("abort",stop,{once:true});
      if(signal?.aborted)stop();
      const cleanup = () => {clearTimeout(timer);signal?.removeEventListener("abort",stop);};
      child.stdout.on("data", chunk => {
        if(overflow)return;
        stdout+=chunk.toString();
        if(Buffer.byteLength(stdout)>16*1024*1024){overflow=true;stdout="";stop();}
      });
      // Upstream logs can echo manuscript text or credentials; never forward them to the browser.
      child.stderr.resume();
      child.stdin.on("error",()=>{});
      child.on("error",error => {cleanup();reject(Error(error.code==="ENOENT"?"未安装 Claude Code，未修改源码":"Claude Code 无法启动，未修改源码"));});
      child.on("close",code => {
        cleanup();
        if(signal?.aborted)return reject(signal.reason || Error("Claude Code 已停止，未修改源码"));
        if(timedOut)return reject(Error("Claude Code 请求超时，未修改源码"));
        if(overflow)return reject(Error("Claude Code 返回结果过大，未保存或应用修改"));
        resolve({code,stdout});
      });
      child.stdin.end(modelInput);
    });
    let result;
    try {result=JSON.parse(response.stdout);}catch {throw Error("Claude Code 返回无效 JSON，未保存或应用修改");}
    if(response.code!==0 || result?.is_error || (typeof result?.result === "string" && /^\s*API Error\b/.test(result.result))) {
      if(config.localAuth && process.env.CLAUDE_LOCAL_ERROR_LOG){
        const redact=text=>String(text).replace(/\b(?:sk-[A-Za-z0-9_-]+|olp_[A-Za-z0-9]+|Bearer\s+[A-Za-z0-9._-]+)/g,"[REDACTED]").slice(0,8000);
        await writeFile(process.env.CLAUDE_LOCAL_ERROR_LOG,JSON.stringify({time:new Date().toISOString(),model:config.model,exitCode:response.code,subtype:result?.subtype,
          result:redact(result?.result||""),errors:Array.isArray(result?.errors)?result.errors.map(e=>redact(typeof e==="string"?e:JSON.stringify(e))):[]},null,2),{mode:0o600});
      }
      const subtype=result?.subtype;
      if(subtype === "error_max_turns")throw Error("Claude Code 达到本轮推理轮数上限，未保存或应用修改");
      if(subtype === "error_max_budget_usd")throw Error("Claude Code 达到本轮费用上限，未保存或应用修改");
      const details=typeof result?.result === "string" ? result.result : "";
      if(config.localAuth){
        const messages=[details,...(Array.isArray(result.errors)?result.errors.filter(e=>typeof e==="string"):[])].join("\n");
        const status=messages.match(/(?:API Error:|status(?: code)?[=:]?)\s*(\d{3})\b/i)?.[1];
        const category=/insufficient[\s_-]+balance|余额不足|credit.*exhausted/i.test(messages)?"所配置模型服务账户余额不足；请检查该服务账户余额，不是论文或批注格式错误"
          :/not logged in|authentication|\b401\b/i.test(messages)?"登录不可用，请在本机运行 claude auth login"
          :/hit your limit|usage limit|rate.limit|\b429\b|额度|限额/i.test(messages)?"账户使用限额或请求频率限制"
          :/prompt.*too long|context.*(?:length|limit)|too many tokens/i.test(messages)?"本轮全文超出当前模型的上下文容量；没有截断论文"
          :/\b404\b|model.*not found|model.*not exist/i.test(messages)?"账户尚不能使用指定模型；未自动换模型"
          :/overloaded|\b529\b|\b503\b/i.test(messages)?"上游模型暂时过载"
          :/当前模型无法继续此对话/.test(messages)?"上游拒绝继续本次对话；本机客户端仍受所配置服务通道影响"
          :/schema|structured.output/i.test(messages)?"上游结构化输出请求失败"
          :"请求未成功，请检查账户和模型权限";
        throw Error(`本机 Claude Code：${category}${status?`（HTTP ${status}）`:""}${subtype!=="success"&&/^[a-z_]{1,64}$/.test(subtype||"")?` [${subtype}]`:""}；未修改源码`);
      }
      if(details.includes("CLAUDE_CODE_ATTRIBUTION_HEADER") || details.includes("客户端归属信息"))
        throw Error("真实 Claude Code 客户端仍被 UUAPI 归属校验拒绝，请提供商检查上游通道；未修改源码");
      if(details.includes("请求可能被第三方中转改写"))
        throw Error("真实 Claude Code 请求被 UUAPI 上游完整性校验拒绝（400）：上游报告请求可能被中转改写。请 UUAPI 检查原始请求体透传；本轮未修改源码。");
      if(/\b400\b/.test(details))throw Error("真实 Claude Code 请求仍被 UUAPI 上游拒绝（400），未修改源码");
      if(/\b429\b/.test(details))throw Error("Claude Code 请求被上游限流（429），未修改源码");
      throw Error("Claude Code 请求失败，请检查 UUAPI 通道和额度；未修改源码");
    }
    if(!result || result.is_error || result.subtype!=="success")throw Error("Claude Code 未成功完成结构化请求，未保存或应用修改");
    const models=Object.keys(result.modelUsage || {});
    if(!models.length || models.some(model => model!==config.model)) {
      const safeModels=models.map(model=>/^claude-(?:opus|sonnet|haiku|fable)-[a-z0-9._\[\]-]{1,80}$/i.test(model) && (!config.apiKey || !model.includes(config.apiKey)) ? model : "未识别标识");
      throw Error(`Claude Code 返回模型与指定模型不一致（请求 ${config.model}；返回 ${safeModels.join("、")||"未提供模型标识"}），未保存或应用修改`);
    }
    if(result.structured_output == null && !(typeof result.result === "string" && result.result.trim()))throw Error("Claude Code 未返回原生结构化结果，未保存或应用修改");
    let data;
    try {data=result.structured_output ?? parseModelJSON(result.result);}catch {
      const error=Error("Claude Code 返回的结构化结果不是合法 JSON，未保存或应用修改");
      error.code="MODEL_JSON_INVALID";throw error;
    }
    if(!data || typeof data!=="object" || Array.isArray(data))throw Error("Claude Code 未返回结构化建议，未保存或应用修改");
    return data;
  } finally {
    await rm(directory, {recursive:true, force:true});
  }
}
