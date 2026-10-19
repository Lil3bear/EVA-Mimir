import {test} from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,mkdir,writeFile,rm} from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import {execFile} from "node:child_process";
import {promisify} from "node:util";
import {fileURLToPath} from "node:url";

test("GPT-only startup never needs Claude or API credentials and clears inherited paid collaborators",async t=>{
  const cwd=await mkdtemp(path.join(os.tmpdir(),"gpt-only-policy-"));
  t.after(()=>rm(cwd,{recursive:true,force:true}));
  const data=path.join(cwd,"data");
  await mkdir(data);await mkdir(path.join(cwd,"server"));
  await writeFile(path.join(data,"local-restore-manifest.json"),JSON.stringify({projects:["fixture"]}));
  await writeFile(path.join(data,"local-claude-config.json"),JSON.stringify({teamMode:"gpt-only",model:"gpt-6.1-sol",reviewer:""}));
  const keys=["AI_PROVIDER","OPENAI_MODEL","LOCAL_REVISION_ONLY","REVISION_REVIEWER","REVISION_COWRITER_MODEL","REVISION_COWRITER_AUTH","REVISION_CROSSCHECK_MODEL","REVISION_TEAM_MODE"];
  await writeFile(path.join(cwd,"server/index.mjs"),`console.log(JSON.stringify(Object.fromEntries(${JSON.stringify(keys)}.map(k=>[k,process.env[k]]))));`);
  const {stdout}=await promisify(execFile)(process.execPath,[fileURLToPath(new URL("../deploy/run-local-claude.mjs",import.meta.url))],{
    cwd,timeout:10000,env:{...process.env,PATH:"",LOCAL_COWRITER_MODEL:"claude-fable-5-1",REVISION_TEAM_MODE:"dual",REVISION_REVIEWER:"deepseek-official:deepseek-flash",REVISION_COWRITER_MODEL:"claude-opus-5-5",REVISION_COWRITER_AUTH:"local",REVISION_CROSSCHECK_MODEL:"gpt-6.1-sol"},
  });
  const config=JSON.parse(stdout);
  assert.equal(config.AI_PROVIDER,"codex");assert.equal(config.OPENAI_MODEL,"gpt-6.1-sol");assert.equal(config.LOCAL_REVISION_ONLY,"1");
  for(const key of keys.filter(k=>k.startsWith("REVISION_")))assert.equal(config[key],"",key);
  await writeFile(path.join(data,"local-claude-config.json"),JSON.stringify({teamMode:"gpt-only",model:"gpt-6-astra",reviewer:""}));
  const astra=await promisify(execFile)(process.execPath,[fileURLToPath(new URL("../deploy/run-local-claude.mjs",import.meta.url))],{cwd,timeout:10000,env:{...process.env,PATH:""}});
  const chosen=JSON.parse(astra.stdout);assert.equal(chosen.OPENAI_MODEL,"gpt-6-astra");
  for(const key of keys.filter(k=>k.startsWith("REVISION_")))assert.equal(chosen[key],"",key);
  await writeFile(path.join(data,"local-claude-config.json"),JSON.stringify({teamMode:"gpt-only",model:"claude-fable-5-1",reviewer:""}));
  await assert.rejects(promisify(execFile)(process.execPath,[fileURLToPath(new URL("../deploy/run-local-claude.mjs",import.meta.url))],{cwd,timeout:10000,env:{...process.env,PATH:""}}),/未授权/);
});
