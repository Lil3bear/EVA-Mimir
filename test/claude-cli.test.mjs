import {test} from "node:test";
import assert from "node:assert/strict";
import childProcess from "node:child_process";
import {EventEmitter} from "node:events";
import {PassThrough} from "node:stream";
import {readFileSync} from "node:fs";
import {access as fileAccess,mkdtemp,readFile,rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {executeClaude,claudeRevisionInput} from "../server/claude-cli.mjs";
import {generate} from "../server/ai.mjs";

const config={apiKey:"secret-test",baseURL:"https://uuapi.io/v1",model:"claude-sonnet-4-6"};
const request={instructions:"Use the supplied schema. PRIVATE_INSTRUCTIONS",input:"PRIVATE_MANUSCRIPT",schema:{type:"object",properties:{ok:{type:"boolean"}}}};
const success={subtype:"success",is_error:false,modelUsage:{"claude-sonnet-4-6":{}},result:'{"ok":true}'};
test("native manuscript packing preserves every source character, target identity and candidate without duplicated TeX",()=>{
  const source="  Evidence first.\r\n\r\n中文 and \\cite{x}.\r\n";
  const text="Evidence first.",start=source.indexOf(text);
  const original={documents:[{file:"main.tex",content:source},{file:"refs.bib",content:"BIB"}],sourceTargets:[{id:"T1",file:"main.tex",start,end:start+text.length,text}],
    comments:[{id:"c1"}],collaborationCandidate:{patches:[{targetId:"T1",after:"Evidence matters."}]},
    compilationLog:"package load\nfont load\nLaTeX Warning: unresolved\n continuation\n\nfont load\nOutput written on main.pdf\n"};
  const packed=JSON.parse(claudeRevisionInput(JSON.stringify(original)));
  assert.equal(packed.documents[0].sourceSegments.map(s=>s.text).join(""),source);
  assert.deepEqual(packed.documents[0].sourceSegments.filter(s=>s.targetId),[{targetId:"T1",text}]);
  assert.equal(packed.documents[0].content,undefined);assert.equal(packed.sourceTargets[0].text,undefined);
  assert.equal(packed.documents[1].content,"BIB");assert.deepEqual(packed.collaborationCandidate,original.collaborationCandidate);
  assert.match(packed.compilationLog,/LaTeX Warning/);assert.match(packed.compilationLog,/Output written/);
  assert.match(packed.compilationLogScope,/No manuscript source is omitted/);
  assert.throws(()=>claudeRevisionInput(JSON.stringify({...original,sourceTargets:[{...original.sourceTargets[0],text:"stale"}]})),/分段/);
});
function fakeProcess(t, output, {code=0,inspect=()=>{},hang=false}={}){
  let child;
  t.mock.method(childProcess,"spawn",(binary,args,options)=>{
    inspect(binary,args,options);
    child=Object.assign(new EventEmitter(),{pid:987654321,stdin:new PassThrough(),stdout:new PassThrough(),stderr:new PassThrough()});
    child.stdin.on("finish",()=>{if(!hang)queueMicrotask(()=>{child.stdout.end(typeof output==="string"?output:JSON.stringify(output));child.stderr.end();child.emit("close",code);});});
    return child;
  });
  return ()=>child;
}
test("real CLI transport disables tools and discovery, keeps secrets off argv, verifies model and removes temporary context",async t=>{
  let directory;
  fakeProcess(t,success,{inspect:(binary,args,options)=>{
    directory=options.cwd;
    assert.ok(args.includes("--bare"));assert.ok(args.includes("--no-session-persistence"));
    assert.deepEqual(JSON.parse(args[args.indexOf("--json-schema")+1]),request.schema);assert.equal(args[args.indexOf("--max-turns")+1],"3");
    assert.match(readFileSync(args[args.indexOf("--append-system-prompt-file")+1],"utf8"),/OUTPUT CONTRACT/);
    assert.equal(args[args.indexOf("--tools")+1],"");assert.equal(args[args.indexOf("--setting-sources")+1],"");
    assert.equal(args[args.indexOf("--mcp-config")+1],'{"mcpServers":{}}');
    assert.equal(args[args.indexOf("--model")+1],config.model);assert.ok(!args.includes("--fallback-model"));
    assert.ok(!args.includes("--dangerously-skip-permissions"));
    assert.ok(!JSON.stringify(args).includes("secret-test"));assert.ok(!JSON.stringify(args).includes("PRIVATE_MANUSCRIPT"));
    assert.equal(options.env.ANTHROPIC_API_KEY,"secret-test");assert.equal(options.env.ANTHROPIC_BASE_URL,"https://uuapi.io");
    assert.equal(options.env.HOME,directory);assert.equal(options.env.TEAM_PASSWORD_HASH,undefined);
  }});
  assert.deepEqual(await executeClaude(config,request),{ok:true});
  await assert.rejects(fileAccess(directory));
});
test("CLI errors, prose, unexpected models and missing structured results cannot become source edits",async t=>{
  for(const output of ["secret-test PRIVATE_MANUSCRIPT",{...success,is_error:true,result:"secret-test PRIVATE_MANUSCRIPT"},{...success,modelUsage:{"different-model":{}}},{...success,result:null}]){
    fakeProcess(t,output);
    await assert.rejects(executeClaude(config,request),error=>{assert.ok(!error.message.includes("secret-test"));assert.ok(!error.message.includes("PRIVATE_MANUSCRIPT"));return true;});
  }
  fakeProcess(t,success,{code:1});await assert.rejects(executeClaude(config,request),/请求失败/);
});
test("local Claude uses native login in safe mode, never exports credentials or gateway configuration",async t=>{
  fakeProcess(t,{...success,modelUsage:{"claude-opus-5-5":{}}},{inspect:(binary,args,options)=>{
    assert.ok(args.includes("--safe-mode"));assert.ok(!args.includes("--bare"));
    assert.ok(!args.includes("--setting-sources"));assert.equal(args[args.indexOf("--tools")+1],"");
    assert.notEqual(options.env.HOME,options.cwd);
    for(const key of ["ANTHROPIC_API_KEY","ANTHROPIC_AUTH_TOKEN","ANTHROPIC_BASE_URL","OPENAI_API_KEY","SESSION_SECRET"])
      assert.equal(options.env[key],undefined);
    assert.ok(!args.includes("--fallback-model"));
  }});
  assert.deepEqual(await executeClaude({localAuth:true,model:"claude-opus-5-5"},request),{ok:true});
});
test("Fable text JSON compatibility keeps native authentication, model identity and strict JSON parsing",async t=>{
  fakeProcess(t,{...success,modelUsage:{"claude-fable-5-1":{}}},{inspect:(binary,args)=>{
    assert(args.includes("--safe-mode"));assert(!args.includes("--json-schema"));
    assert.equal(args[args.indexOf("--tools")+1],"");
    assert.match(readFileSync(args[args.indexOf("--append-system-prompt-file")+1],"utf8"),/OUTPUT CONTRACT/);
  }});
  const settings={localAuth:true,model:"claude-fable-5-1",nativeStructuredOutput:false};
  assert.deepEqual(await executeClaude(settings,request),{ok:true});
  fakeProcess(t,{...success,modelUsage:{"claude-fable-5-1":{}},result:"Here is JSON: {\"ok\":true}"});
  await assert.rejects(executeClaude(settings,request),e=>e.code==="MODEL_JSON_INVALID");
});
test("local error diagnostics are private and redact keys without leaking raw provider text to the browser",async t=>{
  const directory=await mkdtemp(path.join(os.tmpdir(),"claude-error-test-"));
  const old=process.env.CLAUDE_LOCAL_ERROR_LOG;
  process.env.CLAUDE_LOCAL_ERROR_LOG=path.join(directory,"error.json");
  t.after(async()=>{if(old===undefined)delete process.env.CLAUDE_LOCAL_ERROR_LOG;else process.env.CLAUDE_LOCAL_ERROR_LOG=old;await rm(directory,{recursive:true,force:true});});
  fakeProcess(t,{subtype:"success",is_error:false,result:"API Error: 400 当前模型无法继续此对话 sk-private-key olp_private PRIVATE_MANUSCRIPT"},{code:1});
  await assert.rejects(executeClaude({model:"claude-opus-5-5",localAuth:true},request),error=>{
    assert.match(error.message,/HTTP 400/);assert.match(error.message,/上游拒绝继续/);
    assert.ok(!error.message.includes("PRIVATE_MANUSCRIPT"));assert.ok(!error.message.includes("sk-private-key"));return true;
  });
  const log=await readFile(process.env.CLAUDE_LOCAL_ERROR_LOG,"utf8");
  assert.ok(!log.includes("sk-private-key"));assert.ok(!log.includes("olp_private"));assert.ok(log.includes("[REDACTED]"));
});
test("an explicit upstream insufficient balance is never misreported as malformed comments or login failure",async t=>{
  fakeProcess(t,{subtype:"success",is_error:true,result:"Failed to authenticate. API Error: 403 insufficient balance PRIVATE_MANUSCRIPT"},{code:1});
  await assert.rejects(executeClaude({localAuth:true,model:"claude-fable-5-1"},request),error=>{
    assert.match(error.message,/余额不足/);assert.match(error.message,/HTTP 403/);
    assert(!error.message.includes("[success]"));assert(!error.message.includes("PRIVATE_MANUSCRIPT"));return true;
  });
});
test("CLI accepts one enclosing JSON code fence losslessly but never extracts JSON from surrounding prose",async t=>{
  fakeProcess(t,{...success,result:'```json\n{"ok":true}\n```'});
  assert.deepEqual(await executeClaude(config,request),{ok:true});
  for (const result of ['Here is the result:\n{"ok":true}', '```json\n{"ok":true}\n```\nDone.', '```json\n{"ok":true,}\n```']) {
    fakeProcess(t,{...success,result});
    await assert.rejects(executeClaude(config,request),error=>error.code==="MODEL_JSON_INVALID");
  }
});
test("native CLI structured output is consumed instead of an empty prose result",async t=>{
  fakeProcess(t,{...success,result:"\n\n",structured_output:{ok:true}});
  assert.deepEqual(await executeClaude(config,request),{ok:true});
  fakeProcess(t,{...success,result:"\n\n",structured_output:[]});
  await assert.rejects(executeClaude(config,request),/未返回结构化/);
  fakeProcess(t,{...success,result:"\n\n"});
  await assert.rejects(executeClaude(config,request),error=>error.code!=="MODEL_JSON_INVALID" && /原生结构化/.test(error.message));
  fakeProcess(t,{...success,result:"API Error: 400 CLAUDE_CODE_ATTRIBUTION_HEADER secret-test"});
  await assert.rejects(executeClaude(config,request),error=>error.code!=="MODEL_JSON_INVALID" && /归属校验/.test(error.message) && !error.message.includes("secret-test"));
});
test("CLI keeps source target catalogue in manuscript data, not duplicated in the output tool schema",async t=>{
  const schema={type:"object",properties:{patches:{type:"array",items:{type:"object",properties:{targetId:{type:"string",enum:["T1","T2"]}}}}}};
  fakeProcess(t,success,{inspect:(binary,args)=>{
    assert.equal(JSON.parse(args[args.indexOf("--json-schema")+1]).properties.patches.items.properties.targetId.enum,undefined);
  }});
  await executeClaude(config,{...request,schema});assert.deepEqual(schema.properties.patches.items.properties.targetId.enum,["T1","T2"]);
});
test("Opus allows a bounded manuscript-writing budget without changing other models",async t=>{
  fakeProcess(t,{...success,modelUsage:{"claude-opus-5-5":{}}},{inspect:(binary,args)=>{
    assert.equal(args[args.indexOf("--max-budget-usd")+1],"4");assert.equal(args[args.indexOf("--max-turns")+1],"3");
  }});
  assert.deepEqual(await executeClaude({...config,model:"claude-opus-5-5"},request),{ok:true});
  fakeProcess(t,{...success,modelUsage:{"claude-fable-5-1":{}}},{inspect:(binary,args)=>{assert.equal(args[args.indexOf("--max-budget-usd")+1],"6");assert.equal(args[args.indexOf("--effort")+1],"medium");}});
  assert.deepEqual(await executeClaude({...config,model:"claude-fable-5-1"},request),{ok:true});
});
test("model mismatch names are diagnostic, never silently normalized or replaced",async t=>{
  fakeProcess(t,{...success,modelUsage:{"claude-opus-4-6":{},"secret-test PRIVATE_MANUSCRIPT":{}}});
  await assert.rejects(executeClaude(config,request),error=>{
    assert.match(error.message,/claude-opus-4-6/);assert.match(error.message,/未识别标识/);
    assert.ok(!error.message.includes("secret-test"));assert.ok(!error.message.includes("PRIVATE_MANUSCRIPT"));return true;
  });
});
test("CLI cancellation and timeout kill the process group without retry",async t=>{
  let killed=0;
  let child=fakeProcess(t,success,{hang:true});
  t.mock.method(process,"kill",(pid,signal)=>{assert.equal(pid,-987654321);assert.equal(signal,"SIGKILL");killed++;queueMicrotask(()=>child().emit("close",null));});
  await assert.rejects(executeClaude(config,{...request,timeoutMs:10}),/超时/);
  const controller=new AbortController();
  child=fakeProcess(t,success,{hang:true,inspect:()=>setTimeout(()=>controller.abort(Error("cancelled")),10)});
  await assert.rejects(executeClaude(config,{...request,signal:controller.signal}),/cancelled/);
  assert.equal(killed,2);
});
test("CLI failure categories are reported without echoing provider messages or credentials",async t=>{
  for(const [subtype,result,expected] of [
    ["error_max_turns","secret-test PRIVATE_MANUSCRIPT",/轮数上限/],
    ["error_max_budget_usd","secret-test",/费用上限/],
    ["error_during_execution","API Error 400 CLAUDE_CODE_ATTRIBUTION_HEADER secret-test",/归属校验/],
    ["success","API Error: 400 检测到 Claude Code 请求可能被第三方中转改写 secret-test",/原始请求体透传/],
    ["error_during_execution","API Error 400 secret-test PRIVATE_MANUSCRIPT",/400/],
    ["error_during_execution","API Error 429 secret-test",/429/],
  ]){
    fakeProcess(t,{is_error:true,subtype,result},{code:1});
    await assert.rejects(executeClaude(config,request),error=>{assert.match(error.message,expected);assert.ok(!error.message.includes("secret-test"));assert.ok(!error.message.includes("PRIVATE_MANUSCRIPT"));return true;});
  }
});
test("revision integration uses the real CLI transport but still materializes and validates current TeX targets",async t=>{
  t.mock.method(globalThis,"fetch",()=>{throw Error("No ordinary API fallback allowed");});
  t.mock.method(childProcess,"spawn",(binary,args)=>{
    const instructions=readFileSync(args[args.indexOf("--append-system-prompt-file")+1],"utf8");
    const schema=JSON.parse(args[args.indexOf("--json-schema")+1]);
    assert.equal(schema.properties.patches.items.properties.targetId.enum,undefined);
    const child=Object.assign(new EventEmitter(),{pid:987654321,stdin:new PassThrough(),stdout:new PassThrough(),stderr:new PassThrough()});
    let input="";child.stdin.on("data",chunk=>{input+=chunk;});
    child.stdin.on("finish",()=>queueMicrotask(()=>{
      const targetId=JSON.parse(input).sourceTargets[0].id;
      child.stdout.end(JSON.stringify({...success,result:JSON.stringify({summary:"Local polish",coverage:"TeX only",findings:[],patches:[{targetId,after:"Evidence matters.",reason:"Local wording",commentIds:["c1"]}]})}));
      child.emit("close",0);
    }));
    return child;
  });
  const result=await generate({comments:[{id:"c1",author:"you",status:"open",quote:"Evidence first."}]},
    {id:"r1",files:{"main.tex":Buffer.from("Evidence first.").toString("base64")}},
    {mode:"revise",skillIds:["writing"],instructions:"Improve the sentence"},
    {...config,provider:"openai",localRevisionOnly:true,revisionTransport:"claude-cli"});
  assert.equal(result.patches[0].file,"main.tex");assert.equal(result.patches[0].before,"Evidence first.");assert.equal(result.patches[0].after,"Evidence matters.");
  const native=await generate({comments:[{id:"c1",author:"you",status:"open",quote:"Evidence first."}]},
    {id:"r1",files:{"main.tex":Buffer.from("Evidence first.").toString("base64")}},
    {mode:"revise",skillIds:["writing"],instructions:"Improve the sentence"},
    {model:config.model,provider:"claude",localAuth:true,localRevisionOnly:true,revisionTransport:"claude-cli"});
  assert.equal(native.patches[0].after,"Evidence matters.");
});
