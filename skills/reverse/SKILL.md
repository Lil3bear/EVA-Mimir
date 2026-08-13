# Reverse 逆向分析 Skill — CTF 逆向工程题全流程指引

## 适用场景
CTF Reverse 类题目，包括 ELF/PE 逆向、加密算法还原、混淆代码分析、脱壳、Binary Patching、.NET/Java 反编译等。

## ⚠️ 核心原则
**所有 hex/字节操作必须用 Python 脚本处理，禁止手动计算。**
**逆向出加密逻辑后，写完整的解密脚本，不要手算中间结果。**

## ⚠️ 工作区隔离规则（极重要）
**每道题的所有文件操作必须在自己的工作目录下进行，绝不使用 /root/workspace 或 /tmp 存放题目二进制文件。**

1. **题目文件复制**：收到题目后，立即将题目二进制复制到当前工作目录（`$PWD`，即 `/workspace/<unique_code>/`）
2. **下载到当前目录**：从靶场下载文件时使用 `curl -o ./validator <url>` 而不是 `-o /tmp/xxx`
3. **不信任已有文件**：如果工作目录已有 validator/firmware 等文件，先 `md5sum` 比对并确认 `file` 类型，与题目描述不符则重新下载
4. **禁止 cd /root/workspace**：永远使用 `cd $PWD` 或直接在当前目录操作，不要切换到 `/root/workspace`
5. **反汇编文件命名**：使用含题目前缀的文件名（如 `f206_dis.txt` 而非 `dis.txt`），避免跨题覆盖

**为什么这很重要**：多个逆向题并行时共用 `/root/workspace`，不同题的 validator/firmware 文件会互相覆盖，导致分析错误文件浪费大量轮次。

## ⚠️ 文件来源判定规则（极重要）
1. **靶场页面声明的文件类型 = 真实文件类型**，不要自行推翻
2. 每次开始分析前：`file ./binary && ls -la ./binary && md5sum ./binary`
3. 如果工作目录的文件大小/类型与靶场页面描述不符 → **重新从靶场下载**
4. 从靶场下载后立即验证：`curl -o ./validator http://TARGET/download && chmod +x ./validator && file ./validator`

## ❗ 状态机/加密求解策略选择（极重要）

逆向出算法后，先评估状态空间大小，再选算法：

| 状态空间 | 策略 | bash timeout |
|-----------|--------|-------------|
| < 10^5 | BFS 暴力枚举 | 120s |
| 10^5 ~ 10^8 | A* + 剪枝 / Meet-in-the-middle | 300s |
| > 10^8 或无法枚举 | Z3 约束求解 / angr 符号执行 | 300s |
| 有明确目标函数 | 梯度下降 / 模拟退火 | 300s |

### 关键规则：
1. 写完求解脚本后，先用 `bash({"cmd": "...", "timeout": 30})` 跑一次快速测试
2. 30s 内出结果 → 完成
3. 超时 → **不要重复跑同一个脚本**，必须换算法（如 BFS 超时换 Z3）
4. 用 `bash({"cmd": "python3 solve.py", "timeout": 300})` 给求解脚本更长超时

### Z3 求解模板（状态空间过大时优先用这个）
```python
from z3 import *

# 定义变量（每个字节一个 BitVec）
key = [BitVec(f'k{i}', 8) for i in range(KEY_LEN)]
s = Solver()

# 约束：可打印 ASCII
for k in key:
    s.add(k >= 0x20, k < 0x7f)

# 约束：加密算法逻辑（从逆向分析中还原）
# state = INIT_STATE
# for i in range(KEY_LEN):
#     state = transform(state, key[i])
# s.add(state == TARGET_STATE)

if s.check() == sat:
    m = s.model()
    solution = bytes([m[k].as_long() for k in key])
    print(f"Found: {solution}")
else:
    print("UNSAT")
```

### Meet-in-the-middle 模板（求解空间可拆半时）
```python
from itertools import product

# 正向计算前半部分的所有可能状态
forward = {}
for combo in product(range(0x20, 0x7f), repeat=HALF_LEN):
    state = compute_forward(combo)
    forward[state] = combo

# 反向计算后半部分，查找碰撞
for combo in product(range(0x20, 0x7f), repeat=HALF_LEN):
    state = compute_backward(combo)
    if state in forward:
        print(f"Found: {forward[state]} + {combo}")
        break
```

## 实战验证的解题模式（来自成功案例）

