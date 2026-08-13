# 第六轮优化 — B 类多阶段渗透深度分析

> 时间：2026-08-11
> 基于：第五轮实战日志（run5.log + solver-history）

## 第五轮 B 类实际结果（修正）

memory.md 记录的"b-01 3/4, b-03 2/4"需要修正——实际上 b-01 的 3/4 和 b-03 的 3/4 来自不同轮次：

| 题目 | R1 | R2 | R3 | 最终 |
|------|----|----|----|----|
| b-01 | 1/1（API 返回 completed） | 无提交 | 无提交 | 1 flag |
| b-03 | 2/4 flag | 0 new（重复提交） | +1 new = 3/4 | 3/4 flag |
| b-02 | 0/6 | 0/6 | — | 0 flag |

## b-03 完整攻击链还原

### R1（2/4 flag）

1. **信息收集**：curl 首页 → nginx/PHP 7.4 → 锐安科技
2. **后台登录爆破**：admin:admin/123456/password 全失败
3. **路径探测**：robots.txt(200)/backup.sql(200)/www.zip(200)/admin/upload.php(302)
4. **LFI 确认**：`services.php?lang=....//....//....//....//etc/passwd` 可读
5. **后台登录成功**：admin/Admin@123 爆破命中
6. **文件上传 getshell**：上传 shell.php（hint 说后缀检测不全面），.php/.phtml 均可上传执行
7. **flag1**：`cat /challenge/flag1.txt` → 提交成功（进度 1/4）
8. **flag2**：通过 LFI 读另一台机器的 flag：`services.php?lang=....//....//....//....//challenge/flag1.txt` → 提交成功（进度 1/4 — 注意仍显示 1/4，说明不同机器的 flag 分别计算）
9. **内网扫描**：发现 172.18.0.x 和 172.19.0.x 网段
10. **卡住**：50+ 轮尝试各种内网渗透（Redis/MySQL/OA/SSH），但没有 ssh 客户端，传输通道建立失败

### R2（0 new）

- 重新开始，但只是重复提交已有 flag
- 网络拓扑变了，旧情报无效

### R3（+1 flag = 3/4）

1. **快速重建 shell**：login + upload shell.php + 验证 RCE
2. **Redis 探测**：上传 redis.php 脚本到 webshell，连接 172.19.0.4:6379，发现 corporate_secret 等 key
3. **SSH 爆破成功**：上传 brute2.py（Python paramiko），爆破 devops/Admin123 登入跳板机 172.18.0.3
4. **flag3**：`cat /challenge/flag2.txt` 在跳板机上 → 提交成功（进度 2/4）
5. **flag4（来自 OA? 同一个请求?）**：从 brute2.py 的输出中发现第二个 flag → 提交成功（进度 3/4）
6. **flag5 卡住**：
   - 跳板机 devops 无 sudo
   - admin SSH 密码爆破在 'root123' 处因传输错误中断，剩余 16 项未测
   - 172.18.0.4 的 LFI 不工作（代码不同）
   - OA 系统 (172.19.0.2:8080) 登录失败
   - 60 轮耗尽

## 核心问题

### 问题 1：方向循环检测误判 webshell 操作

**现象**：
- `shell.php?c=` 被循环警告 **15 次**
- `admin/upload.php` 被循环警告 **16 次**
- `s.php` 被循环警告 **14 次**

**根因**：循环检测只看 URL path 模式，把"通过 webshell 执行不同命令"错误标记为循环。webshell 的 URL 固定但命令内容完全不同，这是正常的 RCE 通道使用。

**影响**：Agent 被大量循环警告干扰，可能影响决策方向。

**修复方案**：在 `solver/observer/loop.py` 的 URL 指纹提取中，对已知 webshell 模式（路径含 shell/cmd/s.php + 有参数 c/cmd/x）做白名单，不触发循环警告。或者将 URL + 参数值一起作为指纹（当前只用 URL path）。

### 问题 2：容器缺少 SSH 客户端

**现象**：Docker 容器没有 `ssh`/`sshpass`，Agent 需要自写 Python SSH 客户端（paramiko），浪费 5-10 轮。

**影响**：写 SSH 客户端封装 + 调试 = 约 5-10 轮。

**修复方案**：Docker 镜像预装 `openssh-client` + `sshpass`。

### 问题 3：靶场网络布局每轮变化

