import {test} from "node:test";
import assert from "node:assert/strict";
import {EventEmitter} from "node:events";
import {PassThrough} from "node:stream";
import {mkdtemp,rm,readdir} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {piResponse,executePi} from "../server/pi-cli.mjs";

const response = (text,stopReason="stop") => JSON.stringify({type:"message_end",message:{role:"assistant",provider:"deepseek",model:"deepseek-flash",stopReason,content:[{type:"text",text}]}})+"\n";
test("Pi parser accepts only complete assistant JSON and rejects truncated or failed output",()=>{
  assert.deepEqual(piResponse(response('{"ok":true}')),{ok:true});
  assert.deepEqual(piResponse(response('```json\n{"ok":true}\n```')),{ok:true});
  assert.throws(()=>piResponse(response("{}","length")),/complete/);
  assert.throws(()=>piResponse(response("{}","error")),/error/);
  assert.throws(()=>piResponse(response("{}"),"different-model"),/unexpected model/);
  const failed=JSON.stringify({type:"message_end",message:{role:"assistant",stopReason:"error",errorMessage:"402 insufficient balance PRIVATE_DIAGNOSTIC"}});
  assert.throws(()=>piResponse(failed),error=>error.code==="DEEPSEEK_BALANCE"&&!error.message.includes("PRIVATE_DIAGNOSTIC"));
  assert.throws(()=>piResponse(response("prose")),{code:"MODEL_JSON_INVALID"});
  assert.throws(()=>piResponse(""),/complete/);
});
test("Pi transport disables tools/discovery, preserves sessions, sends prompt over stdin and supports cancellation",async()=>{
  const directory = await mkdtemp(path.join(os.tmpdir(),"mimir-pi-test-"));
  const previous = process.env.MIMIR_PI_SESSION_DIR;
  process.env.MIMIR_PI_SESSION_DIR = directory;
  let sent;
  const fake = (command,args,options) => {
    assert.equal(command,"pi");assert(args.includes("--no-tools"));assert(args.includes("--no-extensions"));
    assert(args.includes("--no-context-files"));assert(args.includes("--no-approve"));assert(!args.includes("--no-session"));
    assert.equal(args[args.indexOf("--provider")+1],"deepseek");
    assert.equal(options.detached,true);
    const child = new EventEmitter();
    child.stdout=new PassThrough();child.stderr=new PassThrough();child.stdin=new PassThrough();
    child.stdin.on("data",d=>{sent=String(d);});
    queueMicrotask(()=>{child.stdout.write(response('{"ok":true}'));child.emit("close",0);});
    return child;
  };
  try {
    assert.deepEqual(await executePi({model:"deepseek-flash"},{instructions:"SKILLS",input:"PRIVATE_MANUSCRIPT",schema:{type:"object"}},fake),{ok:true});
    assert.match(sent,/SKILLS/);assert.match(sent,/PRIVATE_MANUSCRIPT/);assert.equal((await readdir(directory)).length,1);
    const controller=new AbortController();controller.abort();
    await assert.rejects(executePi({model:"x"},{signal:controller.signal},()=>assert.fail("must not spawn")),{name:"AbortError"});
  } finally {
    if(previous===undefined)delete process.env.MIMIR_PI_SESSION_DIR;else process.env.MIMIR_PI_SESSION_DIR=previous;
    await rm(directory,{recursive:true,force:true});
  }
});
