# 嵌入式 / 授权引擎 / 序列号校验 逆向

> 适用：授权引擎、许可证校验、序列号校验器、设备授权校验器等"输入 key/序列号 → 校验 → 放行"类二进制题。

## 识别题型
- 题目描述含「授权」「许可证」「序列号」「license」「serial」「authorization engine」。
- 程序行为：要求输入 key/序列号，校验通过才输出 flag 或解锁功能。
- 常见架构：ELF x86/x64、ARM 固件、Go 二进制、.NET。

## 三种破解路径（按优先级）

### 路径 A：算法还原 → 生成合法 key
校验逻辑是确定性的（hash/CRC/自定义加密）时，还原算法生成合法 key：
```bash
file ./binary && strings -n 5 ./binary | grep -iE 'key|serial|license|flag|correct|wrong|invalid'
objdump -d -Mintel ./binary | grep -A60 '<main>'
# 找到比较逻辑后，用 Python 复现算法，或用 z3 求解：
python3 -c "
from z3 import *
x = BitVec('x', 32)
solve(condition(x) == expected_const)
"
```

### 路径 B：Patch 校验点（最快，通常直接拿 flag）
定位"校验失败"分支，反转条件或 NOP 掉校验调用：
```bash
objdump -d -Mintel ./binary | grep -B5 -A5 'jne\|je\|jz\|jnz' | grep -iE 'wrong|invalid|fail'
# 用 Python 改字节：JNE↔JE (0x75↔0x74)，或把 call check 改成 NOP (0x90)
data = bytearray(open('binary','rb').read())
data[offset] = 0x74  # 例如把 jne 改成 je
open('patched','wb').write(data)
# 或把校验函数开头改成 mov eax,1; ret
```

### 路径 C：硬编码 key / 格式还原
- `strings` 直接出 key/license 明文，或出 key 格式提示（`%s-%s-%s`）。
- license 文件结构：解析字段（用户名、到期时间、校验和），还原校验和算法。
- 授权引擎常把 flag 用 key 派生密钥 AES 加密——还原 key 后解密 flag。

## 嵌入式授权引擎专项（f2-05 类）
1. 先 `strings` 找「valid/invalid/license/serial」字符串定位校验函数。
2. 分析 key 派生逻辑（常见：硬件 ID + 固定密钥 → HMAC/哈希）。
3. flag 通常由 key 派生密钥加密：还原 key 后用 AES 解密。
4. 若校验在固件/远程服务，考虑 patch 或伪造响应。

## 序列号校验器专项（f2-07 类）
1. 确认序列号格式（长度、分段、字符集）。
2. 找校验函数（常见 `strlen` + 逐字符运算 + 常量比较）。
3. 用 z3 逐位求解满足约束的序列号。
4. 提交合法序列号拿 flag。

## 工具链
- 静态：`file` / `strings` / `readelf` / `objdump` / `rizin`（若可用）
- 动态：`gdb` / `ltrace` / `strace`
- 求解：`z3-solver`（已装）
- Patch：Python `open('rb').read()` 改字节写回
