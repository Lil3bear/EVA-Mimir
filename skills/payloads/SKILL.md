---
name: payloads
description: PayloadsAllTheThings 精选语料库。需要某类漏洞的具体 payload、绕过、字典时按分类加载。
---

# Payload 语料库

## 使用方式
用 `skill_load(name="payloads", resource=<文件名>)` 加载对应分类的 payload 语料。不要一次读全部。

## 分类路由

| 漏洞类型 | resource |
|---|---|
| SQL 注入 | `sql-injection.md` |
| 命令注入 | `command-injection.md` |
| 文件包含 | `file-inclusion.md` |
| SSRF | `server-side-request-forgery.md` |
| XSS | `xss-injection.md` |
| 文件上传 | `upload-insecure-files.md` |
| JWT | `json-web-token.md` |
| XXE | `xxe-injection.md` |
| SSTI | `server-side-template-injection.md` |
| 反序列化 | `insecure-deserialization.md` |
| CVE 利用 | `cve-exploits.md` |
| 原型链污染 | `prototype-pollution.md` |
| LDAP 注入 | `ldap-injection.md` |
| NoSQL 注入 | `nosql-injection.md` |

## 约束
- payload 里 `TARGET`、`<target>`、`example.com` 都是占位符，替换成真实目标。
- 数值/hex/碰撞类 payload 必须 bash 本地验证后才用。
