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

