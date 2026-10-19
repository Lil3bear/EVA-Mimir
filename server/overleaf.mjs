import { spawn } from "node:child_process";
import { mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { safePath } from "./core.mjs";

export function overleafURL(value) {
  const url = new URL(value);
  if (
    url.protocol !== "https:" ||
    url.hostname !== "git.overleaf.com" ||
    url.port ||
    url.password ||
    (url.username && url.username !== "git") ||
    url.search ||
    url.hash ||
    !/^\/[a-zA-Z0-9]+$/.test(url.pathname)
  )
    throw new Error("仅支持不含 token 的 Overleaf Cloud Git 地址");
  url.username = "git";
  return url.toString();
}

export function planSync(base, local, remote) {
  const changes = [],
    conflicts = [];
  for (const name of new Set([...Object.keys(base), ...Object.keys(local)])) {
    if (base[name] === local[name] || remote[name] === local[name]) continue;
    safePath(name);
    if (remote[name] !== base[name]) conflicts.push(name);
    else changes.push(name);
  }
  if (conflicts.length)
    throw new Error(
      `Overleaf 与本地同时修改了这些文件，已停止同步，不会覆盖：${conflicts.join("、")}`,
    );
  return changes;
}

export function git(args, { cwd, token, input, signal, index } = {}) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason);
    const env = {
      PATH: process.env.PATH,
      HOME: process.env.HOME,
      TMPDIR: process.env.TMPDIR,
      GIT_TERMINAL_PROMPT: "0",
      GIT_ASKPASS: "/usr/bin/false",
      SSH_ASKPASS: "/usr/bin/false",
    };
    for (const name of [
      "HTTPS_PROXY",
      "HTTP_PROXY",
      "ALL_PROXY",
      "NO_PROXY",
      "SSL_CERT_FILE",
    ])
      if (process.env[name]) env[name] = process.env[name];
    if (index) env.GIT_INDEX_FILE = index;
    if (token) {
      env.GIT_CONFIG_COUNT = "1";
      env.GIT_CONFIG_KEY_0 = "http.https://git.overleaf.com/.extraHeader";
      env.GIT_CONFIG_VALUE_0 = `Authorization: Basic ${Buffer.from(`git:${token}`).toString("base64")}`;
    }
    const child = spawn(
      "git",
      [
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "credential.username=git",
        "-c",
        "http.followRedirects=false",
        "-c",
        "protocol.file.allow=never",
        "-c",
        "protocol.ext.allow=never",
        ...args,
      ],
      { cwd, env, detached: true, stdio: ["pipe", "pipe", "pipe"] },
    );
    const chunks = [];
    let stderr = "",
      size = 0,
      timedOut = false;
    const stop = () => {
      try {
        process.kill(-child.pid, "SIGKILL");
      } catch {}
    };
    const timer = setTimeout(() => {
      timedOut = true;
      stop();
    }, 90000);
    signal?.addEventListener("abort", stop, { once: true });
    child.stdin.on("error", () => {});
    child.stdout.on("data", (chunk) => {
      size += chunk.length;
      if (size > 100 * 1024 * 1024) stop();
      else chunks.push(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr = (stderr + chunk.toString()).slice(-4000);
    });
    const cleanup = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", stop);
    };
    child.on("error", (error) => {
      cleanup();
      reject(new Error(`无法运行 Git：${error.message}`));
    });
    child.on("close", (code) => {
      cleanup();
      if (signal?.aborted) return reject(signal.reason);
      if (code !== 0)
        return reject(
          new Error(
            timedOut
              ? "Overleaf Git 连接超时"
              : /Authentication failed|could not read|401|403/i.test(stderr)
                ? "Overleaf Git 未认证或没有访问权限，请配置 Git token（不会使用浏览器 Cookie）"
                : `Git 同步失败：${stderr}`,
          ),
        );
      resolve(Buffer.concat(chunks));
    });
    child.stdin.end(input);
  });
}

