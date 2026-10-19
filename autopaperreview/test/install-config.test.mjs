import {test} from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,readFile,stat,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {execFile} from "node:child_process";
import {promisify} from "node:util";
import {fileURLToPath} from "node:url";

test("fresh team setup creates private credentials without printing or overwriting them",async t=>{
  const directory=await mkdtemp(path.join(tmpdir(),"paper-install-"));
  t.after(()=>rm(directory,{recursive:true,force:true}));
  const args=[fileURLToPath(new URL("../deploy/init-pull-config.mjs",import.meta.url)),"https://papers.example","team"];
  const options={env:{...process.env,TEAM_CONFIG_DIR:directory}};
  const {stdout}=await promisify(execFile)(process.execPath,args,options);
  const file=path.join(directory,"team-bridge.json"),before=await readFile(file,"utf8"),config=JSON.parse(before);
  assert.equal(config.access.origin,"https://papers.example");
  assert.equal(config.token.length,64);assert.equal((await stat(file)).mode&0o777,0o600);
  assert.ok(!stdout.includes(config.token));assert.ok(!stdout.includes(config.access.secret));
  await assert.rejects(promisify(execFile)(process.execPath,args,options));
  assert.equal(await readFile(file,"utf8"),before);
});
