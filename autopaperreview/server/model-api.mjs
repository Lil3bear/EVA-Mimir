export async function structuredRequest(config, { instructions, input, schema, name, signal, maxTokens = 16000 }) {
  const baseURL = (config.baseURL || "https://api.openai.com/v1").replace(/\/$/, "");
  const anthropic = config.apiFormat === "anthropic";
  const chat = ["chat", "chat-json"].includes(config.apiFormat);
  const body = anthropic ? {
    model: config.model, max_tokens: maxTokens, system: [{type:"text",text:`${instructions}\nReturn the result using the ${name} tool (structured output only, no action execution). Encode all quotation marks, backslashes and newlines with valid JSON escapes. Write summaries and reasons as plain prose without embedded ASCII double quotation marks; source patches must still preserve the exact original text.`}],
    messages: [{role:"user", content:[{type:"text",text:input}]}],
    tools: [{name, description:"Return the structured result. This tool does not execute any action.", input_schema:schema, strict:true}],
    // UUAPI Opus 5.5 rejects forced tool choice; tool-only validation below still applies.
    tool_choice: config.model === "claude-opus-5-5"
      ? {type:"auto", disable_parallel_tool_use:true}
      : {type:"tool", name, disable_parallel_tool_use:true},
  } : chat ? {
    model:config.model, messages:[{role:"system",content:config.apiFormat === "chat-json" ? `${instructions}\nReturn only the JSON DATA INSTANCE, not the schema. Root keys must be exactly: ${Object.keys(schema.properties||{}).join(", ")}. Never echo schema metadata (type, properties, required, additionalProperties), add a wrapper, or output Markdown. The following schema is a contract, NOT the answer:\n${JSON.stringify(schema)}` : instructions},{role:"user",content:input}],
    response_format:config.apiFormat === "chat-json" ? {type:"json_object"} : {type:"json_schema",json_schema:{name,strict:true,schema}},
    max_tokens:maxTokens,
    ...(config.disableThinking ? {thinking:{type:"disabled"}} : {}),
    ...(config.reasoningEffort ? {reasoning_effort:config.reasoningEffort} : {}),
  } : {
    model:config.model, store:false, instructions, input,
    text:{format:{type:"json_schema",name,strict:true,schema}}, max_output_tokens:maxTokens,
  };
  const response = await fetch(`${baseURL}/${anthropic ? "messages" : chat ? "chat/completions" : "responses"}`, {
    method:"POST",
    headers: {"Content-Type":"application/json", ...(anthropic ? {"x-api-key":config.apiKey,"anthropic-version":"2023-06-01"} : {Authorization:`Bearer ${config.apiKey}`})},
    signal:signal ? AbortSignal.any([signal,AbortSignal.timeout(240000)]) : AbortSignal.timeout(240000),
    body:JSON.stringify(body),
  });
  let data;
  try {data=await response.json();}
  catch {throw new Error(`模型网关未返回可解析的 JSON（HTTP ${response.status}），请检查网关或上游服务。未保存模型结果、未应用修改。`);}
  if(!data || typeof data!=="object" || Array.isArray(data))throw new Error("模型网关返回无法识别的数据格式，未保存模型结果、未应用修改。");
  if (!response.ok) {
    if (response.status === 402 && new URL(baseURL).hostname === "tokenhub.tencentmaas.com" && String(data.error?.code) === "401008") {
      throw new Error("TokenHub 此模型免费额度已耗尽且未开启后付费（402）；请管理员检查控制台额度。未自动启用付费，也未切换模型。");
    }
    if(response.status === 402 && new URL(baseURL).hostname === "tokenhub.tencentmaas.com")
      throw new Error("TokenHub 拒绝此模型请求（402：额度或计费权限不足），请检查该模型额度与计费配置。未自动开启后付费，也未切换模型。");
    const message = typeof data.error?.message === "string" ? data.error.message : "";
    if (response.status === 400 && new URL(baseURL).hostname === "uuapi.io" &&
        (message.includes("CLAUDE_CODE_ATTRIBUTION_HEADER") || message.includes("Claude Code 请求缺少客户端归属信息"))) {
      throw new Error("UUAPI 上游拒绝网页请求（400）：上游报告缺少 Claude Code 客户端归属信息。此网页使用标准 API，不是 Claude Code 客户端；请联系 UUAPI 确认该密钥的 Claude 通道支持普通 API 调用。未应用任何修改；不会伪造客户端身份、自动重试或切换模型。");
    }
    if (anthropic && response.status === 400 && data.error?.type === "upstream_error") {
      // Only expose the gateway's request ID, never its raw message or echoed manuscript/credentials.
      const safeMessage = config.apiKey ? message.replaceAll(config.apiKey, "[REDACTED]") : message;
      const requestId = safeMessage.match(/\brequest id:\s*([A-Za-z0-9_-]{1,100})\b/i)?.[1];
      throw new Error(`模型网关已连通，但上游 Claude 拒绝本次请求（400）。${message.includes("当前模型无法继续此对话") ? "上游报告当前会话无法继续；这不是服务器断网。" : "需要提供商排查上游服务。"}未应用任何修改。${requestId ? `请求编号：${requestId}` : ""}`);
    }
    throw new Error(`模型请求失败 (${response.status})，请检查服务端提供商、额度与模型配置`);
  }
  if (config.requireModelIdentity && data.model !== config.model)
    throw new Error("模型网关返回的模型标识与指定模型不一致或缺失，未保存模型结果、未应用修改；不会自动替换模型。");
  if (anthropic) {
    if (data.stop_reason !== "tool_use") throw new Error(data.stop_reason==="max_tokens"?"模型输出不完整：达到本次输出上限，未保存模型结果、未应用修改。":"模型输出不完整或没有返回结构化结果，未保存修改");
    const tool = data.content?.find(c => c.type === "tool_use" && c.name === name);
    if (!tool?.input) throw new Error("模型没有返回结构化结果");
    // Some compatible relays wrap serialized tool arguments instead of decoding them.
    if (typeof tool.input._raw === "string" && Object.keys(tool.input).length === 1) {
      const decoded=parseModelJSON(tool.input._raw);
      return new URL(baseURL).hostname === "uuapi.io" ? decodeSerializedToolFields(decoded,schema) : decoded;
    }
    return new URL(baseURL).hostname === "uuapi.io" ? decodeSerializedToolFields(tool.input,schema) : tool.input;
  }
  if (chat) {
    if (data.choices?.[0]?.finish_reason !== "stop") throw new Error(data.choices?.[0]?.finish_reason==="length"?"模型输出不完整：达到本次输出上限，未保存模型结果、未应用修改。":"模型输出不完整，未保存修改");
    return parseModelJSON(data.choices[0].message.content);
  }
  if (data.status !== "completed") throw new Error(`模型输出不完整 (${data.status})，未保存修改`);
  const output = data.output?.flatMap(o=>o.content||[]).filter(c=>c.type === "output_text").map(c=>c.text).join("");
  if (!output) throw new Error("模型拒绝请求或没有返回结构化结果");
  return parseModelJSON(output);
}

export function parseModelJSON(text) {
  // A single enclosing Markdown fence is presentation, not a repair of the JSON payload.
  const value=typeof text === "string" ? text.trim() : "";
  const fenced=value.match(/^```(?:json)?\s*\n([\s\S]*?)\n```$/);
  try {return JSON.parse(fenced ? fenced[1] : value);}
  catch {const error=new Error("模型返回的结构化结果不是合法 JSON，未应用任何修改");error.code="MODEL_JSON_INVALID";throw error;}
}

// Some relays serialize individual tool containers; decode JSON only, never repair prose or source strings.
function decodeSerializedToolFields(value,schema) {
  if(["array","object"].includes(schema?.type) && typeof value === "string") {
    try {
      const decoded=JSON.parse(value);
      if(schema.type === "array" ? Array.isArray(decoded) : decoded && typeof decoded === "object" && !Array.isArray(decoded))value=decoded;
    } catch { /* Keep invalid data for strict caller validation. */ }
  }
  if(schema?.type === "array" && Array.isArray(value))return value.map(item=>decodeSerializedToolFields(item,schema.items));
  if(schema?.type === "object" && value && typeof value === "object" && !Array.isArray(value))return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,decodeSerializedToolFields(item,schema.properties?.[key])]));
  return value;
}
