# EVA-Mimir 分层多 Agent 架构 TODO

## 已完成

- [x] Challenge / attempt 私有 Memory、Ideas、Control 隔离
- [x] Shared evidence proposal 与 Observer promote
- [x] task 切换时清理 shared/attempt 状态
- [x] Observer 聚合审阅各 attempt，但 Solver 不读取其他 attempt 原始看板

## 实施顺序

### P1：统一 Session Lineage / Append-only Journal

目标：所有 Solver session、tool boundary、compaction、recovery、branch 都进入带 parent_id 的追加日志，禁止依赖覆盖式 history 重建状态。

### P2：Planner / Subtask Contract

目标：Planner 将题目拆成有边界、有成功条件、有停止条件的 SubtaskContract，再分配给 Solver。

### P3：Attempt Claim / Lease

状态：已完成第一版（`solver/runtime/claims.py`）。

目标：同一 challenge 内的 hypothesis、攻击方向、服务目标只能被一个 attempt 占用；lease 过期后才能接管。

### P4：Typed Evidence / Artifact Bus

状态：已完成第一版（`solver/runtime/artifacts.py`）。

目标：Solver 只通过结构化 artifact 共享事实，不共享整段自然语言 Memory；每个 artifact 有来源、证明引用、置信度、状态和过期时间。

### P5：Observer Command Bus

状态：已完成第一版（`solver/runtime/commands.py`）。

当前支持持久化、target attempt、state version、过期轮次、acknowledge；Solver 每轮消费命令并写入 lineage。

目标：Observer 输出结构化 assign/merge/promote/pause/fork/close 命令，Solver 不再依赖自由文本纠偏完成调度。

### P6：Multi-Flag Stage Ledger

状态：已完成第一版（`solver/runtime/stage_ledger.py`）。

当前接入 `challenge_submit_flag` 和 `challenge_get_state`，按平台 flag index 记录进度、当前 stage、attempt 来源和事件，不保存原始 flag。

目标：记录 flag stage、依赖关系、已提交 flag、剩余 flag、当前 owner 和下一阶段条件。

### P7：Scheduler 持久化重试状态

状态：已完成第一版（`solver/runtime/retry_ledger.py`）。

当前持久化 `fail_streak`、attempts、abandoned、cooldown；任务身份变化时自动隔离。主循环不再只依赖进程内存。

### P8：验证

状态：已完成第一版回放/隔离测试（`solver/runtime/replay.py`）和统一状态事件校验（`solver/runtime/state_events.py`）。

- [x] 两个 Solver 并行且私有状态互不可见
- [x] proposal 未 promote 前不可见
- [x] task/run/challenge 之间无状态污染
- [x] lineage 可回放和恢复
- [x] claim/lease 可互斥并过期接管
- [x] retry/abandon 状态可跨进程恢复
- [x] artifact pending/approved 生命周期可回放
- [x] Memory/claim/artifact/command/stage/submission/retry 写入 canonical state event log
- [ ] Observer 合并冲突证据不污染 Solver（真实平台 e2e）
- [ ] 真实 multi-flag 并行 e2e
