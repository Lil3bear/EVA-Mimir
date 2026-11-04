import {test} from "node:test";
import assert from "node:assert/strict";
import {mkdtemp, readFile, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {experienceStore} from "../server/experience.mjs";

test("experience preserves comment changes, deduplicates retries and excludes credentials", async () => {
  const directory=await mkdtemp(path.join(os.tmpdir(),"experience-test-"));
  try {
    let store=experienceStore(directory);
    const p={id:"paper",name:"Example",comments:[{id:"one",author:"you",body:"Use plain language",status:"open"}],history:[],overleaf:{token:"private-token"}};
    await Promise.all([store.record(p),store.record(p)]);
    p.comments[0].body="No ornamental hyphens";
    await store.record(p);
    p.comments[0].status="resolved";
    await store.record(p);
    store=experienceStore(directory);
    await store.record(p);
    const state=JSON.parse(await readFile(path.join(directory,"events.json")));
    assert.equal(state.events.length,3);
    const md=await store.markdown();
    assert.match(md,/Use plain language/);
    assert.match(md,/No ornamental hyphens/);
    assert.doesNotMatch(md,/private-token/);
    p.comments[0].body="olp_abcdefghijklmnop";
    await store.record(p);
    assert.doesNotMatch(await store.markdown(),/olp_abcdefghijklmnop/);
    assert.match(await store.markdown(),/REDACTED/);
  } finally {await rm(directory,{recursive:true,force:true});}
});

test("personal editing evidence preserves rejected candidates, instructions and skill versions",async()=>{
  const directory=await mkdtemp(path.join(os.tmpdir(),"mimir-evidence-"));
  try {
    const store=experienceStore(directory);
    const p={id:"paper",name:"Demo",comments:[],history:[],reports:[{id:"r",instructions:"Keep the technical claim",skillManifest:{hash:"v1"}}],proposals:[{id:"p",revision:"before",status:"pending",patches:[{before:"old",after:"new",reason:"clarity"}],transport:"pi-cli"}]};
    await store.record(p);p.proposals[0].status="rejected";await store.record(p);
    const state=JSON.parse(await readFile(path.join(directory,"events.json")));
    assert.equal(state.events.filter(e=>e.kind==="revision-result").length,2);
    assert.equal(state.events.find(e=>e.status==="rejected").patches[0].after,"new");
    assert.equal(state.events.find(e=>e.kind==="editing-request").report.skillManifest.hash,"v1");
  } finally {await rm(directory,{recursive:true,force:true});}
});
