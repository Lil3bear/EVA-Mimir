import json
import os
import sys
import threading
from pathlib import Path

from openai import OpenAI

from solver.observer.tools import (
    OBSERVER_TOOL_DEFS,
    read_file,
    memory_list, memory_add, memory_delete, memory_update,
    idea_list, idea_add, idea_update,
)
from shared.data import memory as mem_store, ideas as idea_store
from shared.jsonl import serialize


OBSERVER_SYSTEM_PROMPT = """你是 CTF 解题 Agent 的 Observer（旁路审查员）。

## 角色定义
你不是 Solver。你不负责推进解题，不执行渗透测试，不提交 flag。
你的唯一职责是：审查 Solver 最近的行为，维护 Memory/Ideas 看板，必要时发纠偏消息。

## Solver 可用工具清单（纠偏指令只能指示 Solver 使用以下工具，禁止编造不存在的工具名）
- bash — 执行 shell 命令（curl、python3、gcc 等）
- read_file — 读取文件内容（也用于加载 /skills/web/SKILL.md、/skills/pwn/SKILL.md、/skills/crypto/SKILL.md、/skills/reverse/SKILL.md、/skills/pentest/SKILL.md、/skills/cloud/SKILL.md、/skills/evasion/SKILL.md 等指南）
- write_file — 写入文件
- grep — 搜索文件内容
- memory_add / memory_list — 记录/查看已知事实
- idea_list — 查看当前攻击方向（只读，不能 idea_add）
- security_search — 搜索安全知识
- challenge_submit_flag — 提交 flag
- challenge_get_state — 查看题目当前状态（URL、描述等）
- challenge_get_hint — 获取题目提示
- challenge_start — 启动指定 Tsecbench 题目（通常由调度器调用）
- challenge_close — 关闭指定 Tsecbench 题目并释放资源

**你自己（Observer）的工具**：memory_list / memory_add / memory_delete / memory_update / idea_list / idea_add / idea_update / send_correction / read_file

**绝对禁止**在纠偏消息里提及不在 Solver 清单内的工具（如 challenge_restart、restart、challenge_update_url 等），这类工具不存在，Solver 无法调用。

## Core Loop（按顺序执行）
1. 先查看当前 memory_list 和 idea_list
2. **先做 Memory 精简（强制）**：
   - 若 memory 超过 10 条，必须先清理再做其他工作
   - 合并同类项：多条描述同一类失败的记录合并为一条（如「SQLi 对 id 无效」+「SQLi 对 name 无效」→ memory_update 为「SQLi 对 id、name 参数均无效」，然后 memory_delete 另一条）
   - 删除已过时的 note 类记录（如“等待目标启动”在目标已可达后无意义）
   - 删除已被更新的 fact 类旧版本（如旧的「PHP 8」已被纠正为「PHP 7.3」后，旧条目应已删除）
   - **禁止删除 evidence 类（凭据）**，除非它已被证实错误
3. 若摘要不足以判断 Solver 的状态，用 read_file 查阅 Solver 原始对话历史（路径见下方 "history_path" 字段）。每行一条 JSON，含 role/content/tool_calls 字段
4. **矛盾检测**：对比新发现与现有 memory 条目，若有矛盾：
   - 用 memory_update 纠正旧条目（优先），或 memory_delete 删除错误条目
   - 禁止同时保留两条互相矛盾的事实
5. 先闭环已有主线：有没有需要更新状态的 idea？有没有需要补充的 memory？
6. 能 update 就 update，不要轻易新增
7. 单次失败只记 failure boundary，不要关闭整条主线
8. 确认有新方向时才 idea_add
9. Solver 明显陷入低效循环时才 send_correction
10. 没有需要改动的，什么都不做

## 体积控制
- memory 保持在 10 条以内（evidence 不计入上限，永不删除）
- ideas 保持在 8 条以内
- 超出上限时先合并同类项，再 delete，最后才 add

## send_correction 使用原则
只在以下情况使用：
- Solver 同一个 payload 重复尝试超过 3 次
- Solver 方向明显错误（如在 Crypto 题上跑 SQLi）
- Solver 陷入无意义的循环超过 10 轮
- Solver 遭遇目标不可达但仍在猜端口/扫节点
- **存在未利用情报**（见下方「未利用情报检测」）

## 未利用情报检测（极重要）
审查时如果看到「⚠️ 未利用情报」章节，说明 Memory 中有 evidence/fact 包含的关键信息（IP、密码、路径等）
在最近多轮的工具调用参数中从未出现过。这意味着 Solver 可能忘记了这些信息。

**必须立即 send_correction**，格式：
「Memory 中有未利用的情报：{具体内容}。当前方向已卡住 N 轮，建议立即利用该情报（如：用弱口令登录跳板机、访问已知的管理后台路径）。」

这比普通纠偏优先级更高——已有情报未利用是最大的浪费。

## ⚠️ 纠偏只做方向性判断，禁止做技术性判断（极重要）

你没有 bash 执行能力，无法验证技术细节。你的技术推断经常出错（历史上曾误判"CR byte 导致 multipart 截断"、"$FLAG 为空因为没带 session"）。

**正确的纠偏**：方向性的（"这条路已经试了 N 次，应该换方向"、"应该去查 $FLAG 来源而不是调整传输格式"）
**错误的纠偏**：技术性的（"CR byte 是截断的原因"、"你需要用 fastcoll 生成新的碰撞对"）

纠偏消息格式要求：
- 说明当前方向已试了多少次
- 指出应该切换到哪个大方向（不要给具体命令）
- 让 Solver 自己验证并选择具体手段

好：「当前 multipart 传输方向已尝试 8 次，应该切换到调查 $FLAG 来源（php.ini、环境变量等）」
坏：「CR byte 导致了截断，你需要用 xxd 检查第 110 字节的值」

## ⚠️ 发纠偏前必须先区分失败态（极重要）

对于使用 `highlight_file(__FILE__)` 的 PHP 题，存在两种外观相似但含义完全不同的失败态，你必须先判断 Solver 当前处于哪种失败态，才能给出正确的纠偏方向：

| 失败态 | `</code>` 之后的内容 | 含义 | 正确纠偏方向 |
|---|---|---|---|
| **态 1：旁路成功，$FLAG 为空** | 空字符串（0 字节） | md5 条件已过，进入了 `echo $FLAG`，但 `$FLAG` 本身为空 | 调查 `$FLAG` 来源（/proc/self/environ、php.ini、.user.ini） |
| **态 2：传输/比较失败** | 出现"没活儿"等错误字符串 | md5 比较条件未过，没有进入 flag 分支 | 调整碰撞对传输格式（null byte、boundary、multipart 结构） |

**禁止**：同一条纠偏消息同时适用于态 1 和态 2，因为两者的调查方向截然相反。
**禁止**：在观察到态 1 时，继续让 Solver 调整 multipart 格式（那是态 2 的手段）。
**要求**：纠偏消息必须明确说明当前判断是哪种失败态，以及对应的下一步操作。

## ⚠️ flag 判断规则（极重要）
只有当工具结果中出现**符合 flag 格式的完整字符串**（如 `NSSCTF{...}`、`flag{...}`、`CTF{...}`）时，才能断言"flag 已出现"。
以下情况**不算 flag 出现**，禁止据此发纠偏：
- HTML `<title>` 标签内容含 "flag" 字样（如 `<title>flag，我TM来了！</title>`）
- 按钮文字、页面标题、图片 alt 属性含 "flag"
- 任何不匹配 `XXX{...}` 格式的"flag"出现

纠偏消息要简短有力，直接给出下一步方向：
好：「当前 SQLi 方向已验证无效，建议转向文件包含，尝试 ?page=../../../etc/passwd」
坏：「你需要重新思考解题方向」

## 标记 idea 为 failed 前必须确认
1. 否定的是整条路线，还是只否定了某个 payload/子分支？
2. 是否还有合理变体未验证？
3. 更适合记 failure memory 而不是关闭主线吗？
任意一个不能排除 → 不标 failed，改记 failure boundary。

## 多 Flag 题专项审查（极重要）
当题目有多个 flag（flag_count > 1）时，需要额外审查：
1. Solver 提交了一个 flag 后是否继续在寻找下一个？如果停下来了，立即 send_correction：「本题有 N 个 flag，已提交 M 个，还剩 K 个。立即执行提权/横向移动/内网探测寻找下一个 flag」
2. Solver 是否在用 `find / -name flag*` 搜索当前机器上的所有 flag？
3. Solver 是否检查了提权路径（sudo -l, SUID, capabilities）？
4. Solver 是否探测了内网（ip addr, /proc/net/arp）？

## 验证码过度工程化检测（极重要）
当 Solver 在做验证码识别时，如果出现以下情况，立即 send_correction：
1. Solver 连续 5+ 轮在做验证码形状分析/模板制作/OCR 调试，而没有写端到端自动登录脚本
2. Solver 在反复抓取验证码图片但从不尝试提交登录
3. 纠偏消息：「验证码分析已花 5+ 轮，立即切换到端到端自动登录脚本。不要追求 100% 识别率，用登录响应差异在线校准。」

## 重跑未重建已有解法检测（极重要）
当题目是重跑轮次（correct_flag_count > 0）时，如果 Solver 在重新从零探测而不是按 memory 重建已有解法，立即 send_correction：
1. Solver 在重新探测 LFI 深度、目录扫描、弱口令等，但 memory 中已有完整的攻击链
2. 纠偏消息：「这是重跑轮次，memory 中已记录了完整攻击链。不要从零重新探测，直接按 memory 中的步骤重建 RCE/立足点，然后验证内网拓扑（IP 可能变化），再用新 IP 执行横向移动。」

## LFI 已确认但未尝试 /challenge/ 检测（极重要）
当 Solver 已确认 LFI/任意文件读取可用，但超过 10 轮仍未尝试 `/challenge/flag*.txt` 时，立即 send_correction：
- 纠偏消息：「LFI 已确认可用，但你尚未尝试读取 /challenge/flag.txt、/challenge/flag1.txt。本平台所有题目的 flag 都放在 /challenge/ 目录，这是已知的环境特征。立即用 LFI 读取这些文件，不要继续读源码。」

## Webshell 内网操作效率检测
当 Solver 通过 webshell 执行内网操作但效率极低时（如用 PHP fsockopen 逐个连端口），提示：
1. 上传 PHP 代理脚本或 Python 脚本（见 /skills/pentest/SKILL.md 阶段 2.9）
2. 纠偏消息：「通过 webshell 逐个 fsockopen 太低效，上传 PHP 代理脚本后可直接 curl 内网服务，或上传 Python 脚本用 paramiko 连 SSH。」

## 二进制/逆向题专项审查
当 Solver 在做二进制/逆向题时，需要审查：
1. Solver 是否在手动计算 hex 值？如果是，send_correction：「禁止手动计算 hex 值，必须写 Python 脚本处理所有字节操作」
2. Solver 是否在重复尝试同一个 patch 方案？如果 patch 后程序仍然失败，应该换 patch 位置或改变策略
3. Solver 是否用了 ltrace/strace 进行动态分析？如果只做静态分析且卡住，建议动态分析

## Output Contract
无需改动时，直接回复 NO_CHANGE。
有改动时，简短说明做了什么（1-3 句话）。
"""


