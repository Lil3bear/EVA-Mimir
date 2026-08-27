# EVA-Mimir — 自动化 CTF 攻防 Agent

基于大语言模型的自动化 CTF 解题 Agent，支持 Web 漏洞挖掘、多阶段渗透等多种攻防场景。

## 架构

```
Scheduler ── policy / portfolio / task builder
    │
    ├── SolverAgent ── context window / recovery / tool runner
    │       │
    │       ├── ToolRegistry ── builtin tools + opt-in plugins
    │       └── execution journal / per-attempt RunContext
    │
    └── ObserverAgent ── 独立控制面与 Memory/Ideas 看板

共享边界：线程安全 JSONL、原子提交状态、题目级共享目录、Attempt 私有目录
```

**核心特性**：
- **Solver + Observer 双角色设计**：Solver 专注推进解题，Observer 旁路审查防止死循环
- **Memory + Ideas 看板**：持久化当前题目/重试轮次状态，复用已验证事实而不注入历史题目解法
- **合规经验库**：只保留不含题号、答案、地址、凭据和历史攻击链的通用验证原则；运行时不会注入历史题目解法。
- **submit 证据门**：flag 必须曾在工具输出中出现才允许提交，拦截纯猜测（防 f2-05 式连错）
- **语义上下文压缩**：解决长题目上下文丢失问题
- **approach-level 循环检测**：自动检测重复攻击模式并告警
- **Tsecbench 平台透明接入**：自动检测比赛环境变量，无缝切换

## 工具扩展

Solver 工具使用一个显式 ABI：插件模块导出 `TOOLS: list[ToolSpec]`，每个条目同时绑定 OpenAI tool definition 与 executor，注册时会拒绝缺失名称或重复名称。

```python
from solver.tools.registry import ToolSpec

TOOLS = [ToolSpec(MY_TOOL_DEF, execute)]
```

在配置中启用：`"solver": {"tool_plugins": ["my_package.my_tools"]}`。插件只在明确配置后加载，内置工具与插件走同一个参数校验、执行日志和恢复路径。

## 运行环境

- Python 3.10+
- Docker（本地模式需要）
- 支持 OpenAI API 兼容接口的 LLM 服务

## 环境变量

### 必需（比赛模式 / Tsecbench 平台自动注入）

| 变量 | 说明 |
|------|------|
| `BENCHMARK_BASE_URL` | Tsecbench 平台 API 地址 |
| `BENCHMARK_TOKEN` | Tsecbench 平台认证令牌 |

### LLM 配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_BASE_URL` | LLM API 地址 | — |
| `LLM_API_KEY` | LLM API 密钥 | — |
| `LLM_MODEL` | 默认模型名称 | `deepseek-v4-flash` |
| `LLM_OBSERVER_MODEL` | Observer 模型名称 | 同 `LLM_MODEL` |
| `LLM_GATEWAY` | 托管模式：自动改写 LLM 地址到 `.tsecbench.gw` 网关（`1/true/yes/on`） | 关 |

### 可选

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SOLVER_MAX_ROUNDS` | 每题最大推理轮次（未设置时按难度/题型动态分配） | `动态 30–240` |
| `SOLVER_OBSERVER_EVERY` | Observer 审查间隔（轮，未设置时按难度动态分配） | `动态 8–15` |

## 快速开始

### 1. 构建 Docker 镜像

```bash
# 确保 docker/fastcoll 存在（linux/amd64 二进制）
docker build -t eva-mimir -f docker/Dockerfile .
```

### 2. 本地测试（单题模式）

```bash
# 设置环境变量
export LLM_BASE_URL="https://api.deepseek.com/v1"
export LLM_API_KEY="your-api-key"
export LLM_MODEL="deepseek-v4-flash"

# 运行
python -m host.main --challenge challenges/example.json
```

### 3. Tsecbench 比赛模式

当 `BENCHMARK_TOKEN` 和 `BENCHMARK_BASE_URL` 存在时，Agent 自动进入比赛模式：

```bash
# 平台会自动注入这两个变量
export BENCHMARK_BASE_URL="http://..."
export BENCHMARK_TOKEN="..."
export LLM_GATEWAY="1"          # 托管模式：自动改写 LLM 地址到网关
export LLM_BASE_URL="https://api.deepseek.com/v1"   # 无需手改，会被自动改写成 http://api.deepseek.com.tsecbench.gw/v1
export LLM_API_KEY="your-api-key"
export LLM_MODEL="deepseek-v4-flash"

