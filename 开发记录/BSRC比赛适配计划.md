# BSRC Agent+ 比赛适配：差距分析与实施计划

> 分析时间：2026-08-07
> 比赛关键节点：
> - 作品提交截止：8 月 16 日 23:59
> - 靶场实战：8 月 17-18 日（限两轮，每轮 360 分钟，63 题，23000 分）

---

## 一、差距分析：比赛要求 vs 当前项目

### ✅ 已具备

| 能力 | 状态 | 位置 |
|------|------|------|
| Solver Agent + 工具链 | 完成 | `solver/agent.py` + `solver/tools/` |
| Observer 旁路审查 + 纠偏 | 完成 | `solver/observer/` |
| Memory + Ideas 状态管理 | 完成 | `shared/data/` |
| TsecbenchClient API 客户端 | 完成，7 测试通过 | `solver/platform/tsecbench_client.py` |
| 多题调度器（顺序单题） | 完成，5 测试通过 | `solver/platform/scheduler.py` |
| 自动模式切换（Bridge / Tsecbench） | 完成 | `solver/main.py` |
| Docker 容器化框架 | 完成 | `docker/Dockerfile` |
| 上下文压缩 + 语义摘要 | 完成 | `solver/agent.py` |
| Web 漏洞 Skill | 完成 | `skills/web/SKILL.md` |

### ❌ 必须解决（阻塞参赛）

| # | 问题 | 影响 | 严重性 |
|---|------|------|--------|
| **B1** | **LLM API 地址硬编码，不支持平台网关改写** | 平台沙箱内无法访问外部 API，Agent 完全无法运行 | **致命** |
| **B2** | **settings.json 含硬编码 API Key** | 平台审计会公开对话记录，密钥泄露 | **致命** |
| **B3** | **Docker 镜像缺少 `docker/fastcoll`** | 镜像构建失败 | **致命** |
| **B4** | **镜像体积未评估（含 SageMath 约 2-3GB）** | 平台限制 1GB，超限无法上传 | **致命** |
| **B5** | **无 README 说明运行环境和部署方式** | 作品提交必须有，评审需要 | **高** |

### ⚠️ 应该解决（影响得分）

| # | 问题 | 影响 |
|---|------|------|
| **S1** | 只有 Web Skill，缺少 Pwn/Crypto/Cloud/Evasion 能力 | 63 题覆盖 6 个维度，只能做 Web 类 |
| **S2** | 调度器是顺序单题，平台允许同时 3 题 | 360 分钟内解题效率低 |
| **S3** | 无技术方案文档（PDF/Markdown，5000 字以内） | 作品提交必交材料 |
| **S4** | 无 Demo 视频或在线 Demo | 加分项 |
| **S5** | solver.md prompt 只针对 Web 题优化 | 非 Web 题可能表现差 |
| **S6** | 模型固定用 Claude，平台白名单里没有 Claude | 必须换模型 |

---

## 二、实施计划

### 第一优先级：致命问题修复（必须完成，否则无法参赛）

#### B1 + B2 + B6：LLM API 网关适配 + 密钥环境变量化

**平台网关改写规则**：
- 域名后增加 `.tsecbench.gw`
- 如果原 URL 是 https，改成 http
- 例：`https://api.deepseek.com/v1` → `http://api.deepseek.com.tsecbench.gw/v1`

**平台白名单模型**（约 17 项）：DeepSeek、混元、豆包、通义、Kimi、智谱、百川、MiniMax

**当前问题**：
- `settings.json` 硬编码了 `base_url` 和 `api_key`
- `solver/agent.py`、`solver/observer/agent.py`、`solver/tools/search_tool.py` 都从 settings 读 LLM 配置
- Claude 不在白名单内

**改动方案**：
1. 所有 LLM 配置完全通过环境变量注入：
   - `LLM_BASE_URL` — API 地址（平台网关地址）
   - `LLM_API_KEY` — API 密钥
   - `LLM_MODEL` — 默认模型名
   - `LLM_OBSERVER_MODEL` — Observer 模型名（可选，默认用 LLM_MODEL）
2. `solver/main.py` 的 `_load_settings_from_env()` 已支持，确认覆盖了所有使用点
3. `settings.json` 中的密钥替换为占位符，添加 `.gitignore`
4. 选择白名单模型：推荐 **DeepSeek-V3** 或 **Qwen-Max**（推理能力强，支持 function calling）

**改动文件**：
- `solver/agent.py` — 确认从 settings 读取，不硬编码 fallback URL
- `solver/observer/agent.py` — 同上
- `solver/tools/search_tool.py` — 同上
- `settings.json` — 移除硬编码密钥
- `.gitignore` — 确认 settings.json 策略

#### B3：fastcoll 二进制

