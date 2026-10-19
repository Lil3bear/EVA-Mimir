import {test} from "node:test";
import assert from "node:assert/strict";
import express from "express";
import http from "node:http";
import {installAccess,passwordHash} from "../server/access.mjs";
test("shared deployment requires authentication, rejects cross-origin requests and signs secure sessions",async t=>{
  const app=express(); app.use(express.json());
  const server=app.listen(0,"127.0.0.1"); await new Promise(r=>server.once("listening",r));
  installAccess(app,{shared:true,origin:"https://papers.example",port:server.address().port,passwordHash:passwordHash("test password"),secret:"s".repeat(64)});
  app.get("/api/private",(req,res)=>res.json({ok:true}));
  t.after(()=>{server.closeAllConnections();server.close();});
  const url=`http://127.0.0.1:${server.address().port}`;
  const headers={Host:"papers.example","Content-Type":"application/json",Origin:"https://papers.example"};
  assert.equal((await fetch(url+"/api/private",{headers})).status,401);
  const login=await fetch(url+"/api/session",{method:"POST",headers,body:JSON.stringify({username:"team",password:"test password"})});
  assert.equal(login.status,200);
  const cookie=login.headers.get("set-cookie");
  for(const flag of ["HttpOnly","Secure","SameSite=Strict"]) assert.ok(cookie.includes(flag));
  assert.equal((await fetch(url+"/api/private",{headers:{...headers,Cookie:cookie.split(";")[0]}})).status,200);
  assert.equal((await fetch(url+"/api/private",{headers:{...headers,Origin:"https://evil.example",Cookie:cookie.split(";")[0]}})).status,403);
  assert.equal(await new Promise(resolve=>http.get(url+"/api/private",{headers:{Host:"evil.example"}},res=>{res.resume();resolve(res.statusCode);})),403);
  assert.equal((await fetch(url+"/api/private",{headers:{...headers,Cookie:`autopaperreview_session=${Date.now()+60000}.${"0".repeat(64)}`}})).status,401);
  for(let i=0;i<10;i++) await fetch(url+"/api/session",{method:"POST",headers,body:JSON.stringify({username:"team",password:"wrong"})});
  assert.equal((await fetch(url+"/api/session",{method:"POST",headers,body:JSON.stringify({username:"team",password:"wrong"})})).status,429);
});
test("public sharing fails closed without credentials",()=>{
  assert.throws(()=>installAccess(express(),{shared:true,port:4317}),/共享部署必须/);
});
