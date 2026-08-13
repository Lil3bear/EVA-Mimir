import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

from openai import OpenAI

from solver.tools import bash_tool, file_tools, memory_tools, idea_tools, bridge_tools, search_tool
from solver.observer.loop import ObserverLoop
from solver.worker_context import ctx as _ctx
from shared.jsonl import serialize


# 线程安全的 stdout 输出锁
_emit_lock = threading.Lock()


# 工具定义注册表
TOOL_DEFS = [
    bash_tool.TOOL_DEF,
    file_tools.READ_TOOL_DEF,
    file_tools.WRITE_TOOL_DEF,
    file_tools.GREP_TOOL_DEF,
    memory_tools.MEMORY_ADD_TOOL_DEF,
    memory_tools.MEMORY_LIST_TOOL_DEF,
    idea_tools.IDEA_LIST_TOOL_DEF,
    search_tool.TOOL_DEF,
    bridge_tools.SUBMIT_FLAG_TOOL_DEF,
    bridge_tools.GET_STATE_TOOL_DEF,
    bridge_tools.GET_HINT_TOOL_DEF,
    bridge_tools.START_CHALLENGE_TOOL_DEF,
    bridge_tools.CLOSE_CHALLENGE_TOOL_DEF,
]

# 工具执行分发表
TOOL_EXECUTORS = {
    "bash":                    bash_tool.execute,
    "read_file":               file_tools.read_file,
    "write_file":              file_tools.write_file,
    "grep":                    file_tools.grep,
    "memory_add":              memory_tools.memory_add,
    "memory_list":             memory_tools.memory_list,
    "idea_list":               idea_tools.idea_list,
    "security_search":         search_tool.search,
    "challenge_submit_flag":   bridge_tools.submit_flag,
    "challenge_get_state":     bridge_tools.get_state,
    "challenge_get_hint":      bridge_tools.get_hint,
    "challenge_start":          bridge_tools.start_challenge,
    "challenge_close":          bridge_tools.close_challenge,
}


def _emit(event_type: str, data: Any = None) -> None:
    msg = {"type": event_type, "data": data}
    with _emit_lock:
        sys.stdout.write(serialize(msg))
        sys.stdout.flush()


def _load_skills_index(skills_dir: str) -> str:
    skills_path = Path(skills_dir)
    if not skills_path.exists():
        return ""
    lines = ["## 可用 Skills（需要时用 read_file 加载完整内容）"]
    for skill_md in sorted(skills_path.rglob("SKILL.md")):
        try:
            first_line = skill_md.read_text().split("\n")[0].lstrip("#").strip()
        except Exception:
            first_line = skill_md.parent.name
        rel = skill_md.relative_to(skills_path)
        lines.append(f"- `/skills/{rel}` — {first_line}")
    return "\n".join(lines)


def _build_system_prompt(skills_dir: str, prompt_file: str = "") -> str:
    # 确定 prompt 文件路径，优先用参数，其次用同目录的 prompts/solver.md
    if not prompt_file:
        prompt_file = str(Path(__file__).parent.parent / "prompts" / "solver.md")

    try:
        base_prompt = Path(prompt_file).read_text(encoding="utf-8").strip()
    except Exception as e:
        raise RuntimeError(f"无法读取 prompt 文件 {prompt_file}：{e}")

    skills_index = _load_skills_index(skills_dir)
    if skills_index:
        base_prompt += f"\n\n{skills_index}\n"
        base_prompt += "\n需要特定技术知识时，用 read_file 加载对应 SKILL.md 全文。\n"

    return base_prompt


# 渗透阶段定义
_PHASES = ("RECON", "INITIAL_ACCESS", "POST_EXPLOIT", "DATA_EXFIL")

