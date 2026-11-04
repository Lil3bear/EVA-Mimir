import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, symlink, chmod, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

test(
  "simulated malformed model IDs survive the full propose/approve/compile workflow without touching unrelated comments",
  { timeout: 120000 },
  async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), "autopaper-links-"));
    const bin = path.join(directory, "bin");
    await mkdir(bin);
    const fixture = fileURLToPath(
      new URL("./fixtures/codex-fixture.mjs", import.meta.url),
    );
    await chmod(fixture, 0o755);
    await symlink(fixture, path.join(bin, "codex"));
    const child = spawn(process.execPath, ["server/index.mjs"], {
      env: {
        ...process.env,
        PORT: "4399",
        DATA_DIR: path.join(directory, "data"),
        AI_PROVIDER: "codex",
        OPENAI_MODEL: "gpt-6.1-sol",
        PATH: `${bin}${path.delimiter}${process.env.PATH}`,
        NODE_ENV: "production",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    const base = "http://localhost:4399/api";
    async function api(url, body) {
      const res = await fetch(base + url, {
        method: body ? "POST" : "GET",
        headers:
          body instanceof FormData
            ? {}
            : { "Content-Type": "application/json" },
        body:
          body instanceof FormData
            ? body
            : body
              ? JSON.stringify(body)
              : undefined,
      });
      const result = await res.json();
      assert.ok(res.ok, JSON.stringify(result));
      return result;
    }
    try {
      await new Promise((resolve, reject) => {
        child.stdout.on("data", (data) => {
          if (data.toString().includes("Autopaperreview:")) resolve();
        });
        child.on("error", reject);
        child.on("exit", (code) => reject(new Error(`Server exited ${code}`)));
      });
      const form = new FormData();
      form.append("demo", "true");
      form.append("trusted", "true");
      let project = await api("/projects/import", form);
      const url = `/projects/${project.id}`;
      const original = project.revision;
      await api(`${url}/comments`, {
        body: "Revise this sentence.",
        quote: "Each stage leaves an explicit record.",
        pdfRevision: null,
      });
      project = await api(`${url}/comments`, {
        body: "Leave this other comment open.",
        pdfRevision: null,
      });
      const knownId = project.comments[0].id;
      project = await api(`${url}/ai`, {
        mode: "revise",
        instructions: "Test metadata handling",
        skillIds: ["writing"],
        consent: true,
      });
      const proposal = project.proposals[0];
      assert.equal(project.revision, original);
      assert.deepEqual(proposal.patches[0].commentIds, [knownId]);
      assert.deepEqual(proposal.patches[0].unlinkedCommentIds, [
        "F1",
        "invented-id",
      ]);
      project = await api(`${url}/proposals/${proposal.id}/apply`, {});
      assert.notEqual(project.revision, original);
      assert.equal(project.pdfRevision, project.revision);
      assert.equal(project.comments[0].addressed, true);
      assert.equal(project.comments[1].addressed, undefined);
      assert.ok(project.comments.every((c) => c.status === "open"));
      assert.ok(
        (await api(`${url}/source?file=main.tex`)).content.includes(
          "Each stage retains an explicit record for the author.",
        ),
      );
      const pdf = await fetch(base + `${url}/pdf/${project.pdfRevision}`);
      assert.equal(
        Buffer.from(await pdf.arrayBuffer())
          .subarray(0, 4)
          .toString(),
        "%PDF",
      );
      const automatic = await api("/projects/import", form);
      const autoURL = `/projects/${automatic.id}`;
      await api(`${autoURL}/automation`, {
        enabled: true,
        consent: true,
        skillIds: ["writing"],
      });
      await api(`${autoURL}/comments`, {
        body: "AUTO_VALID_FIXTURE: revise the record sentence",
        quote: "Each stage leaves an explicit record.",
        pdfRevision: null,
      });
      assert.equal((await api(`${autoURL}/activity`)).job.status, "queued");
      async function waitJob(predicate) {
        for (let i = 0; i < 300; i++) {
          const state = (await api(`${autoURL}/activity`)).job;
          if (predicate(state)) return state;
          if(state?.status==="failed")throw new Error(`background job failed: ${state.error}`);
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        throw new Error("background job timeout");
      }
      await waitJob((job) => job.status === "running" && job.phase === "model");
      await api(`${autoURL}/comments`, {
        body: "AUTO_VALID_FIXTURE: revise the final sentence",
        quote:
          "Scientific decisions and final acceptance of changes remain with the author.",
        pdfRevision: null,
      });
      assert.equal(
        (await api(`${autoURL}/activity`)).job.pendingComments,
        true,
      );
      let fresh;
      for (let i = 0; i < 300; i++) {
        fresh = await api(autoURL);
        if (fresh.history.length === 3) break;
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
      assert.equal(fresh.history.length, 3);
      assert.equal(fresh.pdfRevision, fresh.revision);
      assert.ok(
        fresh.comments.every((c) => c.addressed && c.status === "open"),
      );
      const job = await waitJob((job) => job.status === "completed");
      assert.ok(job.events.some((e) => e.phase === "compiling"));
      assert.ok(job.events.some((e) => e.phase === "saved"));
      await api(`${autoURL}/comments`, {
        body: "AUTO_VALID_FIXTURE: do not run this queued request",
        pdfRevision: null,
      });
      await api(`${autoURL}/jobs/cancel`, {});
      assert.equal((await api(`${autoURL}/activity`)).job.status, "cancelled");
    } finally {
      child.kill("SIGTERM");
      await new Promise((resolve) => child.once("close", resolve));
      await rm(directory, { recursive: true, force: true });
    }
  },
);
