# CTF-agent vs BreachWeave 对比分析

> 分析时间：2026-08-09
> 对比对象：BreachWeave（腾讯云黑客松第二届，613 支队伍，线上初赛第一、线下决赛一等奖）
> 参考资料：`D:\顺丰蓝军实习\学习\学习笔记\BreachWeave_Agent架构学习笔记.md`（全项目代码阅读完成）

---

## 〇、一句话总结

**BreachWeave 是工业级多 Agent 协作框架，我们是实用主义的单 Agent 系统。差距主要在架构层面（调度、隔离、扩展性），Solver 内核层面我们已经追得很近。**

---

## 一、架构层对比

| 维度 | BreachWeave | 我们 | 差距分析 |
|------|------------|------|----------|
| **语言** | TypeScript strict + Bun | Python 3.10+ | Python 在渗透场景更自然（pwntools/sqlmap 都是 Python 生态），选型合理 |
| **Agent SDK** | 自研 `@mariozechner/pi-coding-agent` | 直接调 OpenAI SDK | 我们没有中间 SDK 层，Agent 循环是手写的。**好处**：完全可控、无黑盒；**坏处**：事件系统、Extension 机制、流式传输全靠自己维护 |
| **架构层数** | **3 层**：Planner → Solver → Observer | **2 层**：Solver + Observer | **最大差距**。我们没有 Planner，多题调度是 Scheduler 逐题循环，不是 AI 决策 |
| **UI** | React Web + TUI (Ink) | rich TUI | 差距明显但影响不大（比赛不看 UI） |

### 核心差距：Planner 层

BreachWeave 的 Planner 是**用 LLM 做调度决策**的 AI Agent：
- 每 30s 轮询，用大模型决定"要不要起新题/加 solver/kill stale solver"
- 有 5 个专用工具（`planner_start/stop_challenge`, `planner_launch/stop_solver`, `planner_get_state`）
- `planner_stop_challenge` 在代码层 throw 拦截非 stale 题目（硬约束）
- 可以给同一题**并行启动多个 Solver**（不同 prompt/模型组合）

我们的 Scheduler 是**纯代码逻辑**：
- 按难度排序 → ThreadPoolExecutor 并行（max_workers=3）→ 逐题 start/run/close
- 没有运行时动态调度能力（不能中途加 solver、不能根据进展换策略）
- 同一题只有一个 Solver

**影响评估**：比赛中这是**最值钱的差距**。多 Solver 并发意味着同一题可以同时跑不同 prompt（kimi-security + claude），谁先出 flag 算谁的。我们只有一把枪，他们有三把。

---

## 二、Solver 内核对比

| 维度 | BreachWeave | 我们 | 差距 |
|------|------------|------|------|
| **ReAct 循环** | SDK 内置 | 手写 while 循环 | 功能等价 ✅ |
| **工具集** | bash/read/edit/write/grep/find/ls + 自定义 | bash/read_file/write_file/grep + 自定义 | 基本等价 ✅ |
| **角色隔离** | Solver 没有 `idea_add`（硬约束） | 已修复移除 ✅ | 已对齐 ✅ |
| **重复操作检测** | 无（依赖 Observer 纠偏） | **三层检测**（命令级/approach 级/目标不可达） | **我们更强** 🟢 |
| **上下文压缩** | SDK 内置 + `pentest-compaction.ts` 注入压缩指导 | 语义摘要 + 滑动窗口 + Observer 消息钉住 | 基本等价 ✅ |
| **大工具结果** | >32000 字 → 存文件 + 提示路径（SKILL.md 豁免） | >8000 字 → 存文件 + 提示路径 | 我们阈值更低（更保守），缺少 SKILL.md 豁免逻辑 |
| **security_search** | 调 Kimi API（真实搜索引擎） | 用同 LLM 接口生成 | 他们有真实搜索引擎，我们是 LLM 编知识 ⚠️ |
| **Skills 系统** | SDK 内置，Prompt YAML front matter 白名单控制 | 手写，读 SKILL.md 目录 | 功能等价，但我们没有白名单控制 |
| **强制首轮流程** | 无明确固定流程 | 有！读 Skill → 搜 writeup（难题）→ 首次探测 | **我们更强** 🟢 |
| **空转保护** | 无（靠 Observer + stale 超时） | `tool_choice="required"` + 连续 3 轮无工具调用 nudge | **我们更强** 🟢 |

**结论**：Solver 内核层面我们已经不弱，某些防御性设计（重复检测、强制流程）比 BreachWeave 还细。

---

## 三、Observer 对比

