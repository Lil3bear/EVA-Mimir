# EVA-Mimir 分层多 Agent 架构

## 设计理念

EVA-Mimir 是一个面向 CTF 评测（TSecBench）的自动化解题 Agent。核心设计目标是：**在有限时间内稳定地解出尽可能多的题目，同时保证多题目、多 Solver 并行时不互相污染状态。**

架构遵循三个基本原则：

1. **默认隔离，受控共享** —— 不同题目、不同 run、不同 Solver attempt 的状态默认互不可见；只有经过 Observer 验证的结构化证据才能跨边界共享。
2. **事件源 + 投影** —— 所有状态变化追加写入不可变的事件日志，可回放、可审计、可重建；JSON 状态文件只是加速读取的缓存投影。
3. **确定性控制面** —— 停机、换向、预算、放弃等决策由确定性代码（而非 LLM 自由发挥）统一管理，避免"用必须继续覆盖停机条件"。

---

## 分层状态模型

```text
全局 Skills（只读，通用知识）
└── benchmark task（按 token/run 隔离）
    └── challenge
        ├── shared/          Observer 批准后的共享事实与证据
        │   ├── memory/      已批准共享 Memory
        │   ├── proposals/   待审核的证据提案
        │   ├── artifacts/   Typed evidence（foothold/credential/host/flag_stage）
        │   ├── claims.json  Hypothesis 互斥租约
        │   ├── commands.jsonl  Observer 调度命令
        │   ├── stage-ledger.json  多 Flag 阶段进度
        │   └── state-events.jsonl  canonical 状态事件源（hash chain）
        └── attempts/
            ├── aggressive/  私有 Memory、Ideas、Control、lineage
            └── steady/      私有 Memory、Ideas、Control、lineage
```

**关键约束**：Solver 的 `memory_add`/`idea_add` 写入自己的 attempt 私有目录；`memory_list` 只能读到自己的私有状态 + 已批准的 shared 事实。一个 Solver 永远不会直接读取另一个 Solver 的原始思路。

---

## 核心模块

| 模块 | 职责 |
|---|---|
| `scoped_state.py` | 分层状态视图：solver 私有 / observer 聚合 / shared 已批准 |
| `lineage.py` | append-only session 树（session_id/parent_id/branch_id），compaction/checkpoint/fork 都是追加节点 |
| `contracts.py` | Planner 输出的 SubtaskContract：objective/hypothesis/成功条件/停止条件 |
| `claims.py` | Hypothesis 互斥租约：同一方向只能被一个 attempt 占用，lease 过期可接管 |
| `artifacts.py` | Typed Evidence Bus：结构化证据（带来源/置信度/状态），Observer 批准后才共享 |
| `commands.py` | Observer Command Bus：可持久化、可确认、可过期的调度命令 |
| `stage_ledger.py` | 多 Flag 阶段进度（按 flag index 记录，不存原始 flag）|
| `retry_ledger.py` | 跨进程持久化的 fail_streak/abandoned/cooldown，解决"进程重启后重复启动死路" |
| `state_events.py` | canonical 状态事件源（hash chain 可校验、可回放）|
| `replay.py` | 只读回放与不变量校验 |

---

## 多 Solver 协作协议

难题允许多个 Solver 并行探索，但协作通过**结构化协议**，而非共享自然语言看板：

```text
Solver A 发现证据
   ↓ artifact_publish（proposal，其他 Solver 暂不可见）
Observer 验证
   ↓ artifact_approve / memory_promote
进入 shared 层
   ↓
Solver B 可消费已验证证据
```

同时：

- `claim` 保证两个 Solver 不重复同一 hypothesis；
- `command` 让 Observer 可以定向调度（assign/pause/fork/close）；
- `stage_ledger` 让多 Flag 题的阶段进度共享、不存 flag 原文。

### hard/瓶颈题：竞争假设（agent-team 式）

hard/difficult 题由 `portfolio.py` 生成三个正交竞争假设并行攻坚：

```text
foothold（Web 初始入口）   ─┐
lateral（SSRF/内网/凭据复用）─┼─> 各自独立 context，claim 互斥
source（源码/配置泄露）     ─┘    谁先解出谁赢（stop_event）
```

- 每个 attempt 的 `model="pro"` → 切换到 `llm.pro_model`（默认 `deepseek-v4-pro`）；
  用 `solver.pro_enabled=false` 或环境变量 `LLM_PRO_MODEL` 覆盖。
- `memory_scope="private"`：原始思路/失败流水默认互不可见；结构化证据经
  `artifact_publish → artifact_approve`（或 `memory_share → memory_promote`）受控共享。
- 一个 challenge 只选一个 Observer（当前为 foothold）作为控制面，避免多个
  Observer 并发修改共享看板。

---

## 调度与题目分级

`policy.py` 按 **tier + ROI** 排序题目：

- **tier**：难度升序（简单后难 easy → medium → hard）；同难度内再把耗时长、易占满 worker slot 的 pentest/pwn/reverse 家族（b/e/f）推迟到尾部；
- **ROI**：同类内按"期望分 / 成本"排序。

这解决了"b 类多阶段题一开始就占满全部并行 slot、导致 a 类快速题排队"的问题（run-12717 的根因）。

---

## 防爆破护栏（分题型 + 迭代利用豁免）

`bash_tool.py` 的反爆破护栏只针对**发往当前目标 host 的盲目字典爆破**：

- 同结构硬阈值放宽到 12（避免误伤 LFI/SSRF 等需要多次探测的利用）；
- shell 循环塞 ≥4 变体 → 判定为字典爆破，立即拦截；
- **oracle 驱动的迭代利用**（SQLi 盲注/LFI/SSRF/命令注入/向打分端点迭代提交）豁免，给 60 次宽裕预算；
- 内网横向移动（b 类）和 webshell 命令执行不受限。

---

## 稳定性的关键保障

1. **状态事件源**：所有写操作（memory/claim/artifact/command/stage/submission/retry）都追加写入 `state-events.jsonl`，带 hash chain，可检测篡改、可回放重建。
2. **跨进程持久化**：retry/abandon/cooldown 不依赖进程内存，重启后不重复启动死路。
3. **任务隔离**：benchmark task 身份（URL+token 的 hash）变化时，自动清理旧任务的 shared/attempts/恢复状态。
4. **Solver 结束自动释放 claim**：避免 baseline 重跑时旧 claim 残留导致"方向被自己占用"。

---

## 测试

```text
227 passed
```

覆盖：分层隔离、claim 互斥与过期接管、artifact pending/approved 生命周期、lineage 回放与篡改检测、retry 跨进程恢复、Observer 命令定向、题目排序分级、防爆破分题型等。

---

## 设计取舍（为什么这么做）

| 取舍 | 理由 |
|---|---|
| 默认私有、受控共享 | 多 Solver 共享整段思路会导致 A/B 题知识污染、错误方向互相传染 |
| 事件源 + 投影 | 多套状态文件各自写会漂移；append-only 事件源可审计可回放 |
| 确定性控制面 | LLM 自己判断"要不要停"不可靠；停机/换向/预算必须由代码决定 |
| 结构化命令而非自然语言纠偏 | 自然语言纠偏无法确认、无法定向、无法过期 |
| 按 tier 分级而非按难度 | 静态难度标签 ≠ 实际解题成本；tier+ROI 更贴近"先拿分"目标 |