### 模式 A：IoT 固件逆向三步法
适用于：固件管理控制台、IoT 设备凭据提取类题目

1. **口令提取**：找到密码校验函数，通常是 .rodata 中的常量 XOR 单字节密钥
   ```python
   # 常见模式：字节数组 XOR 单字节 → 明文密码
   data = open('firmware.bin', 'rb').read()
   pwd = bytes(b ^ KEY for b in data[OFFSET:OFFSET+LEN])
   print("password =", pwd)
   ```
2. **ELF 段映射换算**：.data 段 vaddr ≠ 文件偏移！必须用 `readelf -l` 查段表
   ```bash
   readelf -l firmware.bin | grep -A1 LOAD
   readelf -S firmware.bin | grep -E "\.(text|rodata|data)"
   ```
   换算公式：`file_offset = vaddr - (segment_vaddr - segment_offset)`
3. **一次性解密脚本**：把口令验证 + 密钥派生 + 解密写成一个完整脚本一次跑出

### 模式 B：自解密二进制逐层剥壳
适用于：Packed ELF、Self-Decrypt、多层加密类题目

1. **提取口令**：找 .rodata 中的加密口令数据，XOR/SUB 单字节还原
2. **哈希生成密钥流**：识别哈希算法（djb2、FNV-1a 等），实现密钥流生成
3. **逐层解密**：密钥流 XOR 密文 → 得到下一层（可能是 shellcode）
4. **shellcode 内再解密**：shellcode 可能还有一层 XOR，继续解
5. **每层都用 Python，不手算**

### 模式 C：多轮变换逆推
适用于：命令处理器、密钥校验、多轮加密变换类题目

1. **提取常量表**：从 .rodata dump 所有变换表（如 table1/table2/table3）
2. **确定每轮操作**：如 `rol(n) → add(k) → xor(m)`
3. **写逆运算**：**逆序操作**（先 xor → 再 sub → 再 ror），这是关键
4. **正向验证**：逆推结果代入正向变换，确认与期望输出一致
   ```python
   # 逆运算后必须验证
   result = reverse_transform(expected_output)
   assert forward_transform(result) == expected_output
   print("Verified:", result)
   ```

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

## 阶段一：文件分析

### 1.1 基础信息
```bash
# 文件类型
file ./challenge

# 字符串搜索
strings ./challenge | grep -iE "flag|password|key|secret|correct|wrong|success"
strings -el ./challenge  # UTF-16LE（Windows 程序常见）

# 查找嵌入的 flag 格式
strings ./challenge | grep -oE "[a-zA-Z0-9_]+\{[^}]+\}"

# Section 信息
readelf -S ./challenge 2>/dev/null
objdump -h ./challenge 2>/dev/null

# 查看符号表（有无 strip）
nm ./challenge 2>/dev/null | head -30
readelf -s ./challenge 2>/dev/null | grep -i "func\|flag\|main\|check\|verify"
```

### 1.2 检查是否加壳
```bash
# UPX 壳
strings ./challenge | grep -i "upx"
# 脱壳
upx -d ./challenge -o ./challenge_unpacked

# 通用检测
python3 -c "
data = open('./challenge', 'rb').read()
if b'UPX' in data: print('UPX packed')
if b'.text' not in data and b'.code' not in data: print('Possibly packed (no .text section)')
# 检查 entropy（加壳后 entropy 通常 > 7）
import math, collections
c = collections.Counter(data)
entropy = -sum(count/len(data) * math.log2(count/len(data)) for count in c.values() if count)
print(f'Entropy: {entropy:.2f} (>7 suggests packing)')
"
```

---

## 阶段二：静态分析

### 2.1 反汇编
```bash
# objdump 反汇编
objdump -d ./challenge | head -200

# 聚焦 main 函数
objdump -d ./challenge | awk '/^[0-9a-f]+ <main>:/,/^[0-9a-f]+ </' | head -100

# 查找关键函数（check、verify、validate 等）
objdump -d ./challenge | grep -E '<(main|check|verify|validate|flag|encrypt|decrypt)>'

# 使用 pwntools
python3 -c "
from pwn import *
e = ELF('./challenge')
# 列出所有符号
for name, addr in sorted(e.symbols.items(), key=lambda x:x[1]):
    if any(k in name.lower() for k in ['main','check','flag','verify','encrypt','win','key']):
        print(f'{name}: {hex(addr)}')
if 'main' in e.symbols:
    print(e.disasm(e.symbols['main'], 300))
"
```

