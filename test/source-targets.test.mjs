import {test} from "node:test";
import assert from "node:assert/strict";
import {sourceTargets,materializeTargets} from "../server/source-targets.mjs";
import {applyPatches} from "../server/core.mjs";
test("unique selected text gets its own target so surrounding spaces and TeX cannot be reformatted",()=>{
  const source="Before~\\cite{x}. \r\nSelected sentence: \r\nAfter~\\cite{y}.";
  const files={"main.tex":Buffer.from(source).toString("base64"),"figure.pdf":"UEZERklMRQ=="};
  const targets=sourceTargets(files,[{quote:"Selected sentence:",file:"main.tex"}]);
  assert.equal(targets.length,1);assert.equal(targets[0].text,"Selected sentence:");
  const patches=materializeTargets(files,targets,[{targetId:targets[0].id,after:"Improved sentence:",reason:"polish",commentIds:["c1"]}]);
  const updated=applyPatches(files,patches);
  assert.equal(Buffer.from(updated["main.tex"],"base64").toString(),source.replace("Selected sentence:","Improved sentence:"));
  assert.equal(updated["figure.pdf"],files["figure.pdf"]);
});
test("ambiguous or PDF-only quotes retain paragraph context rather than guessing a narrow source range",()=>{
  const files={"main.tex":Buffer.from("Same.\n\nSame.\n\nUnique~\\cite{x}.").toString("base64")};
  assert.deepEqual(sourceTargets(files,[{quote:"Same."}]),sourceTargets(files));
  assert.deepEqual(sourceTargets(files,[{quote:"Unique [1]."}]),sourceTargets(files));
  assert.deepEqual(sourceTargets(files,[{quote:"Unique~\\cite{x}."},{quote:"PDF quote"}]),sourceTargets(files));
});
test("overlapping exact quotes merge, and explicit files disambiguate otherwise duplicate passages",()=>{
  const files={"a.tex":Buffer.from("Alpha beta gamma.").toString("base64"),"b.tex":Buffer.from("Alpha beta gamma.").toString("base64")};
  const ranges=sourceTargets(files,[{quote:"Alpha beta",file:"a.tex"},{quote:"beta gamma.",file:"a.tex"}]);
  assert.equal(ranges.length,1);assert.equal(ranges[0].file,"a.tex");assert.equal(ranges[0].text,"Alpha beta gamma.");
});
test("server-owned TeX ranges edit duplicate paragraphs independently and preserve CRLF and binary assets",()=>{
  const text='Same~\\cite{x}.\r\n\r\nSame~\\cite{x}.\r\n\r\nUntouched.';
  const files={'main.tex':Buffer.from(text).toString('base64'),'figure.pdf':'UEZERklMRQ=='};
  const targets=sourceTargets(files);assert.equal(targets.length,3);
  const patches=materializeTargets(files,targets,[{targetId:targets[1].id,after:'Improved~\\cite{x}.',reason:'polish',commentIds:['c1']}]);
  const next=applyPatches(files,patches);
  assert.equal(Buffer.from(next['main.tex'],'base64').toString(),'Same~\\cite{x}.\r\n\r\nImproved~\\cite{x}.\r\n\r\nUntouched.');
  assert.equal(next['figure.pdf'],files['figure.pdf']);assert.equal(Buffer.from(files['main.tex'],'base64').toString(),text);
});
test("multiple targets in one file become one exact source edit without overlap",()=>{
  const files={'main.tex':Buffer.from('First.\n\nSecond.\n\nLast.').toString('base64')},targets=sourceTargets(files);
  const patches=materializeTargets(files,targets,[{targetId:targets[0].id,after:'One.',reason:'a',commentIds:['c1']},{targetId:targets[1].id,after:'Two.',reason:'b',commentIds:['c2']}]);
  assert.equal(patches.length,1);assert.equal(patches[0].after,'One.\n\nTwo.\n\nLast.');assert.deepEqual(new Set(patches[0].commentIds),new Set(['c1','c2']));
});
test("unknown or duplicate targets are rejected rather than guessed",()=>{
  const files={'main.tex':Buffer.from('First.').toString('base64')},targets=sourceTargets(files);
  const p={targetId:targets[0].id,after:'One.',reason:'a',commentIds:['c1']};
  assert.throws(()=>materializeTargets(files,targets,[p,p]),/不存在或重复/);
  assert.throws(()=>materializeTargets(files,targets,[{...p,targetId:'missing'}]),/不存在或重复/);
});
