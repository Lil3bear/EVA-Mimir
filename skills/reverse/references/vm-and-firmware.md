### 模式 D：VM 字节码虚拟机
适用于：自定义 VM、字节码解释器类题目

#### D.1 VM 快速识别（反汇编中看到以下特征 → 立即走 VM 流程）

```
⚠️ 看到以下 3 个特征中的任意 2 个 = VM 题，不要继续逐行读反汇编，直接写模拟器：

特征 1 - 跳转表分发：jmp [base + index*4] 或 jmp [base + index*8]
特征 2 - 字节码数组：连续数据段 + 主循环中 movzx eax, BYTE PTR [base+IP]
特征 3 - 主循环结构：取指 → 解码(opcode + 偏移) → 查表跳转 → handler → 更新IP → 循环
```

#### D.2 VM 分析三步法（严格按顺序，每步限 3 轮）

**第一步：提取 VM 数据（3 轮内完成）**
```bash
# 1. 确认分析的是正确文件（参考"文件来源判定规则"）
file ./binary && ls -la ./binary && md5sum ./binary

# 2. 一次性 dump 所有关键数据段
readelf -S ./binary | grep -E "\.(text|rodata|data|bss)"
readelf -l ./binary | grep -A1 LOAD  # 段映射：vaddr→文件偏移

# 3. 提取字节码（通常是 .data 或 .rodata 中的连续数组）
#    特征：主循环中 r12/r13 指向的基址 + 偏移读取
#    objdump -d ./binary | grep -A3 "lea.*\[rip"  # 找字节码基址加载
```

**第二步：定位 handler 表（2 轮内完成）**
```python
# 从反汇编中提取跳转表（通常在 .text 或 .rodata 中）
# 跳转表 = N 个 4 字节相对偏移，指向 N 个 handler
# 反汇编中找：movsxd rax, DWORD PTR [r13+rax*4]; add rax,r13; jmp rax

# 用 Python 提取跳转表：
import struct
data = open('binary', 'rb').read()
# 跳转表偏移（从反汇编的 lea r13,[rip+X] 获取）
table_offset = 0x2004  # 替换为实际偏移
table = struct.unpack_from(f'<{11}i', data, table_offset)  # 11 项
for i, off in enumerate(table):
    print(f"handler[{i}] -> {hex(0x2004 + off)}")  # 绝对地址 = 表基址+偏移
```

**第三步：写模拟器 + 跑 trace（5 轮内完成）**

#### D.3 VM 模拟器模板（完整版）

