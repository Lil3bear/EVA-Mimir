# 第六轮复盘 — 四题分析与 prompt/skill 补强

> 时间：2026-08-12
> 基于：第六轮实战日志（run_log_round6.txt）
> 触发：用户要求分析 c-01/c-02/c-03/c-09 失败原因，以及 b-01/b-02/b-03 多阶段渗透卡点

---

## 一、C 类漏洞利用题（c-01/c-02/c-03/c-09）

### c-01：1Panel CVE-2024-39907

**卡点**：安全入口码（entrance code）无法获取
- Solver 猜了 15+ 轮入口码，全部零进展
- `challenge_get_state` 返回 URL 为**空**（实例未分配 URL）
- 尝试了 175.178.8.209:34587（缓存 target.txt）和 10.0.185.130:10086（旧实例），均不可达

**根因**：平台问题——实例 URL 为空。非 Solver 能力问题。

**解决**：需 `challenge_start` 重启获取新实例 URL。

---

### c-02：ComfyUI-Manager 配置注入

**卡点**：db_mode 注入时，Solver 只试了 `%0a`（LF），从未试 `%0d`（CR）
- Solver 在本地 Python 验证了 `\r` CR 注入可行
- 但 curl 实际发出的是 `%0a`（LF），`write_config` 把 LF 转成 tab 续行，无法落盘独立键
- 重启端点 `/manager/reboot`（无 `/api` 前缀）也多次被忽略

**根因**：Solver "知行不合一"——本地验证了 CR 可行，但 curl 命令里用错了编码。

**修复**：
1. `prompts/solver.md`：新增 `## 配置文件注入时 CR vs LF` 规则
2. `skills/web/SKILL.md`：新增 `### 6.5 ComfyUI-Manager 配置注入（CR 字节绕过）`

---

### c-03：Dify React2Shell RCE

**卡点**：两个实例版本不同
- 实例1（10.0.185.129:3000）：同主机有 c-06 HugeGraph(8080)，用 HugeGraph RCE 拿到 flag ✅
- 实例2（10.0.185.130:3000）：c-06 实例已关闭，只能直攻 React2Shell → 307→500 失败 ❌

**根因**：Dify 版本差异导致 React2Shell 漏洞在不同实例上表现不同。实例1 是"运气好"——同主机有更容易 exploit 的 HugeGraph。

**修复**：
1. `skills/web/SKILL.md`：新增 `### 6.6 Dify / React2Shell (CVE-2025-55182) 多版本利用`
2. `prompts/solver.md`：中间件表中新增 Dify/Next.js 行，引导先扫同主机其他端口
3. 指纹表新增 Dify 行

---

### c-09：OFBiz Groovy 沙箱绕过

**卡点**：登录 bypass 没正确执行
- Solver 尝试了多次 `requirePasswordChange=Y` 但没正确携带 session cookie
- Observer 明确指出 "admin/ofbiz 登录成功" 是误报
- Groovy 黑名单拦截 `System`/`execute`/`println`/`Runtime`/`ProcessBuilder`/`cmd`/`class`

**根因**：CVE-2023-51467 认证绕过流程不完整——Solver 不知道 login + requirePasswordChange=Y 后要保存 JSESSIONID cookie 再访问 ProgramExport。

**修复**：
1. `skills/web/SKILL.md`：重写 `### 5.2 OFBiz CVE-2023-51467 认证绕过 + ProgramExport RCE`
2. 新增完整登录绕过流程（`-c /tmp/sess_ofbiz.jar` 保存 cookie）
3. 新增 4 个 payload 变体 + 关键陷阱说明

---

## 二、B 类多阶段渗透题（b-01/b-02/b-03）

### b-01：卡在横向移动（SSH 跳板机）

**进度**：2/4 flags
- ✅ flag1: LFI 直读 /challenge/flag1.txt
- ✅ flag2: error.log 投毒 RCE 后读文件
- ⛔ flag3/4: 需要 SSH 横向到 172.18.0.x 跳板机

**卡点**：内网探测方法错误
- Solver 用 `ping` 扫 docker 网段，docker 桥接网过滤 ICMP，全部零响应
- 在 `192.168.10.20`（管理网卡 IP，不可达）上浪费时间
- 真正的跳板机在 `172.18.0.x` docker 网段，IP 在重跑中变化

**修复**：
1. `skills/pentest/SKILL.md` 4.1 节重写：`⚠️ Docker 网络环境禁止用 ping`
2. TCP 端口探测提升为首选方法
3. 新增网卡识别指南（eth0/docker0/lo 区分）

---

### b-02：卡在后台登录

**进度**：1/6 flags
- ✅ flag1: 通过某种方式拿到
- ⛔ flag2-6: 需要登录 /admin 后台，找到 OA 系统迁移地址

**卡点**：通用弱口令字典爆破完仍无匹配，但没测框架默认凭证
- 167 个通用弱口令 × 7 用户名全部无匹配
- weaver 系默认凭证（sysadmin/1、admin/1、weaver/weaver 等）从未测试

**修复**：
1. `skills/pentest/SKILL.md` 4.4 节新增：7 套 OA/后台系统框架默认凭证
2. 泛微/致远/通达/用友/帆软/蓝凌/DedeCMS 默认口令表
3. 框架默认凭证爆破脚本模板