| 维度 | BreachWeave | 我们 | 差距 |
|------|------------|------|------|
| **触发机制** | 每 6 轮 + hint + agent_end | 每 6 轮 + hint + agent_end + approach 循环触发 | **我们更灵活** 🟢 |
| **防骚扰** | 3 道保险（题目完成/冷却 6 轮/内容+行为指纹去重） | 内容指纹去重（无冷却期限制） | 我们缺少冷却期 ⚠️（但换成了"不同方向不限次数"的策略） |
| **纠偏注入位置** | `deliverAs: "steer"`（SDK 特殊处理） | 下一轮开头注入 + `[OBSERVER]` 前缀 | 我们手动实现了类似效果 ✅ |
| **看板压缩** | Observer 专门负责看板压缩（12 条 memory / 8 条 ideas 上限） | 同样 12/8 上限 | 对齐 ✅ |
| **Observer 读原始对话** | `query_solver_history` 工具（读 .jsonl） | `read_file(.solver-history.jsonl)` | 功能等价 ✅ |
| **每次审查独立 session** | ✅ 无状态（每次新建 session） | ✅ 同样 | 对齐 ✅ |
| **System Prompt** | 硬编码在代码里（不是 .md 文件） | 硬编码在代码里 | 一样 ✅ |
| **矛盾检测** | 无明确规则 | 有！先 memory_update 纠正旧条目，禁止并存矛盾事实 | **我们更强** 🟢 |
| **纠偏只做方向性判断** | 无此规则 | 有！明确禁止技术性判断（踩过坑的经验） | **我们更强** 🟢 |
| **失败态精确区分** | 无 | 有！PHP highlight_file 题的态1/态2 区分 | **我们更强** 🟢（虽然是场景特化） |
| **无进展强干预** | 无（依赖 Planner 做 stale 判断） | 有！全 failed 快速路径 + 连续无进展阈值 | **我们更强** 🟢 |

**结论**：Observer 我们的设计比 BreachWeave 更精细。我们踩过的坑（误判 flag、技术性纠偏误导、纠偏被忽略）都转化成了具体规则，BreachWeave 的 Observer 更泛化但约束更少。

---

## 四、Docker / 隔离对比

| 维度 | BreachWeave | 我们 |
|------|------------|------|
| **Solver 位置** | Docker 容器（每个 Solver 独立容器） | Docker 容器 |
| **通信协议** | stdin/stdout JSONL | stdin/stdout JSONL |
| **Host Bridge** | 请求/响应 + requestId 异步匹配 | 同样 |
| **多 Solver 并发** | ✅ 同一题多个容器 | ❌ 同一题只有一个 Solver |
| **Memory 广播** | 有！变化后广播给同题所有 Solver | 不需要（单 Solver） |
| **容器内二进制** | Bun 编译的 Linux x64 二进制挂载进去 | Python 代码 volume 挂载 |
| **Init Payload** | stdin 第一行 JSON | 文件（.init_payload.json）解决 Windows pipe 问题 |

**Windows 兼容**：我们用文件传 init payload 避免 Windows Docker Desktop 的 stdin pipe 时序问题，这是工程细节上的务实解法。

---

## 五、数据层对比

| 维度 | BreachWeave | 我们 |
|------|------------|------|
| **锁机制** | mkdir 原子性（目录锁） | fcntl 文件锁（Linux）/ Windows 不锁 |
| **原子写入** | tmp + rename | 一样 ✅ |
| **Memory 追加** | 不加锁（各写各文件） | 不加锁 ✅ |
| **Ideas 去重** | content 转小写比较 | 有（idea_store 实现） |
| **前缀匹配查找** | 支持 ID 前缀查找 | 支持 ✅ |
| **Stats / 统计** | 完整统计系统（Token 消耗、耗时、按模型/prompt 分桶） | 无 |

**差距**：我们没有 Stats 统计。对比赛影响不大，但对事后分析（哪个模型效果好、每题花了多少 Token）很有价值。

---

## 六、配置与扩展性对比

| 维度 | BreachWeave | 我们 |
|------|------------|------|
| **Prompt 管理** | YAML front matter（model/skills/tools 白名单/MCP）+ resolvePromptSession 9 步流程 | settings.json + prompt 文件路径 |
| **Provider 管理** | 多 provider 注册（Anthropic/OpenAI/智谱...）+ UUID 区分同名 provider | 单一 OpenAI 兼容接口 |
| **MCP 支持** | 有 | 无 |
| **Extension 系统** | SDK 事件总线 + Extension Factory | 无（Observer 是硬编码的唯一 extension） |
| **Subagent** | 支持（单个/并行/链式 3 种模式） | 无 |

**差距**：BreachWeave 的配置系统是"框架级"的——可以给不同题目组合不同 prompt + 模型 + 工具集 + MCP server，运行时动态切换。我们是"应用级"的——改 settings.json 切换模型，prompt 文件切换 prompt，但没有运行时动态组合能力。

---

## 七、独有优势（我们有，BreachWeave 没有）

| 特性 | 说明 |
|------|------|
| **三层重复操作检测** | 命令级 + approach 级 + 目标不可达，从 curl 和 Python inline 脚本提取 URL 模式 |
| **纠偏方向性 vs 技术性区分** | 踩过 Observer 误判的坑，明确禁止技术性判断 |
| **失败态精确区分** | PHP highlight_file 题的两种失败态自动判断 |
| **矛盾检测** | Memory 里新旧事实冲突时强制先 update |
| **无进展快速路径** | 全部 idea failed → 立即强干预，不等周期 |
| **强制首轮流程** | 读 Skill → 搜 writeup（难题）→ 首次探测 |
| **`tool_choice="required"` + nudge** | 防止 LLM 空转不调工具 |
| **每 6 轮自动注入状态快照** | 不依赖 Solver 主动查询 Memory/Ideas |
| **Tsecbench 透明接入** | 环境变量驱动，代码零修改切换比赛环境 |
| **并行调度 + thread-local 隔离** | 多题并行时每题独立上下文，无状态污染 |
| **Scoreboard 实时看板** | 并行模式下实时显示各题进度 |

