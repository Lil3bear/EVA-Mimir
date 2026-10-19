import { test } from "node:test";
import assert from "node:assert/strict";
import {
  overleafURL,
  planSync,
  git,
  pushOverleaf,
} from "../server/overleaf.mjs";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
test("only credential-free Overleaf Cloud HTTPS Git URLs are accepted", () => {
  assert.equal(
    overleafURL("https://git.overleaf.com/abc123"),
    "https://git@git.overleaf.com/abc123",
  );
  for (const url of [
    "file:///tmp/repo",
    "https://example.com/a",
    "https://git:secret@git.overleaf.com/a",
    "https://git.overleaf.com/a?token=secret",
    "https://git.overleaf.com:1234/a",
    "http://git.overleaf.com/a",
  ])
    assert.throws(() => overleafURL(url));
});
test("three-way sync pushes only local changes and preserves unrelated remote edits", () => {
  assert.deepEqual(
    planSync(
      { "main.tex": "base", "other.tex": "old" },
      { "main.tex": "revised", "other.tex": "old" },
      { "main.tex": "base", "other.tex": "remote" },
    ),
    ["main.tex"],
  );
  assert.deepEqual(
    planSync(
      { "main.tex": "base" },
      { "main.tex": "revised" },
      { "main.tex": "revised" },
    ),
    [],
  );
  assert.deepEqual(planSync({}, { "new.tex": "new" }, {}), ["new.tex"]);
  assert.deepEqual(
    planSync({ "deleted.tex": "base" }, {}, { "deleted.tex": "base" }),
    ["deleted.tex"],
  );
});
test("conflicting edits and conflicting deletion stop synchronization instead of overwriting", () => {
  assert.throws(
    () =>
      planSync(
        { "main.tex": "base" },
        { "main.tex": "local" },
        { "main.tex": "remote" },
      ),
    /同时修改/,
  );
  assert.throws(
    () => planSync({ "main.tex": "base" }, {}, { "main.tex": "remote" }),
    /停止同步/,
  );
});

test(
  "real Git plumbing pushes a fast-forward commit, preserves remote-only edits, and rejects concurrent same-file changes",
  { timeout: 30000 },
  async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), "autopaper-git-"));
    const remote = path.join(directory, "remote.git"),
      local = path.join(directory, "local.git");
    const execute = (args, options) =>
      git(["-c", "protocol.file.allow=always", ...args], options);
    const run = async (args, cwd, input) =>
      (await execute(args, { cwd, input })).toString().trim();
    async function commitFiles(files, parent) {
      await run(
        parent ? ["read-tree", parent] : ["read-tree", "--empty"],
        remote,
      );
      for (const [name, content] of Object.entries(files)) {
        const hash = await run(
          ["hash-object", "-w", "--stdin"],
          remote,
          content,
        );
        await run(
          ["update-index", "--add", "--cacheinfo", "100644", hash, name],
          remote,
        );
      }
      const tree = await run(["write-tree"], remote);
      const sha = await run(
        [
          "-c",
          "user.name=Test",
          "-c",
          "user.email=test@localhost",
          "commit-tree",
          tree,
          ...(parent ? ["-p", parent] : []),
        ],
        remote,
        "test\n",
      );
      await run(["update-ref", "refs/heads/main", sha], remote);
      return sha;
    }
    try {
      await run(["init", "--bare", "--initial-branch=main", remote], directory);
      const first = await commitFiles({
        "main.tex": "base",
        "other.tex": "original",
      });
      await run(["clone", "--bare", "--", remote, local], directory);
      await commitFiles({ "other.tex": "changed remotely" }, first);
      const base = {
        "main.tex": Buffer.from("base").toString("base64"),
        "other.tex": Buffer.from("original").toString("base64"),
      };
      const files = {
        ...base,
        "main.tex": Buffer.from("revised locally").toString("base64"),
      };
      const repo = { directory: local, branch: "refs/heads/main" };
      const result = await pushOverleaf(repo, base, files, undefined, {
        execute,
        revisionMetadata:{revision:"source-revision",sourceCommit:"local-source-sha",model:"fixture-editor",provider:"openai"},
      });
      assert.match(await run(["log","-1","--format=%B","main"],remote),/fixture-editor/);
      assert.deepEqual(result.files, ["main.tex"]);
      assert.equal(
        await run(["show", "main:main.tex"], remote),
        "revised locally",
      );
      assert.equal(
        await run(["show", "main:other.tex"], remote),
        "changed remotely",
      );
      const remoteHead = await commitFiles(
        { "main.tex": "edited again remotely" },
        result.head,
      );
      await assert.rejects(
        pushOverleaf(
          repo,
          files,
          {
            ...files,
            "main.tex": Buffer.from("another local edit").toString("base64"),
          },
          undefined,
          { execute },
        ),
        /同时修改/,
      );
      assert.equal(await run(["rev-parse", "main"], remote), remoteHead);
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  },
);
