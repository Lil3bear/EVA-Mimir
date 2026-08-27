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

### 1.2 目录/参数发现（受预算约束，禁止字典扫描）
```bash
# 平台对同一请求结构有 3 次硬预算：ffuf/dirb/gobuster 字典扫描会一次性烧光并封死通道，禁止使用。
# 目录与参数只能从题目描述、响应体注释/源码、Memory 里的线索推导，再精确访问一次。
curl -si http://TARGET_URL/<从线索推导出的唯一路径>
```

---