### 2.2 Python 反编译
```bash
# .pyc 反编译
pip install uncompyle6 decompyle3 2>/dev/null
uncompyle6 ./challenge.pyc 2>/dev/null || decompyle3 ./challenge.pyc 2>/dev/null

# 如果版本不兼容，用 dis 模块反汇编字节码
python3 -c "
import dis, marshal, struct
with open('./challenge.pyc','rb') as f:
    magic = f.read(4)
    f.read(12)  # 跳过 timestamp 等
    code = marshal.load(f)
dis.dis(code)
"

# PyInstaller 打包的 EXE
pip install pyinstxtractor 2>/dev/null
python3 pyinstxtractor.py ./challenge.exe
# 然后反编译提取出的 .pyc
```

### 2.3 Java 反编译
```bash
# .class 文件
javap -c ./Challenge.class

# .jar 文件 — 用 cfr 反编译
java -jar cfr.jar ./challenge.jar --outputdir ./decompiled/ 2>/dev/null

# 直接搜索 flag
unzip -l challenge.jar
unzip -p challenge.jar "*.class" | strings | grep -i flag
```

### 2.4 .NET 反编译
```bash
# 检测 .NET
file ./challenge.exe | grep -i "\.NET\|Mono\|CLI"

# 使用 monodis
monodis ./challenge.exe

# 或用 ilspy（命令行版）
ilspycmd ./challenge.exe 2>/dev/null
```

---

## 阶段三：常见算法识别与还原

### ⚠️ 所有算法还原必须写完整 Python 脚本，不要手算！

### 3.1 XOR 加密
```python
# 特征：汇编中出现 xor reg, KEY 循环
# 还原：
encrypted = bytes.fromhex("ENCRYPTED_HEX")
key = b"KEY"
decrypted = bytes(e ^ key[i % len(key)] for i, e in enumerate(encrypted))
print(decrypted)

# 如果密钥未知，尝试已知明文攻击
# 假设 flag 以 "flag{" 开头
known = b"flag{"
key_fragment = bytes(e ^ k for e, k in zip(encrypted[:5], known))
print("Possible key fragment:", key_fragment)
```

### 3.2 Caesar / ROT 变换
```python
# 特征：add/sub 固定值后 mod 26
def caesar_brute(ct):
    for shift in range(256):
        pt = bytes((b - shift) % 256 for b in ct)
        if b'flag' in pt or b'CTF' in pt:
            print(f"shift={shift}: {pt}")

caesar_brute(bytes.fromhex("ENCRYPTED_HEX"))
```

### 3.3 Base64 变表
```python
# 特征：有一个 64 字节的字符串常量作为编码表
import string, base64
std_table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
custom_table = "CUSTOM_64_CHARS"  # 从程序中提取

encoded = "ENCODED_STRING"
trans = str.maketrans(custom_table, std_table)
decoded = base64.b64decode(encoded.translate(trans))
print(decoded)
```

### 3.4 RC4
```python
def rc4(key, data):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    i = j = 0
    result = []
    for byte in data:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        result.append(byte ^ S[(S[i] + S[j]) % 256])
    return bytes(result)

key = b"secret_key"
ct = bytes.fromhex("CIPHERTEXT_HEX")
print(rc4(key, ct))
```

### 3.5 TEA / XTEA
```python
import struct

def tea_decrypt(v, key):
    v0, v1 = struct.unpack('<2I', v)
    k = struct.unpack('<4I', key)
    delta = 0x9e3779b9
    s = (delta * 32) & 0xffffffff
    for _ in range(32):
        v1 = (v1 - (((v0 << 4) + k[2]) ^ (v0 + s) ^ ((v0 >> 5) + k[3]))) & 0xffffffff
        v0 = (v0 - (((v1 << 4) + k[0]) ^ (v1 + s) ^ ((v1 >> 5) + k[1]))) & 0xffffffff
        s = (s - delta) & 0xffffffff
    return struct.pack('<2I', v0, v1)

key = b'\x00' * 16  # 从程序中提取密钥
ct = bytes.fromhex("CIPHERTEXT_HEX")
pt = b''
for i in range(0, len(ct), 8):
    pt += tea_decrypt(ct[i:i+8], key)
print(pt)
```

