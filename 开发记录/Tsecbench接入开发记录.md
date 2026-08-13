# Tsecbench 接入开发记录

> 开始时间：2026-08-07
> 项目路径：`D:\AgentProjectPractice\CTF-agent`

## 当前状态

- 已阅读官方接入页：`https://tsecbench.zc.tencent.com/#integration`
- 官方提供三种接入方式：提示词、Python SDK、HTTP API。
- 本项目保留 Solver + Observer + Memory 的现有架构，采用 HTTP API 方式接入，避免把解题流程交给平台 SDK。
- 上一轮已修复 Solver 无初始化文件时的错误回退，并为 Docker 构建增加 `fastcoll` 缺失前置检查。
- 已新增 `tests/test_startup.py`，当前 2 个启动测试通过；Python 编译检查通过。
- 当前 Docker 镜像仍缺少 `docker/fastcoll`，Docker Desktop 也尚未启动，容器构建尚未验证。

## 官方环境与鉴权

- 平台注入：`BENCHMARK_BASE_URL`、`BENCHMARK_TOKEN`。
- 所有平台 API 使用请求头：`BENCHMARK_TOKEN: <token>`。
- VPN 预检必须先请求 `http://10.0.100.58`，响应 JSON 的 `status` 必须为 `ok`。
- 靶场地址由启动接口返回，通常是 VPN 内的 `IP:端口`，不能把平台地址当作靶场地址。

## 官方 API

```text
GET  {BASE_URL}/openapi/v1/challenges
POST {BASE_URL}/openapi/v1/challenges/start?unique_code=<code>
GET  {BASE_URL}/openapi/v1/challenges/hint?unique_code=<code>
POST {BASE_URL}/openapi/v1/challenges/submit
POST {BASE_URL}/openapi/v1/challenges/close?unique_code=<code>
```

提交请求体：

```json
{"unique_code": "<code>", "flag": "<flag>"}
```

关键返回字段：

- 列题：`unique_code`、`description`、`difficulty`、`level`、`flag_count`、`correct_flag_count`、`is_completed`、`container_status`、`container_addr`
- 启动：`unique_code`、`container_addr`
- 提示：`unique_code`、`hint`
- 提交：`correct`、`awarded`、`cumulative_score`、`correct_flag_count`、`total_flag_count`、`matched_flag_index`
- 关闭：`unique_code`、`closed`

## 错误处理约定

- `task_not_found`：Token 无效或缺失，立即停止。
- `challenge_not_found`：题目编号错误，跳过该题。
- `invalid_state`：任务结束、活跃题目达到上限或通关后请求 Hint，需要结合 message 判断。
- `duplicate`：Flag 已计分，不重复提交。
- `resource_unavailable`：靶场不可用，可短暂重试。
- `internal_error`：最多重试一次后停止或换题。

## 本轮实现边界

第一阶段只实现可独立测试的 `TsecbenchClient`：VPN 检测、列表、启动、Hint、提交、关闭、统一鉴权和错误类型。暂不猜测 Agent 多题调度策略，也不删除现有本地 Host Bridge。

## 第一阶段实现结果

完成时间：2026-08-07

- 新增 `solver/platform/tsecbench_client.py`。
- 新增 `solver/platform/__init__.py`，统一导出客户端、数据模型和异常。
- `TsecbenchClient.from_env()` 从官方环境变量创建客户端。
- `TsecbenchClient.is_configured()` 用于检测比赛环境是否配置完整。
- 已实现 `check_vpn()`、`list_challenges()`、`start_challenge()`、`get_hint()`、`submit_flag()`、`close_challenge()`。
- 已实现题目、启动、提示、提交、关闭和 VPN 返回数据模型。
- 已实现业务错误、422 校验错误、非 JSON 响应和网络错误映射。
- 根目录 `requirements.txt` 已补充 `requests>=2.31.0`。
- 新增 `tests/test_tsecbench_client.py`。
- 当前测试结果：7 个测试通过；`compileall` 通过；客户端公共导入通过。

下一阶段：设计多题调度器，明确 `unique_code` 的生命周期，再把 Tsecbench 后端接入 `challenge_*` 工具。现有本地 Host Bridge 在此之前保持不变。

## 第二阶段实现结果

完成时间：2026-08-07

### 新增文件

- **`solver/platform/scheduler.py`** — 多题调度器
  - `Scheduler` 类：VPN 检测 → 列题 → 按难度排序 → 逐题 start → SolverAgent.run → close
  - `_sort_challenges()`：按难度升序排列（easy → medium → hard），同难度按 unique_code 字典序
  - `_build_task_from_challenge()`：从平台 Challenge 数据构建 SolverAgent 的 task 文本，含靶场地址、难度、描述、多 flag 提示
  - `SchedulerResult` / `SchedulerReport`：单题结果和最终报告数据模型
  - `_default_agent_factory()`：默认 SolverAgent 工厂，延迟导入避免循环依赖
  - `agent_factory` 参数：支持测试时注入 mock agent
  - `close_all_active()`：异常退出时清理所有已启动的题目
- **`tests/test_scheduler.py`** — 调度器测试（7 个测试用例）
  - `SortChallengesTests`：难度排序
  - `BuildTaskTests`：task 文本生成（含 container_addr、多 flag、无地址）
  - `SchedulerTests`：跳过已完成题目、完整解题流程、InvalidState 错误处理