**现象**：
- R1: Redis 在 172.19.0.4
- R3: Redis 在 172.19.0.4（但 172.19.0.2 CONNFAIL）
- 每次 start_challenge 后网络拓扑可能不同

**影响**：跨轮次的 memory 中的 IP 地址和端口信息可能过时。

**修复方案**：
- 在 pentest SKILL 中提醒：每次重跑后内网拓扑可能变化，必须重新扫描
- 重跑时自动清理与 IP 相关的 memory 条目（标记为 stale）

### 问题 4：admin SSH 密码爆破中断未恢复

**现象**：admin SSH 爆破到 'root123' 时因 `paramiko.SSHException: No existing session` 错误中断，剩余 16 个密码（含 Tiandun2024 族）未测试。Observer 纠偏指出了这个问题，但 60 轮已耗尽。

**影响**：如果 admin 密码在未测试的 16 个中，flag4 就能拿到。

**修复方案**：
- SSH 爆破脚本加重试逻辑（连接断开后重建）
- pentest SKILL 增加"SSH 爆破必须完整跑完字典"的规则

### 问题 5：多阶段渗透轮次不够

**现象**：b-03 R3 在第 53 轮才通过 SSH 爆破找到 flag3/4，只剩 7 轮探索 flag5。

**影响**：medium 题 60 轮对于 4-flag 多阶段渗透题可能不够。

**修复方案**：
- B 类题 max_rounds 提高到 80-100
- 或者在 `_should_force_stop()` 中，对已提交过 flag 的多阶段题不做 force_stop

## 优化方案汇总

### 优化 1：webshell URL 白名单（预期 +300~600 分）

**文件**：`solver/observer/loop.py`

**方案**：URL 指纹提取时，对 webshell 模式（路径含 shell/cmd/s.php 等 + 有命令参数）不触发循环警告。改为按命令内容的攻击向量分类（如同一个 LFI payload 重复才算循环）。

### 优化 2：Docker 预装 SSH 工具（预期 +200~400 分）

**文件**：`docker/Dockerfile`

**方案**：`apt-get install -y openssh-client sshpass`（约 10MB）

### 优化 3：B 类题 max_rounds 提高（预期 +300~500 分）

**文件**：`solver/ctfplatform/scheduler.py` 或 `solver/agent.py`

**方案**：
- B 类题（flag_count >= 4）max_rounds 提高到 100
- 或者：已提交过 flag 的多阶段题，force_stop 阈值翻倍

### 优化 4：渗透 SKILL 增加跳板机标准操作（预期 +200~400 分）

**文件**：`skills/pentest/SKILL.md`

**方案**：增加"SSH 进入跳板机后的标准操作序列"：
1. `cat /challenge/flag*.txt` — 立即搜索 flag
2. `sudo -l` + `cat /etc/sudoers.d/*` — 检查提权路径
3. `cat /proc/net/arp` + `ip addr` — 发现更深层网络
4. `ls /home/*/` + `cat /home/*/.bash_history` — 找其他用户的凭据
5. `curl http://内网IP/` — 探测内网 Web 服务
6. 如果发现 admin 有 sudo，立即用已有密码 + 常见弱口令爆破 admin SSH

### 优化 5：重跑时自动标记 IP memory 为过期

**文件**：`solver/ctfplatform/scheduler.py` 或 `solver/agent.py`

**方案**：多阶段渗透题重跑时，在 task 描述中增加提示：
"⚠️ 这是重跑轮次。上一轮发现的内网 IP 和端口可能已变化，必须重新扫描确认。"

### 优化 6：SSH 爆破脚本模板写入 SKILL

**文件**：`skills/pentest/SKILL.md`

**方案**：提供完整的 paramiko SSH 爆破+执行脚本模板，包含：
- 连接重试逻辑
- 字典必须完整跑完（不因单次连接错误放弃）
- 成功后立即执行 flag 搜索命令
- 常见弱口令内置字典

## 预期增分

| 优化 | 预期增分 | 难度 | 优先级 |
|------|---------|------|--------|
| 1 webshell 白名单 | +300~600 | 中 | P1 |
| 2 SSH 工具预装 | +200~400 | 低 | P0 |
| 3 B 类 max_rounds | +300~500 | 低 | P1 |
| 4 跳板机标准操作 | +200~400 | 低 | P1 |
| 5 IP memory 过期标记 | +100~200 | 低 | P2 |
| 6 SSH 爆破模板 | +200~400 | 低 | P1 |
| **合计** | **+1300~2500** | | |
