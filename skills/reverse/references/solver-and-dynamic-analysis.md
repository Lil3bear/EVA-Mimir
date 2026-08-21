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
