import {test} from "node:test";
import assert from "node:assert/strict";
import {createTranslationClient} from "../src/translation-client.mjs";
test("browser translation is cached and never calls a paid model",async()=>{
  let calls=0;
  const client=createTranslationClient({native:()=>({create:async()=>({translate:async()=>{calls++;return "译文";}})}),request:()=>{throw Error("paid API must not be used");}});
  assert.equal(await client({text:"Paper",engine:"browser"}),"译文");
  assert.equal(await client({text:"Paper",engine:"browser"}),"译文");
  assert.equal(calls,1);
});
test("unsupported local translation never silently falls back to a paid engine",async()=>{
  let paid=0;
  const client=createTranslationClient({native:()=>null,request:async()=>{paid++;return {translation:"paid"};}});
  await assert.rejects(client({text:"Paper",engine:"browser"}),/不会自动调用/);
  assert.equal(paid,0);
  assert.equal(await client({text:"Paper",engine:"fast",model:"cheap"}),"paid");
  assert.equal(await client({text:"Paper",engine:"fast",model:"cheap"}),"paid");
  assert.equal(paid,1);
});
