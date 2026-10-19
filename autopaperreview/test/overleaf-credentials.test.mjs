import test from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,readFile,stat,writeFile,rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {overleafCredentials} from "../server/overleaf-credentials.mjs";

test("Overleaf credentials survive restart, are URL/project bound, encrypted and removable", async()=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),"overleaf-credentials-"));
  const id="11111111-1111-4111-8111-111111111111", other="22222222-2222-4222-8222-222222222222", url="https://git@git.overleaf.com/test";
  try {
    const store=overleafCredentials(dir);
    assert.equal(await store.get(id,url),undefined);
    await Promise.all([store.set(id,url,"test-only-secret"),store.set(other,url,"other-secret")]);
    assert.equal(await store.get(other,url),"other-secret");
    await store.delete(other);
    const restarted=overleafCredentials(dir);
    assert.equal(await restarted.get(id,url),"test-only-secret");
    assert.equal(await restarted.get(id,url+"other"),undefined);
    assert.equal(await restarted.get(other,url),undefined);
    const encrypted=await readFile(path.join(dir,`${id}.json`),"utf8");
    assert.ok(!encrypted.includes("test-only-secret"));
    assert.equal((await stat(dir)).mode & 0o777,0o700);
    for(const file of ["key",`${id}.json`]) assert.equal((await stat(path.join(dir,file))).mode & 0o777,0o600);
    await writeFile(path.join(dir,`${other}.json`),encrypted);
    await assert.rejects(restarted.get(other,url),/无法解密/);
    await restarted.set(id,url,"replacement");
    assert.equal(await store.get(id,url),"replacement");
    await restarted.delete(id);
    assert.equal(await restarted.get(id,url),undefined);
    await assert.rejects(store.get("../escape",url),/Invalid project/);
  } finally {await rm(dir,{recursive:true,force:true});}
});