_PHASE_PROMPTS = {
    "INITIAL_ACCESS": (
        "[阶段切换 → INITIAL_ACCESS] 已获得目标系统的初始访问权限。\n"
        "立即执行以下标准动作：\n"
        "1. whoami && id → 确认当前权限\n"
        "2. uname -a && cat /etc/os-release → 系统版本\n"
        "3. ip addr && cat /etc/hosts → 网络拓扑\n"
        "4. find / -perm -4000 2>/dev/null → SUID 提权\n"
        "5. cat /etc/shadow 2>/dev/null → 凭证收集\n"
        "6. history && env → 泄露的凭证/连接串\n"
        "7. crontab -l && ls /etc/cron* 2>/dev/null → 定时任务\n"
        "8. arp -a && netstat -tlnp 2>/dev/null → 内网资产发现\n"
        "每发现一个新信息立即用 memory_add 记录！"
    ),
    "POST_EXPLOIT": (
        "[阶段切换 → POST_EXPLOIT] 已提交部分 flag，进入后渗透阶段。\n"
        "必须继续寻找剩余 flag，立即执行：\n"
        "1. sudo -l → 检查提权路径\n"
        "2. find / -name 'flag*' -o -name '*.key' -o -name 'secret*' 2>/dev/null → 搜索 flag 文件\n"
        "3. cat /proc/net/arp && ip route → 内网资产\n"
        "4. grep -r 'password\\|passwd\\|credential' /var/www/ /etc/ /home/ /opt/ 2>/dev/null | head -30 → 凭据\n"
        "5. ls -la /home/*/.ssh/ /root/.ssh/ 2>/dev/null → SSH 密钥\n"
        "6. 检查数据库连接串 → mysql/redis/mongodb\n"
        "绝对不能停下来，必须找到所有 flag！"
    ),
    "DATA_EXFIL": (
        "[阶段切换 → DATA_EXFIL] 发现内网资产，进入数据挖掘阶段。\n"
        "对每个发现的内网主机：\n"
        "1. 用已有凭据尝试 SSH/数据库连接\n"
        "2. curl 探测常见端口（80/443/8080/3306/6379/27017）\n"
        "3. 每台机器都搜索 flag 文件\n"
        "4. 检查是否可以跳板到更深层网络"
    ),
}


# 按难度分级的默认 max_rounds
_DIFFICULTY_MAX_ROUNDS = {
    "easy": 30,
    "medium": 60,
    "hard": 100,
    "difficult": 100,
}

# B 类多阶段渗透题额外轮次加成（多 flag 题需要更多探索时间）
# 第6轮复盘：b类全挂(0/3)，max_rounds不足是主因，大幅提升
_PENTEST_EXTRA_ROUNDS = {
    "easy": 40,      # 30 -> 70
    "medium": 120,   # 60 -> 180
    "hard": 80,      # 100 -> 180
    "difficult": 80, # 100 -> 180
}


