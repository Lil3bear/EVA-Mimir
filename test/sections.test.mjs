import {test} from "node:test";
import assert from "node:assert/strict";
import {discoverSections,publicSections,sectionDocuments,sectionSkillPrompt,validateSectionResult,reviewSection} from "../server/sections.mjs";

const b64 = value => Buffer.from(value, "utf8").toString("base64");
const project = {main:"main.tex",venue:"WWW"};
const revision = {files:{
  "main.tex":b64("\\documentclass{article}\\begin{document}\\input{sec/01_intro}\\input{sec/04_method}\\end{document}"),
  "sec/01_intro.tex":b64("\\section{Introduction}\nMotivation text. We claim a gap."),
  "sec/04_method.tex":b64("\\section{Method}\nWe update the state with Eq. 3."),
  "refs.bib":b64("@article{a,title={A}}"),
}};
const documents = sectionDocuments(revision);

test("discoverSections prefers chapter files over the main include file", () => {
  const sections = discoverSections(project, revision);
  assert.deepEqual(sections.map(section => section.id).sort(), ["introduction", "method"]);
  assert.ok(sections.find(section => section.id === "method").text.includes("Eq. 3"));
  assert.ok(sections.find(section => section.id === "introduction").skillIds.includes("writing-ai-paper"));
  assert.equal(publicSections(sections)[0].text, undefined);
});

test("single-file manuscripts fall back to sectioning main.tex", () => {
  const single = {files:{"main.tex":b64("\\section{Introduction}\nA.\n\\section{Experiments}\nB.")}};
  const sections = discoverSections(project, single);
  assert.deepEqual(sections.map(section => section.id).sort(), ["experiments", "introduction"]);
});

test("validateSectionResult anchors quotes and downgrades missing ones", () => {
  const section = discoverSections(project, revision).find(item => item.id === "method");
  const raw = {
    section:"method", alignment:"方法需要与引言的主张对齐。", summary:"一处引用未定位。",
    findings:[
      {title:"机制缺少定义",body:"状态更新没有说明停止条件。",file:"sec/04_method.tex",quote:"We update the state with Eq. 3.",suggestion:"补停止条件。",severity:"major",certainty:"confirmed",relatedSection:"introduction"},
      {title:"引句不在原文",body:"疑似旧版。",file:"sec/04_method.tex",quote:"not in this manuscript",suggestion:"核对。",severity:"minor",certainty:"confirmed",relatedSection:""},
    ],
    crossRefs:[{from:"method",to:"introduction",issue:"贡献没有落在机制上。"}],
    blockers:[],
  };
  const result = validateSectionResult(raw, section, documents);
  assert.equal(result.findings[0].anchored, true);
  assert.equal(result.findings[0].certainty, "confirmed");
  assert.equal(result.findings[1].anchored, false);
  assert.equal(result.findings[1].certainty, "unverified");
});

test("sectionSkillPrompt combines the section rule with existing skills", async () => {
  const section = discoverSections(project, revision).find(item => item.id === "method");
  const prompt = await sectionSkillPrompt(section);
  assert.match(prompt, /Method sub-agent/);
  assert.match(prompt, /学术表达/);
});

test("reviewSection calls the injected model and returns a validated result", async () => {
  const sections = discoverSections(project, revision);
  const section = sections.find(item => item.id === "introduction");
  let seen = null;
  const raw = {section:"introduction",alignment:"主线成立。",summary:"没有阻塞。",findings:[],crossRefs:[],blockers:[]};
  const result = await reviewSection({
    project, section, sections, documents, config:{provider:"openai",apiKey:"test",model:"deepseek-flash"},
    invoke:async (config, options) => { seen = options; return raw; },
  });
  assert.equal(result.alignment, "主线成立。");
  assert.equal(seen.name, "section_alignment");
  assert.match(seen.instructions, /dedicated sub-agent/);
});

test("abstract outside any section is captured, and workflow maps to method", () => {
  const value = {files:{"main.tex":b64("\\begin{abstract}Short abstract.\\end{abstract}\n\\section{Introduction}\nA.\n\\section{Workflow}\nB.")}};
  const sections = discoverSections(project, value);
  assert.deepEqual(sections.map(section => section.id), ["abstract", "introduction", "method"]);
  assert.ok(sections[0].text.includes("Short abstract."));
});
