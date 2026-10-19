import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm,rename,writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import os from "node:os";
import path from "node:path";
import { atomicJSON } from "../server/core.mjs";
import {commentSnapshot} from "../server/comment-log.mjs";
test(
  "HTTP workflow: comments persist, failed patches roll back, successful patches compile, stale proposals cannot overwrite, export and restore",
  { timeout: 120000 },
  async () => {
    const data = await mkdtemp(path.join(os.tmpdir(), ".autopaper-api-"));
    const child = spawn(process.execPath, ["server/index.mjs"], {
      env: {
        ...process.env,
        PORT: "4398",
        DATA_DIR: data,
        OPENAI_API_KEY: "",
        AI_PROVIDER: "openai",
        NODE_ENV: "production",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    const base = "http://localhost:4398/api";
    async function request(url, options = {}) {
      const r = await fetch(base + url, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
        body: options.body ? JSON.stringify(options.body) : undefined,
      });
      return { status: r.status, data: await r.json() };
    }
    try {
      await new Promise((resolve, reject) => {
        child.stdout.on("data", (d) => {
          if (d.toString().includes("Autopaperreview:")) resolve();
        });
        child.on("error", reject);
        child.on("exit", (code) => reject(new Error(`server exited ${code}`)));
      });
      assert.equal(
        (
          await request("/projects", {
            headers: { Origin: "https://malicious.example" },
          })
        ).status,
        403,
      );
      const form = new FormData();
      form.append("demo", "true");
      form.append("trusted", "true");
      const imported = await fetch(`${base}/projects/import`, {
        method: "POST",
        body: form,
      });
      let p = await imported.json();
      assert.equal(imported.status, 200);
      const projectPath = path.join(data, p.id, "project.json");
      const url = `/projects/${p.id}`;
      const reader=(await request(url,{headers:{'X-Workspace-View':'reader'}})).data;
      assert.equal(reader.detailsLoaded,false);assert.deepEqual(reader.proposals,[]);
      assert.equal((await request(url)).data.detailsLoaded,true);
      const initial = p.revision;
      const staleJob=await request(`${url}/jobs`,{method:"POST",body:{mode:"revise",skillIds:["writing"],instructions:"",consent:true,apply:true,expectedRevision:randomUUID()}});
      assert.equal(staleJob.status,202);
      let staleState;
      for(let i=0;i<50;i++) {
        staleState=(await request(`${url}/activity`)).data.job;
        if(staleState?.status==="failed")break;
        await new Promise(resolve=>setTimeout(resolve,20));
      }
      assert.equal(staleState.status,"failed");
      assert.match(staleState.error,/版本已变化/);
      assert.ok(!staleState.events.some(event=>event.phase==="model"));
      const built = await request(`${url}/compile`, { method: "POST" });
      assert.equal(built.status, 200, JSON.stringify(built.data));
      p = built.data;
      const pdf = await fetch(base + `${url}/pdf/${p.pdfRevision}`);
      const pdfBytes=Buffer.from(await pdf.arrayBuffer());
      assert.equal(pdf.headers.get("accept-ranges"),"bytes");
      assert.equal(
        pdfBytes
          .subarray(0, 4)
          .toString(),
        "%PDF",
      );
      const partial=await fetch(base+`${url}/pdf/${p.pdfRevision}`,{headers:{Range:"bytes=0-31"}});
      assert.equal(partial.status,206);
      assert.equal(partial.headers.get("content-range"),`bytes 0-31/${pdfBytes.length}`);
      assert.deepEqual(Buffer.from(await partial.arrayBuffer()),pdfBytes.subarray(0,32));
      const commented = await request(`${url}/comments`, {
        method: "POST",
        body: {
          body: "Keep author control explicit.",
          quote: "The author annotates",
          pdfRevision: p.pdfRevision,
          page: 1,
          x: 0.4,
          y: 0.3,
        },
      });
      p = commented.data;
      const commentId = p.comments[0].id;
      const requestId = randomUUID();
      const repeatedInput={body:"Concurrent retry fixture",pdfRevision:p.pdfRevision,requestId};
      const retries=await Promise.all(Array.from({length:10},()=>request(`${url}/comments`,{method:"POST",body:repeatedInput})));
      assert(retries.every(r=>r.status===200));
      const repeated=(await request(url)).data.comments.filter(c=>c.requestId===requestId);
      assert.equal(repeated.length,1);
      assert.equal((await request(`${url}/comments`,{method:"POST",body:{...repeatedInput,body:"Different request"}})).status,409);
      // Remove only this isolated fixture so the original workflow assertions stay focused.
      const retryProject=JSON.parse(await readFile(projectPath,"utf8"));
      retryProject.comments=retryProject.comments.filter(c=>c.requestId!==requestId);
      await atomicJSON(projectPath,retryProject);
      assert.equal((await request(url)).data.comments[0].id, commentId);
      const skillIds=(await request("/health")).data.skills.map(s=>s.id);
      assert.equal(skillIds.length,16);
      const automatic=await request(`${url}/automation`,{method:"POST",body:{enabled:true,startNow:false,consent:true,skillIds}});
      assert.equal(automatic.status,200);assert.deepEqual(automatic.data.automation.skillIds,skillIds);
      const failedRun=await request(`${url}/jobs`,{method:"POST",body:{mode:"revise",skillIds,instructions:"test missing credentials",consent:true}});
      assert.equal(failedRun.status,202);
      let archived;
      for(let i=0;i<100;i++){archived=(await request(`${url}/jobs/history`)).data.find(x=>x.id===failedRun.data.job.id);if(archived?.status==="failed")break;await new Promise(r=>setTimeout(r,20));}
      assert.equal(archived.status,"failed");assert.ok(archived.model);assert.equal(archived.provider,"openai");
      assert.equal((await request(`${url}/jobs`,{method:"POST",body:{mode:"review",skillIds,instructions:"invalid draft mode",consent:true,candidateProposalId:randomUUID()}})).status,400);
      const missingDraft=await request(`${url}/jobs`,{method:"POST",body:{mode:"revise",skillIds,instructions:"refine unavailable draft",consent:true,candidateProposalId:randomUUID()}});
      assert.equal(missingDraft.status,202);
      let missingState;
      for(let i=0;i<100;i++){missingState=(await request(`${url}/activity`)).data.job;if(missingState?.id===missingDraft.data.job.id&&missingState.status==="failed")break;await new Promise(r=>setTimeout(r,20));}
      assert.equal(missingState.status,"failed");assert.match(missingState.error,/待复核草稿/);
      assert.equal(
        (
          await request(`${url}/ai`, {
            method: "POST",
            body: {
              mode: "review",
              skillIds: ["writing"],
              instructions: "",
              consent: true,
            },
          })
        ).status,
        400,
      );
      assert.equal(
        (
          await request(`${url}/ai`, {
            method: "POST",
            body: {
              mode: "review",
              skillIds: ["writing"],
              instructions: "",
              consent: false,
            },
          })
        ).status,
        400,
      );
      const before = "Each stage leaves an explicit record.";
      const failureId = randomUUID(),
        successId = randomUUID(),noopId=randomUUID();
      const stored = JSON.parse(await readFile(projectPath, "utf8"));
      stored.proposals.push({
        id: failureId,
        revision: p.revision,
        status: "pending",
        patches: [
          {
            file: "main.tex",
            before,
            after: "\\thiscommanddoesnotexist",
            reason: "test failure",
            commentIds: [commentId],
          },
        ],
      });
      stored.proposals.push({
        id: successId,
        model:"fixture-editor",provider:"openai",
        archiveComments:true,effectiveCommentIds:[commentId],
        sourceComments:[commentSnapshot(stored.comments[0])],
        revision: p.revision,
        status: "pending",
        patches: [
          {
            file: "main.tex",
            before,
            after: "Each stage retains an explicit record for the author.",
            reason: "test success",
            commentIds: [commentId],
          },
        ],
      });
      stored.proposals.push({id:noopId,revision:p.revision,status:"pending",patches:[{file:"main.tex",before,after:before,reason:"no change",commentIds:[commentId]}]});
      const staleCommentsId=randomUUID();
      stored.proposals.push({...structuredClone(stored.proposals.find(x=>x.id===successId)),id:staleCommentsId,sourceComments:[{...commentSnapshot(stored.comments[0]),body:"An earlier opinion that was edited"}]});
      await atomicJSON(projectPath, stored);
      const staleCommentResult=await request(`${url}/proposals/${staleCommentsId}/apply`,{method:"POST"});
      assert.equal(staleCommentResult.status,400);assert.match(staleCommentResult.data.error,/批注.*改变/);
      assert.equal((await request(`${url}/proposals/${noopId}/apply`,{method:"POST"})).status,400);
      const unchanged=(await request(url)).data;assert.equal(unchanged.revision,initial);assert.equal(unchanged.comments[0].addressed,undefined);assert.equal(unchanged.proposals.find(x=>x.id===noopId).status,"pending");
      assert.equal(
        (
          await request(`${url}/proposals/${failureId}/apply`, {
            method: "POST",
          })
        ).status,
        400,
      );
      let after = (await request(url)).data;
      assert.equal(after.revision, initial);
      assert.equal(after.pdfRevision, initial);
      assert.equal(
        after.proposals.find((s) => s.id === failureId).status,
        "pending",
      );
      assert.notEqual(after.comments[0].addressed,true);
      assert.equal(after.proposals.find(s=>s.id===failureId).applyAttempts[0].status,"failed");
      const repo=path.join(data,p.id,"source-history.git"),savedRepo=path.join(data,p.id,"history.saved");
      await rename(repo,savedRepo);await writeFile(repo,"not a Git directory");
      try{
        assert.equal((await request(`${url}/proposals/${successId}/apply`,{method:"POST"})).status,400);
        const gitFailed=(await request(url)).data;assert.equal(gitFailed.revision,initial);assert.notEqual(gitFailed.comments[0].addressed,true);assert.equal(gitFailed.proposals.find(x=>x.id===successId).status,"pending");
      }finally{await rm(repo,{force:true});await rename(savedRepo,repo);}
      const applied = await request(`${url}/proposals/${successId}/apply`, {
        method: "POST",
      });
      assert.equal(applied.status, 200, JSON.stringify(applied.data));
      after = applied.data;
      assert.notEqual(after.revision, initial);
      assert.equal(after.pdfRevision, after.revision);
      assert.equal(after.comments[0].addressed, true);
      assert.equal(after.comments[0].status, "open");
      assert.ok(after.comments[0].archivedAt);assert.equal(after.comments[0].archiveProposalId,successId);
      const proposal=after.proposals.find(x=>x.id===successId);
      assert.equal(proposal.commentLog[0].body,"Keep author control explicit.");
      assert.equal(proposal.resultRevision,after.revision);assert.equal(proposal.model,"fixture-editor");assert.match(proposal.gitCommit,/^[a-f0-9]{40}$/);
      assert.equal(after.history[0].provenance.model,"fixture-editor");assert.equal(after.history[0].parent,initial);
      const diff=await request(`${url}/history/${after.revision}/diff`);assert.equal(diff.status,200);assert.match(diff.data.diff,/fixture-editor/);assert.match(diff.data.diff,/\+[^\n]*Each stage retains/);
      const reopened=await request(`${url}/comments/${commentId}`,{method:"PATCH",body:{status:"open",archived:false}});
      assert.equal(reopened.status,200);assert.equal(reopened.data.comments[0].archivedAt,null);assert.equal(reopened.data.comments[0].addressed,false);
      assert.equal(reopened.data.proposals.find(x=>x.id===successId).commentLog.length,1);
      assert.equal(
        (
          await request(`${url}/proposals/${failureId}/apply`, {
            method: "POST",
          })
        ).status,
        400,
      );
      const source = (await request(`${url}/source?file=main.tex`)).data;
      assert.ok(
        source.content.includes("retains an explicit record for the author"),
      );
      assert.equal(
        (
          await request(`${url}/source`, {
            method: "PUT",
            body: {
              file: "main.tex",
              content: source.content,
              revision: initial,
            },
          })
        ).status,
        409,
      );
      const exported = await fetch(base + `${url}/export`);
      assert.equal(exported.status, 200);
      assert.ok(exported.headers.get("content-type").includes("zip"));
      const restored = (
        await request(`${url}/restore/${initial}`, { method: "POST" })
      ).data;
      assert.equal(restored.history.length, 3);
      assert.notEqual(restored.revision, initial);
      assert.equal(restored.comments.length, 1);
      assert.equal(restored.comments[0].addressed,false);assert.equal(restored.comments[0].status,"open");assert.equal(restored.history[0].restoredFrom,initial);assert.match(restored.history[0].gitCommit,/^[a-f0-9]{40}$/);
      const partialId=randomUUID(),partialStored=JSON.parse(await readFile(projectPath,"utf8"));
      partialStored.proposals.push({id:partialId,revision:restored.revision,status:"pending",archiveComments:true,effectiveCommentIds:[commentId],provider:"fixture",model:"fixture-editor",sourceComments:[commentSnapshot(partialStored.comments[0])],patches:[{file:"main.tex",before:"The author annotates",after:"The author reviews and annotates",reason:"Language improved; scientific request remains pending",commentIds:[commentId]}]});
      await atomicJSON(projectPath,partialStored);
      assert.equal((await request(`${url}/proposals/${partialId}/apply`,{method:"POST",body:{keepOpenCommentIds:[randomUUID()]}})).status,400);
      const partialApply=await request(`${url}/proposals/${partialId}/apply`,{method:"POST",body:{keepOpenCommentIds:[commentId]}});
      assert.equal(partialApply.status,200,JSON.stringify(partialApply.data));
      assert.equal(partialApply.data.pdfRevision,partialApply.data.revision);
      assert.equal(partialApply.data.comments[0].addressed,false);assert.equal(partialApply.data.comments[0].archivedAt,null);
      assert.equal(partialApply.data.comments[0].partialRevision,partialApply.data.revision);
      assert.deepEqual(partialApply.data.history[0].provenance.keepOpenCommentIds,[commentId]);
      assert.equal(partialApply.data.proposals.find(x=>x.id===partialId).commentLog.length,0);
    } finally {
      child.kill("SIGTERM");
      await new Promise((resolve) => child.once("close", resolve));
      await rm(data, { recursive: true, force: true });
    }
  },
);
