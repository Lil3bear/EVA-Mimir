# 进程注入代码检测绕过

> 适用：题目要求提交"进程注入代码"（C/Python/汇编），由检测器静态评估（如
> POST /check 接收 code+description），有 N 条检测规则，触发 <= K 条才通过
> （例如 5 条规则触发 <=2 条，bypass_score >= 60%）。precheck 要求真实函数/
> 导入/赋值，API 名必须静态可解析（字符串拼接 "ke"+"rnel32" 或 getattr 会触发）。

## 1. 先搞清楚检测规则（最重要）

不要瞎试变体。先确定检测器在找什么，常见规则是"进程注入的典型 API 组合"：

| 检测点 | 典型 Win32 API | 对应 NT API |
|---|---|---|
| 打开目标进程 | OpenProcess | NtOpenProcess |
| 分配远程内存 | VirtualAllocEx | NtAllocateVirtualMemory |
| 写入远程内存 | WriteProcessMemory | NtWriteVirtualMemory |
| 修改内存保护 | VirtualProtectEx | NtProtectVirtualMemory |
| 创建远程线程 | CreateRemoteThread | NtCreateThreadEx |
| 队列 APC | QueueUserAPC | NtQueueApcThread |
| 直接系统调用 | syscall 指令 | — |

**判断规则的办法**：先提交一个"教科书式"的完整注入代码（OpenProcess +
VirtualAllocEx + WriteProcessMemory + CreateRemoteThread），看它触发几条；再逐个
删 API，看哪条规则对应哪个 API。

## 2. 绕过技巧（按优先级，每种只试一次）

### 2.1 NT API 替代 Win32 API
检测器常只认 Win32 名。改用 ntdll 的 NT API（功能等价，名字不同）：
```c
// 不用 OpenProcess，改用 NtOpenProcess（需从 ntdll 动态解析）
typedef NTSTATUS (NTAPI *pNtOpenProcess)(PHANDLE, ACCESS_MASK, POBJECT_ATTRIBUTES, PCLIENT_ID);
// 静态声明函数指针，API 名 NtOpenProcess 仍静态可解析（满足 precheck）
```

### 2.2 映射注入（替代 VirtualAllocEx + WriteProcessMemory）
用共享内存段代替"远程写内存"，避免命中"分配/写入远程内存"两条规则：
```c
// NtCreateSection + NtMapViewOfSection：本进程和远程进程映射同一内存段
// 本进程写入后，远程进程直接读，不需要 WriteProcessMemory
```

### 2.3 回调/APC 注入（替代 CreateRemoteThread）
用线程池回调触发远程执行，避免命中"创建远程线程"规则：
```c
// 用 QueueUserAPC 或 SetThreadpoolWait 替代 CreateRemoteThread
// 注意：QueueUserAPC 本身可能也被检测，可改用 CreateTimerQueueTimer 等回调
```

### 2.4 进程空洞化（替代 CreateProcess + 注入）
直接以挂起方式创建目标进程，写入后再恢复：
```c
// NtCreateProcess（挂起）→ 写入 → NtResumeThread
// 避免 OpenProcess（新进程句柄已有），避免 CreateRemoteThread（恢复主线程即可）
```

## 3. 关键原则

- **API 名必须静态可解析**：用 `typedef ... (*pNtXxx)` 声明函数指针，名字里含
  完整 API 名；不要用 `GetProcAddress("ke"+"rnel32")` 这种拼接（precheck 会拒）。
- **保留真实函数/导入/赋值**：precheck 要求代码"像真的"，空壳或纯注释会拒。
- **逐个规则验证**：每改一版，提交 /check 看触发条数，定位是哪条规则没绕过。
- **不要用 syscall 直接指令**：若检测器专门查 `syscall` 指令，改回 NT API。
- **优先 C 代码**：Python 的 ctypes 调用链常被额外检测，C 代码更接近"真实注入"。