```python
#!/usr/bin/env python3
"""VM 模拟器 — 从二进制中提取字节码/数据/跳转表，模拟执行并输出 flag"""
import struct, sys

# ====== 1. 从二进制提取数据 ======
data = open('./binary', 'rb').read()

# 段映射（从 readelf -l 获取）
# LOAD off M → vaddr V: file_offset = vaddr - (V - M)
# 例如：LOAD off 0x1000 vaddr 0x0000 → file_off = 0x4020 - 0x0000 + 0x1000 = 0x5020
# 简化：直接按 vaddr 读（如果 vaddr = file_off）

# 字节码（从反汇编 lea r12,[rip+X] 获取 vaddr）
BYTECODE_OFF = 0x3010  # 文件偏移（= vaddr 0x4010 - 段基址 0x4000 + 段文件偏移 0x3000）
bytecode = data[BYTECODE_OFF:BYTECODE_OFF+10]  # 10 字节

# Key（从反汇编 lea r15,[rip+X] 获取 vaddr）
KEY_OFF = 0x301a
key = data[KEY_OFF:KEY_OFF+4]  # 4 字节

# Tape（数据数组，从反汇编 lea rcx,[rip+X] 获取）
TAPE_OFF = 0x3020
TAPE_LEN = 56  # 从 readelf 段大小或反汇编 cmp r14d,0x1e 推断
# 通常 tape 长度 = 循环上限（cmp r14d, N → N+1 轮）
tape = data[TAPE_OFF:TAPE_OFF+TAPE_LEN]

# 跳转表（从反汇编 lea r13,[rip+X] 获取）
JUMPTABLE_OFF = 0x2004
NUM_HANDLERS = 11  # 从 cmp edx, 0x9 推断（0..9 → 10 个 handler + 可能更多）
table = struct.unpack_from(f'<{NUM_HANDLERS}i', data, JUMPTABLE_OFF)

print(f"bytecode ({len(bytecode)}B): {bytecode.hex()}")
print(f"key ({len(key)}B): {key.hex()}")
print(f"tape ({len(tape)}B): {tape[:32].hex()}...")
print(f"jump_table ({len(table)} entries): {[hex(t) for t in table[:5]]}...")

# ====== 2. 模拟执行 ======
IP = 0          # 指令指针（edx）
r14 = 0         # 轮次计数器
MAX_ROUNDS = 32  # 从 cmp r14d, 0x1f 推断
output = []
trace = []

# 解码函数：bytecode[IP] → handler 索引
# 从反汇编 add eax,0x3f; cmp al,0xa; ja default 推断
# 解码 = (bytecode[IP] + 0x3f) & 0xff，若 > 0xa → default
# 但更常见的做法是 bytecode[IP] ^ 0xc3 → handler 索引
# 需要从反汇编确认具体解码逻辑

def decode(opcode):
    """解码字节码 → handler 索引"""
    # 常见模式 1: opcode ^ 0xc3
    # 常见模式 2: (opcode + 0x3f) & 0xff
    # 从反汇编的 add/sub/xor 立即数确定
    return (opcode + 0x3f) & 0xff  # 替换为实际解码

def handler_tape(IP):
    """tape handler: 读取 tape[r14]"""
    global r14
    if r14 < len(tape):
        val = tape[r14]
    else:
        val = 0
    trace.append((r14, 'tape', val))
    return IP + 1

def handler_key(IP):
    """key handler: 读取 key[r14 & 3]"""
    global r14
    val = key[r14 & 3]
    trace.append((r14, 'key', val))
    return IP + 1

def handler_dot(IP):
    """dot handler: 输出一个字符"""
    # 输出字符通常是固定值（如 0x2e='.'）或由 eax/某寄存器决定
    # 关键：输出字符 = 从字节码/tape/key 的某种组合派生
    ch = 0x2e  # 替换为实际输出逻辑
    output.append(chr(ch))
    trace.append((r14, 'dot', ch))
    return IP + 1

def handler_inc(IP):
    """inc handler: r14++"""
    global r14
    r14 += 1
    trace.append((r14, 'inc', None))
    return IP + 1

def handler_cjump(IP):
    """条件跳转：r14 < MAX → 跳回 IP=0，否则继续"""
    if r14 < MAX_ROUNDS - 1:  # -1 因为 inc 在 cjump 之前执行
        return 0  # 跳回 IP=0
    else:
        return IP + 1  # 继续执行（通常是 exit）

def handler_skip(IP):
    """skip handler: 跳过下一条指令"""
    return IP + 2  # 跳过 2 个位置

def handler_default(IP):
    """default handler: 无操作，IP+1"""
    return IP + 1

def handler_exit(IP):
    """exit handler: 退出循环"""
    return -1

# handler 表（索引 → 函数）
handlers = {
    0: handler_key,      # 从跳转表索引映射
    1: handler_tape,
    2: handler_default,
    3: handler_skip,
    4: handler_inc,
    5: handler_dot,
    6: handler_skip,     # 可能与 3 相同
    9: handler_exit,
    10: handler_cjump,
}

# ====== 3. 主循环 ======
for step in range(100000):
    if IP < 0 or IP >= len(bytecode):
        break
    opcode = bytecode[IP]
    idx = decode(opcode)
    
    # 特判：某些 opcode 直接跳转（如 0xc3 → skip）
    if opcode == 0xc3:  # 特判值
        IP = handler_skip(IP)
        continue
    
    if idx > 0xa:  # default 分支
        IP = handler_default(IP)
        continue
    
    handler = handlers.get(idx, handler_default)
    new_IP = handler(IP)
    
    if new_IP < 0:  # exit
        break
    IP = new_IP

# ====== 4. 输出结果 ======
print(f"\nRounds: {r14}, Output: {''.join(output)}")
print(f"Trace ({len(trace)} steps):")
for t in trace[:10]:
    print(f"  r14={t[0]:2d} {t[1]:8s} {t[2]}")
if len(trace) > 10:
    print(f"  ... ({len(trace)-10} more)")

# ====== 5. 从字节码自指特征推导 flag ======
# 常见模式：flag[i] = bytecode[i] ^ 0xc3（字节码直接编码 flag）
# 或：flag[i] = (tape[i] ^ key[i&3]) ^ bytecode[i%len(bytecode)]
# 用 FLAG{ 前缀验证各种组合
prefix = b'FLAG{'
for combo_name, combo in [
    ("bytecode ^ 0xc3", bytes(b ^ 0xc3 for b in bytecode)),
    ("bytecode + 0x3f", bytes((b + 0x3f) & 0xff for b in bytecode)),
]:
    if combo[:5] == prefix or combo[:5] == b'flag{':
        print(f"\n🎉 FLAG from {combo_name}: {combo}")
```

#### D.4 VM 题常见陷阱与对策

