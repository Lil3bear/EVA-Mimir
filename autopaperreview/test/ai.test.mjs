import { test } from "node:test";
import assert from "node:assert/strict";
import { generate, revisionComments } from "../server/ai.mjs";
import childProcess from "node:child_process";
import {EventEmitter} from "node:events";
import {PassThrough} from "node:stream";
import {writeFile} from "node:fs/promises";
const revision = {
  id: "r1",
  files: { "main.tex": Buffer.from("Evidence first.").toString("base64") },
};
const project = {
  venue: "ICLR 2027",
  comments: [],
  log: "",
  pdfRevision: null,
};
const request = { mode: "review", skillIds: ["writing"], instructions: "" };
function mockResult(value) {return {ok:true,json:async()=>({status:"completed",output:[{content:[{type:"output_text",text:JSON.stringify(value)}]}]})};}
test("unlinked edits receive one constrained correction without inventing links or relaxing the source gate",async t=>{
  let calls=0;
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    const body=JSON.parse(options.body),input=JSON.parse(body.input);calls++;
    if(calls===2)assert.match(body.instructions,/Drop unrelated edits instead of inventing links/);
    return mockResult({summary:"Local",coverage:"TeX",findings:[],patches:[{targetId:input.sourceTargets[0].id,after:"Evidence matters.",reason:"Requested wording",commentIds:calls===1?[]:["c1"]}]});
  });
  const result=await generate({...project,comments:[{id:"c1",author:"you",status:"open",quote:"Evidence first."}]},revision,{...request,mode:"revise"},{apiKey:"test",model:"test",localRevisionOnly:true});
  assert.equal(calls,2);assert.deepEqual(result.effectiveCommentIds,["c1"]);
});
test("AI comments require explicit scope and resolved or archived comments never enter a local revision",async t=>{
  const comments=[{id:"human",author:"you",status:"open",quote:"Evidence first."},{id:"ai",author:"ai",status:"open",file:"main.tex"},
    {id:"resolved",author:"ai",status:"resolved"},{id:"archived",author:"you",status:"open",archivedAt:"now"},{id:"addressed",author:"ai",status:"open",addressed:true}];
  const config={apiKey:"test",model:"test",localRevisionOnly:true};
  assert.deepEqual(revisionComments({...project,comments},{mode:"revise"},config).map(c=>c.id),["human"]);
  assert.deepEqual(revisionComments({...project,comments},{mode:"revise",commentScope:"allPending",commentIds:["ai","resolved"]},config).map(c=>c.id),["ai"]);
  assert.deepEqual(revisionComments({...project,comments},{mode:"revise",commentIds:["ai","resolved"]},{localRevisionOnly:false}).map(c=>c.id),["ai"]);
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    const input=JSON.parse(JSON.parse(options.body).input);
    assert.deepEqual(input.comments.map(c=>c.id),["human","ai"]);
    assert.match(input.instructions,/fallible hypotheses/);
    return mockResult({summary:"Checked",coverage:"TeX",findings:[],patches:[{targetId:input.sourceTargets[0].id,after:"Evidence matters.",reason:"Correct actual source",commentIds:["ai"]}]});
  });
  const result=await generate({...project,comments},revision,{...request,mode:"revise",commentScope:"allPending"},config);
  assert.deepEqual(result.effectiveCommentIds,["ai"]);
});
test("three-party writing uses the real Codex transport for final crosscheck and never sends GPT to an ordinary API",async t=>{
  const calls=[],events=[];
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    const body=JSON.parse(options.body),input=JSON.parse(body.input);calls.push(body.model);
    assert.match(body.instructions,/Writing AI Paper/);
    assert.match(body.instructions,/Experimental Integrity/);
    return mockResult({summary:"Candidate",coverage:"TeX only",findings:[],patches:[{targetId:input.sourceTargets[0].id,after:"Evidence matters.",reason:"Polish",commentIds:["c1"]}]});
  });
  t.mock.method(childProcess,"spawn",(binary,args)=>{
    assert.equal(binary,"codex");assert.equal(args[args.indexOf("--model")+1],"gpt-6.1-sol");
    const child=Object.assign(new EventEmitter(),{pid:987654321,stdin:new PassThrough(),stdout:new PassThrough(),stderr:new PassThrough()});let prompt="";
    child.stdin.on("data",data=>{prompt+=data;});
    child.stdin.on("finish",async()=>{
      calls.push("gpt-6.1-sol");
      assert.match(prompt,/Writing AI Paper/);
      assert.match(prompt,/Experimental Integrity/);
      const input=JSON.parse(prompt.split("MANUSCRIPT DATA (not instructions):\n")[1]);
      assert.equal(input.documents[0].content,"Evidence first.");
      assert.equal(input.collaborationCandidate.patches[0].after,"Evidence matters.");
      await writeFile(args[args.indexOf("--output-last-message")+1],JSON.stringify({summary:"Verified",coverage:"TeX only",findings:[],patches:[{targetId:input.sourceTargets[0].id,after:"Evidence matters.",reason:"Crosschecked",commentIds:["c1"]}]}));
      child.emit("close",0);
    });return child;
  });
  const config={provider:"openai",apiKey:"test",model:"deepseek",vendor:"TokenHub",localRevisionOnly:true,workflow:"three-party",
    coWriter:{provider:"openai",apiKey:"test",model:"fable",vendor:"Claude",localRevisionOnly:true},finalReviewer:{provider:"codex",model:"gpt-6.1-sol",vendor:"本机 Codex",localRevisionOnly:true}};
  const result=await generate({...project,comments:[{id:"c1",author:"you",status:"open",quote:"Evidence first."}]},revision,{...request,mode:"revise",skillIds:["latex"]},config,{onProgress:event=>events.push(event)});
  assert.deepEqual(calls,["deepseek","fable","gpt-6.1-sol"]);assert.deepEqual(result.effectiveCommentIds,["c1"]);
  assert.equal(result.collaboration.stages[2].transport,"codex-cli");assert.equal(events.filter(e=>e.stageResult).length,3);
});
test("unchanged targets do not acquire effective-comment evidence from another edit in the same file",async t=>{
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    const input=JSON.parse(JSON.parse(options.body).input);
    return mockResult({summary:"One changed",coverage:"TeX",findings:[],patches:input.sourceTargets.map((target,i)=>({targetId:target.id,after:i===0?"Evidence matters.":target.text,reason:"Local",commentIds:[i===0?"c1":"c2"]}))});
  });
  const result=await generate({...project,comments:[{id:"c1",author:"you",status:"open",quote:"Evidence first."},{id:"c2",author:"you",status:"open",quote:"Leave unchanged."}]},
    {id:"r",files:{"main.tex":Buffer.from("Evidence first.\n\nLeave unchanged.").toString("base64")}},
    {...request,mode:"revise"},{apiKey:"test",model:"test",localRevisionOnly:true});
  assert.deepEqual(result.effectiveCommentIds,["c1"]);assert.deepEqual(result.patches[0].commentIds,["c1"]);
});
test("joint writing requires DeepSeek draft, Opus refinement and DeepSeek crosscheck on original source",async t=>{
  const calls=[];
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    const body=JSON.parse(options.body),input=JSON.parse(body.input);
    calls.push(body.model);
    assert.equal(input.documents[0].content,"Evidence first.");
    assert(!input.documents.some(d=>/\.(cls|bst)$/.test(d.file)));
    assert.deepEqual(input.contextManifest.typesettingOnly,["acmart.cls","ACM-Reference-Format.bst"]);
    assert.match(input.instructions,/WWW.*The Web Conference/);
    if(calls.length>1){
      assert.equal(input.collaborationCandidate.patches[0].targetId,input.sourceTargets[0].id);
      assert.equal(input.collaborationCandidate.patches[0].before,undefined);
      assert.equal(input.collaborationCandidate.patches[0].after,calls.length===2?"Draft evidence.":"Precise evidence.");
    }
    const after=calls.length===1?"Draft evidence.":"Precise evidence.";
    return mockResult({summary:body.model,coverage:"TeX only",findings:[],patches:[{targetId:input.sourceTargets[0].id,after,reason:"Polish",commentIds:["c1"]}]});
  });
  const config={provider:"openai",apiKey:"test",model:"deepseek",vendor:"TokenHub",localRevisionOnly:true,
    workflow:"joint",coWriter:{provider:"openai",apiKey:"test",model:"opus",vendor:"UUAPI",localRevisionOnly:true}};
  const source={...revision,files:{...revision.files,"acmart.cls":Buffer.from("CLASS_IMPLEMENTATION").toString("base64"),"ACM-Reference-Format.bst":Buffer.from("BIB_STYLE_IMPLEMENTATION").toString("base64")}};
  const result=await generate({...project,comments:[{id:"c1",author:"you",status:"open",quote:"Evidence first."}]},source,{...request,mode:"revise"},config);
  assert.deepEqual(calls,["deepseek","opus","deepseek"]);
  assert.equal(result.patches[0].after,"Precise evidence.");
  assert.deepEqual(result.collaboration.stages.map(s=>s.role),["draft","refine","crosscheck"]);
  assert.ok(!JSON.stringify(result).includes('"apiKey"'));
  assert.match(result.coverage,/未按字符数截断/);
  assert.equal(Buffer.from(revision.files["main.tex"],"base64").toString(),"Evidence first.");
});
test("failed collaborator stops joint writing without accepting the draft or silently falling back",async t=>{
  let calls=0;t.mock.method(globalThis,"fetch",async()=>{
    calls++;if(calls===2)return {ok:false,status:400,json:async()=>({error:{message:"unavailable"}})};
    return mockResult({summary:"draft",coverage:"TeX",findings:[],patches:[]});
  });
  await assert.rejects(generate(project,revision,{...request,mode:"revise"},{apiKey:"test",model:"deepseek",vendor:"TokenHub",coWriter:{apiKey:"test",model:"opus",vendor:"UUAPI"}}),/refine.*未应用任何联合修改/);
  assert.equal(calls,2);
});
test("final crosscheck can veto edits; an earlier candidate is never used as fallback",async t=>{
  let calls=0;t.mock.method(globalThis,"fetch",async()=>{
    calls++;
    return mockResult({summary:calls===3?"Vetoed":"Draft",coverage:"TeX",findings:[],patches:calls===3?[]:[{file:"main.tex",before:"Evidence first.",after:"Unsafe assertion.",reason:"Draft",commentIds:[]}]});
  });
  const result=await generate(project,revision,{...request,mode:"revise"},{apiKey:"test",model:"deepseek",vendor:"TokenHub",coWriter:{apiKey:"test",model:"opus",vendor:"UUAPI"}});
  assert.equal(calls,3);assert.deepEqual(result.patches,[]);assert.equal(result.collaboration.stages.length,3);
  assert.equal(result.collaboration.stages[0].patches.length,1);
});
test("UUAPI Sonnet revisions use source targets without changing the configured API protocol",async t=>{
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    assert.equal(url,'https://uuapi.io/v1/messages');const body=JSON.parse(options.body);
    assert.equal(body.model,'claude-sonnet-4-6');
    const input=JSON.parse(body.messages[0].content[0].text),target=input.sourceTargets[0];
    assert.ok(body.tools[0].input_schema.properties.patches.items.properties.targetId);
    assert.equal(body.tools[0].input_schema.properties.patches.items.properties.before,undefined);
    return {ok:true,json:async()=>({stop_reason:'tool_use',content:[{type:'tool_use',name:'paper_review',input:{summary:'ok',coverage:'TeX',findings:[],patches:[{targetId:target.id,after:'Evidence matters.',reason:'polish',commentIds:['c1']}]}}]})};
  });
  const r=await generate({...project,comments:[{id:'c1',author:'you',status:'open',quote:'Evidence first.'}]},revision,{...request,mode:'revise'},{provider:'openai',apiKey:'test',baseURL:'https://uuapi.io/v1',apiFormat:'anthropic',model:'claude-sonnet-4-6',localRevisionOnly:true});
  assert.equal(r.patches[0].before,'Evidence first.');assert.equal(r.patches[0].after,'Evidence matters.');
});
test("PDF quote is only a hint: exact current TeX and non-overlapping patches are required before saving",async t=>{
  const source="An agent~\\cite{smith} improves.\nNext sentence.";
  const rev={id:"tex-current",files:{"main.tex":Buffer.from(source).toString("base64"),"figure.pdf":Buffer.from("PDF_BINARY").toString("base64")}};
  const p={...project,pdfRevision:"old-pdf",comments:[{id:"c1",quote:"An agent [1] improves."}]};
  let calls=0;const events=[];
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    const body=JSON.parse(options.body),input=JSON.parse(body.input);calls++;
    assert.equal(input.documents.length,1);assert.equal(input.documents[0].content,source);
    assert.equal(input.editingContract.target,"Current .tex source files in documents, NEVER the PDF or extracted PDF text");
    if(calls===2)assert.match(body.instructions,/VALIDATION FEEDBACK/);
    return mockResult({summary:"ok",coverage:"TeX only",findings:[],patches:[{file:"main.tex",before:calls===1?p.comments[0].quote:source,after:"An improved sentence.",reason:"polish",commentIds:["c1"]}]});
  });
  const r=await generate(p,rev,{...request,mode:"revise"},{apiKey:"test",model:"sonnet"},{onProgress:e=>events.push(e)});
  assert.equal(calls,2);assert.equal(r.patches[0].before,source);assert.ok(events.some(e=>e.message.includes("仅重试一次")));
  assert.equal(Buffer.from(rev.files['main.tex'],'base64').toString(),source);
});
test("serialized patch arrays are rejected and regenerated, never coerced or silently accepted",async t=>{
  let calls=0;t.mock.method(globalThis,"fetch",async()=>{calls++;return mockResult({summary:"ok",coverage:"source",findings:[],patches:"[]"});});
  await assert.rejects(generate(project,revision,{...request,mode:"revise"},{apiKey:"test",model:"test"}),/两次.*结构格式/);assert.equal(calls,2);
});
test("overlapping TeX replacements cannot invalidate a later patch silently",async t=>{
  let calls=0;t.mock.method(globalThis,"fetch",async()=>{calls++;return mockResult({summary:"ok",coverage:"source",findings:[],patches:[{file:"main.tex",before:"Evidence first.",after:"Evidence matters.",reason:"polish",commentIds:[]},{file:"main.tex",before:"Evidence first.",after:"Evidence is first.",reason:"polish",commentIds:[]}]});});
  await assert.rejects(generate(project,revision,{...request,mode:"revise"},{apiKey:"test",model:"test"}),/两次.*TeX 原文定位/);assert.equal(calls,2);
});
test("upstream failures do not cause billable retry or model switching",async t=>{
  let calls=0;t.mock.method(globalThis,"fetch",async()=>{calls++;return {ok:false,status:400,json:async()=>({error:{type:"upstream_error",message:"Unavailable"}})};});
  await assert.rejects(generate(project,revision,{...request,mode:"revise"},{apiKey:"test",model:"claude-sonnet-4-6",apiFormat:"anthropic"}),/400/);assert.equal(calls,1);
});
test("malformed serialized tool JSON gets one correction request, not a silent repair",async t=>{
  let calls=0;t.mock.method(globalThis,"fetch",async()=>{calls++;return {ok:true,json:async()=>({stop_reason:"tool_use",content:[{type:"tool_use",name:"paper_review",input:{_raw:calls===1?'{"patches":':JSON.stringify({summary:"ok",coverage:"source",findings:[],patches:[]})}}]})};});
  const result=await generate(project,revision,{...request,mode:"revise"},{apiKey:"test",model:"claude-sonnet-4-6",apiFormat:"anthropic"});
  assert.deepEqual(result.patches,[]);assert.equal(calls,2);
});
test("local revision policy blocks global requests and unlinked edits, keeping full paper context",async t=>{
  const config={apiKey:"test",model:"claude-sonnet-4-6",localRevisionOnly:true};
  await assert.rejects(generate(project,revision,{...request,mode:"revise"},config),/全局修改已暂时关闭/);
  let unlinked=false;
  const id="f8a13d66-93cf-4bc5-8d2d-0ebf8b375daa";
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    const body=JSON.parse(options.body),input=JSON.parse(body.input);
    assert.equal(input.comments.length,1);assert.equal(input.comments[0].id,id);
    assert.ok(input.documents.some(d=>d.content==="Evidence first."));
    assert.match(input.instructions,/global rewriting is disabled/);
    assert.equal(input.sourceTargets[0].text,"Evidence first.");
    return {ok:true,json:async()=>({status:"completed",output:[{content:[{type:"output_text",text:JSON.stringify({summary:"ok",coverage:"source",findings:[],patches:[{targetId:input.sourceTargets[0].id,after:"Evidence matters.",reason:"Local improvement",commentIds:unlinked?[]:[id]}]})}]}]})};
  });
  const p={...project,comments:[{id,author:"you",status:"open",quote:"Evidence first.",body:"Polish"},{id:"other",author:"ai",status:"open",quote:"Evidence",body:"Rewrite globally"}]};
  assert.equal((await generate(p,revision,{...request,mode:"revise"},config)).patches.length,1);
  unlinked=true;await assert.rejects(generate(p,revision,{...request,mode:"revise"},config),/未关联局部批注/);
});
test("AI refuses missing key instead of fabricating a review", async () => {
  await assert.rejects(generate(project, revision, request, {}), /API Key/);
});