---

## 八、需要追赶的关键差距（按影响排序）

### 🔴 影响大，值得投入

| # | 差距 | 影响 | 建议 |
|---|------|------|------|
| 1 | **无 Planner / 无多 Solver 并发** | 同一题只有一种攻击策略在跑，BreachWeave 可以同时跑 3 种。比赛 ROI 差距可能有 2-3x | 短期：不需要 LLM Planner，但可以支持同一题启动多个 Solver（不同 prompt/模型），"谁先出 flag 算谁的" |
| 2 | **security_search 用 LLM 编知识** | 遇到冷门 CVE 或具体版本号漏洞时，LLM 编出来的信息可能是错的 | 接入真实搜索引擎（Tavily/Serper API），或至少接 RAG |
| 3 | **无 Subagent 能力** | 不能把"侦察"和"利用"拆成独立子任务并行跑 | 中期可加，但当前单 Solver 架构能跑大多数题 |

### 🟡 有差距但影响有限

| # | 差距 | 说明 |
|---|------|------|
| 4 | Extension 机制 | 我们的 Observer 是唯一 extension，硬编码挂载。如果将来要加 scope-guard 等扩展，需要重构 |
| 5 | Stats 统计 | 对事后分析有价值，但不影响比赛成绩 |
| 6 | MCP 支持 | BreachWeave 有但实际比赛也没怎么用 |
| 7 | SKILL.md 截断豁免 | 我们 8000 字阈值下 SKILL.md 大概率不超，但极端情况可能被截 |
| 8 | Web UI | 比赛用不上 |

---

## 九、总体评估

```
                        BreachWeave          我们
                       ┌─────────┐       ┌─────────┐
  架构层（Planner）     │ ████████ │       │ ██      │   差距最大
                       ├─────────┤       ├─────────┤
  Solver 内核          │ ███████  │       │ ████████ │   我们略强
                       ├─────────┤       ├─────────┤
  Observer             │ ██████   │       │ █████████│   我们明显更强
                       ├─────────┤       ├─────────┤
  Docker / 隔离        │ ████████ │       │ ██████   │   差距在多容器
                       ├─────────┤       ├─────────┤
  配置 / 扩展性        │ █████████│       │ ████     │   框架 vs 应用
                       ├─────────┤       ├─────────┤
  工程细节             │ ███████  │       │ ████████ │   并行安全/Win兼容
                       └─────────┘       └─────────┘
```

**一句话**：BreachWeave 赢在"框架化 + 多 Solver 并发 + Planner AI 调度"，我们赢在"Solver/Observer 内核的防御性设计更深"（重复检测、矛盾检测、失败态区分、方向性/技术性纠偏区分）。

---

## 十、后续开发方向（按优先级）

> 从本文分析中提取的可执行改进项，详细方案见 `优化路线图.md`。

### P0：同一题多 Solver 并发

**目标**：支持给同一道题同时启动 2-3 个 Solver（不同 prompt 或模型），谁先出 flag 算谁的。

**方案草案**：
1. Scheduler 为每题创建 N 个 Solver 实例（N 由配置控制）
2. 每个 Solver 使用不同的 prompt 文件（如 `solver-aggressive.md` + `solver-methodical.md`）
3. 共享 Memory/Ideas（已有目录锁保护），第一个提交正确 flag 后通知其他 Solver 终止
4. 需要新增 Memory 广播机制（参考 BreachWeave 的 `broadcastChallengeBoardUpdateToRunningSolvers`）

**不需要做的**：
- 不需要 LLM Planner（代码逻辑足够，比赛题目固定不需要动态调度）
- 不需要每个 Solver 独立 Docker 容器（线程隔离 + thread-local 已经够用）

### P1：security_search 接入真实搜索引擎

**目标**：用真实搜索结果替代 LLM 编造的知识。

**可选方案**：
- Tavily API（CTF 友好，有代码块提取）
- Serper API（Google 搜索代理）
- DuckDuckGo（免费，但结果质量不如前两者）
- 保留当前 LLM 方案作为 fallback（搜索 API 不可用时）

### P2：Stats 统计系统

**目标**：事后分析每题的 Token 消耗、耗时、模型效果。

**方案**：
- 每轮记录 `response.usage`（prompt_tokens / completion_tokens）
- 按题目/模型/prompt 分桶汇总
- 输出到 `workspace/<challenge_id>/stats.json`

### P3：SKILL.md 截断豁免

**目标**：bash_tool 截断时，如果输出是 `read_file` 读取的 SKILL.md 内容，不截断。

**方案**：在 `file_tools.read_file` 中对 SKILL.md 文件放宽输出上限（如 32000 字）。
