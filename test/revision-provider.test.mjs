import {test} from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,writeFile,rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {revisionProvider,publicRevisionProvider,collaborativeRevision} from "../server/revision-provider.mjs";
import {execFile} from "node:child_process";
import {promisify} from "node:util";
import {passwordHash} from "../server/access.mjs";

test("explicit dual mode excludes Claude and requires the authorized official writer and native GPT",()=>{
  const writer={provider:"openai",vendor:"DeepSeek 官方",baseURL:"https://api.deepseek.com/v1",model:"deepseek-flash",apiKey:"PRIVATE",localRevisionOnly:true};
  const team=collaborativeRevision(writer,{provider:"codex"},"claude-fable-5-1",{teamMode:"dual",localAuth:true,crosscheckModel:"gpt-6.1-sol"});
  assert.equal(team.coWriter.provider,"codex");assert.equal(team.coWriter.model,"gpt-6.1-sol");assert.equal(team.finalReviewer,undefined);
  assert.equal(publicRevisionProvider(team).teamMode,"dual");assert(!JSON.stringify(publicRevisionProvider(team)).includes("PRIVATE"));
  assert.throws(()=>collaborativeRevision(writer,{provider:"openai"},null,{teamMode:"dual",localAuth:true,crosscheckModel:"gpt-6.1-sol"}));
});

test("official DeepSeek uses a separate fixed-origin credential and the same native crosscheck team",async t=>{
  const directory=await mkdtemp(path.join(os.tmpdir(),"official-deepseek-"));
  t.after(()=>rm(directory,{recursive:true,force:true}));
  const file=path.join(directory,"official.json");
  const settings={baseURL:"https://api.deepseek.com/v1",apiKey:"PRIVATE_OFFICIAL_KEY",model:"deepseek-flash"};
  await writeFile(file,JSON.stringify(settings),{mode:0o600});
  const writer=await revisionProvider({localRevisionOnly:true},"deepseek-official:deepseek-flash",undefined,file);
  const team=collaborativeRevision(writer,{provider:"codex"},"claude-opus-5-5",{localAuth:true,crosscheckModel:"gpt-6.1-sol"});
  assert.equal(team.vendor,"DeepSeek 官方");assert.equal(team.model,"deepseek-flash");assert.equal(team.localRevisionOnly,true);
  assert.equal(team.coWriter.apiKey,undefined);assert.equal(team.finalReviewer.model,"gpt-6.1-sol");
  assert(!JSON.stringify(publicRevisionProvider(team)).includes("PRIVATE"));
  await writeFile(file,JSON.stringify({...settings,baseURL:"https://untrusted.example/v1"}));
  await assert.rejects(revisionProvider({},"deepseek-official:deepseek-flash",undefined,file),/不会转发密钥/);
});

test("native local login cannot be exposed by public binding or shared deployment",async t=>{
  const directory=await mkdtemp(path.join(os.tmpdir(),"local-claude-access-"));
  t.after(()=>rm(directory,{recursive:true,force:true}));
  for(const configuration of [{BIND_HOST:"0.0.0.0",SHARED_MODE:"0"},{BIND_HOST:"127.0.0.1",SHARED_MODE:"1"}])
    await assert.rejects(promisify(execFile)(process.execPath,["server/index.mjs"],{cwd:new URL("..",import.meta.url),timeout:10000,env:{...process.env,DATA_DIR:directory,PORT:"4319",REVISION_COWRITER_AUTH:"local",PUBLIC_ORIGIN:"https://papers.example",TEAM_PASSWORD_HASH:passwordHash("test password"),SESSION_SECRET:"s".repeat(64),...configuration}}),error=>{
      assert.match(error.stderr,/本机 Claude 登录模式只允许本机回环服务/);return true;
    });
});