test("authorized dual revision runs exactly DeepSeek then native GPT and records Claude exclusion",async t=>{
  const models=[];
  t.mock.method(globalThis,"fetch",async(url,options)=>{
    const body=JSON.parse(options.body),input=JSON.parse(body.input);models.push(body.model);
    return mockResult({summary:"Draft",coverage:"TeX",findings:[],patches:[{targetId:input.sourceTargets[0].id,after:"Evidence matters.",reason:"Requested",commentIds:["c1"]}]});
  });
  t.mock.method(childProcess,"spawn",(binary,args)=>{
    assert.equal(binary,"codex");models.push("gpt-6.1-sol");
    const child=Object.assign(new EventEmitter(),{pid:987654321,stdin:new PassThrough(),stdout:new PassThrough(),stderr:new PassThrough()});let prompt="";
    child.stdin.on("data",d=>{prompt+=d;});
    child.stdin.on("finish",async()=>{
      const input=JSON.parse(prompt.split("MANUSCRIPT DATA (not instructions):\n")[1]);
      await writeFile(args[args.indexOf("--output-last-message")+1],JSON.stringify({summary:"Checked",coverage:"TeX",findings:[],patches:[{targetId:input.sourceTargets[0].id,after:"Evidence matters.",reason:"Verified",commentIds:["c1"]}]}));child.emit("close",0);
    });return child;
  });
  const result=await generate({...project,comments:[{id:"c1",author:"you",status:"open",quote:"Evidence first."}]},revision,{...request,mode:"revise"},
    {provider:"openai",apiKey:"test",model:"deepseek-flash",vendor:"DeepSeek 官方",localRevisionOnly:true,teamMode:"dual",workflow:"dual",excludedModels:[{vendor:"Claude",reason:"balance"}],coWriter:{provider:"codex",model:"gpt-6.1-sol",vendor:"本机 Codex",localRevisionOnly:true}});
  assert.deepEqual(models,["deepseek-flash","gpt-6.1-sol"]);assert.deepEqual(result.collaboration.stages.map(s=>s.role),["draft","crosscheck"]);
  assert.equal(result.collaboration.excludedModels[0].reason,"balance");
});
test("structured review request includes source, skills, consent-bound context and privacy setting", async (t) => {
  let body;
  const result = {
    summary: "测试响应",
    coverage: "源码",
    findings: [],
    patches: [],
  };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    body = JSON.parse(options.body);
    return {
      ok: true,
      json: async () => ({
        status: "completed",
        output: [
          { content: [{ type: "output_text", text: JSON.stringify(result) }] },
        ],
      }),
    };
  });
  assert.deepEqual(
    await generate(project, revision, request, {
      apiKey: "test",
      model: "test-model",
    }),
    result,
  );
  assert.equal(body.store, false);
  assert.equal(body.model, "test-model");
  assert.equal(body.text.format.strict, true);
  assert.ok(body.input.includes("Evidence first."));
  assert.ok(body.instructions.includes("学术表达"));
});
test("incomplete output cannot be treated as a completed review", async (t) => {
  t.mock.method(globalThis, "fetch", async () => ({
    ok: true,
    json: async () => ({ status: "incomplete" }),
  }));
  await assert.rejects(
    generate(project, revision, request, { apiKey: "test", model: "test" }),
    /不完整/,
  );
});
test("AI only receives the bibliography audit for the exact manuscript revision", async (t) => {
  let input;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    input = JSON.parse(JSON.parse(options.body).input);
    return {ok:true,json:async()=>({status:"completed",output:[{content:[{type:"output_text",text:JSON.stringify({summary:"ok",coverage:"source",findings:[],patches:[]})}]}]})};
  });
  await generate({...project,bibAudit:{revision:"r1",entries:[]}},revision,request,{apiKey:"test",model:"test"});
  assert.match(input.bibliographyAudit.scope,/metadata only/);
  await generate({...project,bibAudit:{revision:"old",entries:[]}},revision,request,{apiKey:"test",model:"test"});
  assert.equal(input.bibliographyAudit,null);
});

