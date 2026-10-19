import {reviewerRegistry} from "./peer-review.mjs";
import {readFile} from "node:fs/promises";
import {homedir} from "node:os";
import path from "node:path";

export async function revisionProvider(primary, id, filename, officialFile=path.join(homedir(),".config/autopaperreview/deepseek-official.json")) {
  if(!id)return primary;
  if(id==="deepseek-official:deepseek-flash") {
    const official=JSON.parse(await readFile(officialFile,"utf8"));
    if(official.baseURL!=="https://api.deepseek.com/v1" || official.model!=="deepseek-flash" || typeof official.apiKey!=="string" || !official.apiKey.trim())
      throw Error("DeepSeek 官方配置无效，不会转发密钥至其他服务");
    return {provider:"openai",vendor:"DeepSeek 官方",baseURL:official.baseURL,apiKey:official.apiKey,model:official.model,modelName:"DeepSeek V4.1 Flash（官方）",apiFormat:"chat-json",disableThinking:true,localRevisionOnly:primary.localRevisionOnly,revisionTransport:"api",backup:false};
  }
  const candidate=(await reviewerRegistry(primary,filename)).find(model=>model.id===id && model.vendor==="TokenHub");
  if(!candidate)throw Error("配置的备用修订模型不可用；不会自动选择其他模型");
  return {...candidate.config,localRevisionOnly:primary.localRevisionOnly,revisionTransport:"api",vendor:candidate.vendor,modelName:candidate.name,backup:true};
}

export function publicRevisionProvider(config) {
  return {model:config.model,displayName:config.modelName||config.model,provider:config.provider,vendor:config.vendor || (config.provider==="codex"?"Codex":"主服务"),
    apiOrigin:config.localAuth?config.configuredOrigin||null:config.provider==="codex"?null:new URL(config.baseURL).origin,backup:Boolean(config.backup),
    ...(config.localAuth?{localAuth:true}:{}),
    ...(config.teamMode?{teamMode:config.teamMode,excludedModels:config.excludedModels}:{}),
    ...(config.coWriter ? {workflow:config.workflow,collaborator:publicRevisionProvider(config.coWriter)} : {}),
    ...(config.finalReviewer?{finalReviewer:publicRevisionProvider(config.finalReviewer)}:{})};
}

export function collaborativeRevision(writer, primary, model, {localAuth=false,localOrigin,crosscheckModel,teamMode}={}) {
  if(teamMode==="dual") {
    if(!localAuth || primary.provider!=="codex" || crosscheckModel!=="gpt-6.1-sol" || writer.vendor!=="DeepSeek 官方" || writer.baseURL!=="https://api.deepseek.com/v1" || writer.model!=="deepseek-flash")
      throw Error("双模型修订仅支持明确授权的官方 DeepSeek 与本机 GPT 6.1");
    return {...writer,workflow:`www-crosscheck-local-dual-v1:${writer.model}:${crosscheckModel}`,teamMode:"dual",excludedModels:[{vendor:"本机 Claude Code",reason:"UUAPI insufficient balance; author authorized two-model revision"}],coWriter:{provider:"codex",vendor:"本机 Codex",model:crosscheckModel,modelName:"GPT 6.1",localRevisionOnly:writer.localRevisionOnly}};
  }
  if(teamMode)throw Error("未知的写作团队模式");
  if (!model) return writer;
  const names={"claude-opus-5-5":"Opus 5.5","claude-fable-5-1":"Fable 5.1"};
  const authorizedWriter=writer.vendor==="TokenHub" || (writer.vendor==="DeepSeek 官方" && writer.baseURL==="https://api.deepseek.com/v1" && writer.model==="deepseek-flash");
  if (!authorizedWriter || !Object.hasOwn(names,model) || (!localAuth && (!primary.apiKey || new URL(primary.baseURL).hostname !== "uuapi.io")))
    throw Error("联合修订需要已授权写作模型及明确配置的 Claude 协作模型，不会自动替换模型");
  if(crosscheckModel && (!localAuth || crosscheckModel!=="gpt-6.1-sol"))throw Error("三方写作仅支持本机 Claude Code 与明确指定的 GPT 6.1，不会自动换模型");
  if(localAuth)return {...writer,workflow:`www-crosscheck-local-${crosscheckModel?"team-v1":"v1"}:${writer.model}:${model}${crosscheckModel?`:${crosscheckModel}`:""}`,
    coWriter:{provider:"claude",model,modelName:names[model],vendor:"本机 Claude Code",localAuth:true,...(model==="claude-fable-5-1"?{reasoningEffort:"medium"}:{}),...(localOrigin?{configuredOrigin:new URL(localOrigin).origin}:{}),revisionTransport:"claude-cli",localRevisionOnly:writer.localRevisionOnly},
    ...(crosscheckModel?{finalReviewer:{provider:"codex",vendor:"本机 Codex",model:crosscheckModel,modelName:"GPT 6.1",localRevisionOnly:writer.localRevisionOnly}}:{})};
  return {...writer,workflow:`www-crosscheck-v1:${writer.model}:${model}`,
    coWriter:{...primary,model,modelName:names[model],vendor:"UUAPI",apiFormat:"anthropic",revisionTransport:primary.revisionTransport||"api",requireModelIdentity:true,localRevisionOnly:writer.localRevisionOnly}};
}