### 修改文件

- **`solver/main.py`** — 入口重构为双模式
  - `main()` 检测 `BENCHMARK_TOKEN` + `BENCHMARK_BASE_URL`：
    - 存在 → `_run_tsecbench_mode()`：创建 TsecbenchClient + Scheduler，遍历所有题目
    - 不存在 → `_run_bridge_mode()`：原有 Host Bridge 单题模式（完全不变）
  - `_load_settings_from_env()`：从 settings.json + 环境变量加载 LLM/Solver 配置
  - Tsecbench 模式结束后输出比赛报告（总题数、解出、部分完成、失败、累计得分）
- **`solver/platform/__init__.py`** — 新增导出 `Scheduler`、`SchedulerReport`、`SchedulerResult`

### 数据流（Tsecbench 模式）

```
solver/main.py
  └─ _run_tsecbench_mode()
       └─ Scheduler.run_all()
            ├─ client.check_vpn()
            ├─ client.list_challenges()
            └─ for challenge in sorted_todo:
                 ├─ client.start_challenge(code)
                 ├─ bridge_tools.configure_tsecbench(client, code)
                 ├─ SolverAgent(task).run()
                 │    └─ challenge_submit_flag → bridge_tools → _request_tsecbench → client.submit_flag
                 │    └─ challenge_get_hint   → bridge_tools → _request_tsecbench → client.get_hint
                 │    └─ challenge_get_state  → bridge_tools → _request_tsecbench → client.list_challenges
                 ├─ client.close_challenge(code)
                 └─ bridge_tools.clear_tsecbench()
```

### 未改动（保持不变）

- `solver/tools/bridge_tools.py` — 第一阶段已实现 `_request_backend()` 双通道分发、`configure_tsecbench()` 和 `clear_tsecbench()`，本轮无需修改
- `solver/agent.py` — SolverAgent 不感知运行模式，通过 bridge_tools 透明切换后端
- `host/main.py` — 本地模式入口保持不变
- `solver/platform/tsecbench_client.py` — API 客户端保持不变

### 测试结果

- 全部 14 个测试通过（7 client + 2 startup + 5 scheduler 新增 = 14）
- `compileall` 全量编译通过

### 已知限制

- 当前为**顺序单题模式**，一次只解一道题。平台允许同时启动 3 题，后续可扩展为并行调度
- 调度器不会主动调用 `get_hint`（由 SolverAgent 在需要时调用），避免自动扣分
- task 文本中的 flag_format 硬编码为 `flag{...}`，因平台未返回 flag 格式字段
- Tsecbench 模式下不走 Docker 容器（直接在当前进程运行 SolverAgent），适合比赛环境的容器化部署

## API 接入实测

完成时间：2026-08-08

### 测试结果

使用 `tests/test_api_live.py` 对真实 Tsecbench 平台进行连通性测试，**全部 5 个接口验证通过**：

| 接口 | 结果 | 备注 |
|------|------|------|
| VPN 检测 | ⚠️ 未连通 | VPN 未连接，但不阻塞平台 API |
| `GET /challenges` | ✅ 通过 | 返回 63 道题，总分 23000 |
| `POST /challenges/start` | ✅ 通过 | 选 a-05 (easy)，返回容器地址 `10.0.188.136:80` |
| `GET /challenges/hint` | ✅ 通过 | 返回提示内容 |
| `POST /challenges/close` | ✅ 通过 | 容器正常关闭 |

### 题目概况

- **总题数**：63 道
- **总分**：23000 分
- **难度分布**：easy 9 / medium 25 / hard 29
- **题目分组**：e 系列（WAF/沙箱绕过）、a 系列（常规 Web）、b 系列（渗透链，多 flag）、c 系列（基础漏洞）、d 系列、f 系列
- **关键发现**：平台 API 不需要 VPN 即可访问，VPN 仅用于连接靶场容器（`container_addr`）

### Bug 修复

- `tests/test_api_live.py`：新增 `io.TextIOWrapper` 包装 stdout/stderr，修复 Windows GBK 终端输出 emoji（✅⚠️❌🔲）时的 `UnicodeEncodeError`

### 注意事项

- ⚠️ 测试中获取了 a-05 的 hint，后续提交该题 flag 会按 `hint_cost_radio` 扣分
- VPN 仅在需要访问 `container_addr`（靶场容器）时才需要连接
- 平台 token `5008ff7a-9f0f-4751-9d5a-584771edaa2a` 对应当前跑分任务

## 下一阶段计划

- ~~比赛环境实测：连接 VPN、验证完整流程~~ → ✅ API 层已验证
- ~~并行调度：同时启动最多 3 题，利用平台并发上限~~ → ✅ 信号量控制已实现
- ~~第一轮实战~~ → ❌ 0 分，详见 `开发记录/第一轮实战复盘.md`
- **重要变更**：`solver/platform/` 已重命名为 `solver/ctfplatform/`
- 下次实战前先跑单题验证完整链路
- Hint 策略：根据题目难度和已用轮次自动决定是否调用 get_hint
- Docker 镜像适配：当前确认 Docker Desktop 无法访问 VPN，改用 WSL 直接跑
