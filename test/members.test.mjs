import {test} from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,rm,readFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import express from "express";
import {installAccess,passwordHash} from "../server/access.mjs";
import {actorHeader,verifiedActor} from "../server/actor.mjs";
import {experienceStore} from "../server/experience.mjs";

test("personal accounts persist, reject shared login and spoofing, deduplicate presence",async t=>{
  const directory=await mkdtemp(path.join(tmpdir(),"members-"));
  t.after(()=>rm(directory,{recursive:true,force:true}));
  const options={shared:true,origin:"https://papers.example",passwordHash:passwordHash("invite"),secret:"s".repeat(64),membersFile:path.join(directory,"members.json")};
  async function serve() {
    const app=express();app.use(express.json());
    const server=app.listen(0,"127.0.0.1");await new Promise(r=>server.once("listening",r));
    installAccess(app,{...options,port:server.address().port});
    t.after(()=>{server.closeAllConnections();server.close();});
    return async (route,body,cookie)=>fetch(`http://127.0.0.1:${server.address().port}/api/${route}`,{method:body===undefined?"GET":"POST",headers:{"content-type":"application/json",...(cookie?{Cookie:cookie}:{})},body:body===undefined?undefined:JSON.stringify(body)});
  }
  const request=await serve();
  assert.equal((await request("session",{username:"team",password:"invite"})).status,400);
  assert.equal((await request("session",{username:"alice",password:"personal-password",register:true,displayName:"Alice",invitePassword:"bad"})).status,401);
  const cookies=[],ids=[];
  for(const name of ["Alice","Bob"]) {
    const response=await request("session",{username:name,password:"personal-password",register:true,displayName:name,invitePassword:"invite"});
    assert.equal(response.status,200);cookies.push(response.headers.get("set-cookie").split(";")[0]);ids.push((await response.json()).member.id);
  }
  assert.notEqual(ids[0],ids[1]);
  await request("session/presence",{},cookies[0]);
  assert.equal((await (await request("session/presence",{},cookies[0])).json()).count,1);
  assert.equal((await (await request("session/presence",{},cookies[1])).json()).count,2);
  assert.equal((await request("session/presence",{})).status,401);
  assert.equal((await request("session",{username:"alice",password:"wrong"})).status,401);
  const restarted=await serve();
  assert.equal((await (await restarted("session",undefined,cookies[0])).json()).member.id,ids[0]);
  const stored=await readFile(options.membersFile,"utf8");assert.ok(!stored.includes("personal-password"));
  const actor={id:ids[0],name:"Alice"},secret="k".repeat(64);
  const header=actorHeader(actor,"POST","/api/projects/p/comments",secret)["x-workspace-actor"];
  assert.deepEqual(verifiedActor(header,"POST","/api/projects/p/comments",secret),actor);
  assert.equal(verifiedActor(header,"POST","/api/projects/other/comments",secret),null);
  assert.equal(verifiedActor(header,"POST","/api/projects/p/comments","wrong"),null);
  const store=experienceStore(path.join(directory,"experience"));
  await store.recordOperation("p","rev",{actor,method:"POST",url:"/api/projects/p/comments"});
  assert.ok((await store.markdown()).includes(ids[0]));
});
