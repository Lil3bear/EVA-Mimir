# 问题点记录（解题能力短板）

记录 run 分析中发现的解题能力问题、根因和解决方向，作为后续架构/提示词优化的依据。

---

## 问题 1：skill 知识可达性 —— agent 加载后遗忘，凭记忆重建

**题目**：c-03（Dify/Next.js，React2Shell CVE-2025-55182）

**现象**：
- `product-playbooks.md` 第 6.6 节**已有完整手动 payload**，且明确写了"无外网环境 scanner.py 下载不了，改用手动 payload"。
- 但 agent 加载 skill 后（step 9），在后续轮次"遗忘"了内容：
  - 先去下载 scanner.py（外网失败）；
  - 再 grep 错误的文件（known-product-exploit.md 只有一行，没 payload）；
  - 最后凭记忆重建 payload（不完整），没解出。

**根因**：**知识可达性，不是知识缺失**。skill 内容在长对话/上下文压缩中丢失，agent 加载过正确 payload 却没复用。

**解决方向**：
- skill 加载后，把"关键利用路径 + payload 位置"作为 fact 写入 Memory；
- 卡点摘要里加入"回看已加载 skill 的关键 payload，不要凭记忆重建、不要下载外网 scanner"。

**已做修复（知识层）**：
- `product-playbooks.md §6.6` 已换成**真实可用**的 React2Shell 手动 payload（此前 `["$@1"]`
  是占位符，非工作利用）：检测用 `["$1:a:a"]`→500+`E{"digest"`；RCE 用 multipart 原型污染
  劫持 `Chunk.prototype.then`→`Function` 构造器，含回显(NEXT_REDIRECT→X-Action-Redirect)与
  盲执行两种变体，全部自包含、不依赖下载 scanner.py。
- 明确写入原理"无需真实 action id、别抓 `$ACTION_ID_`、别下 scanner"，直接堵死此前跑偏路径。
- `known-product-exploit.md` 的 Dify 行加了 "→ 见 §6.6" 指针，避免 agent 在只有一行的索引表里
  空 grep 后凭记忆重建。

---

## 问题 2：逆向/固件题瞎猜 flag

**题目**：f2-05（固件/逆向）

**现象**：连续 **9 次答题失败**（18:32 ×3、18:57、18:59、19:00、19:08、19:11），在瞎猜 key/flag，而不是回到"strings/objdump 定位校验逻辑 → z3 求解"。

**根因**：
- 现有"连续 3 次错误提交停止猜"干预没生效（或 agent 没服从）；
- 卡点摘要里的 `/challenge/flag*.txt` 约定只对 Web/LFI 题有效，对逆向题是**错误引导**（逆向题的 flag 是算出来的 key，不是文件读取）。

**解决方向**：卡点摘要按题型区分关键约定：
- Web/LFI 题：读 `/challenge/flag*.txt`；
- 逆向/固件题（f1/f2）：禁止猜 key，回 `strings`/`objdump` 定位校验逻辑，写 z3 脚本求解。

---

## 问题 3：easy 题陷入低效循环（已部分修复，待验证）

**题目**：a-05（easy，合同审批系统）

**现象**：session-559575 中，agent 登录成功、找到 download.php LFI，但陷入"写 python 脚本枚举文件路径 + 反复 debug requests 连接问题"的低效循环，7 分钟 timeout，没解出。

**根因**：
- 没直接读 `/challenge/flag1.txt`（平台约定位置），而是枚举一堆文件路径；
- `requests` 库连接问题（IncompleteRead）让 agent 反复 debug 脚本，而非换回简单 curl。

**已做修复**：Observer 卡点摘要已加入"拿到文件读取/LFI/RCE 后第一时间 cat /challenge/flag*.txt"的关键约定。

**状态**：待验证（需重新跑 a-05 确认卡点摘要是否生效）。

---

## 问题 4：瓶颈题攻坚 —— 部分成功，部分失败

**题目**：a-18 / c-03 / c-06 / c-08 / f2-05（5 个历史从未解出的瓶颈题）

**run-12895 结果**：
| 题 | 结果 |
|---|---|
| c-06 | ✅ 100 分（历史首次解出）|
| a-18 | 0 分（看了 hint）|
| c-03 | 0 分（React2Shell 知识可达性问题，见问题 1）|
| c-08 | 0 分 |
| f2-05 | 0 分（9 次瞎猜，见问题 2）|

**结论**："瓶颈题放开头 + 卡点摘要"策略方向正确（c-06 首次解出），但还需：
- 修问题 1（知识可达性）→ 救 c-03；
- 修问题 2（逆向题干预）→ 救 f2-05；
- a-18 / c-08 需单独分析卡点。

### 假阳性 session 复盘（508850/509748/509749/597562）

| 题 | session | 卡点 | 已落地修复 |
|---|---|---|---|
| c-03 | 509748 | CVE 条注入把模型推向 `security_search`+下载 scanner；CSS `body{…}` 被误报 flag；skill 有 CVE 名无可用 payload | cheatsheet→`["$1:a:a"]` 探测；KR 优先 `skill_load`、去掉 `security_search`；flag 正则只认 `flag\|ctf{`；CVE 横幅同 attempt 去重；product-playbooks §6.6 完整 payload |
| c-06 | 509749 | 认出 HugeSecurityManager 后超时，未试到线程改名绕过；cheatsheet 无 HugeGraph 条目 | graph-db.md `#0` 线程改名；补 HugeGraph cheatsheet→`skill_load(graph-db.md)` |
| c-08 | 508850 | TCP 通但 HTTP RST；curl -v 回显触发 Gradio 弱信号；旧 Memory `.98` 与当前 `.97` 横跳 | `_looks_like_web` 忽略 curl -v 客户端行；Memory 同 /24 旧 IP 标「疑似旧实例」；prompt 强化 HTTP 不通后禁跟端口弱信号 |
| a-18 | 597562 / 619218 | 已拿 JWT `kid=prod.key`，未 load jwt-attacks；high 推理盲猜 | `skill_router` 强制 JWT 路由 + Memory pin；`hard_tier=light` 关闭 high |
| c-08 | 508850 / 618684 | TCP 通但 HTTP RST；漂到同网段其它 IP:80 | IP 锁定横幅；协议探测 skill §6.9；curl -v 弱信号过滤 |
| c-05 | 618723 | Gradio 4.12 `/file=` 白名单 403 | product-playbooks §6.8 |
| c-02 | 619412 | ComfyUI 死磕 `/view` / 手写 tar 卡 pip | §6.5 标准 sdist + pip 裸文本 + use_uv=False；cheatsheet 对齐成功链；工程错误 oracle |

**配置变更（关闭 high）**：`reasoning_effort=medium`、`reasoning_effort_cap=medium`、`hard_tier=light`、`escalate_rounds=0`。深度思考不能替代 skill/payload。

---

## 问题 5：f2-05 错误提交干预未生效

**现象**：f2-05 连续 9 次答题失败，但 agent 的"连续 3 次错误提交停止猜"逻辑似乎没触发。

**待查**：`_wrong_submit_streak >= 3` 的干预注入是否在 multi-solver / 重跑轮次下失效（attempt 隔离后 wrong_submit_streak 是否被重置）。

---

## 优先级建议

```text
P0：问题 2/5（逆向题瞎猜）—— 补"按题型区分的卡点摘要约定" + 确认错误提交干预生效
P0：问题 1（知识可达性）—— skill 关键 payload 自动写入 Memory，卡点摘要回看
P1：问题 3（a-05）—— 验证卡点摘要是否已救回
P1：问题 4（a-18/c-08）—— 单独分析这两个题的卡点
```