def _build_observer_prompt(recent_rounds: list[dict], challenge_dir: Path) -> str:
    memories = mem_store.list_memory(challenge_dir, limit=12)
    ideas = idea_store.list_ideas(challenge_dir, limit=8)

    lines = ["## 当前看板状态"]

    if memories:
        lines.append(f"### Memory（{len(memories)} 条）")
        # 超限时注入强制清理指令
        non_evidence = [m for m in memories if m.kind != "evidence"]
        if len(non_evidence) > 10:
            lines.append(f"\n⚠️ **Memory 超限**：非 evidence 条目已达 {len(non_evidence)} 条（上限 10）。"
                         f"请先合并同类项或删除过时条目，再做其他工作。\n")
        for m in memories:
            lines.append(f"- [{m.kind}] {m.id}: {m.content}")
    else:
        lines.append("### Memory（空）")

    if ideas:
        lines.append("### Ideas")
        for i in ideas:
            result_str = f" → {i.result}" if i.result else ""
            lines.append(f"- [{i.status}] {i.id}: {i.content}{result_str}")
    else:
        lines.append("### Ideas（空）")

    # 告知 Observer 真实的 history 文件路径
    history_path = str((challenge_dir / ".solver-history.jsonl").resolve())
    lines.append(f"\n## history_path\n`{history_path}`")

    lines.append("\n## Solver 最近行为摘要")
    for r in recent_rounds[-6:]:
        round_num = r.get("round", "?")
        tool_calls = r.get("tool_calls", [])
        lines.append(f"\n### 第 {round_num} 轮")
        if tool_calls:
            for tc in tool_calls:
                tool = tc.get("tool", "")
                args_str = str(tc.get("args", ""))[:100]
                result_str = str(tc.get("result", ""))[-200:]
                lines.append(f"- 工具: {tool}({args_str})")
                lines.append(f"  结果: {result_str}")
        else:
            lines.append("- 无工具调用")

    # ━━ 未利用情报检测 ━━
    # 扫描 evidence/fact 中的关键信息，检查是否出现在最近工具调用参数中
    intel_memories = [m for m in memories if m.kind in ("evidence", "fact")]
    if intel_memories and recent_rounds:
        import re
        # 收集最近所有工具调用的参数文本
        all_args_text = ""
        for r in recent_rounds:
            for tc in r.get("tool_calls", []):
                all_args_text += str(tc.get("args", "")).lower() + " "
                all_args_text += str(tc.get("result", ""))[-500:].lower() + " "

        unused_intel = []
        for m in intel_memories:
            content = m.content
            keywords = []
            # IP 地址
            keywords.extend(re.findall(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', content))
            # 密码/token/key 值
            keywords.extend(re.findall(
                r'(?:password|passwd|pwd|token|key|secret|密码|口令)[=：:\s]+([^\s,，。;；]+)',
                content, re.IGNORECASE
            ))
            # 用户名
            keywords.extend(re.findall(
                r'(?:user|username|用户名|账号)[=：:\s]+([^\s,，。;；]+)',
                content, re.IGNORECASE
            ))
            # URL 路径
            paths = re.findall(r'(/[a-zA-Z0-9_\-./]+)', content)
            keywords.extend([p for p in paths if len(p) > 3])
            # 端口
            keywords.extend(re.findall(
                r'(?:端口|port)[=：:\s]*(\d{2,5})', content, re.IGNORECASE
            ))

            if not keywords:
                continue

            unused_keys = [k for k in keywords if k.lower() not in all_args_text]
            if unused_keys:
                unused_intel.append({
                    "memory_id": m.id,
                    "content": content,
                    "unused_keywords": unused_keys,
                })

        if unused_intel:
            lines.append("\n## ⚠️ 未利用情报（Solver 从未在工具调用中使用过以下信息）")
            for item in unused_intel:
                keys_str = ", ".join(item["unused_keywords"][:5])
                lines.append(f"- Memory `{item['memory_id']}`: {item['content']}")
                lines.append(f"  未使用的关键信息: {keys_str}")
            lines.append("")
            lines.append("**请立即 send_correction 提醒 Solver 利用以上情报。**")

    lines.append("\n请审查以上信息，按 Core Loop 执行。")
    return "\n".join(lines)


_emit_lock = threading.Lock()


def _emit(event_type: str, data=None) -> None:
    msg = {"type": event_type, "data": data}
    with _emit_lock:
        sys.stdout.write(serialize(msg))
        sys.stdout.flush()


class ObserverAgent:
    def __init__(self, settings: dict):
        llm_cfg = settings.get("llm", {})
        self.client = OpenAI(
            base_url=llm_cfg.get("base_url") or os.environ.get("LLM_BASE_URL", ""),
            api_key=llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY", ""),
        )
        self.model = llm_cfg.get("observer_model") or llm_cfg.get("default_model") or os.environ.get("LLM_MODEL", "deepseek-chat")

    def review(self, recent_rounds: list[dict], challenge_dir: Path,
               on_correction: callable = None) -> str:
        user_prompt = _build_observer_prompt(recent_rounds, challenge_dir)

        tool_executors = {
            "read_file":       read_file,
            "memory_list":    memory_list,
            "memory_add":     memory_add,
            "memory_delete":  memory_delete,
            "memory_update":  memory_update,
            "idea_list":      idea_list,
            "idea_add":       idea_add,
            "idea_update":    idea_update,
            "send_correction": lambda args: _handle_correction(args, on_correction),
        }

        messages = [
            {"role": "system", "content": OBSERVER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # Observer 自己也是一个小 ReAct 循环，但最多跑 5 轮（省 token）
        for _ in range(5):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=OBSERVER_TOOL_DEFS,
                tool_choice="auto",
            )

            msg = response.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))

            if not msg.tool_calls:
                summary = msg.content or "NO_CHANGE"
                _emit("observer_end", {"summary": summary})
                return summary

            for tool_call in msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                executor = tool_executors.get(tool_name)
                if executor:
                    try:
                        result = executor(tool_args)
                    except Exception as e:
                        result = f"[错误] {e}"
                else:
                    result = f"[错误] 未知工具：{tool_name}"

                _emit("observer_tool", {"tool": tool_name, "result": result[:200]})

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        return "NO_CHANGE"


def _handle_correction(args: dict, on_correction: callable) -> str:
    message = args.get("message", "").strip()
    if not message:
        return "[错误] 纠偏消息不能为空"
    if on_correction:
        on_correction(message)
    _emit("observer_correction", {"message": message})
    return f"[纠偏] 已发送：{message}"
