import {test} from "node:test";
import assert from "node:assert/strict";
import {loadPDF,pdfErrorMessage} from "../src/pdf-load.mjs";

test("PDF retries a transient read with exactly the same URL and destroys failed tasks",async()=>{
  const calls=[],retries=[];let destroyed=0;
  const loading=loadPDF(options=>{
    calls.push(options);
    return {promise:calls.length<3?Promise.reject({status:503}):Promise.resolve("document"),destroy(){destroyed++;}};
  },{url:"/api/projects/one/pdf/exact-revision"},{delays:[1,1],onRetry:n=>retries.push(n)});
  assert.equal(await loading.promise,"document");
  assert.equal(destroyed,2);assert.deepEqual(retries,[1,2]);
  assert.deepEqual(calls.map(c=>c.url),Array(3).fill("/api/projects/one/pdf/exact-revision"));
  await loading.destroy();assert.equal(destroyed,3);
});
test("PDF retry is bounded and does not retry authorization, missing or corrupt files",async()=>{
  for(const error of [{status:401},{status:403},{status:404},{name:"InvalidPDFException"},{status:503},{status:524}]) {
    let calls=0;
    const loading=loadPDF(()=>({promise:(calls++,Promise.reject(error)),destroy(){}}),{url:"/pdf"},{delays:[1,1]});
    await assert.rejects(loading.promise);
    assert.equal(calls,[503,524].includes(error.status)?3:1);
    assert(!pdfErrorMessage(error).includes("Unexpected server response"));
  }
});
test("destroying a PDF during retry prevents any later read",async()=>{
  let calls=0,loading;
  loading=loadPDF(()=>({promise:(calls++,Promise.reject({status:503})),destroy(){}}),{url:"/pdf"},{delays:[100],onRetry(){queueMicrotask(()=>loading.destroy());}});
  await assert.rejects(loading.promise);assert.equal(calls,1);
});