test("patch schema permits only actual existing comment IDs, not reviewer finding labels", async (t) => {
  let format;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    format = JSON.parse(options.body).text.format;
    return {
      ok: true,
      json: async () => ({
        status: "completed",
        output: [
          {
            content: [
              {
                type: "output_text",
                text: JSON.stringify({
                  summary: "test",
                  coverage: "source",
                  findings: [],
                  patches: [],
                }),
              },
            ],
          },
        ],
      }),
    };
  });
  const id = "f8a13d66-93cf-4bc5-8d2d-0ebf8b375daa";
  await generate(
    {
      ...project,
      comments: [{ id, body: "Revise this sentence.", status: "open" }],
    },
    revision,
    request,
    { apiKey: "test", model: "test" },
  );
  assert.deepEqual(
    format.schema.properties.patches.items.properties.commentIds.items.enum,
    [id],
  );
  await generate(project, revision, request, { apiKey: "test", model: "test" });
  assert.equal(
    format.schema.properties.patches.items.properties.commentIds.maxItems,
    0,
  );
});

test("manuscripts over 250,000 characters are sent in full without an application character cap", async (t) => {
  const content = "Full manuscript. ".repeat(30000) + "END_OF_MANUSCRIPT";
  const template = "Template content. ".repeat(20000) + "END_OF_TEMPLATE";
  const largeRevision = {
    id: "large",
    files: {
      "main.tex": Buffer.from(content).toString("base64"),
      "acmart.cls": Buffer.from(template).toString("base64"),
    },
  };
  let received;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    received = JSON.parse(JSON.parse(options.body).input).documents;
    return {
      ok: true,
      json: async () => ({
        status: "completed",
        output: [
          {
            content: [
              {
                type: "output_text",
                text: JSON.stringify({
                  summary: "test",
                  coverage: "source",
                  findings: [],
                  patches: [],
                }),
              },
            ],
          },
        ],
      }),
    };
  });
  await generate(project, largeRevision, request, {
    apiKey: "test",
    model: "test",
  });
  assert.equal(received.find((d) => d.file === "main.tex").content, content);
  assert.equal(received.find((d) => d.file === "acmart.cls").content, template);
});
