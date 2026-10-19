import { test } from "node:test";
import assert from "node:assert/strict";
import { Jobs } from "../server/jobs.mjs";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function terminal(jobs, id) {
  for (let i = 0; i < 150; i++) {
    const job = await jobs.get(id);
    if (job && !["queued", "running", "cancelling"].includes(job.status))
      return job;
    await sleep(10);
  }
  throw new Error("job did not finish");
}
function manager() {
  const data = new Map();
  return new Jobs({
    read: async (id) => data.get(id) || null,
    write: async (id, state) => {
      data.set(id, structuredClone(state));
    },
  });
}
test("no source edits and unaccepted proposals are never labelled completed; model provenance persists",async()=>{
  const jobs=manager();
  jobs.enqueue("noop",async({progress})=>{progress({phase:"reading",model:"fixture-editor",provider:"openai",revision:"r1",message:"reading"});return {outcome:"no_changes",message:"未修改"};});
  const noop=await terminal(jobs,"noop");assert.equal(noop.status,"no_changes");assert.equal(noop.model,"fixture-editor");assert.equal(noop.provider,"openai");assert.equal(noop.revision,"r1");
  jobs.enqueue("proposal",async()=>({outcome:"proposed",message:"待确认"}));assert.equal((await terminal(jobs,"proposal")).status,"awaiting_approval");
});
test("automatic comments do not replace a queued manual Bib audit", async () => {
  const jobs = manager(), calls = [];
  jobs.enqueue("bib", async () => {calls.push("audit");}, {title:"Bib audit",delay:20});
  jobs.enqueue("bib", async () => {calls.push("revise");}, {automatic:true,title:"Auto revision"});
  await sleep(1700);
  assert.deepEqual(calls,["audit","revise"]);
  assert.equal((await jobs.get("bib")).title,"Auto revision");
});
test("background progress is observable and persists a completed result", async () => {
  const jobs = manager();
  jobs.enqueue("p", async ({ progress }) => {
    progress({ phase: "model", message: "model started" });
    await sleep(30);
    return { message: "saved", revision: "r2" };
  });
  await sleep(10);
  assert.equal((await jobs.get("p")).status, "running");
  const result = await terminal(jobs, "p");
  assert.equal(result.result.revision, "r2");
  assert.ok(result.events.some((e) => e.message === "model started"));
});
test("new comments during a running automatic task queue exactly one subsequent round", async () => {
  const jobs = manager();
  let first = 0,
    next = 0;
  jobs.enqueue(
    "p",
    async () => {
      first++;
      await sleep(40);
      return { message: "first" };
    },
    { automatic: true },
  );
  await sleep(10);
  jobs.enqueue(
    "p",
    async () => {
      next++;
      return { message: "next" };
    },
    { automatic: true },
  );
  jobs.enqueue(
    "p",
    async () => {
      next++;
      return { message: "next" };
    },
    { automatic: true },
  );
  assert.equal((await jobs.get("p")).pendingComments, true);
  for (let i = 0; i < 250; i++) {
    if (next) break;
    await sleep(10);
  }
  await terminal(jobs, "p");
  assert.equal(first, 1);
  assert.equal(next, 1);
});
test("queued cancellation prevents model execution and an interrupted stored task is not silently resumed", async () => {
  const jobs = manager();
  let ran = false;
  jobs.enqueue(
    "p",
    async () => {
      ran = true;
    },
    { delay: 100 },
  );
  jobs.cancel("p");
  await sleep(150);
  assert.equal(ran, false);
  assert.equal((await jobs.get("p")).status, "cancelled");
  const restarted = new Jobs({
    read: async () => ({ status: "running", events: [] }),
    write: async () => {},
  });
  assert.equal((await restarted.get("p")).status, "interrupted");
});
test("running cancellation aborts the task and suppresses an automatic next round", async () => {
  const jobs = manager();
  let next = false;
  jobs.enqueue(
    "p",
    ({ signal }) =>
      new Promise((resolve, reject) =>
        signal.addEventListener("abort", () => reject(signal.reason)),
      ),
    { automatic: true },
  );
  await sleep(10);
  jobs.enqueue(
    "p",
    async () => {
      next = true;
    },
    { automatic: true },
  );
  jobs.cancel("p");
  assert.equal((await terminal(jobs, "p")).status, "cancelled");
  assert.equal(next, false);
});
test("manual application finalizes only its matching proposed job, including after restart",async()=>{
  const jobs=manager();
  jobs.enqueue("p",async()=>({outcome:"proposed",proposal:"draft-1",message:"待确认"}));await terminal(jobs,"p");
  assert.equal(await jobs.markApplied("p","another-draft","r2"),false);
  assert.equal((await jobs.get("p")).status,"awaiting_approval");
  assert.equal(await jobs.markApplied("p","draft-1","r2"),true);
  const applied=await jobs.get("p");assert.equal(applied.status,"completed");assert.equal(applied.result.revision,"r2");assert.equal(applied.result.outcome,"applied");
  assert.equal(await jobs.markApplied("p","draft-1","r2"),false);
  let saved={status:"awaiting_approval",result:{proposal:"disk-draft"},events:[]};
  const restarted=new Jobs({read:async()=>structuredClone(saved),write:async(_,state)=>{saved=structuredClone(state);}});
  assert.equal(await restarted.markApplied("p","disk-draft","r3"),true);assert.equal(saved.status,"completed");assert.equal(saved.revision,"r3");
  restarted.enqueue("p",async()=>({message:"new task"}),{delay:100});
  assert.equal(await restarted.markApplied("p","disk-draft","r4"),false);assert.equal((await restarted.get("p")).status,"queued");
  restarted.cancel("p");
});
