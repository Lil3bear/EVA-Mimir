# 尾段捞分（Salvage）— 360 分钟基准

TSecBench 全量赛程 **360 分钟（6h）**。尾段策略按 **benchmark 墙钟** 分级，并随 `SOLVER_TOTAL_TIMEOUT` 等比缩放。

## 分级（默认阈值，基于 360min）

| 阶段 | 触发（benchmark 剩余） | 行为 |
|------|------------------------|------|
| **normal** | > 140min | 常规调度 |
| **salvage** | ≤ 140min | 切断长难题；回收 easy/medium；单 agent |
| **critical** | ≤ 72min（20%） | 同上 + 跳过 0 进展 hard |
| **final** | ≤ 36min（10%） | **仅** salvage focus + 未尝试 easy/medium |

第 1 轮 retry 不进入 salvage（默认 `min_retry_round=2`）。

## 长难题 vs 简单捞分

- **结束**：b/e/f、hard、≥4 flag → `mark_abandoned`
- **捞分**：abandon / fail_streak / Connection error / 多轮 0 flag 的 **easy/medium**

## 配置

`settings.json` → `solver.salvage`：

```json
{
  "benchmark_minutes": 360,
  "salvage_remaining_min": 140,
  "critical_remaining_min": 72,
  "final_remaining_min": 36,
  "min_retry_round": 2
}
```

环境变量：

```bash
SOLVER_TOTAL_TIMEOUT=360          # 默认已改为 360
SOLVER_BENCHMARK_MINUTES=360
SOLVER_SALVAGE_REMAINING_MIN=140
SOLVER_CRITICAL_REMAINING_MIN=72
SOLVER_FINAL_REMAINING_MIN=36
```

## 日志

- `salvage_phase` — 当前阶段 + benchmark/run 剩余分钟
- `late_game_cut_long_hard` — 切断的长难题
- `salvage_focus` — 集中重试列表
- `salvage_only_filter` — final 阶段过滤后题数