test("joint configuration is explicit, redacted and does not mutate single-model settings",()=>{
  const writer={provider:"openai",vendor:"TokenHub",model:"deepseek/deepseek-flash",baseURL:"https://tokenhub.tencentmaas.com/v1",apiKey:"PRIVATE_TH",localRevisionOnly:true};
  const primary={provider:"openai",model:"sonnet",baseURL:"https://uuapi.io/v1",apiKey:"PRIVATE_UU"};
  assert.equal(collaborativeRevision(writer,primary,""),writer);
  const config=collaborativeRevision(writer,primary,"claude-opus-5-5");
  assert.equal(config.coWriter.apiKey,"PRIVATE_UU");assert.equal(config.coWriter.localRevisionOnly,true);
  assert.equal(writer.coWriter,undefined);assert.equal(primary.model,"sonnet");
  const safe=publicRevisionProvider(config);assert.equal(safe.collaborator.model,"claude-opus-5-5");
  assert.ok(!JSON.stringify(safe).includes("PRIVATE"));
  const fallback=collaborativeRevision(writer,{...primary,revisionTransport:"claude-cli"},"claude-fable-5-1");
  assert.equal(fallback.coWriter.model,"claude-fable-5-1");
  assert.equal(fallback.coWriter.modelName,"Fable 5.1");
  assert.equal(fallback.coWriter.revisionTransport,"claude-cli");
  assert.equal(fallback.coWriter.requireModelIdentity,true);
  assert.equal(fallback.workflow,"www-crosscheck-v1:deepseek/deepseek-flash:claude-fable-5-1");
  assert.equal(publicRevisionProvider(fallback).collaborator.displayName,"Fable 5.1");
  assert.ok(!JSON.stringify(publicRevisionProvider(fallback)).includes("PRIVATE"));
  assert.equal(config.coWriter.model,"claude-opus-5-5");
  const local=collaborativeRevision(writer,{provider:"codex"},"claude-opus-5-5",{localAuth:true});
  assert.equal(local.coWriter.localAuth,true);assert.equal(local.coWriter.provider,"claude");
  assert.equal(local.coWriter.apiKey,undefined);assert.equal(local.coWriter.baseURL,undefined);
  assert.equal(publicRevisionProvider(local).collaborator.localAuth,true);
  assert.equal(publicRevisionProvider(local).collaborator.apiOrigin,null);
  assert.notEqual(local.workflow,config.workflow);
  const team=collaborativeRevision(writer,{provider:"codex"},"claude-fable-5-1",{localAuth:true,crosscheckModel:"gpt-6.1-sol"});
  assert.equal(team.finalReviewer.provider,"codex");assert.equal(team.finalReviewer.model,"gpt-6.1-sol");
  assert.equal(publicRevisionProvider(team).finalReviewer.displayName,"GPT 6.1");
  assert.notEqual(team.workflow,local.workflow);
  assert.throws(()=>collaborativeRevision(writer,primary,"claude-opus-5-5",{crosscheckModel:"gpt-6.1-sol"}),/三方写作/);
  assert.throws(()=>collaborativeRevision(writer,primary,"claude-fable-5-1",{localAuth:true,crosscheckModel:"another"}),/不会自动换模型/);
  assert.throws(()=>collaborativeRevision(writer,primary,"other"),/不会自动替换/);
});

test("revision backup is explicit, preserves the primary and local-edit policy, and never exposes its key",async t=>{
  const directory=await mkdtemp(path.join(os.tmpdir(),"revision-provider-"));
  t.after(()=>rm(directory,{recursive:true,force:true}));
  const filename=path.join(directory,"providers.json");
  await writeFile(filename,JSON.stringify({baseURL:"https://tokenhub.tencentmaas.com/v1",apiKey:"PRIVATE_BACKUP_KEY",models:[{id:"deepseek/deepseek-flash"}]}),{mode:0o600});
  const primary={provider:"openai",apiKey:"PRIVATE_PRIMARY_KEY",baseURL:"https://uuapi.io/v1",model:"claude-sonnet-4-6",localRevisionOnly:true,revisionTransport:"claude-cli"};
  assert.equal(await revisionProvider(primary,"",filename),primary);
  const selected=await revisionProvider(primary,"tokenhub:deepseek/deepseek-flash",filename);
  assert.equal(selected.model,"deepseek/deepseek-flash");assert.equal(selected.apiKey,"PRIVATE_BACKUP_KEY");
  assert.equal(selected.revisionTransport,"api");assert.equal(selected.localRevisionOnly,true);assert.equal(selected.disableThinking,true);
  assert.equal(primary.model,"claude-sonnet-4-6");assert.equal(primary.apiKey,"PRIVATE_PRIMARY_KEY");
  assert.deepEqual(publicRevisionProvider(selected),{model:"deepseek/deepseek-flash",displayName:"deepseek/deepseek-flash",provider:"openai",vendor:"TokenHub",apiOrigin:"https://tokenhub.tencentmaas.com",backup:true});
  assert.ok(!JSON.stringify(publicRevisionProvider(selected)).includes("PRIVATE_"));
  await assert.rejects(revisionProvider(primary,"tokenhub:missing",filename),/不可用/);
  await assert.rejects(revisionProvider(primary,"primary:claude-sonnet-4-6",filename),/不可用/);
});
