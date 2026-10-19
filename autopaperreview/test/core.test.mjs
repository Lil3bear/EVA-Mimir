import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import AdmZip from "adm-zip";
import {
  safePath,
  importZip,
  applyPatches,
  detectMain,
  compileFiles,
} from "../server/core.mjs";
import { skillPrompt, skills } from "../server/skills.mjs";
const encoded = (text) => Buffer.from(text).toString("base64");

test("paths reject traversal, absolute, hidden and backslash paths", () => {
  for (const p of [
    "../secrets.tex",
    "/etc/passwd",
    "a/../../b.tex",
    "a\\b.tex",
    ".latexmkrc",
    "C:/a.tex",
  ])
    assert.throws(() => safePath(p));
  assert.equal(safePath("sections/method.tex"), "sections/method.tex");
});
test("ZIP imports binary assets and detects entrypoint, rejects empty source", () => {
  const zip = new AdmZip();
  zip.addFile("project/main.tex", Buffer.from("\\documentclass{article}"));
  zip.addFile("plot.png", Buffer.from([0, 1, 2]));
  zip.addFile("script.sh", Buffer.from("do not run"));
  const files = importZip(zip.toBuffer());
  assert.equal(detectMain(files), "project/main.tex");
  assert.equal(files["script.sh"], undefined);
  assert.deepEqual(
    Buffer.from(files["plot.png"], "base64"),
    Buffer.from([0, 1, 2]),
  );
  assert.throws(() => importZip(new AdmZip().toBuffer()), /没有 LaTeX/);
});
test("patch application is exact, non-mutating, rejects ambiguous or missing source", () => {
  const files = {
    "main.tex": encoded("one two three"),
    "other.tex": encoded("same same"),
  };
  const next = applyPatches(files, [
    { file: "main.tex", before: "two", after: "$& safe" },
  ]);
  assert.equal(
    Buffer.from(next["main.tex"], "base64").toString(),
    "one $& safe three",
  );
  assert.equal(
    Buffer.from(files["main.tex"], "base64").toString(),
    "one two three",
  );
  assert.throws(() =>
    applyPatches(files, [{ file: "other.tex", before: "same", after: "no" }]),
  );
  assert.throws(() =>
    applyPatches(files, [{ file: "missing.tex", before: "x", after: "" }]),
  );
  assert.throws(() => applyPatches(files, []));
});
test("all twelve skills load actual attributed reference material", async () => {
  assert.equal(skills.length, 16);
  for (const skill of skills)
    assert.ok((await skillPrompt([skill.id])).length > 400, skill.id);
  await assert.rejects(skillPrompt(["invented"]));
});
test("native TeX compilation returns a real PDF and failure preserves the input", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "autopaper-"));
  const text =
    "\\documentclass{article}\n\\begin{document}Evidence first.\\end{document}";
  const files = { "main.tex": encoded(text) };
  try {
    const result = await compileFiles(
      files,
      "main.tex",
      "pdflatex",
      path.join(dir, "good"),
    );
    assert.equal(result.pdf.subarray(0, 4).toString(), "%PDF");
    assert.ok(result.log.includes("Output written"));
    await assert.rejects(
      compileFiles(
        {
          "main.tex": encoded(
            "\\documentclass{article}\\begin{document}\\end{document}",
          ),
          "main.pdf": result.pdf.toString("base64"),
        },
        "main.tex",
        "pdflatex",
        path.join(dir, "empty"),
      ),
      /没有生成 PDF/,
    );
    await assert.rejects(
      compileFiles(
        {
          "main.tex": encoded(
            "\\documentclass{article}\\begin{document}\\nonexistent\\end{document}",
          ),
        },
        "main.tex",
        "pdflatex",
        path.join(dir, "bad"),
      ),
      /编译失败/,
    );
    assert.equal(Buffer.from(files["main.tex"], "base64").toString(), text);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