export async function connectOverleaf(directory, value, token) {
  const url = overleafURL(value);
  const temporary = path.join(directory, `overleaf-${randomUUID()}.git`);
  await mkdir(directory, { recursive: true });
  try {
    await git(["clone", "--bare", "--", url, temporary], { token });
    const branch = (await git(["symbolic-ref", "HEAD"], { cwd: temporary }))
      .toString()
      .trim();
    if (!branch.startsWith("refs/heads/"))
      throw new Error("Overleaf 未提供可同步的默认分支");
    return {
      directory: temporary,
      url,
      branch,
      head: (await git(["rev-parse", "HEAD"], { cwd: temporary }))
        .toString()
        .trim(),
    };
  } catch (error) {
    await rm(temporary, { recursive: true, force: true });
    throw error;
  }
}

export async function prepareSync(
  repository,
  base,
  files,
  token,
  signal,
  execute = git,
) {
  const options = { cwd: repository.directory, token, signal };
  await execute(["fetch", "origin", repository.branch], options);
  const head = (await execute(["rev-parse", "FETCH_HEAD"], options))
    .toString()
    .trim();
  const remote = {},
    modes = {};
  const names = [
    ...new Set([...Object.keys(base), ...Object.keys(files)]),
  ].filter((name) => base[name] !== files[name]);
  for (const name of names) {
    safePath(name);
    const entry = (
      await execute(["ls-tree", "-z", head, "--", name], options)
    ).toString();
    if (!entry) continue;
    const match = /^(100644|100755) blob ([a-f0-9]+)\t/.exec(entry);
    if (!match) throw new Error(`Overleaf 文件类型不支持同步：${name}`);
    modes[name] = match[1];
    remote[name] = (
      await execute(["cat-file", "blob", match[2]], options)
    ).toString("base64");
  }
  return { head, modes, changes: planSync(base, files, remote) };
}

export async function pushOverleaf(
  repository,
  base,
  files,
  token,
  { signal, progress = () => {}, execute = git,revisionMetadata=null } = {},
) {
  progress({
    phase: "syncing",
    message: "获取 Overleaf 最新版本并检查同文件冲突",
  });
  const plan = await prepareSync(
    repository,
    base,
    files,
    token,
    signal,
    execute,
  );
  if (!plan.changes.length)
    return {
      head: plan.head,
      files: [],
      message: "Overleaf 已包含本地修改，无需推送",
    };
  const index = path.join(repository.directory, `sync-${randomUUID()}.index`);
  const options = { cwd: repository.directory, token, signal, index };
  try {
    await execute(["read-tree", plan.head], options);
    for (const name of plan.changes) {
      if (files[name] === undefined)
        await execute(["update-index", "--force-remove", "--", name], options);
      else {
        const hash = (
          await execute(["hash-object", "-w", "--stdin"], {
            ...options,
            input: Buffer.from(files[name], "base64"),
          })
        )
          .toString()
          .trim();
        await execute(
          [
            "update-index",
            "--add",
            "--cacheinfo",
            plan.modes[name] || "100644",
            hash,
            name,
          ],
          options,
        );
      }
    }
    const tree = (await execute(["write-tree"], options)).toString().trim();
    const commit = (
      await execute(
        [
          "-c",
          "user.name=Autopaperreview",
          "-c",
          "user.email=autopaperreview@localhost",
          "commit-tree",
          tree,
          "-p",
          plan.head,
        ],
        {
          ...options,
          input: `Autopaperreview: synchronize compiled local revision\n${revisionMetadata?"\n"+JSON.stringify(revisionMetadata)+"\n":""}`,
        },
      )
    )
      .toString()
      .trim();
    progress({
      phase: "syncing",
      message: `推送 ${plan.changes.length} 个已更改文件至 Overleaf（非强制推送）`,
      files: plan.changes,
    });
    await execute(
      ["push", "origin", `${commit}:${repository.branch}`],
      options,
    );
    return {
      head: commit,
      files: plan.changes,
      message: `已同步 ${plan.changes.length} 个文件至 Overleaf`,
    };
  } finally {
    await rm(index, { force: true });
    await rm(`${index}.lock`, { force: true });
  }
}
