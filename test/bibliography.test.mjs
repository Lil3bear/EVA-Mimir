import {test} from "node:test";
import assert from "node:assert/strict";
import {bibliography, safeArticleURL, verifyEntry} from "../server/bibliography.mjs";
import {citationEntry} from "../src/citation-links.mjs";
const encoded = value => Buffer.from(value).toString("base64");
test("Bib parser handles macros, braces and duplicates; local checks identify missing and empty citations", () => {
  const result = bibliography({"r.bib": encoded('@string{venue="Test Journal"}\n@article{a,title={{A {nested} title}},author={Smith, John},year={2025},journal=venue,doi={10.1234/test}}\n@misc{a,title={Second},url={javascript:alert(1)}}'), "main.tex": encoded('\\cite{a,missing} \\citep{} % \\cite{ignored}\n')});
  assert.equal(result.entries.length,2);
  assert.equal(result.entries[0].url,"https://doi.org/10.1234/test");
  assert.equal(result.entries[1].url,null);
  assert.ok(result.entries.every(e => e.problems.some(p => p.includes("重复引用键"))));
  assert.ok(result.issues.some(e => e.message.includes("missing")));
  assert.ok(result.issues.some(e => e.message === "存在空引用"));
  assert.ok(!result.issues.some(e => e.message.includes("ignored")));
});
test("citation links use exact PDF destinations, never bibliography order or guessed citation numbers", () => {
  const entries = [{key:"key",url:"https://example.com"},{key:"other.key"}];
  assert.equal(citationEntry("cite.key",entries),entries[0]);
  assert.equal(citationEntry("cite.0@other.key",entries),entries[1]);
  assert.equal(citationEntry("cite.1",entries),null);
  assert.equal(citationEntry("cite.key",[...entries,{key:"key"}]),null);
  assert.equal(citationEntry("section.key",entries),null);
  for (const url of ["javascript:alert(1)","file:///etc/passwd","https://user:pass@example.com"]) assert.equal(safeArticleURL(url),null);
});
const entry = {title:"A Test Paper",authors:["Smith"],year:"2025",doi:"10.1234/test"};
const response = work => async () => ({ok:true,json:async()=>({message:work})});
const work = {title:["A test paper"],author:[{family:"Smith"}],published:{"date-parts":[[2025]]},DOI:"10.1234/test"};
test("external metadata checks distinguish agreement, conflicts and unverified responses", async () => {
  assert.equal((await verifyEntry(entry,{fetcher:response(work)})).status,"verified");
  assert.equal((await verifyEntry(entry,{fetcher:response({...work,title:["An unrelated paper"]})})).status,"mismatch");
  assert.equal((await verifyEntry(entry,{fetcher:response({...work,DOI:"10.1234/other"})})).status,"mismatch");
  assert.equal((await verifyEntry({...entry,doi:""},{fetcher:response({items:[{...work,title:["Wrong top result"]},work]})})).status,"verified");
  assert.equal((await verifyEntry(entry,{fetcher:async()=>({ok:false,status:404})})).status,"unverified");
  assert.equal((await verifyEntry({...entry,doi:""},{fetcher:response({items:[{...work,title:["Similar but different"]}]})})).status,"candidate");
  assert.equal((await verifyEntry(entry,{fetcher:async()=>{throw Error("network offline")}})).status,"unverified");
});