---

### b-03：卡在 OA 登录 + Redis 深度利用

**进度**：2/4 flags
- ✅ flag1: webshell RCE 后读 /challenge/flag1.txt
- ✅ flag2: 通过某种方式
- ⛔ flag3: 需要 OA 登录或 Redis 深度利用
- ⛔ flag4: AES 加密备份文件解密

**卡点 1**：Session cookie 验证码绕过未执行
- Observer 已明确"验证码明文存在 session cookie 中可绕过"
- Solver 却花了几十轮做 OCR 和弱口令爆破

**卡点 2**：Redis 只查了 DB0
- DB1-15 从未枚举
- AES 备份密钥拿到了但从未定位/解密备份文件

**修复**：
1. `skills/pentest/SKILL.md` 2.8.1 节强化：`⚠️ 最高优先级：Session Cookie 泄露验证码！`
2. `skills/pentest/SKILL.md` 4.5 节强化：`⚠️ b-03 教训：只查了 DB0，DB1-15 从未枚举`
3. AES 备份解密节强化：分步骤 ①搜备份文件 → ②SSH 到 OA 主机搜 → ③解密

---

## 三、修改文件清单

### `prompts/solver.md`

| 位置 | 修改内容 |
|------|---------|
| 新增 `## 配置文件注入时 CR vs LF` | CR(`%0d`) vs LF(`%0a`) 规则 + c-02 教训 + Python socket 备选方案 |
| 中间件表新增 `Dify/Next.js` | 引导先扫同主机其他端口，引用 c-03 教训 |
| 新增 `### 🔴 文件读取后立即尝试 flag 位置` | `## 方向穷尽时的系统化切换` 之前，强制前3轮读 /challenge/flag*.txt |
| 强化 `### 🔴 重跑/重建优先级` | 新增 a-07 教训引用 + 严格按 memory 步骤重建 |

### `skills/web/SKILL.md`

| 位置 | 修改内容 |
|------|---------|
| 指纹表新增 `Dify` 行 | 端口 3000 + Next.js 特征 → 搜索 React2Shell + 扫同主机 |
| `### 5.2` OFBiz 重写 | CVE-2023-51467 认证绕过完整流程 + 4 个 payload + 陷阱说明 |
| `### 6.5` ComfyUI-Manager 全新 | CR 注入攻击链 + `%0d` vs `%0a` + socket 原始发包 |
| `### 6.6` Dify/React2Shell 全新 | 多版本策略 + 同主机端口扫描 + ACTION_ID 变体 + 版本差异表 |

### `skills/pentest/SKILL.md`

| 位置 | 修改内容 |
|------|---------|
| `### 4.1` 内网发现重写 | `⚠️ Docker 网络禁止 ping` + TCP 优先 + 网卡识别指南 |
| `### 4.3` SSH 跳板强化 | 新增网段识别（docker0/eth0/lo）+ 管理 IP 不可达警告 |
| `### 4.4` 新增框架默认凭证 | 7 套 OA 系统默认口令表 + 爆破脚本模板 |
| `### 2.8.1` 验证码绕过强化 | `⚠️ 最高优先级：Session Cookie 泄露验证码` + b-03 教训 |
| `### 4.5` Redis 强化 | `⚠️ b-03 教训：只查了 DB0` + 强制枚举所有 16 个 DB |
| AES 备份解密强化 | `⚠️ b-03 教训` + 分步骤搜索 + SSH 到 OA 主机搜 |

### `solver/observer/agent.py`

| 位置 | 修改内容 |
|------|---------|
| 新增 `LFI 已确认但未尝试 /challenge/ 检测` | 10 轮未试就纠偏，强制提醒 /challenge/flag*.txt |
| 强化 `重跑未重建已有解法检测` | 更明确的纠偏消息格式 |

---

## 四、覆盖的失败题目

| 题目 | 失败原因 | 修复方式 | 预期效果 |
|------|---------|---------|---------|
| c-01 | 平台问题（URL 为空） | 需 `challenge_start` 重启 | 非代码层面可修 |
| c-02 | Solver 只试了 LF 没试 CR | ✅ solver.md CR vs LF 规则 + web SKILL.md 6.5 | 下次可解 |
| c-03 | 实例1 靠 HugeGraph 过，实例2 无 HugeGraph | ✅ web SKILL.md 6.6 多版本策略 | 有备选方案 |
| c-09 | OFBiz 登录 bypass 没正确执行 | ✅ web SKILL.md 5.2 完整登录绕过流程 | 下次可解 |
| b-01 | ping 扫 docker 内网零响应 | ✅ pentest SKILL.md 4.1 TCP 优先 | 下次可解 |
| b-02 | 没测框架默认凭证 | ✅ pentest SKILL.md 4.4 weaver 等 7 套默认凭证 | 下次可解 |
| b-03 | session cookie 验证码未利用 + Redis 只查 DB0 | ✅ pentest SKILL.md 2.8.1 + 4.5 强化 | 下次可解 |
| a-05 | LFI 后花 24 轮读源码才试 /challenge/ | ✅ solver.md 强制规则 + Observer 检测 | 下次 3 轮内解决 |
| a-07 | 重跑时从零探测而非复用 memory | ✅ solver.md 重跑/重建优先级强化 | 下次直接复用 |