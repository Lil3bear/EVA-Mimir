import childProcess from "node:child_process";
import { mkdtemp, writeFile, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

function cliEnvironment() {
  const env = {};
  for (const name of [
    "PATH",
    "HOME",
    "CODEX_HOME",
    "TMPDIR",
    "SYSTEMROOT",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
  ]) {
    if (process.env[name]) env[name] = process.env[name];
  }
  return env;
}

export async function codexStatus() {
  return new Promise((resolve) => {
    childProcess.execFile(
      "codex",
      ["login", "status"],
      { env: cliEnvironment(), timeout: 8000, maxBuffer: 8192 },
      (error, stdout, stderr) => {
        const authenticated =
          !error && /Logged in using ChatGPT/i.test(`${stdout}\n${stderr}`);
        resolve({
          available: !error || error.code !== "ENOENT",
          authenticated,
          message: authenticated
            ? "已登录 ChatGPT"
            : error?.code === "ENOENT"
              ? "未安装 Codex CLI"
              : "请在终端运行 codex login，使用 ChatGPT 账户登录",
        });
      },
    );
  });
}

export async function executeCodex(
  prompt,
  schema,
  model,
  { timeoutMs = 600000, signal, onProgress = () => {} } = {},
) {
  signal?.throwIfAborted();
  const directory = await mkdtemp(path.join(os.tmpdir(), "autopaper-codex-"));
  const schemaFile = path.join(directory, "schema.json");
  const outputFile = path.join(directory, "response.json");
  try {
    await writeFile(schemaFile, JSON.stringify(schema), { mode: 0o600 });
    const args = [
      "exec",
      "--ignore-user-config",
      "--ephemeral",
      "--skip-git-repo-check",
      "--sandbox",
      "read-only",
      "--color",
      "never",
      "--json",
      "-C",
      directory,
      "--model",
      model,
      "--output-schema",
      schemaFile,
      "--output-last-message",
      outputFile,
      "-c",
      'approval_policy="never"',
      "-c",
      'forced_login_method="chatgpt"',
      "-c",
      'web_search="disabled"',
      "-c",
      "project_doc_max_bytes=0",
      "--enable",
      "skip_host_skill_discovery",
    ];
    for (const feature of [
      "shell_tool",
      "unified_exec",
      "code_mode_host",
      "multi_agent",
      "apps",
      "plugins",
      "hooks",
      "skill_search",
      "browser_use",
      "computer_use",
      "image_generation",
      "view_image",
      "sleep_tool",
      "goals",
      "workspace_dependencies",
    ])
      args.push("--disable", feature);
    args.push("-");
    await new Promise((resolve, reject) => {
      const child = childProcess.spawn("codex", args, {
        cwd: directory,
        env: cliEnvironment(),
        detached: true,
        stdio: ["pipe", "pipe", "pipe"],
      });
      let stderr = "",
        lineBuffer = "",
        cliError = "",
        timedOut = false;
      const stop = () => {
        try {
          process.kill(-child.pid, "SIGKILL");
        } catch {}
      };
      signal?.addEventListener("abort", stop, { once: true });
      if (signal?.aborted) stop();
      onProgress({
        phase: "model",
        message: "Codex 已启动，等待模型返回结构化修订",
      });
      const timer = setTimeout(() => {
        timedOut = true;
        stop();
      }, timeoutMs);
      child.stderr.on("data", (data) => {
        stderr = (stderr + data.toString()).slice(-4000);
      });
      child.stdout.on("data", (data) => {
        lineBuffer += data.toString();
        const lines = lineBuffer.split("\n");
        lineBuffer = lines.pop().slice(-1000000);
        for (const line of lines) {
          try {
            const event = JSON.parse(line);
            if (event.type === "turn.started")
              onProgress({
                phase: "model",
                message: "模型已开始处理本轮源码与批注",
              });
            if (
              event.type === "item.completed" &&
              event.item?.type === "agent_message"
            )
              onProgress({
                phase: "validating",
                message: "已收到模型结果，正在验证修改",
              });
            if (event.type === "error")
              cliError = event.message || "Codex 运行失败";
            if (event.type === "turn.failed")
              cliError = event.error?.message || "Codex 运行失败";
          } catch {}
        }
      });
      child.stdin.on("error", () => {});
      child.on("error", (error) => {
        clearTimeout(timer);
        signal?.removeEventListener("abort", stop);
        reject(
          new Error(
            error.code === "ENOENT"
              ? "未安装 Codex CLI，请先安装并运行 codex login"
              : `Codex 无法启动: ${error.message}`,
          ),
        );
      });
      child.on("close", (code) => {
        clearTimeout(timer);
        signal?.removeEventListener("abort", stop);
        if (signal?.aborted) return reject(signal.reason);
        if (timedOut)
          return reject(new Error("Codex 已超时（10 分钟），本轮未修改源码"));
        if (code !== 0 || cliError)
          return reject(
            new Error(
              `Codex 运行失败: ${(cliError || stderr || `退出码 ${code}`).slice(-3000)}`,
            ),
          );
        resolve();
      });
      child.stdin.end(prompt);
    });
    return JSON.parse(await readFile(outputFile, "utf8"));
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}
