# CTF Agent — 自动化 CTF 攻防 Agent

基于大语言模型的自动化 CTF 解题 Agent，支持 Web 漏洞挖掘、多阶段渗透等多种攻防场景。

## 架构

```
┌─ Scheduler（多题调度器）────────────────────┐
│  VPN检测 → 列题 → 按难度排序 → 逐题调度     │
└────────────────────────────────────────────┘
         ↓ 每道题
┌─ SolverAgent（解题主循环）─────────────────┐
│  ReAct 循环：推理 → 工具调用 → 观察         │
│  工具：bash / curl / file / grep / search  │
│  Memory + Ideas 状态管理                    │
└────────────────────────────────────────────┘
         ↕
┌─ ObserverAgent（旁路审查）────────────────┐
│  每 6 轮自动审查                            │
│  方向性纠偏 / 死循环检测 / 看板维护          │
└────────────────────────────────────────────┘
```

**核心特性**：
- **Solver + Observer 双角色设计**：Solver 专注推进解题，Observer 旁路审查防止死循环
- **Memory + Ideas 看板**：持久化状态管理，跨轮次复用攻击经验
- **语义上下文压缩**：解决长题目上下文丢失问题
- **approach-level 循环检测**：自动检测重复攻击模式并告警
- **Tsecbench 平台透明接入**：自动检测比赛环境变量，无缝切换

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
| `LLM_MODEL` | 默认模型名称 | `deepseek-chat` |
| `LLM_OBSERVER_MODEL` | Observer 模型名称 | 同 `LLM_MODEL` |

### 可选

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SOLVER_MAX_ROUNDS` | 每题最大推理轮次 | `100` |
| `SOLVER_OBSERVER_EVERY` | Observer 审查间隔（轮） | `6` |

## 快速开始

### 1. 构建 Docker 镜像

```bash
# 确保 docker/fastcoll 存在（linux/amd64 二进制）
docker build -t ctf-agent -f docker/Dockerfile .
```

### 2. 本地测试（单题模式）

```bash
# 设置环境变量
export LLM_BASE_URL="https://api.deepseek.com/v1"
export LLM_API_KEY="your-api-key"
export LLM_MODEL="deepseek-chat"

# 运行
python -m host.main --challenge challenges/example.json
```

### 3. Tsecbench 比赛模式

当 `BENCHMARK_TOKEN` 和 `BENCHMARK_BASE_URL` 存在时，Agent 自动进入比赛模式：

```bash
# 平台会自动注入这两个变量
export BENCHMARK_BASE_URL="http://..."
export BENCHMARK_TOKEN="..."
export LLM_BASE_URL="http://api.deepseek.com.tsecbench.gw/v1"
export LLM_API_KEY="your-api-key"

# 直接启动
python -m solver.main
```

### 4. 打包上传

```bash
docker save -o agent.tar ctf-agent:latest
gzip agent.tar
# 上传 agent.tar.gz（需 < 1GB）
```

## 平台网关适配

Tsecbench 平台沙箱内无法直接访问公网，LLM API 地址需按以下规则改写：

- 域名后增加 `.tsecbench.gw`
- `https` 改成 `http`

示例：
```
原地址：https://api.deepseek.com/v1
改后：  http://api.deepseek.com.tsecbench.gw/v1
```

通过 `LLM_BASE_URL` 环境变量传入改写后的地址即可，**代码中无需任何修改**。

## 项目结构

```
CTF-agent/
├── solver/              # Solver Agent（容器内运行）
│   ├── agent.py         # 主循环：ReAct + 工具调用
│   ├── main.py          # 入口：自动检测运行模式
│   ├── observer/        # Observer 旁路审查
│   │   ├── agent.py     # Observer 审查逻辑
│   │   ├── loop.py      # 触发控制
│   │   └── tools.py     # Observer 专用工具
│   ├── platform/        # Tsecbench 平台接入
│   │   ├── tsecbench_client.py  # API 客户端
│   │   └── scheduler.py         # 多题调度器
│   └── tools/           # Solver 工具链
│       ├── bash_tool.py     # Shell 命令执行
│       ├── bridge_tools.py  # 平台交互（submit/hint/state）
│       ├── file_tools.py    # 文件操作
│       ├── search_tool.py   # 安全知识搜索
│       └── ...
├── host/                # Host 主进程（本地模式）
├── shared/              # 共享数据模型
├── prompts/             # Solver/Observer 提示词
├── skills/              # 题目类型指南
├── docker/              # Docker 构建文件
├── tests/               # 单元测试
└── challenges/          # 题目配置文件
```

## 测试

```bash
python -m unittest discover tests/ -v
```

## 支持的 LLM

通过平台白名单验证的模型：

- DeepSeek（deepseek-chat / deepseek-coder）
- 通义千问（qwen-max / qwen-plus）
- 智谱 GLM（glm-4）
- 豆包、Kimi、百川、MiniMax 等

使用 OpenAI API 兼容接口，通过 `LLM_BASE_URL` 指定。

## License

MIT
