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

### hard 题：默认单链单 agent；竞争假设仅限多入口

**默认（当前 settings）**：`pro_enabled=false`，`hard_competing_hypotheses=false`。

- hard **单 flag** 的 a-/c-/d-/e2-/e3-/f* → **单 agent + skill_chain/playbook**
  （不开 foothold/lateral/source；单链 Web 产品题开并行假设会放大方差、抢 lane）
- hard 且 `flag_count > 1`，或显式 `hard_competing_hypotheses=true` → 竞争假设：

```text
foothold（Web 初始入口）   ─┐
lateral（SSRF/内网/凭据复用）─┼─> 仅多 flag hard / opt-in
source（源码/配置泄露）     ─┘
```

- attempt 的 `model="pro"` **仅当** `solver.pro_enabled` 为 `true`/`hard_only` 时
  才会切到 `llm.pro_model`；当前默认 **关闭**，全部走 flash/medium。
- `memory_scope="private"`：原始思路默认互不可见；结构化证据经
  `artifact_publish → artifact_approve` 受控共享。
- 多 Solver 时一个 challenge 只选一个 Observer 作为控制面。

### 稳定模型拓扑（勿再漂移）

```text
主路径（light / hard / summary / observer）
  → deepseek-v4-flash-0731（tokenhub 同 key）
兜底结构调用（llm.fallback_models）
  → glm-5.3-flash（仅主路径瞬时错误耗尽后切换；tool_choice=auto + thinking enabled）
heavy / escalate
  → 配置保留但 escalate_rounds=0，默认不启用
```

主路径与兜底**必须是不同模型**：若 `tiers.light` 写成 glm，则 failover 到 glm 无效。
GLM 专用于结构/工具调用兜底，不要当默认主模型（除非显式改拓扑并清空/更换 fallback）。

### 知识注入（避免多套指纹表）

```text
bash 输出
  ├─ knowledge_router  → CVE/产品 cheatsheet（只注入、不硬拦；步骤须 ⊆ playbook 成功链）
  ├─ skill_chain       → 指纹表（唯一真相）→ 强制 skill_load + 歪路 gate
  └─ skill_router      → 链横幅（委托 skill_chain）+ IP 漂移 / URL bug / 工程错误 oracle
agent Memory pin       → 把已触发链钉进 Memory，不是第四套指纹
```

**工程错误 oracle（稳定「可解工程题」的关键）**：工具 stderr 命中已知失败类
（如 pip `neither setup.py nor pyproject.toml`、uv 不认 `--no-build-isolation`、
`/api/manager/reboot` 405）时，直接给出**下一步动作**，禁止用「死路」语言封死备选。
产品玩法以 playbook「最短成功链」为准；cheatsheet 不得主推已被实测证伪的链（如 Comfy `git_url`）。

### 控制面主路径（其余为增强）

**主路径**：`scheduler/policy` → `agent` 工具门控（含 `skill_chain`）→ `skills/` playbook。  
**增强层（保留、勿再加厚）**：claims / artifacts / commands / lineage /
decision_state / strategy_controller / salvage。归因时先查主路径。

---

## 调度与题目分级

`policy.py` 按 **tier + ROI** 排序题目：

- **tier**：难度升序（简单后难 easy → medium → hard）；同难度内再把耗时长、易占满 worker slot 的 pentest/pwn/reverse 家族（b/e/f）推迟到尾部；
- **ROI**：同类内按"期望分 / 成本"排序。

**Lane 与工具门控**（`agent.py`）：

- **Fast Lane**：easy + medium（含 c-* 综合服务）；单 agent、少 Observer；`security_search` 前 15 轮禁止；
- **Deep Lane**：hard/difficult、多阶段渗透（b-*）；可换向/止损；
  **当前 `pro_enabled=false`**，即使开竞争假设也不会切 pro 模型；
- **hint**：easy 默认拒绝；hard 更早门槛；卡死才解锁；
- medium c-* 卡死时经 `fast_lane_rounds`（默认 30 轮）升级到 Deep，而非开局 Deep。

**尾段抢分**（**360min** benchmark，`solver/runtime/salvage.py`）：

