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

### 1.0 诊断优先（遇到异常响应必须先做，不要急着爆破）

**题目描述里的异常词（"响应异常""系统异常""报错""无法访问"）= 出题人指向的漏洞点，优先深挖。**

遇到 `5xx`、`4xx` 异常或行为异常的端点时，按顺序做：
1. **先 dump 完整响应 body**（GET/POST/不同 Content-Type 都试一遍）：
   ```bash
   curl -si http://TARGET/path | cat -A | head -60
   curl -si -X POST http://TARGET/path -H 'Content-Type: application/json' -d '{}' | head -60
   ```
2. 检查 body 是否泄漏：traceback / 源码路径 / 配置 / debug PIN / 堆栈。
   - Flask debug 开启 → 直接拿 Werkzeug debugger PIN 或源码。
   - 泛化 `Internal Server Error` → debug 关，进入第 3 步。
3. 异常原因才是线索：登录页恒 500 可能是模板缺失/DB 异常/配置缺失——先搞清楚为什么 500，再决定是爆破、session 伪造还是源码泄漏。
4. **禁止在未确认异常根因前就跑弱口令/SQLi/大规模爆破**（浪费轮次）。

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

