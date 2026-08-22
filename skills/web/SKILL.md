---
name: web
description: 处理 HTTP/Web 入口的 CTF 题。发现 HTTP 响应、Web 框架、登录接口、文件读取或注入点时使用。
---

# Web 渗透 Skill

## 首次流程
1. 确认协议与入口：`curl -si <URL>` 保留响应头、正文、Cookie。
2. **先对照下面的「响应特征 → 产品识别」表提出候选产品/漏洞方向。**
3. 再用 `skill_load(name="web", resource=...)` 加载对应 reference；只验证与当前证据匹配的一条路线。

## ❗ 响应特征 → 产品识别（curl 后先对照）

首页响应返回后，对照此表形成候选。端口是弱信号，产品/CVE 必须由响应或路径特征佐证；表中的动作是验证建议，不是成功结论。

| 响应特征 | 产品/漏洞 | 验证建议 |
|---|---|---|
| HTML 含 `gradio` 或 `gr-` 前缀，端口 7860 | Gradio | `skill_load(web, product-playbooks.md)` + CVE-2024-1561 文件读 |
| 端口 3000 + HTML 含 `Next.js` 或 `data-public-api-prefix` | Dify(Next.js) | CVE-2025-55182 React2Shell + 扫同主机其他端口 |
| HTTPS 8443 + HTML 含 `ofbiz` 或 `webtools` | Apache OFBiz | CVE-2023-51467 未授权 RCE + 试 admin/ofbiz |
| `Server: Python` + 路径含 `/api/manager` | ComfyUI-Manager | CVE-2025-67303 config RCE |
| HTML 含 `1panel` 或 `/api/v1/auth/login` | 1Panel | CVE-2024-39907 SQLi 写 shell |
| `Server: GeoServer` 或 HTML 含 geoserver | GeoServer | CVE-2024-36401 RCE |
| `X-Powered-By: Next.js` | Next.js | CVE-2025-29927 中间件绕过 |
| `X-Powered-By: ThinkPHP` | ThinkPHP | 5.x RCE |
| `Set-Cookie: rememberMe=deleteMe` | Shiro | 默认密钥反序列化 |
| `Set-Cookie: session=eyJ` | Flask session | flask-unsign 破解密钥 |
| 响应含 `?cmd=`/`?ip=`/`?host=` | 命令注入 | `;id` `\|id` `$(id)` 全试 |
| 响应含 `?url=`/`?fetch=` | SSRF | `file:///etc/passwd` + `http://127.0.0.1` |
| 响应含 `.php` + `file=` 参数 | 文件包含 | php://filter 读源码 |
| 响应含 `?page=`/`?tpl=` | 模板/文件包含 | `?page=../../../etc/passwd` + `?page={{7*7}}` |
| 响应含 `highlight_file(__FILE__)` | PHP 源码审计 | 读懂逻辑找绕过 |
| 输出含 `password=xxx` 或 `passwd: xxx` | 泄露凭据 | 用该密码登录所有登录接口 |
| 403 + 响应头含 `X-Admin-Key` | Header 鉴权 | `-H 'X-Admin-Key: true'` 布尔绕过 |
| `.git/HEAD` 返回 `ref: refs/heads/` | Git 泄露 | git-dumper 拉源码审计 |
| `robots.txt` 含隐藏路径 | 目录信息 | 逐个访问被禁路径 |
| 响应含 `upload` / 文件上传表单 | 文件上传 | 上传 webshell |
| `Authorization: Bearer eyJ` | JWT | 解码→alg→none/弱密钥 |
| HTML 含 `phpinfo()` | PHP 信息泄露 | 看 disable_functions/版本 |
| 描述/页面含 `CloudFunc`/`云函数`/`serverless`/`Lambda` | Serverless 云函数 | `skill_load(name="cloud", resource="serverless.md")` |

## 路由

| 观察到的证据 | 加载 reference |
|---|---|
| 指纹命中已知产品（1Panel/ComfyUI/Dify/Gradio/通达OA/Shiro 等） | `product-playbooks.md` 或 `known-product-exploit.md` |
| 图数据库 HugeGraph/Neo4j（gremlin/cypher/关联检索） | `graph-db.md` |
| PHP 源码 / `highlight_file` / MD5 比较 / 文件上传 | `php-exploitation.md` 或 `php-payload-builder.md` |
| Java 序列化 / Spring / Struts / FastJSON / Tomcat | `java-exploitation.md` |
| JWT / OAuth token / 签名算法 | `jwt-attacks.md` |
| SSRF / URL 过滤绕过 / 云元数据 | `ssrf.md` |
| SQL 注入 / XSS / 文件包含 / 命令注入等通用漏洞 | `common-vulnerabilities.md` |
| 需要目录扫描 / 指纹识别 / 技术栈判断 | `reconnaissance.md` |
| 已认证/可写文件但拿不到命令执行 | `foothold-to-rce.md` |
| 需要具体 payload 语料库（PayloadsAllTheThings） | 切到 `payloads` skill |

## 关键原则
- **找到任意 `XXX{...}` 立即提交**，不要因为格式"看起来不对"跳过。
- 同一 URL/参数重复尝试不超过 3 次。
- 搜索结果/模型给出的数值类 payload 必须 bash 本地验证。
- 目标不可达时：第 3 次起停止访问，改调 `challenge_get_state`，不猜端口不扫网段。
- 多服务同主机：不要只挖一个入口，对每个端口独立指纹。
