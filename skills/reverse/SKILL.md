---
name: reverse
description: 处理二进制逆向/固件分析题：ELF/PE 逆向、加密算法还原、脱壳、Binary Patching、.NET/Java 反编译、固件/VM 分析。
---

# 逆向分析 Skill

## 首次流程
1. 先 `ls -la && file ./<附件>`，确认文件类型。
2. `strings` + `checksec`/`readelf` 快速摸清结构。
3. 根据目标，用 `skill_load(name="reverse", resource=...)` 加载对应 reference。

## 路由

| 任务/证据 | 加载 reference |
|---|---|
| 静态分析、反汇编、字符串、定位关键函数 | `static-analysis.md` |
| 动态调试、GDB、运行跟踪 | `solver-and-dynamic-analysis.md` |
| 加密/编码算法还原 | `algorithms.md` |
| 需要 patch 二进制绕过检测 | `binary-patching.md` |
| 固件、VM、自制格式 | `vm-and-firmware.md` |
| 授权引擎/许可证/序列号校验 | `embedded-license.md` |
| 卡住时的通用解题策略 | `solve-strategies.md` |

## 关键原则
- 需要精确 hex/字节操作时必须写 Python 脚本，禁止手算。
- 附件下载到当前题目目录，不要放 /tmp（会被并行题污染）。
- 逆向出的 flag 可能保留原始格式（HTB{...}/gctf{...} 等），符合格式就提交。
