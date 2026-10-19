import { test } from "node:test";
import assert from "node:assert/strict";
import childProcess from "node:child_process";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { writeFile, access } from "node:fs/promises";
import { codexStatus, executeCodex } from "../server/codex.mjs";

test("Codex authentication uses the official CLI, not credential file extraction", async (t) => {
  t.mock.method(childProcess, "execFile", (file, args, options, callback) => {
    assert.equal(file, "codex");
    assert.deepEqual(args, ["login", "status"]);
    assert.equal(options.env.OPENAI_API_KEY, undefined);
    callback(null, "", "Logged in using ChatGPT");
  });
  assert.equal((await codexStatus()).authenticated, true);
});

test("Codex receives manuscript through stdin, runs without tools, validates JSON and cleans up", async (t) => {
  const result = {
    summary: "ok",
    coverage: "source",
    findings: [],
    patches: [],
  };
  let cwd,
    received = "";
  t.mock.method(childProcess, "spawn", (file, args, options) => {
    assert.equal(file, "codex");
    assert.ok(args.includes("gpt-6.1-sol"));
    assert.ok(args.includes("--ignore-user-config"));
    assert.ok(args.includes("--ephemeral"));
    assert.equal(args[args.indexOf("--sandbox") + 1], "read-only");
    for (const feature of [
      "shell_tool",
      "unified_exec",
      "multi_agent",
      "apps",
      "hooks",
    ])
      assert.ok(args.includes(feature));
    assert.equal(options.env.OPENAI_API_KEY, undefined);
    assert.equal(options.env.CODEX_API_KEY, undefined);
    assert.ok(!args.some((a) => a.includes("private manuscript")));
    cwd = options.cwd;
    const child = new EventEmitter();
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    child.stdin = new PassThrough();
    child.stdin.on("data", (data) => {
      received += data.toString();
    });
    child.stdin.on("finish", async () => {
      await writeFile(
        args[args.indexOf("--output-last-message") + 1],
        JSON.stringify(result),
      );
      child.emit("close", 0);
    });
    return child;
  });
  assert.deepEqual(
    await executeCodex("private manuscript", { type: "object" }, "gpt-6.1-sol"),
    result,
  );
  assert.equal(received, "private manuscript");
  await assert.rejects(access(cwd));
});

test("Codex model errors are surfaced without silently falling back to the API", async (t) => {
  t.mock.method(childProcess, "spawn", () => {
    const child = new EventEmitter();
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    child.stdin = new PassThrough();
    child.stdin.on("finish", () => {
      child.stdout.write(
        JSON.stringify({
          type: "turn.failed",
          error: { message: "requested model unavailable" },
        }) + "\n",
      );
      child.emit("close", 1);
    });
    return child;
  });
  await assert.rejects(
    executeCodex("test", {}, "unavailable"),
    /requested model unavailable/,
  );
});
