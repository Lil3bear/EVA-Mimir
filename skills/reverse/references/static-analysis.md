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

