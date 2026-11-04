import {test} from "node:test";
import assert from "node:assert/strict";
import {structuredRequest} from "../server/model-api.mjs";
test("explicit model identity is verified before compatible API output is accepted",async t=>{
  let model="claude-fable-5-1",calls=0;
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    calls++;
    const body=JSON.parse(options.body);
    assert.equal(body.model,"claude-fable-5-1");
    assert.deepEqual(body.response_format,{type:"json_object"});
    return {ok:true,json:async()=>({model,choices:[{finish_reason:"stop",message:{content:'{"ok":true}'}}]})};
  });
  const config={baseURL:"https://uuapi.io/v1",apiFormat:"chat-json",model:"claude-fable-5-1",apiKey:"PRIVATE_KEY",requireModelIdentity:true};
  const request={input:"PRIVATE_MANUSCRIPT",schema:{type:"object",properties:{ok:{type:"boolean"}}},name:"result"};
  assert.deepEqual(await structuredRequest(config,request),{ok:true});
  for(model of ["claude-opus-4-8",undefined,"PRIVATE_KEY PRIVATE_MANUSCRIPT"])
    await assert.rejects(structuredRequest(config,request),e=>/模型标识/.test(e.message)&&!e.message.includes("PRIVATE_"));
  assert.equal(calls,4);
});
test("other TokenHub 402 responses identify billing restrictions without exposing upstream data",async t=>{
  t.mock.method(globalThis,"fetch",async()=>({ok:false,status:402,json:async()=>({error:{code:"other",message:"PRIVATE_KEY PRIVATE_MANUSCRIPT"}})}));
  await assert.rejects(structuredRequest({baseURL:"https://tokenhub.tencentmaas.com/v1",apiKey:"PRIVATE_KEY",model:"deepseek-v4.1-flash",apiFormat:"chat-json"},{input:"example",schema:{type:"object"},name:"result"}),error=>{
    assert.match(error.message,/402/);assert.match(error.message,/未自动开启后付费/);assert.ok(!error.message.includes("PRIVATE_"));return true;
  });
});
test("UUAPI Claude client-only rejection is actionable for both protocols without spoofing or retry",async t=>{
  let calls=0;
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    calls++;
    assert.ok(!JSON.stringify(options.headers).includes("attribution"));
    return {ok:false,status:400,json:async()=>({error:{type:"server_error",message:'Claude Code 请求缺少客户端归属信息 CLAUDE_CODE_ATTRIBUTION_HEADER secret-test PRIVATE_MANUSCRIPT'}})};
  });
  for(const apiFormat of ["anthropic","chat-json"]){
    await assert.rejects(structuredRequest({baseURL:"https://uuapi.io/v1",apiFormat,apiKey:"secret-test",model:"claude-sonnet-4-6"},{input:"PRIVATE_MANUSCRIPT",schema:{type:"object"},name:"result"}),error=>{
      assert.match(error.message,/普通 API/);assert.match(error.message,/未应用任何修改/);
      for(const text of ["secret-test","PRIVATE_MANUSCRIPT"])assert.ok(!error.message.includes(text));
      return true;
    });
  }
  assert.equal(calls,2);
});
test("HTML gateway errors expose HTTP status, not page contents or secrets, without retry",async t=>{
  let calls=0;
  t.mock.method(globalThis,"fetch",async()=>{calls++;return {ok:false,status:502,json:async()=>{throw new SyntaxError("secret-test PRIVATE_MANUSCRIPT <!DOCTYPE html>");}};});
  await assert.rejects(structuredRequest({apiKey:"secret-test",model:"test"},{input:"PRIVATE_MANUSCRIPT",schema:{type:"object"},name:"result"}),error=>{
    assert.match(error.message,/HTTP 502/);assert.match(error.message,/网关/);
    for(const text of ["secret-test","PRIVATE_MANUSCRIPT","DOCTYPE"])assert.ok(!error.message.includes(text));return true;
  });assert.equal(calls,1);
});
test("a sole JSON fence is decoded but surrounding prose and invalid escapes are rejected",async t=>{
  let content='```json\n{"ok":true}\n```';
  t.mock.method(globalThis,"fetch",async()=>({ok:true,json:async()=>({stop_reason:"tool_use",content:[{type:"tool_use",name:"result",input:{_raw:content}}]})}));
  const args=[{apiFormat:"anthropic",apiKey:"test",model:"sonnet"},{input:"synthetic",schema:{type:"object"},name:"result"}];
  assert.deepEqual(await structuredRequest(...args),{ok:true});
  content='Explanation\n```json\n{"ok":true}\n```';await assert.rejects(structuredRequest(...args),e=>e.code==='MODEL_JSON_INVALID');
  content='{"source":"\\cite{x}"}';await assert.rejects(structuredRequest(...args),e=>e.code==='MODEL_JSON_INVALID');
});
test("UUAPI serialized tool arrays are decoded losslessly by schema, not guessed from prose",async t=>{
  let fields={patches:JSON.stringify([{before:'A~\\cite{x}.',commentIds:'["c1"]'}]),findings:'not JSON'};
  t.mock.method(globalThis,"fetch",async()=>({ok:true,json:async()=>({stop_reason:"tool_use",content:[{type:"tool_use",name:"result",input:fields}]})}));
  const schema={type:"object",properties:{patches:{type:"array",items:{type:"object",properties:{before:{type:"string"},commentIds:{type:"array",items:{type:"string"}}}}},findings:{type:"array",items:{type:"string"}}}};
  const r=await structuredRequest({baseURL:"https://uuapi.io/v1",apiFormat:"anthropic",apiKey:"test",model:"claude-sonnet-4-6"},{input:"synthetic",schema,name:"result"});
  assert.deepEqual(r.patches,[{before:'A~\\cite{x}.',commentIds:['c1']}]);assert.equal(r.findings,'not JSON');
  fields={_raw:JSON.stringify(fields)};
  const wrapped=await structuredRequest({baseURL:"https://uuapi.io/v1",apiFormat:"anthropic",apiKey:"test",model:"claude-sonnet-4-6"},{input:"synthetic",schema,name:"result"});
  assert.deepEqual(wrapped,r);
});
test("TokenHub quota error is actionable without leaking upstream content or enabling billing",async t=>{
  let calls=0;
  t.mock.method(globalThis,"fetch",async()=>{calls++;return {ok:false,status:402,json:async()=>({error:{code:"401008",message:"secret-test PRIVATE_MANUSCRIPT"}})};});
  await assert.rejects(structuredRequest({baseURL:"https://tokenhub.tencentmaas.com/v1",apiFormat:"chat-json",apiKey:"secret-test",model:"glm-5.1"},{input:"PRIVATE_MANUSCRIPT",schema:{type:"object"},name:"result"}),error=>{
    assert.match(error.message,/免费额度已耗尽/);assert.match(error.message,/未自动启用付费/);
    assert.ok(!error.message.includes("secret-test"));assert.ok(!error.message.includes("PRIVATE_MANUSCRIPT"));return true;
  });
  assert.equal(calls,1);
});
test("TokenHub JSON-object mode embeds schema and refuses truncated output without switching models",async t=>{
  let finish="stop";
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    const body=JSON.parse(options.body);
    assert.equal(url,"https://tokenhub.tencentmaas.com/v1/chat/completions");
    assert.deepEqual(body.response_format,{type:"json_object"});assert.deepEqual(body.thinking,{type:"disabled"});
    assert.ok(body.messages[0].content.includes('"required":["ok"]'));
    return {ok:true,json:async()=>({choices:[{finish_reason:finish,message:{content:'{"ok":true}'}}]})};
  });
  const args=[{apiFormat:"chat-json",baseURL:"https://tokenhub.tencentmaas.com/v1",apiKey:"test",model:"deepseek-v4-pro",disableThinking:true},{instructions:"JSON",input:"test",schema:{type:"object",required:["ok"]},name:"test"}];
  assert.deepEqual(await structuredRequest(...args),{ok:true});finish="length";await assert.rejects(structuredRequest(...args),/输出上限/);
});
test("UUAPI Anthropic adapter uses forced structured output without exposing credentials in prompt",async t=>{
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    assert.equal(url,"https://uuapi.io/v1/messages");
    const body=JSON.parse(options.body);
    assert.equal(options.headers["x-api-key"],"secret-test");
    assert.ok(!options.body.includes("secret-test"));
    assert.deepEqual(body.tool_choice,{type:"tool",name:"result",disable_parallel_tool_use:true});
    assert.equal(body.tools[0].strict,true);
    assert.equal(body.messages[0].content[0].text,"public example");
    assert.equal(body.system[0].type,"text");
    return {ok:true,json:async()=>({stop_reason:"tool_use",content:[{type:"tool_use",name:"result",input:{ok:true}}]})};
  });
  assert.deepEqual(await structuredRequest({baseURL:"https://uuapi.io/v1",apiFormat:"anthropic",apiKey:"secret-test",model:"claude-sonnet-4-6"},{instructions:"JSON only",input:"public example",schema:{type:"object"},name:"result"}),{ok:true});
});
test("truncated Anthropic output is not accepted",async t=>{
  t.mock.method(globalThis,"fetch",async()=>({ok:true,json:async()=>({stop_reason:"max_tokens",content:[]})}));
  await assert.rejects(structuredRequest({apiFormat:"anthropic",apiKey:"test",model:"test"},{input:"x",schema:{type:"object"},name:"result"}),/不完整/);
});
test("Opus 5.5 uses auto tool choice but still rejects prose instead of structured output",async t=>{
  let structured=true;
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    const body=JSON.parse(options.body);
    assert.deepEqual(body.tool_choice,{type:"auto",disable_parallel_tool_use:true});
    assert.equal(body.tools[0].strict,true);
    return {ok:true,json:async()=>structured
      ? {stop_reason:"tool_use",content:[{type:"tool_use",name:"result",input:{ok:true}}]}
      : {stop_reason:"end_turn",content:[{type:"text",text:"Unvalidated prose"}]}};
  });
  const args=[{apiFormat:"anthropic",apiKey:"test",model:"claude-opus-5-5"},{input:"x",schema:{type:"object"},name:"result"}];
  assert.deepEqual(await structuredRequest(...args),{ok:true});
  structured=false;
  await assert.rejects(structuredRequest(...args),/不完整/);
});
test("relay serialized arguments are decoded as JSON, never guessed or repaired",async t=>{
  let raw=JSON.stringify({ok:true});
  t.mock.method(globalThis,"fetch",async()=>({ok:true,json:async()=>({stop_reason:"tool_use",content:[{type:"tool_use",name:"result",input:{_raw:raw}}]})}));
  const args=[{apiFormat:"anthropic",apiKey:"test",model:"test"},{input:"x",schema:{type:"object"},name:"result"}];
  assert.deepEqual(await structuredRequest(...args),{ok:true});
  raw='{"incomplete":';
  await assert.rejects(structuredRequest(...args),/不是合法 JSON/);
});
test("gateway upstream rejection is distinguished from connectivity and never leaks echoed data",async t=>{
  t.mock.method(globalThis,"fetch",async()=>({ok:false,status:400,json:async()=>({error:{type:"upstream_error",message:"当前模型无法继续此对话 secret-test PRIVATE_MANUSCRIPT (request id: abc_123-xyz)"}})}));
  await assert.rejects(structuredRequest({apiFormat:"anthropic",apiKey:"secret-test",model:"claude-opus-5-5"},{input:"PRIVATE_MANUSCRIPT",schema:{type:"object"},name:"result"}),error=>{
    assert.match(error.message,/不是服务器断网/);
    assert.match(error.message,/abc_123-xyz/);
    assert.ok(!error.message.includes("secret-test"));
    assert.ok(!error.message.includes("PRIVATE_MANUSCRIPT"));
    return true;
  });
});
