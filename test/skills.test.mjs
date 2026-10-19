import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createHash} from "node:crypto";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {effectiveSkillIds, skillPrompt, skillManifest, skills,defaultSkillIds,figureSkillIds,coreSkillIds} from "../server/skills.mjs";
import {peerReviewGuidance} from "../server/peer-review.mjs";

test("writing foundation is mandatory, deduplicated and unknown selections fail closed", async () => {
  const required=skills.filter(s=>s.required).map(s=>s.id);
  assert.deepEqual(effectiveSkillIds(["latex"]),[...required,"latex"]);
  assert.deepEqual(effectiveSkillIds(["writing","writing"]),required);
  assert.deepEqual(effectiveSkillIds([]),required);
  assert.throws(()=>effectiveSkillIds(["invented"]),/未知 skill/);
  await assert.rejects(skillPrompt(["invented"]),/未知 skill/);
  const checklist=await readFile(new URL("../skills/writing-ai-paper/references/checklist.md",import.meta.url),"utf8");
  const macro=await readFile(new URL("../skills/zhihu-paper-structure/SKILL.md",import.meta.url),"utf8");
  const micro=await readFile(new URL("../skills/zhihu-paper-readability/SKILL.md",import.meta.url),"utf8");
  for(const id of skills.map(s=>s.id)) {
    const prompt=await skillPrompt([id]);
    assert.equal(prompt.split(checklist).length-1,1);
    assert.equal(prompt.split(macro).length-1,1);
    assert.equal(prompt.split(micro).length-1,1);
  }
  assert.ok((await peerReviewGuidance(["citations"])).includes(checklist));
  assert.ok((await peerReviewGuidance(["citations"])).includes(macro));
  assert.ok((await peerReviewGuidance(["citations"])).includes(micro));
});

test("logged skill manifest identifies the actual deployed instruction bytes", async () => {
  const manifest=await skillManifest(["latex"]);
  assert.deepEqual(manifest.ids,[...skills.filter(s=>s.required).map(s=>s.id),"latex"]);
  assert.equal(manifest.writingAIpaper.commit,"ab1d5a359702583df09eaa8d6b0f8ac2146b1f60");
  assert.equal(manifest.writingAIpaper.version,"1.1.2");
  assert.equal(manifest.writingAIpaper.localAuthorPreferences.source,"Explicit user instruction in this workspace");
  assert.equal(manifest.writingAIpaper.additionalSources.length,2);
  for(const entry of manifest.files) {
    const bytes=await readFile(new URL(`../${entry.file}`,import.meta.url));
    assert.equal(entry.sha256,createHash("sha256").update(bytes).digest("hex"));
  }
});

test("the three Zhihu skills are discoverable, attributed and reach both legacy and explicit selections once",async()=>{
  const legacy=["writing","review","claims","citations","math","blind","venue","latex"];
  assert.deepEqual(effectiveSkillIds(legacy),defaultSkillIds);
  const ids=["zhihu-paper-structure","zhihu-paper-readability","paper-rebuttal"];
  const urls=["https://zhuanlan.zhihu.com/p/593195527","https://zhuanlan.zhihu.com/p/639732057","https://zhuanlan.zhihu.com/p/602024489"];
  const manifest=await skillManifest(skills.map(s=>s.id)),prompt=await skillPrompt([...legacy,...ids]);
  assert.equal(new Set(manifest.files.map(f=>f.file)).size,manifest.files.length);
  for(const [i,id]of ids.entries()) {
    const definition=manifest.definitions.find(s=>s.id===id);
    assert.equal(definition.sourceURL,urls[i]);
    const content=await readFile(new URL(`../${definition.files[0]}`,import.meta.url),"utf8");
    assert.equal(prompt.split(content).length-1,1);
    assert(content.includes(urls[i]));
  }
});

test("figure guidance is automatically bundled for figure tasks, not injected into every prose call",async()=>{
  assert.equal(figureSkillIds.length,4);
  assert(figureSkillIds.every(id=>!defaultSkillIds.includes(id)));
  const manifest=await skillManifest(figureSkillIds);
  assert(figureSkillIds.every(id=>manifest.ids.includes(id)));
  assert(skills.filter(s=>s.required).every(s=>manifest.ids.includes(s.id)));
  for(const id of figureSkillIds){
    const content=await readFile(new URL(`../skills/${id}/SKILL.md`,import.meta.url),"utf8");
    assert((await skillPrompt(figureSkillIds)).includes(content));
    assert(!(await skillPrompt(defaultSkillIds)).includes(content));
  }
});

test("rebuttal guidance reaches selected review calls and its provenance is logged without forcing it into ordinary writing", async () => {
  const rebuttal=await readFile(new URL("../skills/paper-rebuttal/SKILL.md",import.meta.url),"utf8");
  assert.ok((await skillPrompt(["review"])).includes(rebuttal));
  assert.ok((await peerReviewGuidance(["review"])).includes(rebuttal));
  assert.ok(!(await skillPrompt(["writing"])).includes(rebuttal));
  assert.equal((await skillManifest(["writing"])).rebuttal,undefined);
  const manifest=await skillManifest(["review"]);
  assert.equal(manifest.rebuttal.url,"https://zhuanlan.zhihu.com/p/602024489");
  const entry=manifest.files.find(f=>f.file==="skills/paper-rebuttal/SKILL.md");
  assert.equal(entry.sha256,createHash("sha256").update(rebuttal).digest("hex"));
});

test("eight real app modules load their detailed worksheets with versioned ownership and venue-specific scope",async()=>{
  const manifest=await skillManifest(coreSkillIds),prompt=await skillPrompt(coreSkillIds);
  assert.deepEqual(manifest.moduleContracts.coreIds,coreSkillIds);
  assert.equal(manifest.moduleContracts.version,"2.0.1");
  assert.equal(manifest.rebuttal.version,"1.1.0");
  for(const id of coreSkillIds){
    const file=`skills/modules/${id}.md`,content=await readFile(new URL(`../${file}`,import.meta.url),"utf8");
    assert(manifest.definitions.find(s=>s.id===id).files.includes(file));
    assert.equal(prompt.split(content).length-1,1);
    assert.equal(manifest.files.find(f=>f.file===file).sha256,createHash("sha256").update(content).digest("hex"));
  }
  const venue=await skillPrompt(["venue"]);
  assert(!venue.includes("Start at the official ICLR site"));
  assert.deepEqual(manifest.definitions.find(s=>s.id==="venue").files,["skills/modules/venue.md"]);
});

test("all primary skill Markdown support links resolve and every registered helper reaches the actual prompt",async()=>{
  const root=fileURLToPath(new URL("../",import.meta.url)),manifest=await skillManifest(coreSkillIds),prompt=await skillPrompt(coreSkillIds);
  const own=manifest.files.filter(({file})=>/^skills\/(?:modules\/|zhihu-paper-|paper-rebuttal\/)/.test(file)&&file.endsWith(".md"));
  for(const {file}of own){
    const content=await readFile(path.join(root,file),"utf8");
    assert.equal(prompt.split(content).length-1,1,file);
    for(const match of content.matchAll(/\[[^\]]*\]\(([^)]+)\)/g)){
      const target=match[1].split("#")[0];if(!target||/^https?:/.test(target)||!target.endsWith(".md"))continue;
      await assert.doesNotReject(readFile(path.resolve(root,path.dirname(file),target)),`${file}: ${target}`);
    }
  }
});