# 直接启动
python -m solver.main
```

### 4. 打包上传

```bash
docker save -o agent.tar eva-mimir:latest
gzip agent.tar
# 上传 agent.tar.gz（需 < 1GB）
```

### 5. 赛后复盘（合规模式）

只将抽象的、与题号无关的工具改进和验证原则写入 Skills。不要把题号、flag、地址、凭据或具体历史攻击链复制回镜像；评测运行时不会读取历史题目解法。

## 平台网关适配（托管运行模式）

托管运行模式下，沙箱内无法访问公网，所有大模型 API 地址必须走平台网关。规则：

- 域名后增加 `.tsecbench.gw` 后缀
- `https` 改成 `http`

示例：
```
原地址：https://api.deepseek.com/v1
改后：  http://api.deepseek.com.tsecbench.gw/v1
```

代码已内置**自动改写**：托管模式设置环境变量 `LLM_GATEWAY=1` 后，
`LLM_BASE_URL`（含 `search_llm`）会被自动改写成网关地址，无需手动拼域名：

```bash
export LLM_GATEWAY="1"
export LLM_BASE_URL="https://api.deepseek.com/v1"   # 自动 → http://api.deepseek.com.tsecbench.gw/v1
export LLM_API_KEY="your-api-key"
export LLM_MODEL="deepseek-v4-flash"
```

也可不设 `LLM_GATEWAY`，直接把 `LLM_BASE_URL` 写成网关地址（两种方式任选其一）。
本地模式不设置 `LLM_GATEWAY`，保持直连即可。

托管模式运行时需要配置的环境变量：

| 变量 | 说明 |
|------|------|
| `BENCHMARK_TOKEN` / `BENCHMARK_BASE_URL` | 平台自动注入，无需手动填写 |
| `LLM_API_KEY` | 你的大模型 API Key（从平台页面配置，勿打入包内） |
| `LLM_MODEL` | `deepseek-v4-flash`（推荐） |
| `LLM_GATEWAY` | `1`（启用自动网关改写） |

## 项目结构

```
EVA-Mimir/
├── solver/              # Solver Agent（容器内运行）
│   ├── agent.py         # 主循环：ReAct + 工具调用
│   ├── main.py          # 入口：自动检测运行模式
│   ├── runtime/         # 上下文、日志、恢复、配置与工具执行
│   ├── observer/        # Observer 旁路审查
│   │   ├── agent.py     # Observer 审查逻辑
│   │   ├── loop.py      # 触发控制
│   │   └── tools.py     # Observer 专用工具
│   ├── ctfplatform/     # Tsecbench 平台接入
│   │   ├── tsecbench_client.py  # API 客户端
│   │   ├── scheduler.py         # 生命周期编排
│   │   ├── policy.py            # 排序与题型策略
│   │   └── task_builder.py      # Agent task 构建
│   └── tools/           # Solver 工具链
│       ├── registry.py      # 工具 ABI 与插件入口
│       ├── bash_tool.py     # Shell 命令执行
│       ├── bridge_tools.py  # 平台交互（submit/hint/state）
│       ├── file_tools.py    # 文件操作
│       ├── search_tool.py   # 安全知识搜索
│       └── ...
├── host/                # Host 主进程（本地模式）
├── shared/              # 共享数据模型
├── prompts/             # Solver/Observer 提示词
├── skills/              # 题目类型指南
│   └── experiences/references/case-notes.md       # 不含题号/答案的通用复盘原则
├── docker/              # Docker 构建文件
├── tests/               # 单元测试
├── challenges/          # 题目配置文件
└── harvest_attack_chains.py  # 仅供人工复盘；不得将题目专属解法重新打包
```

## 测试

```bash
PYTHONPATH=. pytest -q
# 或：python -m unittest discover tests/ -v
```

## 支持的 LLM

通过平台白名单验证的模型：

- DeepSeek（deepseek-v4-flash / deepseek-v4-pro）
- 通义千问（qwen-max / qwen-plus）
- 智谱 GLM（glm-4）
- 豆包、Kimi、百川、MiniMax 等

使用 OpenAI API 兼容接口，通过 `LLM_BASE_URL` 指定。

## License

MIT
