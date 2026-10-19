import path from "node:path";
import { randomUUID } from "node:crypto";
import { readFile, writeFile, mkdir, rename, rm } from "node:fs/promises";
import { spawn } from "node:child_process";
import AdmZip from "adm-zip";

export const textExt = /\.(tex|bib|sty|cls|bst|txt|md|csv)$/i;
const allowed =
  /\.(tex|bib|sty|cls|bst|txt|md|csv|pdf|png|jpe?g|eps|svg|otf|ttf)$/i;
export function safePath(name) {
  if (
    typeof name !== "string" ||
    !name ||
    name.includes("\\") ||
    name.includes("\0") ||
    name.startsWith("/") ||
    name.split("/").some((p) => p === ".." || p.startsWith(".")) ||
    /^[A-Za-z]:/.test(name)
  )
    throw new Error("不安全的文件路径");
  return name;
}
export function importZip(buffer) {
  const zip = new AdmZip(buffer);
  const files = {};
  let total = 0;
  const entries = zip.getEntries();
  if (entries.length > 1200) throw new Error("ZIP 文件数超过 1200");
  for (const entry of entries) {
    safePath(entry.entryName);
    if (entry.isDirectory) continue;
    if (((entry.attr >>> 16) & 0o170000) === 0o120000)
      throw new Error("不允许符号链接");
    if (!allowed.test(entry.entryName)) continue;
    total += entry.header.size;
    if (total > 80 * 1024 * 1024 || entry.header.size > 20 * 1024 * 1024)
      throw new Error("解压文件过大");
    if (files[entry.entryName]) throw new Error("重复文件路径");
    files[entry.entryName] = entry.getData().toString("base64");
  }
  if (!Object.keys(files).some((f) => /\.tex$/i.test(f)))
    throw new Error("ZIP 中没有 LaTeX 源文件");
  return files;
}
export function detectMain(files) {
  return (
    Object.keys(files).find(
      (f) =>
        /\.(tex)$/i.test(f) &&
        Buffer.from(files[f], "base64").toString().includes("\\documentclass"),
    ) || Object.keys(files).find((f) => /\.tex$/i.test(f))
  );
}
export async function atomicJSON(file, data) {
  await mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.${randomUUID()}.tmp`;
  await writeFile(tmp, JSON.stringify(data, null, 2));
  await rename(tmp, file);
}
export function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const { signal, ...spawnOptions } = options;
    if (signal?.aborted) return reject(signal.reason);
    let output = "";
    const child = spawn(command, args, {
      ...spawnOptions,
      stdio: ["ignore", "pipe", "pipe"],
      detached: true,
    });
    const timer = setTimeout(() => {
      try {
        process.kill(-child.pid, "SIGKILL");
      } catch {}
    }, 90000);
    const abort = () => {
      try {
        process.kill(-child.pid, "SIGKILL");
      } catch {}
    };
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    const collect = (data) => {
      output = (output + data.toString()).slice(-100000);
    };
    child.stdout.on("data", collect);
    child.stderr.on("data", collect);
    child.on("error", (err) => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(new Error(`无法运行 ${command}: ${err.message}`));
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      if (signal?.aborted) return reject(signal.reason);
      resolve({ code, output });
    });
  });
}
export async function compileFiles(
  files,
  main,
  engine,
  directory,
  { signal, onProgress = () => {} } = {},
) {
  signal?.throwIfAborted();
  safePath(main);
  if (!files[main] || !/\.tex$/i.test(main))
    throw new Error("请选择有效的主 .tex 文件");
  if (!["pdflatex", "xelatex"].includes(engine)) throw new Error("未知编译器");
  await mkdir(directory, { recursive: true });
  for (const [name, data] of Object.entries(files)) {
    safePath(name);
    await mkdir(path.dirname(path.join(directory, name)), { recursive: true });
    await writeFile(path.join(directory, name), Buffer.from(data, "base64"));
  }
  const cwd = path.join(directory, path.dirname(main));
  const outputPdf = path.join(
    cwd,
    path.basename(main).replace(/\.tex$/i, ".pdf"),
  );
  await rm(outputPdf, { force: true });
  const env = {
    PATH: process.env.PATH,
    HOME: process.env.HOME,
    TMPDIR: process.env.TMPDIR,
    openin_any: "p",
    openout_any: "p",
    max_print_line: "200",
    ...(process.env.TEXMFVAR ? {TEXMFVAR:process.env.TEXMFVAR} : {}),
    ...(process.env.TEXMFCONFIG ? {TEXMFCONFIG:process.env.TEXMFCONFIG} : {}),
  };
  const args = [
    "-no-shell-escape",
    "-interaction=nonstopmode",
    "-halt-on-error",
    "-file-line-error",
    path.basename(main),
  ];
  let log = "";
  for (let i = 0; i < 3; i++) {
    onProgress({
      phase: "compiling",
      message: `${main} · LaTeX 第 ${i + 1}/3 轮编译`,
    });
    const result = await run(engine, args, { cwd, env, signal });
    log += result.output;
    if (result.code !== 0)
      throw Object.assign(new Error("LaTeX 编译失败，源文件未被覆盖"), { log });
    if (i === 0) {
      const stem = path.basename(main).replace(/\.tex$/i, "");
      const aux = await readFile(path.join(cwd, `${stem}.aux`), "utf8").catch(
        () => "",
      );
      if (aux.includes("\\bibdata")) {
        const bib = await run("bibtex", [stem], { cwd, env, signal });
        log += bib.output;
        if (bib.code !== 0)
          throw Object.assign(new Error("BibTeX 失败，请检查文献数据库"), {
            log,
          });
      } else if (
        Object.values(files).some(
          (v) =>
            Buffer.from(v, "base64").toString().includes("\\usepackage") &&
            Buffer.from(v, "base64").toString().includes("biblatex"),
        )
      ) {
        const bcf = await readFile(path.join(cwd, `${stem}.bcf`)).catch(
          () => null,
        );
        if (bcf) {
          const bib = await run("biber", [stem], { cwd, env, signal });
          log += bib.output;
          if (bib.code !== 0)
            throw Object.assign(new Error("Biber 失败"), { log });
        }
      }
    }
  }
  const pdf = await readFile(outputPdf).catch(() => {
    throw Object.assign(new Error("编译没有生成 PDF，请检查是否有正文内容"), {
      log,
    });
  });
  return { pdf, log: log.slice(-80000) };
}
export function linkPatchComments(patches, comments) {
  const knownIds = new Set(comments.map((c) => c.id));
  return patches.map((patch) => {
    const ids = [...new Set(patch.commentIds)];
    return {
      ...patch,
      commentIds: ids.filter((id) => knownIds.has(id)),
      unlinkedCommentIds: ids.filter((id) => !knownIds.has(id)),
    };
  });
}

export function applyPatches(files, patches) {
  if (!Array.isArray(patches) || !patches.length || patches.length > 100)
    throw new Error("没有可应用的修改");
  const next = { ...files };
  for (const patch of patches) {
    safePath(patch.file);
    if (
      !/\.tex$/i.test(patch.file) ||
      !next[patch.file] ||
      typeof patch.before !== "string" ||
      !patch.before ||
      typeof patch.after !== "string"
    )
      throw new Error("仅允许修改现有 .tex 文件");
    const text = Buffer.from(next[patch.file], "base64").toString("utf8");
    if (text.split(patch.before).length !== 2)
      throw new Error(`修改位置不唯一或已失效: ${patch.file}`);
    next[patch.file] = Buffer.from(
      text.replace(patch.before, () => patch.after),
    ).toString("base64");
  }
  return next;
}
