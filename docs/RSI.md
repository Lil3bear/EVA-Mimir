# RSI：Recursive Self-Improvement 本地迭代

EVA-Mimir 的 RSI 层在现有 **Prime-style per-challenge harness**（`solver/runtime/harness.py`）之上，增加 **repo 级** 的回归跑分 → 分析 → skill 改动 → 再跑 闭环。目标：在 full benchmark 之前，用维度 pack（web/pentest/binary…）验证架构与 skills，一次只改一层（skill / router / scheduler）。

## 工作流

```text
1. 选 pack（web / pentest / binary / …）
2. ./scripts/rsi_local.sh <pack> [timeout_min]
3. 读 workspace/rsi-report.md → 按 next_actions 改 skill 或 router
4. python3 -m solver.rsi record --pack web --reason "…" --files skills/web/…
5. 重复 2–4，维度稳定后再跑全量 ./run.sh
```

## 配置

| 项 | 位置 | 说明 |
|---|---|---|
| 回归题单 | `config/regression_codes.json` | 按**维度前缀**维护 pack（无默认失败题列表） |
| 开关 | `settings.json` → `rsi` | `enabled`, `auto_analyze`, `local_timeout_minutes` |
| 题号过滤优先级 | env > settings | `SOLVER_ONLY_CODES` > `rsi.only_codes` > pack |

### 环境变量

- `SOLVER_RSI_PACK` — 激活 pack 名（如 `web`、`pentest`）
- `SOLVER_ONLY_CODES` — 逗号分隔，覆盖 pack
- `SOLVER_PREFIX_FILTER` — 前缀 pack（cloud/exploit 等）

比赛模式结束时会自动写 `workspace/rsi-report.json` 并 emit `rsi_report` 事件（`rsi.auto_analyze=true`）。

## CLI

```bash
python3 -m solver.rsi list-packs
python3 -m solver.rsi codes unstable6
python3 -m solver.rsi codes web
python3 -m solver.rsi analyze --workspace ./workspace --pack web
python3 -m solver.rsi record --pack web --reason "Gradio bypass" \
  --files skills/web/references/product-playbooks.md --evidence c-05
```

## Skill 改动账本

`skills/.rsi/refinements.jsonl` 记录每次 skill 编辑（文件 hash、pack、证据题号），与 challenge 级 `memory/refinements.jsonl` 分离，便于审计与回滚对照。

## 与全量 eval 的关系

| 阶段 | 命令 | 目的 |
|---|---|---|
| 架构/路由验证 | `scripts/rsi_local.sh web` | 快反馈，单维度 |
| 单维度 | `scripts/rsi_local.sh pentest` | 多阶段渗透 |
| 不稳定簇 | `./scripts/rsi_local.sh unstable6 180` | 6 题 Web/evasion 回归 |
| 最后一公里 | `./scripts/rsi_local.sh lastmile3 180` | a-03 / b-02 / f2-05 |
|  leaderboard | `./run.sh` | 全量 6h；可选 `skip_codes` |

## 设计原则（与 ARCHITECTURE.md 一致）

1. **证据驱动** — 报告里的 `next_actions` 来自 workspace 得分 + `docs/PROBLEMS.md` 已知模式。
2. **一层一改** — 避免同时改 skill 和 scheduler 导致无法归因。
3. **medium-only 路由** — RSI 迭代优化知识可达性，不依赖 reasoning 升档。