### 3.6 AES / DES（对称加密）
```python
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

# 从逆向中提取 key 和 iv（通常是硬编码常量）
key = bytes.fromhex("KEY_HEX")  # 16/24/32 字节
iv = bytes.fromhex("IV_HEX")    # 16 字节
ct = bytes.fromhex("CT_HEX")

# ECB 模式
cipher = AES.new(key, AES.MODE_ECB)
pt = unpad(cipher.decrypt(ct), AES.block_size)

# CBC 模式
cipher = AES.new(key, AES.MODE_CBC, iv)
pt = unpad(cipher.decrypt(ct), AES.block_size)

print(pt)
```

---

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

## 阶段五：Z3 约束求解

```python
from z3 import *

# 当逆向出的逻辑是一系列约束条件时，用 Z3 自动求解
s = Solver()

# 定义变量（flag 的每个字符）
flag = [BitVec(f'f{i}', 8) for i in range(32)]

# 添加 printable 约束
for f in flag:
    s.add(f >= 32, f <= 126)

# 添加前缀约束（如 flag{）
s.add(flag[0] == ord('f'))
s.add(flag[1] == ord('l'))
s.add(flag[2] == ord('a'))
s.add(flag[3] == ord('g'))
s.add(flag[4] == ord('{'))
s.add(flag[-1] == ord('}'))

# 添加程序逻辑中的约束
# 例如：flag[5] + flag[6] == 200
# s.add(flag[5] + flag[6] == 200)

if s.check() == sat:
    m = s.model()
    result = ''.join(chr(m.eval(f).as_long()) for f in flag)
    print("Flag:", result)
else:
    print("No solution")
```

---

## 阶段六：动态分析

### 6.1 使用 ltrace/strace 跟踪
```bash
# 跟踪库函数调用（看 strcmp/strncmp 的参数）
ltrace ./challenge <<< "test_input" 2>&1 | grep -iE "strcmp|strncmp|memcmp|flag"

# 跟踪系统调用
strace -f ./challenge <<< "test_input" 2>&1 | grep -iE "open\|read\|write\|flag"
```

### 6.2 使用 pwntools 交互
```python
from pwn import *

p = process('./challenge')
# 在比较函数处设置断点
# 通过输入特定内容，观察比较逻辑
p.sendline(b'test_input')
print(p.recvall(timeout=3))
```

### 6.3 使用 GDB 调试
```bash
# 在关键位置设断点
gdb -q ./challenge -ex "break main" -ex "break *0x401234" -ex "run"

# 查看内存中的字符串
gdb -q ./challenge -ex "break *CHECK_ADDR" -ex "run" -ex "x/s \$rdi" -ex "x/s \$rsi"
```

---

## 逆向分析决策树

```
┌─ file + strings → 识别类型
│
├─ ELF/PE 可执行文件？
│  ├─ 加壳？→ upx -d 脱壳
│  ├─ objdump / pwntools 反汇编
│  ├─ 识别加密算法（XOR/Base64/TEA/RC4/AES）
│  ├─ 写 Python 解密脚本
│  └─ 需要 patch？→ 用 bytearray 修改字节
│
├─ Python .pyc？
│  └─ uncompyle6/decompyle3 反编译 → 读源码 → 写解密脚本
│
├─ Java .jar/.class？
│  └─ cfr/javap 反编译 → 读源码 → 写解密脚本
│
├─ .NET？
│  └─ monodis/ilspy 反编译 → 读源码
│
└─ 复杂约束逻辑？
   └─ Z3 求解器
```

---

## 常见坑

| 现象 | 可能原因 | 对策 |
|------|---------|------|
| strings 找不到有用信息 | 字符串被加密/混淆 | 动态运行后 dump 内存，或找解密函数 |
| 反汇编代码太长 | 程序很大或有大量库代码 | 聚焦 main 和交叉引用到 flag 的函数 |
| Z3 求解超时 | 约束太复杂 | 简化约束，或分段求解 |
| Python 反编译失败 | Python 版本不匹配 | 检查 .pyc magic number 确定版本 |
| 加壳后无法分析 | 非标准壳 | 运行后 dump，或手动脱壳 |
| hex 操作结果不对 | 手动计算出错 | **必须写 Python 脚本，禁止手算** |
| patch 后程序 crash | patch 位置不对或破坏了指令边界 | 确认在指令边界 patch，NOP 补齐 |
| ltrace 无输出 | 静态链接 | 改用 strace 或 GDB |