**方案**：在 WSL 中编译 fastcoll linux/amd64 二进制，放到 `docker/fastcoll`。
或者改 Dockerfile 在构建时从源码编译（但会增加构建时间和镜像体积）。

#### B4：Docker 镜像瘦身到 1GB 以下

**当前镜像预估体积**：
- ubuntu:22.04 base: ~80MB
- Python3 + pip: ~200MB
- nmap + gdb + gcc + binutils: ~300MB
- SageMath: ~1.5-2GB ← **这是超限的主因**
- sqlmap + pwntools + 其他: ~200MB

**瘦身方案**：
1. **移除 SageMath**（节省 ~1.5GB）— Crypto 能力降级，但比赛的 Crypto 题不一定需要 SageMath
2. **移除 gdb/gdbserver**（节省 ~50MB）— Pwn 调试可用 pwntools 替代
3. **移除 nmap**（Solver prompt 已禁止 nmap）
4. **用 python3-slim 或 multi-stage build**
5. **合并 RUN 层，清理 apt cache**
6. 目标：控制在 **800MB** 以下（gzip 后 ~400-500MB）

#### B5：README

**内容**：运行环境要求、环境变量说明、本地测试方法、Docker 构建和部署、架构简介。

---

### 第二优先级：得分优化

#### S1：扩展题目类型覆盖

63 题覆盖 6 维度：Web、二进制、漏洞利用、多阶段渗透、云攻击、对抗规避

**可快速扩展的能力**：
- **二进制/Pwn**：pwntools 已在镜像内，新增 `skills/pwn/SKILL.md` prompt 指南
- **多阶段渗透**：本质是多步 Web + 提权，prompt 可覆盖
- **对抗规避**：WAF bypass、编码绕过等，prompt 可覆盖

**需要更多工作的**：
- **云攻击**：需要 AWS CLI、kubectl 等工具，prompt 需要云安全知识
- **Crypto**：没有 SageMath 后能力有限，但简单的编码、hash、RSA 可以靠 Python

#### S2：并行调度（可选）

改 Scheduler 为并行模式，同时启动 3 题，用 ThreadPoolExecutor。
但需要注意 LLM API 并发限制。

#### S6：模型选择

平台白名单推荐：
1. **DeepSeek-V3 / DeepSeek-Coder**：推理能力强，安全知识丰富，function calling 支持好
2. **Qwen-Max（通义）**：中文理解好，工具调用稳定
3. **GLM-4（智谱）**：备选

需要测试 function calling 的兼容性（当前 OpenAI SDK 的 tools 格式是否被这些模型支持）。

---

## 三、技术方案文档大纲（5000 字以内）

```
1. 项目概述（300字）
   - CTF Agent：基于 LLM 的自动化攻防 Agent
   - 核心能力：自动解题、多题调度、自适应纠偏

2. 技术架构（800字 + 架构图）
   - 双层架构：Scheduler → SolverAgent
   - Solver + Observer 双角色设计
   - Memory + Ideas 状态管理
   - 工具链：bash、file、search、bridge_tools
   - Tsecbench API 透明接入

3. 核心算法与方法（1500字）
   - ReAct 循环（推理→行动→观察）
   - Observer 旁路审查机制（防死循环、防误判）
   - 语义上下文压缩（解决长题丢上下文问题）
   - 重复操作检测（命令级 + approach 级）
   - 目标不可达协议
   - 多题调度策略（难度排序、生命周期管理）

4. 实验结果（800字）
   - 本地 CTF 平台测试成绩
   - Tsecbench 跑分结果（如有）
   - 各能力维度覆盖情况

5. 创新点总结（600字）
   - Observer 双角色设计（业界少见）
   - 方向性纠偏 vs 技术性纠偏的区分
   - Memory + Ideas 看板的持久化和跨轮次复用
   - 失败态区分机制
   - approach-level 循环检测
```

---

## 四、执行顺序

| 步骤 | 内容 | 预计工时 | 优先级 |
|------|------|----------|--------|
| 1 | LLM 配置环境变量化 + 移除硬编码密钥 | 1h | P0 |
| 2 | Dockerfile 瘦身（去 SageMath/nmap/gdb） | 2h | P0 |
| 3 | 编译或获取 fastcoll 二进制 | 1h | P0 |
| 4 | 模型切换测试（DeepSeek/Qwen function calling） | 3h | P0 |
| 5 | README 编写 | 1h | P0 |
| 6 | 扩展 Skills（Pwn/渗透/云） | 4h | P1 |
| 7 | 技术方案文档 | 3h | P1 |
| 8 | 本地端到端测试 | 2h | P1 |
| 9 | Demo 视频录制 | 1h | P2 |
| 10 | 并行调度（可选） | 3h | P2 |

---

## 五、立即开始：步骤 1
