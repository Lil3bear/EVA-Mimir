## 阶段四：Binary Patching（对抗规避类常用）

### 4.1 基本 Patching 流程
```python
#!/usr/bin/env python3
"""Binary patching 模板 — 修改可执行文件绕过检测"""

import subprocess

# 1. 读取原始文件
data = bytearray(open('./challenge', 'rb').read())

# 2. 找到需要修改的位置
# 方法 A：搜索特定字节序列
target = bytes.fromhex("75 0a")  # 例如 JNE (跳过成功分支)
offset = data.find(target)
print(f"Found at offset: {hex(offset)}")

# 方法 B：已知偏移（从反汇编获取）
# objdump -d ./challenge | grep -A2 "call.*check"
# offset = 0x1234

# 3. 修改字节
# 常用 patch：
# JNE (75) → JE (74)     反转条件跳转
# JNE (75) → NOP NOP (90 90)  删除跳转，强制执行
# JE (74) → JMP (EB)     条件跳转→无条件跳转
# CALL → NOP (5 个 90)   跳过函数调用
data[offset] = 0x74     # JNE → JE（反转判断）
# 或者
data[offset:offset+2] = b'\x90\x90'  # NOP 掉

# 4. 写回
open('./challenge_patched', 'wb').write(data)

# 5. 加执行权限并运行
import os
os.chmod('./challenge_patched', 0o755)
result = subprocess.run(['./challenge_patched'], capture_output=True, text=True, timeout=10)
print("stdout:", result.stdout)
print("stderr:", result.stderr)
```

### 4.2 常用 x86/x64 指令字节
```python
# 速查表（用于 patching）
PATCHES = {
    'NOP':      b'\x90',
    'RET':      b'\xc3',
    'JMP_SHORT': b'\xeb',       # + 1 字节偏移
    'JE_SHORT':  b'\x74',       # + 1 字节偏移
    'JNE_SHORT': b'\x75',       # + 1 字节偏移
    'JMP_NEAR':  b'\xe9',       # + 4 字节偏移
    'CALL':      b'\xe8',       # + 4 字节偏移
    'XOR_EAX':   b'\x31\xc0',   # xor eax, eax (return 0)
    'MOV_EAX_1': b'\xb8\x01\x00\x00\x00',  # mov eax, 1 (return 1/true)
    'MOV_EAX_0': b'\xb8\x00\x00\x00\x00',  # mov eax, 0 (return 0/false)
}

# 常见 patch 场景：
# 1. 绕过密码/许可证检查：把 check 函数的返回值改为始终 true
#    找到 check 函数开头，写入 mov eax,1; ret
#    data[func_start:func_start+6] = b'\xb8\x01\x00\x00\x00\xc3'
#
# 2. 绕过反调试：NOP 掉 ptrace/IsDebuggerPresent 调用
#    找到 call ptrace，替换为 5 个 NOP
#    data[call_offset:call_offset+5] = b'\x90' * 5
#
# 3. 修改字符串比较结果：反转 JNE → JE
#    data[jne_offset] = 0x74
```

### 4.3 自动化搜索 patch 点
```python
#!/usr/bin/env python3
"""自动查找可能的 patch 点"""

data = open('./challenge', 'rb').read()

# 搜索条件跳转（常见的检查分支点）
import re

# JNE/JE 后跟 "wrong"/"fail"/"incorrect" 字符串引用
for m in re.finditer(rb'\x75.|\x74.|\x0f\x85....|\\x0f\x84....', data):
    offset = m.start()
    # 看跳转目标附近有没有错误信息
    context = data[offset:offset+30]
    print(f"Conditional jump at {hex(offset)}: {context.hex()}")

# 搜索 strcmp/strncmp 调用后的跳转
for pattern_name, pattern in [
    ("test eax,eax; jne", b'\x85\xc0\x75'),
    ("test eax,eax; je",  b'\x85\xc0\x74'),
    ("cmp eax,0; jne",    b'\x83\xf8\x00\x75'),
]:
    for m in re.finditer(re.escape(pattern), data):
        print(f"{pattern_name} at {hex(m.start())}")
```

---