| 陷阱 | 表现 | 对策 |
|------|------|------|
| 分析错文件 | 模拟器输出与预期不符 | 先 `file` + `md5sum` 确认，对比题目描述中的文件大小 |
| 跳转表索引算错 | handler 行为错乱 | 从反汇编精确提取 `add eax, 0x??` 和 `cmp al, 0x??` 的立即数 |
| 段映射错误 | 读取到错误数据 | 用 `readelf -l` 换算 vaddr→文件偏移 |
| 循环边界搞反 | 执行轮数不对 | 仔细看 `cmp r14d, 0x??` 和 `cmovne` 的条件 |
| 输出字符来源不明 | 全部输出相同字符 | 输出字符可能来自 eax 寄存器（前一个 handler 留下的值），追踪数据流 |
| 字节码自指编码 | 模拟器输出无意义 | hint 中"字节码本身就是 flag 构造过程"→ flag 字符由字节码值直接推导 |

#### D.5 VM 题 hint 解读

当 hint 说"字节码本身就是 flag 的构造过程"时：
1. **不要试图让模拟器输出 flag**——模拟器输出的是 VM 的正常执行结果（可能是固定的 '.' 或数字）
2. **flag 从字节码的静态分析中推导**：每轮执行的字节码值的某种组合 = flag 字符
3. **常见编码**：`flag[i] = bytecode[i] ^ CONST` 或 `flag[i] = sum(bytecode[本轮执行序列])`
4. **用 FLAG{ 前缀验证**：取前 5 个字符，与 'FLAG{' 比对，确认编码方式
5. **写 Python 一行推导**，不要反复跑模拟器

#### D.6 VM 解密型题专项（输入 key → VM 解密 → 输出 flag）

**识别**：程序要求输入 access_code/key，通过后输出 N 个字符（可能全是 `.` 占位或
看似无意义的字符），data 段有 N 字节密文 + 短 key 表。这类题的 flag 就是 VM
解密出的那 N 字节，**不要离线枚举加密算法**（XOR/AES/TEA/RC4/LCG/z3 全试一遍
是无效消耗）。

**正确流程（动态调试优先，别静态瞎猜）**：

```bash
# 1. 用 gdb 在"输出字符"处下断点，观察每轮输出字符怎么派生
#    先跑一遍看程序完整执行，再断点看关键 handler
gdb -q -batch -ex 'run VM_KEY07' ./validator
# 找输出点：objdump 找 putchar/putc 调用
objdump -d -Mintel ./validator | grep -B3 -A3 'putchar\|putc\|fputc'

# 2. 在输出点下断点，看每轮 eax/edx 的值（输出的字符从哪个寄存器来）
gdb -q -batch \
  -ex 'b *0x12b0+OFFSET' \
  -ex 'run VM_KEY07' \
  -ex 'info registers eax edx r14' \
  ./validator

# 3. 逆向"输出 handler"：字符 = 密文[i] ⊕ key[i & 3] 或 密文[i] ⊕ 字节码[i] 之类
#    确定派生公式后，写 Python 直接解密，不要继续跑模拟器
```

**关键判据**：
- 输出是 `.` 占位 → 真正的 flag 字符是 VM 内部算出来的，逆向输出 handler 才能看到
- keystream 动态计算 → 不要静态搜二进制里的字节，要跟 gdb 看每轮实际用到的值
- 密文在 data 段（如 0x4020 有 31 字节），key 表也在附近（如 0x401a）→ 优先 `objdump -s -j .data` dump 这两段
- 用 `FLAG{` 前缀验证任何解密公式，前 5 字节对不上就换公式

**最短路径**：gdb 断点拿到第 1 轮输出的字符和它对应的密文/key/字节码，反推出
公式，一次写出 31 字节 flag。不要先把 VM 全部 handler 逆向完。

## 常见加密算法识别标志

| 特征 | 算法 | 关键常量 |
|------|------|----------|
| 32 轮 Feistel + 左移4/右移5 | TEA/XTEA | delta = 0x9E3779B9 |
| hash*33 ^ c，初值 0x1505 | djb2 | 0x1505, *33 |
| hash ^ byte * prime | FNV-1a | 0x811c9dc5 (32-bit), 0x01000193 |
| S-box 256 字节 + KSA + PRGA | RC4 | 256 字节排列 |
| 10/12/14 轮 SubBytes+ShiftRows | AES | Rijndael S-box |
| 16 轮 Feistel + 48-bit 子密钥 | DES | 56-bit key schedule |
| rol/ror + add/sub + xor 循环 | 自定义多轮变换 | 从 .rodata 提取表 |

## Go 二进制逆向方法

stripped Go 二进制特殊处理：
1. **符号恢复**：`strings ./binary | grep 'main\.' | head -20` — Go 即使 strip 也保留部分符号字符串
2. **入口定位**：`objdump -d ./binary | grep -A5 'main.main'` 或搜索 `runtime.main` 交叉引用
3. **字符串提取**：Go 字符串不以 \0 结尾，用 `strings -n 4 ./binary | grep -iE 'flag|key|secret|license|password'`
4. **关键函数定位**：搜索 `crypto/` 相关符号（`crypto/aes`、`crypto/sha256`）判断加密算法
5. **大小对比**：Go 静态链接通常 > 1MB，如果小于 100KB 大概率不是 Go

---

