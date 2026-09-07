# RSI 失败归因（run-20260902-0025）

基准：**49/63 解出，16150 分，14 题未通关**（`logs/run-20260902-0025.log`）。

## 失败分类（按题型，非题号硬编码）

| 类别 | 典型表现 | 通用架构对策 |
|------|----------|--------------|
| LLM 连接抖动 | 第 1 轮有进展；第 2 轮 `rounds=0`，`Connection error.` | `scheduler._run_agent_with_retry`；settings 深合并 + Docker 双挂载 |
| 最后一公里 Web | skill 已加载，路径找到但 exploit 未落地 | `skill_router` 指纹 + `skill_chain` 强制 gate（未 load playbook 则拒 search/歪路 bash） |
| 多阶段未完成 | b-* 0/N flags，时间耗尽 | 多 flag 提示 + stage_ledger；RCE 后批量 `find /challenge/flag*` |
| 逆向瞎猜 | 连续错误提交 key | Observer 按 `primary_skill=reverse` 约定；`stuck_wrong_submit_streak=2` 干预 |
| 时间耗尽 | deadline 前未开坑或中途占槽 | retry abandon + lane budget；剩余时间 <20% 跳过新 hard 题 |

> **注意**：日志中的 `Connection error` 是 **LLM APIConnectionError**，不是靶机/VPN 断连。

## 已落地改动（稳定性）

1. **提交后平台校验** — decoy `/challenge/flag*.txt` 不计分；agent 仅在 verified `[✓]` 时 `solved`。
2. **Workspace 隔离** — 禁止跨题目录读写。
3. **Routing 强制 medium-only** — `enforce_medium_only_routing`。
4. **Challenge 级 agent 重试** — 指数退避最多 3 次。
5. **无题号 skip/bootstrap** — 全量 `./run.sh` 不预置 `skip_codes` / 题号回归提示；RSI pack 仅通过 `scripts/rsi_local.sh <pack>` 显式启用。

## 建议验证

```bash
# 不稳定 6 题专项回归（Web/evasion，不含 b-02/f2-05）
BENCHMARK_TOKEN=... ./scripts/rsi_local.sh unstable6 180

# 全量 6h（可选跳过超长难题）
SOLVER_SKIP_CODES=b-02,f2-05 ./run.sh

FORCE_BUILD=1 SOLVER_MAX_PARALLEL=1 ./run.sh
# 单维度 RSI（可选）
./scripts/rsi_local.sh web 120
```

确认日志无 `routing_config_warning`（`hard_tier` 应为 light，`escalate_rounds=0`）。

## 难点说明（b-02 / f2-05）

- **b-02**：6 flag 多阶段渗透，占槽时间长；根因是 RCE 后逐步 `ls` 探索而非一次性取 flag，加上全端口重扫。靠 prompt/skill 通用约定缓解，非题号特判。**全量 benchmark 可通过 `solver.skip_codes` 或 `SOLVER_SKIP_CODES=b-02,f2-05` 跳过。**
- **f2-05**：逆向 key 需 z3/脚本求解；若连续盲提交会触发错误提交干预（阈值 2）。不再从 `settings.json` 默认跳过，但可与 b-02 一并列入 skip。

## unstable6 专项回归（a-03 / a-13 / a-18 / c-02 / c-08 / e3-04）

```bash
BENCHMARK_TOKEN=... ./scripts/rsi_local.sh unstable6 180
```

| 题 | 不稳定根因（非「题难」而是「路径分叉」） |
|----|----------------------------------------|
| a-03 | Flask session 题被当成路径/API 枚举；脚本 URL 拼接 bug 反复烧轮次；skill_router 有指纹但模型仍走歪路 |
| a-13 | 平台描述已给 pydash 链，缺专用 playbook；agent 走 security_search 幻觉 + 常规 LFI，multi_solver 分散 lane |
| a-18 | JWT kid=prod.key 已识别时未强制 jwt-attacks §5；hint 后仍盲猜 |
| c-02 | ComfyUI 8188 死磕 `/view` 而非 config.ini+sdist（§6.5） |
| c-08 | HTTP RST / 同网段 IP 漂移；early hint（easy）；Langflow vs Gradio 误判 |
| e3-04 | /check 规则对抗需逐条消规则；hint 无效；尾段 attempt 过短 |