- **salvage**（≤140min 剩余）→ **critical**（≤72min）→ **final**（≤36min，仅 easy/salvage）
- 切断长难题 `mark_abandoned`；`collect_salvage_targets` 捞波动/方向错的简单题
- 触发条件：360 墙钟 **或** 缩放后的 run deadline，取更早者

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
5. **并行 workspace 隔离**（`solver/runtime/workspace_guard.py`）：bash/read/write/grep 禁止访问 sibling 题目目录；`.tool-results` 固定在本题 attempt 下。
6. **提交后平台校验**（`bridge_tools.submit_flag`）：API 返回 correct 后再次 `get_state`，进度未涨则 `[✗] 未计分`，agent 不会因诱饵 flag 假 solved。
7. **Routing 强制 medium-only**（`enforce_medium_only_routing`）：配置面也写成 `hard_tier=light` / `escalate_rounds=0`，与运行时一致；`SOLVER_HIGH_TIER=1` 才允许 heavy。
8. **知识链硬门**（`skill_chain`）：指纹命中后未 load 对应 playbook 前，拒绝 `security_search` 与明确歪路 bash；**只拦批量爆破等死胡同，不拦 playbook 合法登录表单**。
9. **失败 idea 软提示**：重试轮不把旧失败写成绝对禁令；含过期 IP 的失败方向自动忽略，减轻实例漂移回归。
10. **单链 hard 单 agent** + `pro_enabled=false` / `hard_competing_hypotheses=false`：避免多 lane 抢配额导致偶发深度不够。
11. **Last-mile 保护**：`solver.lastmile_codes`（a-03/f2-05/b-02）在 salvage/critical **不**被 cut abandon；有部分分的题永不砍；仅 `final` 才放弃 0 分 lastmile。RSI pack `lastmile3` 专测这三题。
12. **同 key 模型故障切换**（`llm.fallback_models`，默认 `glm-5.3-flash`）：主模型连续瞬时错误耗尽重试后切备用；切成功本场粘住。GLM 结构调用单独处理：`tool_choice=auto`（不用 `required`）、`thinking` 只发 `enabled`（5.3 禁 disabled）、`reasoning_effort` 映射到 low/high/max。
13. **慢轮保护**：按剩余墙钟收紧单请求超时与重试次数（`budget_aware_timeout` / `budget_aware_attempts`）；API 超时/限流在 failover 耗尽后**回滚本轮并 nudge**，不把题目终态结束。
14. **自适应背压**（`AdaptiveLLMGate`）：检测到超时/429/5xx 时临时扣留一半 LLM 槽位，降低并发给每个请求更多余量；成功后立即恢复。
15. **Observer advisory 默认**（`solver.observer_mode=advisory`）：默认 `NO_CHANGE`；纠偏仅在决策面 streak 证明空转时放行；`skill_chain` 未闭合时压制纠偏；截断 history / playbook dump 不得 `memory_add`；看板污染条目标为不可信。设 `full` 可恢复旧强干预，`off` 完全关闭。
17. **Memory/Skill 防自污染**：写入门控拦截截断 dump / playbook 长文；Solver 状态快照过滤不可信条目；失败方向软提示（含过期 IP 忽略）；`skill_chain` 为指纹真源、`skill_router` 只做旁路横幅；RSI refinements 只记账不运行时改写 skills。配置面钉死 medium-only + glm 兜底 + `observer_mode=advisory`。

---

## 测试

```text
unittest: tests/test_portfolio_scope.py + tests/test_skill_chain.py + SkillRouterTests
```

覆盖：分层隔离、单链 hard 单 agent、claim 互斥、artifact 生命周期、retry、题目排序、skill 路由与知识链门控等。

---

## RSI 本地迭代

全量 benchmark 之前，用 **回归 pack** 验证架构与 skills，见 [RSI.md](./RSI.md)：

- `config/regression_codes.json` — 按维度题单（含 `unstable6`）
- `scripts/rsi_local.sh` — 本地跑 pack + 生成 `workspace/rsi-report.md`
- `solver/rsi/` — pack 解析、跑后分析、skill 改动账本

---

## 设计取舍（为什么这么做）

| 取舍 | 理由 |
|---|---|
| 默认私有、受控共享 | 多 Solver 共享整段思路会导致 A/B 题知识污染、错误方向互相传染 |
| hard 单链默认单 agent | foothold/lateral/source 对 JWT/pydash/Comfy 单链题是方差放大器 |
| 事件源 + 投影 | 多套状态文件各自写会漂移；append-only 事件源可审计可回放 |
| 确定性控制面 | LLM 自己判断"要不要停"不可靠；停机/换向/预算必须由代码决定 |
| 结构化命令而非自然语言纠偏 | 自然语言纠偏无法确认、无法定向、无法过期 |
| 按 tier 分级而非按难度 | 静态难度标签 ≠ 实际解题成本；tier+ROI 更贴近"先拿分"目标 |
| skill_chain 唯一指纹表 | 避免 skill_router / Memory pin 各写一套指纹导致 playbook 漂移 |
| cheatsheet ⊆ 成功链 + 错误 oracle | 防止注入证伪主链；工程题靠真实 stderr 纠偏，不靠绝对禁令 |
