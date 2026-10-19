import { randomUUID } from "node:crypto";

const active = new Set(["queued", "running", "cancelling"]);
export class Jobs {
  constructor({ read, write }) {
    this.read = read;
    this.write = write;
    this.entries = new Map();
  }
  async get(projectId) {
    const entry = this.entries.get(projectId);
    if (entry) return entry.state;
    const state = await this.read(projectId);
    if (state && active.has(state.status)) {
      state.status = "interrupted";
      state.message = "服务已重启，请核对版本历史后重试";
      await this.write(projectId, state);
    }
    return state;
  }
  enqueue(
    projectId,
    task,
    { delay = 0, automatic = false, title = "AI 修订",model,provider } = {},
  ) {
    const current = this.entries.get(projectId);
    if (current && active.has(current.state.status)) {
      if (!automatic) throw Object.assign(new Error("这篇文章已有后台任务。请先保存批注，等待本轮完成，避免并发覆盖同一版本。"), {status:409});
      if (current.state.status === "queued" && current.state.automatic) {
        clearTimeout(current.timer);
        current.task = task;
        current.timer = setTimeout(() => this.run(projectId, current), delay);
      } else {
        current.next = task;
        current.nextTitle = title;
        current.nextModel=model;current.nextProvider=provider;
        current.state.pendingComments = true;
        this.persist(projectId, current);
      }
      return current.state;
    }
    const state = {
      id: randomUUID(),
      title,
      automatic,
      model,provider,
      status: "queued",
      phase: "queued",
      message: delay ? "新批注已排队，正在合并本轮意见" : "已排队",
      created: new Date().toISOString(),
      started: null,
      updated: new Date().toISOString(),
      events: [],
      pendingComments: false,
    };
    const entry = {
      state,
      task,
      controller: new AbortController(),
      saved: current?.saved || Promise.resolve(),
    };
    this.entries.set(projectId, entry);
    this.progress(projectId, entry, {
      phase: "queued",
      message: state.message,
    });
    entry.timer = setTimeout(() => this.run(projectId, entry), delay);
    return state;
  }
  persist(projectId, entry) {
    const snapshot = structuredClone(entry.state);
    entry.saved = entry.saved
      .catch(() => {})
      .then(() => this.write(projectId, snapshot));
    entry.saved.catch(() => {});
  }
  progress(projectId, entry, event) {
    Object.assign(entry.state, {
      phase: event.phase,
      message: event.message,
      updated: new Date().toISOString(),
    });
    for(const key of ["model","provider","revision","request"])if(event[key]!==undefined)entry.state[key]=event[key];
    entry.state.events.push({ ...event, time: entry.state.updated });
    this.persist(projectId, entry);
  }
  async run(projectId, entry) {
    entry.state.status = "running";
    entry.state.started = new Date().toISOString();
    const progress = (event) => this.progress(projectId, entry, event);
    try {
      const result = await entry.task({
        signal: entry.controller.signal,
        progress,
      });
      entry.state.status = result?.outcome==="no_changes"?"no_changes":result?.outcome==="proposed"?"awaiting_approval":"completed";
      entry.state.result = result;
      progress({ phase: entry.state.status==="completed"?"done":entry.state.status, message: result?.message || "后台任务已完成" });
    } catch (error) {
      entry.state.status = entry.controller.signal.aborted
        ? "cancelled"
        : "failed";
      entry.state.error = entry.controller.signal.aborted
        ? "任务已停止；请核对版本历史"
        : error.message;
      if (error.log) entry.state.log = error.log;
      progress({ phase: entry.state.status, message: entry.state.error });
    }
    await entry.saved.catch(() => {});
    if (entry.next && !entry.controller.signal.aborted)
      this.enqueue(projectId, entry.next, {
        automatic: true,
        delay: 1500,
        title: entry.nextTitle || entry.state.title,
        model:entry.nextModel,provider:entry.nextProvider,
      });
  }
  cancel(projectId) {
    const entry = this.entries.get(projectId);
    if (!entry || !active.has(entry.state.status)) return entry?.state || null;
    entry.next = null;
    entry.state.pendingComments = false;
    if (entry.state.status === "queued") {
      clearTimeout(entry.timer);
      entry.state.status = "cancelled";
    } else entry.state.status = "cancelling";
    entry.controller.abort();
    this.progress(projectId, entry, {
      phase: entry.state.status,
      message:
        entry.state.status === "cancelled"
          ? "排队任务已取消"
          : "正在停止后台进程",
    });
    return entry.state;
  }
  async markApplied(projectId,proposalId,revision) {
    let entry=this.entries.get(projectId);
    const state=entry?.state||await this.read(projectId);
    if(!state||state.status!=="awaiting_approval"||state.result?.proposal!==proposalId)return false;
    if(!entry){
      if(this.entries.has(projectId))return false;
      entry={state,saved:Promise.resolve()};this.entries.set(projectId,entry);
    }
    state.status="completed";
    state.result={...state.result,outcome:"applied",revision,message:"修改已确认、编译并保存；未解决的科学批注仍保留"};
    state.events||=[];
    this.progress(projectId,entry,{phase:"saved",revision,message:state.result.message});
    await entry.saved;
    return true;
  }
}