class SolverAgent:
    def __init__(self, task: str, settings: dict, skills_dir: str):
        self.task = task
        self.skills_dir = skills_dir
        self.prompt_file = settings.get("solver", {}).get("prompt_file", "")
        # 从 task 中提取难度，按难度分级设定 max_rounds
        difficulty = self._extract_difficulty(task)
        default_rounds = _DIFFICULTY_MAX_ROUNDS.get(difficulty, 100)
        # B 类多阶段渗透题（多 flag）额外加轮次
        is_pentest = self._is_pentest_challenge(task)
        if is_pentest:
            extra = _PENTEST_EXTRA_ROUNDS.get(difficulty, 20)
            default_rounds += extra
        self.max_rounds = settings.get("solver", {}).get("max_rounds") or default_rounds
        self._target_url = ""
        # 从 task 中提取 URL
        for line in task.splitlines():
            if "目标地址：" in line or "目标：" in line:
                parts = line.split("：", 1)
                if len(parts) > 1:
                    self._target_url = parts[1].strip()
                    break

        # 渗透阶段状态机
        self._phase = "RECON"
        self._got_shell = False  # 是否已检测到获得 shell
        self._submitted_flag_count = 0  # 已提交的 flag 数
        self._found_internal_ips: set[str] = set()  # 已发现的内网 IP

        llm_cfg = settings.get("llm", {})
        self.client = OpenAI(
            base_url=llm_cfg.get("base_url") or os.environ.get("LLM_BASE_URL", ""),
            api_key=llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY", ""),
        )
        self.model = llm_cfg.get("default_model") or os.environ.get("LLM_MODEL", "deepseek-chat")
        # 摘要压缩用主模型 — 摘要质量直接影响压缩后的解题能力
        # （便宜模型可能丢失关键 payload/凭据细节，风险太高）
        self._summary_model = llm_cfg.get("summary_model") or self.model
        search_tool.init(settings)
        self.messages: list[dict] = []
        self._pending_injections: list[str] = []  # 缓冲 observer 注入，下一轮开始时注入
        self.round = 0
        # 纠偏不服从检测
        self._last_correction: str | None = None
        self._last_correction_round: int = 0
        self._correction_repeat_count: int = 0
        # history 路径按题目隔离（并行安全）
        challenge_dir = _ctx.challenge_dir or "/root/workspace"
        self._history_path = os.path.join(challenge_dir, ".solver-history.jsonl")
        # ✅ 按难度动态调整 Observer 频率
        difficulty = self._extract_difficulty(task)
        default_observer_every = {"easy": 10, "medium": 8, "hard": 6, "difficult": 6}
        observer_every = settings.get("solver", {}).get(
            "observer_every_rounds",
            default_observer_every.get(difficulty, 6)
        )
        self.observer = ObserverLoop(
            settings={**settings, "solver": {**settings.get("solver", {}), "observer_every_rounds": observer_every}},
            on_correction=self.inject_message,
        )
        # 注册 approach 循环触发 Observer 的回调
        bash_tool.register_observer_trigger(
            lambda reason="": self.observer.trigger_now(reason=reason)
        )

    def run(self) -> None:
        system_prompt = _build_system_prompt(self.skills_dir, self.prompt_file)
        self.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self.task},
        ]

        _emit("agent_start", {"task": self.task[:200]})

        consecutive_empty = 0
        while self.round < self.max_rounds:
            self.round += 1

            # ━━ 硬约束：无进展强制停止（代码层，不靠 Observer） ━━
            difficulty = self._extract_difficulty(self.task)
            if self._should_force_stop(difficulty):
                self.observer.on_agent_end()
                _emit("agent_end", {"rounds": self.round, "reason": "force_stop_no_progress"})
                return

            _emit("round_start", {"round": self.round})
            self.observer.on_round_start(self.round)

            # 纠偏消息在本轮 LLM 调用前注入（而非上一轮末尾），确保 Solver 必须看到
            for msg_content in self._pending_injections:
                self.messages.append({"role": "user", "content": msg_content})
            self._pending_injections.clear()

            # 每 6 轮自动注入一次 Memory+Ideas 状态快照，不依赖 Solver 主动查
            if self.round % 6 == 0:
                snapshot = self._build_state_snapshot()
                if snapshot:
                    self.messages.append({"role": "user", "content": snapshot})

            # 每 20 轮强制回顾：注入更强的指令要求 Solver 审视已知信息
            if self.round % 20 == 0:
                review_msg = self._build_forced_review()
                if review_msg:
                    self.messages.append({"role": "user", "content": review_msg})

            # 历史过长时压缩：先生成语义摘要，再裁到最近 N 条
            # ✅ 优化：基于总字符数而非消息数触发压缩，更精确控制 token 消耗
            total_chars = sum(len(str(m.get("content", ""))) for m in self.messages)
            if total_chars > 30000 or len(self.messages) > 40:
                self.messages = self._compress_context()

            # deepseek-v4-pro (thinking model) 不支持 tool_choice="required"
            is_thinking = "v4" in self.model or "think" in self.model.lower()
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=TOOL_DEFS,
                tool_choice="auto" if is_thinking else "required",
            )

            msg = response.choices[0].message
            self.messages.append(msg.model_dump(exclude_none=True))

            # 无工具调用（thinking 模型用 auto 时可能发生）
            if not msg.tool_calls:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    _emit("agent_end", {"rounds": self.round, "reason": "stuck_no_tool"})
                    return
                # nudge：撤销本轮计数，追加 user 消息后重试
                self.round -= 1
                self.messages.append({
                    "role": "user",
                    "content": f"请立即调用 bash 工具执行：curl -si {self._target_url}",
                })
                continue

            consecutive_empty = 0
            solved = False

            # 执行所有工具调用
            for tool_call in msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                _emit("tool_call", {
                    "tool": tool_name,
                    "args": tool_args,
                    "call_id": tool_call.id,
                })

                executor = TOOL_EXECUTORS.get(tool_name)
                if executor:
                    try:
                        result = executor(tool_args)
                    except Exception as e:
                        result = f"[错误] 工具执行异常：{e}"
                else:
                    result = f"[错误] 未知工具：{tool_name}"

                _emit("tool_result", {
                    "tool": tool_name,
                    "call_id": tool_call.id,
                    "result": result[:2000],
                })

                self.observer.on_tool_call(tool_name, tool_args, result)

                # ✅ 智能截断 tool result，平衡 token 节省与信息保留
                truncated_result = result
                _TRUNCATE_LIMIT = 6000  # 普通工具输出上限
                _SKILL_LIMIT = 12000    # Skills 文件允许更大（是解题知识）

                if tool_name == "read_file" and "/skills/" in str(tool_args.get("path", "")):
                    # Skills 文件是解题知识，允许更大但仍设上限
                    if len(result) > _SKILL_LIMIT:
                        truncated_result = result[:_SKILL_LIMIT] + f"\n\n[截断] 原始 {len(result)} 字符，已截取前 {_SKILL_LIMIT}。"
                elif len(result) > _TRUNCATE_LIMIT:
                    # 普通工具输出：保留头尾（头部有响应头，尾部有错误信息/flag）
                    head_size = _TRUNCATE_LIMIT // 2
                    tail_size = _TRUNCATE_LIMIT // 2
                    truncated_result = (
                        result[:head_size]
                        + f"\n\n[截断] 原始输出 {len(result)} 字符，已保留头尾各 {head_size} 字符。"
                        f"如需完整内容，用 grep 或 read_file 定位具体段落。\n\n"
                        + result[-tail_size:]
                    )

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": truncated_result,
                })

                # hint 返回后立即触发 Observer（不等下一个周期）
                if tool_name == "challenge_get_hint":
                    self.observer.trigger_now(reason="hint_received")

                # ━━ 纠偏不服从检测 ━━
                self._check_correction_compliance(tool_name, tool_args)

                # ━━ 渗透阶段自动检测 ━━
                self._detect_phase_transition(tool_name, tool_args, result)

                # flag 提交成功：只有全部 flag 找到才结束，多 flag 题提交一个后继续找下一个
                if tool_name == "challenge_submit_flag" and "正确" in result:
                    if "全部 Flag 已找到" in result:
                        solved = True
                        break
                    # 多 flag 题：提交成功一个但未完成，强制注入继续寻找提示
                    # result 里已含进度和"还有剩余 Flag"提示
                    # 额外注入一条强制指令，确保 Solver 不会停下
                    self._pending_injections.append(
                        f"[多 Flag 提醒] {result} "
                        f"\n\n立即执行以下操作继续寻找下一个 flag："
                        f"\n1. challenge_get_state 查看剩余 flag 数"
                        f"\n2. find / -name 'flag*' 2>/dev/null 搜索当前机器"
                        f"\n3. sudo -l 检查提权路径"
                        f"\n4. ip addr && cat /proc/net/arp 探测内网"
                        f"\n5. grep -r 'password\\|passwd' /var/www/ /etc/ /home/ 2>/dev/null | head -20 收集凭据"
                        f"\n绝对不能停下来，必须继续！"
                    )

            _emit("round_end", {"round": self.round})
            self.observer.on_round_end(self.round)
            self._write_history()

            if solved:
                self.observer.on_agent_end()
                _emit("agent_end", {"rounds": self.round, "reason": "solved"})
                return

        self.observer.on_agent_end()
        _emit("agent_end", {"rounds": self.round, "reason": "max_rounds"})

    def inject_message(self, content: str) -> None:
        # 纠偏消息加前缀，让 Solver 能识别并优先响应
        prefixed = f"[OBSERVER] {content}"
        self._pending_injections.append(prefixed)
        # 记录最后一次纠偏内容和轮次，用于不服从检测
        self._last_correction = content
        self._last_correction_round = self.round
        self._correction_repeat_count = 0

    def _check_correction_compliance(self, tool_name: str, tool_args: dict) -> None:
        """检测 Solver 是否服从了 Observer 纠偏。
        如果纠偏后 2 轮内 Solver 仍在做纠偏明确禁止的事，强制重复纠偏。
        """
        if not self._last_correction:
            return
        if self.round - self._last_correction_round > 2:
            # 纠偏已超过 2 轮，不再检测
            self._last_correction = None
            return

        correction = self._last_correction.lower()
        # 检测纠偏中明确禁止的关键词
        forbidden_patterns = []
        for keyword in ["勿再试", "已穷尽", "已死", "禁止再碰", "不要再",
                        "停止再", "止到此", "别再耗", "不得再"]:
            if keyword in correction:
                # 提取禁止的方向关键词
                import re
                # 找“勿再试 XXX”中的 XXX
                for m in re.finditer(rf'{keyword}[^。，\n]{{0,30}}', correction):
                    forbidden_patterns.append(m.group())

        if not forbidden_patterns:
            return

        # 检查当前 tool_call 是否触及禁止的方向
        if tool_name == "bash":
            cmd = str(tool_args.get("cmd", "")).lower()
            # 简单检测：如果纠偏提到了特定 URL 或路径，而 Solver 还在访问
            violation = False
            for pattern in forbidden_patterns:
                # 提取纠偏中的关键路径/URL
                for kw in ["flag.txt", "/flag", "login", "upload",
                           "download.php", "system-init"]:
                    if kw in pattern and kw in cmd:
                        violation = True
                        break

            if violation:
                self._correction_repeat_count += 1
                if self._correction_repeat_count <= 2:
                    self._pending_injections.append(
                        f"[OBSERVER 强制重复] 你没有服从上次纠偏指令！"
                        f"纠偏内容：{self._last_correction[:300]}\n"
                        f"你必须立即停止当前方向，按照纠偏指令执行！"
                    )

    def _write_history(self) -> None:
        try:
            # 只保留最近 20 条，跳过 system prompt
            recent = [m for m in self.messages if m.get("role") != "system"][-20:]
            with open(self._history_path, "w", encoding="utf-8") as f:
                for m in recent:
                    f.write(json.dumps(m, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _compress_context(self) -> list[dict]:
        system = self.messages[0]

        # 提取全历史中的 [OBSERVER] 纠偏消息，压缩后固定钉在末尾
        observer_msgs = [
            m for m in self.messages
            if m.get("role") == "user"
            and isinstance(m.get("content"), str)
            and m["content"].startswith("[OBSERVER]")
        ]
        non_observer = [
            m for m in self.messages[1:]
            if not (
                m.get("role") == "user"
                and isinstance(m.get("content"), str)
                and m["content"].startswith("[OBSERVER]")
            )
        ]

        # ✅ 优化：动态计算保留数量，目标是保留的消息总字符数 < 15000
        tail = non_observer[-25:]  # 先取最近 25 条
        while tail and tail[0].get("role") == "tool":
            tail = tail[1:]

        # 如果 tail 还是太大，继续缩减
        while len(tail) > 10:
            tail_chars = sum(len(str(m.get("content", ""))) for m in tail)
            if tail_chars <= 15000:
                break
            tail = tail[2:]  # 从前面移除，保留最新的
            while tail and tail[0].get("role") == "tool":
                tail = tail[1:]

        summary = self._generate_summary()
        summary_msg = {
            "role": "user",
            "content": (
                "[上下文已压缩，以下是截至当前的解题状态摘要，请以此为基础继续]\n\n"
                + summary
            ),
        }
        # 只保留最近 2 条 observer 纠偏（防止堆积），固定在最末尾
        return [system, summary_msg] + tail + observer_msgs[-2:]

    def _generate_summary(self) -> str:
        SUMMARY_PROMPT = (
            "你正在解 CTF 题。请根据以上对话历史和状态快照，用中文生成一份简洁的当前状态摘要。\n"
            "凭据、已知事实、失败边界已由 Memory 看板记录，不需要重复。"
            "你只需摘要以下两点（每点 1-3 行）：\n"
            "1. 当前正在尝试的攻击路线和具体技术细节（payload 格式、编码方式、工具用法等）\n"
            "2. 下一步计划（如果当前方向卡住了，应该转向什么）\n"
            "不要超过 200 字。"
        )
        try:
            # 只用最近 15 条消息 + memory/ideas 状态做摘要
            recent_for_summary = [m for m in self.messages[1:] if m.get("role") != "system"][-15:]
            while recent_for_summary and recent_for_summary[0].get("role") == "tool":
                recent_for_summary = recent_for_summary[1:]

            # 注入当前 memory/ideas 状态，弥补截断的历史
            state_snapshot = self._build_state_snapshot()
            if state_snapshot:
                recent_for_summary.insert(0, {"role": "user", "content": state_snapshot})

            recent_for_summary.append({"role": "user", "content": SUMMARY_PROMPT})

            summary_model = self._summary_model or self.model

            resp = self.client.chat.completions.create(
                model=summary_model,
                messages=recent_for_summary,
                tools=None,
                tool_choice=None,
                max_tokens=400,
            )
            return resp.choices[0].message.content or "（摘要生成失败）"
        except Exception as e:
            # 兜底：摘要 LLM 调用失败时，用 Memory + Ideas 状态拼接最小可用摘要
            # 防止压缩后上下文完全丢失（"失忆"导致全题报废）
            fallback_parts = [f"（摘要 LLM 调用失败：{e}，以下为自动生成的状态摘要）"]
            try:
                snapshot = self._build_state_snapshot()
                if snapshot:
                    fallback_parts.append(snapshot)
                # 提取最近 3 条 assistant 消息的 content 片段
                recent_actions = [
                    m.get("content", "")[:150]
                    for m in self.messages[-10:]
                    if m.get("role") == "assistant" and m.get("content")
                ][-3:]
                if recent_actions:
                    fallback_parts.append("最近操作摘要：" + " → ".join(recent_actions))
            except Exception:
                pass
            return "\n".join(fallback_parts) if len(fallback_parts) > 1 else f"（摘要生成失败：{e})"

    def _build_forced_review(self) -> str:
        """
        每 20 轮强制注入的回顾消息。
        与 6 轮快照不同，这里明确要求 Solver 停下来审视已知信息，
        检查是否有未利用的凭据/路径/信息。
        """
        try:
            from shared.data import memory as mem_store, ideas as idea_store
            challenge_dir = Path(_ctx.challenge_dir or "/root/workspace")
            memories = mem_store.list_memory(challenge_dir, limit=15)
            ideas = idea_store.list_ideas(challenge_dir, limit=10)
        except Exception:
            return ""

        lines = [
            f"\u26a0\ufe0f [\u5f3a\u5236\u56de\u987e - \u7b2c {self.round} \u8f6e] \u8bf7\u7acb\u5373\u505c\u4e0b\u5f53\u524d\u64cd\u4f5c\uff0c\u5ba1\u89c6\u4ee5\u4e0b\u5df2\u77e5\u4fe1\u606f\uff1a",
            "",
        ]

        # 列出所有凭据类 memory
        credentials = [m for m in memories if m.kind in ('credential', 'evidence', 'discovery')]
        if credentials:
            lines.append("\U0001f511 \u5df2\u83b7\u53d6\u7684\u51ed\u636e/\u53d1\u73b0\uff1a")
            for m in credentials:
                lines.append(f"  - [{m.kind}] {m.content}")
            lines.append("")

        # 列出\u672a\u5229\u7528\u7684 pending ideas
        pending = [i for i in ideas if i.status == 'pending']
        if pending:
            lines.append("\U0001f4cb \u672a\u63a2\u7d22\u7684\u65b9\u5411\uff1a")
            for i in pending:
                lines.append(f"  - {i.content}")
            lines.append("")

        # \u5217\u51fa\u5931\u8d25\u7684\u65b9\u5411
        failed = [i for i in ideas if i.status == 'failed']
        if failed:
            lines.append("\u26d4 \u5df2\u5931\u8d25\u7684\u65b9\u5411\uff08\u7981\u6b62\u91cd\u590d\uff09\uff1a")
            for i in failed:
                result_str = f"\uff08{i.result}\uff09" if i.result else ""
                lines.append(f"  - {i.content}{result_str}")
            lines.append("")

        lines.append(
            "\u8bf7\u68c0\u67e5\uff1a"
            "1. \u4ee5\u4e0a\u51ed\u636e/\u53d1\u73b0\u4e2d\uff0c\u662f\u5426\u6709\u672a\u5229\u7528\u7684\uff08\u5982\u5bc6\u7801\u672a\u767b\u5f55\u3001\u8def\u5f84\u672a\u8bbf\u95ee\uff09\uff1f"
            "2. \u672a\u63a2\u7d22\u7684\u65b9\u5411\u4e2d\uff0c\u662f\u5426\u6709\u66f4\u6709\u5e0c\u671b\u7684\uff1f"
            "3. \u5f53\u524d\u65b9\u5411\u662f\u5426\u5df2\u7ecf\u5c1d\u8bd5\u592a\u591a\u6b21\uff0c\u5e94\u8be5\u6362\u65b9\u5411\uff1f"
            "\u5ba1\u89c6\u540e\u518d\u7ee7\u7eed\u89e3\u9898\u3002"
        )

        return "\n".join(lines)

    @staticmethod
    def _extract_difficulty(task: str) -> str:
        """从 task 文本中提取难度（easy/medium/hard）。"""
        for line in task.splitlines():
            if '难度' in line:
                lower = line.lower()
                for d in ('easy', 'hard', 'difficult', 'medium'):
                    if d in lower:
                        return d
        return ''

    def _build_state_snapshot(self) -> str:
        """
        读取当前 Memory 和 Ideas，生成状态快照注入 Solver 上下文。
        每 6 轮自动注入，不依赖 Solver 主动调用 memory_list/idea_list。
        按优先级分层：evidence 必注入 > fact > failure（限最近 5 条）> note（限最近 2 条）
        """
        try:
            from shared.data import memory as mem_store, ideas as idea_store
            # 优先从 thread-local 上下文读取（并行安全）
            if _ctx.challenge_dir and _ctx.challenge_dir != "/workspace":
                challenge_dir = Path(_ctx.challenge_dir)
            else:
                challenge_dir_str = os.environ.get("CTF_WORKSPACE", "/workspace")
                challenge_id = os.environ.get("CTF_CHALLENGE_ID", "")
                challenge_dir = Path(challenge_dir_str) / challenge_id if challenge_id else Path(challenge_dir_str)

            memories = mem_store.list_memory(challenge_dir)
            ideas = idea_store.list_ideas(challenge_dir, limit=8)
        except Exception:
            return ""

        lines = ["[状态快照] 当前看板（自动注入，请对照行动）："]

        # ━━ 第一层：evidence（凭据）— 永远全量注入，丢了就解不了题
        evidence = [m for m in memories if m.kind == "evidence"]
        if evidence:
            lines.append("🔑 关键凭据（必须保留）：")
            for m in evidence:
                lines.append(f"  - {m.content}")

        # ━━ 第二层：fact（已确认事实）— 全量注入
        facts = [m for m in memories if m.kind == "fact"]
        if facts:
            lines.append("ℹ️ 已知事实：")
            for m in facts:
                lines.append(f"  - {m.content}")

        # ━━ 第三层：failure（失败边界）— 只保留最近 5 条，避免堆积
        failures = [m for m in memories if m.kind == "failure"]
        if failures:
            shown = failures[-5:]
            lines.append(f"⛔ 失败边界（禁止重复，共 {len(failures)} 条，显示最近 {len(shown)} 条）：")
            for m in shown:
                lines.append(f"  - {m.content}")

        # ━━ 第四层：note（备注）— 只保留最近 2 条
        notes = [m for m in memories if m.kind == "note"]
        if notes:
            shown = notes[-2:]
            lines.append("📝 备注：")
            for m in shown:
                lines.append(f"  - {m.content}")

        # ━━ Ideas 部分
        failed_ideas = [i for i in ideas if i.status == "failed"]
        active_ideas = [i for i in ideas if i.status != "failed"]

        if failed_ideas:
            lines.append("⛔ 已失败方向（禁止重复）：")
            for i in failed_ideas:
                result_str = f"（{i.result}）" if i.result else ""
                lines.append(f"  - {i.content}{result_str}")

        if active_ideas:
            lines.append("待探索方向：")
            for i in active_ideas:
                lines.append(f"  - [{i.status}] {i.content}")

        if len(lines) == 1:
            return ""
        return "\n".join(lines)

    def _detect_phase_transition(self, tool_name: str, tool_args: dict, result: str) -> None:
        """
        根据工具执行结果自动检测渗透阶段转换。
        每次阶段切换时注入对应的标准动作提示。
        """
        import re

        # RECON → INITIAL_ACCESS：检测到获得 shell
        if self._phase == "RECON" and tool_name == "bash" and not self._got_shell:
            shell_indicators = [
                r'uid=\d+',              # id 命令输出
                r'\broot\b.*\broot\b',    # whoami 返回 root
                r'\bwww-data\b',          # web shell
                r'\$\s*$',               # bash prompt
                r'#\s*$',                # root prompt
            ]
            for pattern in shell_indicators:
                if re.search(pattern, result):
                    self._got_shell = True
                    self._transition_to("INITIAL_ACCESS")
                    break

        # 任何阶段 → POST_EXPLOIT：flag 提交成功但未完成
        if tool_name == "challenge_submit_flag" and "正确" in result:
            self._submitted_flag_count += 1
            if "全部 Flag 已找到" not in result and self._phase != "POST_EXPLOIT":
                self._transition_to("POST_EXPLOIT")

        # INITIAL_ACCESS/POST_EXPLOIT → DATA_EXFIL：发现新的内网 IP
        if self._phase in ("INITIAL_ACCESS", "POST_EXPLOIT") and tool_name == "bash":
            internal_ips = re.findall(
                r'(?:(?:172\.(?:1[6-9]|2\d|3[01]))|(?:10\.\d{1,3})|(?:192\.168))\.\d{1,3}\.\d{1,3}',
                result
            )
            # 过滤常见无关 IP
            new_ips = {
                ip for ip in internal_ips
                if not ip.startswith('10.0.100.')  # VPN 网关
                and ip != '172.17.0.1'            # Docker 网关
                and ip not in self._found_internal_ips
            }
            if new_ips:
                self._found_internal_ips.update(new_ips)
                if self._phase != "DATA_EXFIL":
                    self._transition_to("DATA_EXFIL")
                else:
                    # 已在 DATA_EXFIL，但发现新主机，注入提示
                    ips_str = ", ".join(new_ips)
                    self._pending_injections.append(
                        f"[内网发现] 新发现内网主机：{ips_str}。"
                        f"立即用已有凭据尝试访问这些主机！"
                    )

    def _transition_to(self, new_phase: str) -> None:
        """执行阶段切换，注入对应的标准动作提示。"""
        old_phase = self._phase
        self._phase = new_phase
        _emit("phase_transition", {"from": old_phase, "to": new_phase, "round": self.round})

        prompt = _PHASE_PROMPTS.get(new_phase)
        if prompt:
            self._pending_injections.append(prompt)

    @staticmethod
    def _is_pentest_challenge(task: str) -> bool:
        """检测是否是 B 类多阶段渗透题（多 flag）。"""
        task_lower = task.lower()
        # 检测题号前缀 b-
        if 'b-' in task_lower and ('多阶段' in task or '渗透' in task or 'flag' in task_lower):
            return True
        # 检测多 flag 提示
        if '包含' in task and '个 Flag' in task:
            return True
        return False

    def _should_force_stop(self, difficulty: str) -> bool:
        """
        硬约束：无进展强制停止。代码层强制，不依赖 Observer 纠偏后 Solver 听不听话。

        规则（第6轮复盘后调整）：
        1. hard 题超过 70 轮无 flag → 强制停止（原50轮，复盘发现a-15/f2-06重跑后成功）
        2. 任何题超过 100 轮无 flag → 强制停止（原80轮）
        3. 已提交过 flag 的多阶段渗透题，不触发 force_stop
        """
        if self._submitted_flag_count > 0:
            return False  # 有进展，不停

        if difficulty in ("hard", "difficult") and self.round > 70:
            _emit("force_stop", {
                "round": self.round,
                "reason": "hard 题 70 轮无进展",
                "difficulty": difficulty,
            })
            return True

        if self.round > 100:
            _emit("force_stop", {
                "round": self.round,
                "reason": "100 轮无进展",
                "difficulty": difficulty,
            })
            return True

        return False
