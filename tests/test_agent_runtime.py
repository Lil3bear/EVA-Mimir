import threading
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from openai import APITimeoutError

from solver.agent import SolverAgent, _parse_tool_args
from solver.runtime.challenge_ledger import ChallengeLedger
from solver.runtime.context import RunContext, ctx
from solver.runtime.llm import (
    assistant_message_dict,
    completion_kwargs,
    create_with_retry,
)
from solver.runtime.tool_runner import ToolRunner
from solver.tools import search_tool


class LlmRetryTests(unittest.TestCase):
    def test_retries_transient_failure(self):
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise APITimeoutError(request=httpx.Request("POST", "http://llm.test"))
            return "ok"

        sleeps = []
        result = create_with_retry(create, sleep=sleeps.append, model="test")

        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [1.0])

    def test_does_not_retry_programming_error(self):
        calls = 0

        def create(**kwargs):
            nonlocal calls
            calls += 1
            raise ValueError("bad request construction")

        with self.assertRaises(ValueError):
            create_with_retry(create, sleep=lambda _: None)
        self.assertEqual(calls, 1)

    def test_expired_deadline_prevents_request(self):
        create = MagicMock(return_value="should not run")

        with self.assertRaises(TimeoutError):
            create_with_retry(create, deadline=time.time() - 1, model="test")

        create.assert_not_called()

    def test_waiting_for_concurrency_slot_respects_deadline(self):
        gate = threading.BoundedSemaphore(1)
        gate.acquire()
        create = MagicMock(return_value="should not run")
        try:
            with patch("solver.runtime.llm._LLM_SEMAPHORE", gate):
                started = time.time()
                with self.assertRaises(TimeoutError):
                    create_with_retry(
                        create,
                        deadline=time.time() + 0.03,
                        model="test",
                    )
                self.assertLess(time.time() - started, 0.5)
        finally:
            gate.release()

        create.assert_not_called()

    def test_cancelled_request_never_enters_provider(self):
        cancelled = threading.Event()
        cancelled.set()
        create = MagicMock(return_value="should not run")

        with self.assertRaises(Exception) as caught:
            create_with_retry(create, cancel_event=cancelled, model="test")

        self.assertIn("cancel", str(caught.exception).lower())
        create.assert_not_called()

    def test_retry_reuses_request_snapshot(self):
        messages = [{"role": "user", "content": "original"}]
        seen = []

        def create(**kwargs):
            seen.append(kwargs["messages"])
            if len(seen) == 1:
                kwargs["messages"].append({"role": "user", "content": "mutated"})
                messages.append({"role": "user", "content": "external"})
                raise APITimeoutError(request=httpx.Request("POST", "http://llm.test"))
            return "ok"

        create_with_retry(create, sleep=lambda _: None, messages=messages)

        self.assertEqual(seen[1], [{"role": "user", "content": "original"}])


class DeepSeekTransportTests(unittest.TestCase):
    def test_v4_request_enables_thinking_and_omits_tool_choice(self):
        kwargs = completion_kwargs(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": "task"}],
            tools=[{"type": "function"}],
            tool_choice="auto",
            max_tokens=65536,
        )

        self.assertNotIn("tool_choice", kwargs)
        self.assertEqual(kwargs["max_tokens"], 65536)
        self.assertEqual(kwargs["extra_body"]["thinking"], {"type": "enabled"})
        # reasoning_effort 必须是顶层字段（extra_body 传法 tokenhub 不生效）
        self.assertEqual(kwargs["reasoning_effort"], "high")
        self.assertNotIn("reasoning_effort", kwargs["extra_body"])

    def test_generic_request_keeps_tool_choice(self):
        kwargs = completion_kwargs(
            model="other-model",
            messages=[],
            tool_choice="required",
        )
        self.assertEqual(kwargs["tool_choice"], "required")
        self.assertNotIn("extra_body", kwargs)

    def test_v4_request_can_disable_thinking(self):
        kwargs = completion_kwargs(
            model="deepseek-v4-flash",
            messages=[],
            thinking_enabled=False,
        )

        self.assertEqual(kwargs["extra_body"], {"thinking": {"type": "disabled"}})

    def test_tool_call_message_keeps_reasoning_and_non_null_content(self):
        message = SimpleNamespace(
            model_extra={"reasoning_content": "reason"},
            reasoning_content="reason",
            model_dump=lambda **_: {
                "role": "assistant",
                "tool_calls": [{"id": "call-1"}],
                "reasoning_content": "reason",
            },
        )

        serialized = assistant_message_dict(message)

        self.assertEqual(serialized["content"], "")
        self.assertEqual(serialized["reasoning_content"], "reason")


class ToolArgumentTests(unittest.TestCase):
    def test_rejects_invalid_json(self):
        args, error = _parse_tool_args("bash", '{"cmd":')
        self.assertEqual(args, {})
        self.assertIn("有效 JSON", error)

    def test_rejects_missing_required_argument(self):
        _, error = _parse_tool_args("bash", "{}")
        self.assertIn("cmd", error)

    def test_rejects_wrong_argument_type(self):
        _, error = _parse_tool_args("bash", '{"cmd":"id","timeout":"slow"}')
        self.assertIn("integer", error)

    def test_accepts_valid_arguments(self):
        args, error = _parse_tool_args("bash", '{"cmd":"id","timeout":30}')
        self.assertEqual(args, {"cmd": "id", "timeout": 30})
        self.assertEqual(error, "")


class ToolRunnerTests(unittest.TestCase):
    def test_gate_is_journaled_without_calling_executor(self):
        executor = MagicMock(return_value="should not run")
        journal = MagicMock()
        runner = ToolRunner({"bash": executor}, {"bash": {}}, journal)

        result = runner.run(
            call_id="call-1",
            tool_name="bash",
            tool_args={"cmd": "id"},
            args_error="",
            round_num=3,
            gate=lambda *_: "[blocked]",
        )

        executor.assert_not_called()
        journal.prepare.assert_called_once_with("call-1", "bash", {"cmd": "id"}, 3)
        journal.complete.assert_called_once_with("call-1", "bash", "[blocked]")
        self.assertTrue(result.blocked)
        self.assertFalse(result.executed)


class SecuritySearchTests(unittest.TestCase):
    def tearDown(self):
        search_tool._search_client = None
        search_tool._search_model = ""
        search_tool._search_source = ""

    def test_deepseek_search_disables_thinking(self):
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content="无可靠本地知识", reasoning_content=None)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason="stop")]
            )

        search_tool._search_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        search_tool._search_model = "deepseek-v4-flash"
        search_tool._search_source = "deepseek"

        result = search_tool._search_llm("unknown benchmark task")

        self.assertEqual(captured["extra_body"]["thinking"]["type"], "disabled")
        self.assertEqual(captured["max_tokens"], 1200)
        self.assertIn("无可靠本地知识", result)

    def test_reasoning_only_response_is_rejected(self):
        message = SimpleNamespace(content=None, reasoning_content="speculative scratchpad")
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="length")]
        )
        search_tool._search_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_: response)
            )
        )
        search_tool._search_model = "deepseek-v4-flash"
        search_tool._search_source = "deepseek"

        result = search_tool._search_llm("specific challenge title")

        self.assertIn("未生成最终答案", result)
        self.assertIn("finish_reason=length", result)
        self.assertNotIn("speculative scratchpad", result)


class CompactionTests(unittest.TestCase):
    def tearDown(self):
        ctx.reset()

    def test_state_snapshot_uses_memory_for_ip_consistency(self):
        from shared.data.memory import add_memory

        run = RunContext.create(tempfile.mkdtemp(prefix="snapshot-"), "case")
        agent = SolverAgent.__new__(SolverAgent)
        agent.messages = []
        agent._memory_limit = 2
        with ctx.bind(run):
            for suffix in range(1, 4):
                add_memory(
                    Path(ctx.challenge_dir), "fact", f"current host is 10.1.2.{suffix}"
                )
            snapshot = agent._build_state_snapshot()

        self.assertNotIn("10.1.2.1", snapshot)
        self.assertIn("10.1.2.2", snapshot)
        self.assertIn("10.1.2.3", snapshot)

    def test_summarizes_discarded_span_and_preserves_valid_tail(self):
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content="structured summary", model_extra={})
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        agent = SolverAgent.__new__(SolverAgent)
        agent.messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "original task"},
            {"role": "assistant", "tool_calls": [{"id": "old", "name": "bash"}]},
            {"role": "tool", "tool_call_id": "old", "content": "credential=KEEP_ME"},
            {"role": "assistant", "tool_calls": [{"id": "new", "name": "bash"}]},
            {"role": "tool", "tool_call_id": "new", "content": "current result"},
        ]
        agent._keep_recent_tokens = 1
        agent._compaction_summary = "previous summary"
        agent._summary_model = "test-model"
        agent.model = "test-model"
        agent._reasoning_effort = "max"
        agent._summary_max_output_tokens = 16384
        agent._llm_max_attempts = 1
        agent.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        agent._build_state_snapshot = lambda: "STATE"
        agent._on_llm_retry = lambda *args: None

        compacted = agent._compress_context()
        summary_input = captured["messages"][0]["content"]

        self.assertIn("credential=KEEP_ME", summary_input)
        self.assertIn("previous summary", summary_input)
        self.assertEqual(compacted[1]["content"], "original task")
        self.assertIn("structured summary", compacted[2]["content"])
        self.assertEqual(compacted[3]["role"], "assistant")

    def test_injection_queue_drains_atomically(self):
        agent = SolverAgent.__new__(SolverAgent)
        agent._pending_injections = []
        agent._injection_lock = threading.Lock()

        agent._queue_injection("one")
        agent._queue_injection("two")

        self.assertEqual(agent._drain_injections(), ["one", "two"])
        self.assertEqual(agent._drain_injections(), [])

    def test_stale_observer_correction_is_discarded(self):
        agent = SolverAgent.__new__(SolverAgent)
        agent.round = 20
        agent._observer_correction_max_lag = 3
        agent._pending_injections = []
        agent._injection_lock = threading.Lock()

        agent.inject_message("old advice", reviewed_round=10)

        self.assertEqual(agent._drain_injections(), [])

    def test_fresh_observer_correction_keeps_round_watermark(self):
        agent = SolverAgent.__new__(SolverAgent)
        agent.round = 20
        agent._observer_correction_max_lag = 3
        agent._pending_injections = []
        agent._injection_lock = threading.Lock()
        agent._last_correction = None
        agent._last_correction_round = 0
        agent._correction_repeat_count = 0

        agent.inject_message("new advice", reviewed_round=18)

        queued = agent._drain_injections()
        self.assertEqual(len(queued), 1)
        self.assertIn("第 18 轮", queued[0])
        self.assertIn("new advice", queued[0])

    def test_recovery_replays_read_only_but_not_effectful_tool(self):
        agent = SolverAgent.__new__(SolverAgent)
        agent._recovery_state = {
            "recent_completed": [],
            "pending": [
                {
                    "run_id": "old",
                    "call_id": "safe",
                    "tool": "read_file",
                    "args": {"path": "note.txt"},
                },
                {
                    "run_id": "old",
                    "call_id": "unsafe",
                    "tool": "bash",
                    "args": {"cmd": "reboot"},
                },
            ],
        }
        agent._journal = MagicMock()
        read = MagicMock(return_value="saved content")
        bash = MagicMock(return_value="should not run")

        with patch.dict("solver.agent.TOOL_EXECUTORS", {"read_file": read, "bash": bash}):
            message = agent._recover_execution()

        read.assert_called_once_with({"path": "note.txt"})
        bash.assert_not_called()
        agent._journal.complete.assert_called_once()
        self.assertIn("reboot", message)
        self.assertIn("禁止自动重放", message)


class PersistentProgressTests(unittest.TestCase):
    def test_hint_focus_stops_only_without_material_progress(self):
        agent = SolverAgent.__new__(SolverAgent)
        agent._hint_focus_start_round = 2
        agent._hint_focus_limit = 8
        agent._hint_focus_progress_baseline = 0
        agent._material_progress_count = 0
        agent.round = 11
        self.assertTrue(agent._hint_focus_exhausted())

        agent._material_progress_count = 1
        self.assertFalse(agent._hint_focus_exhausted())

    def test_same_http_evidence_still_counts_as_progress_in_next_agent(self):
        """宽松判定：不跨 agent 去重，重复 HTTP 证据也刷新停机计数。"""
        root = Path(tempfile.mkdtemp(prefix="persistent-progress-"))

        first = SolverAgent.__new__(SolverAgent)
        first._ledger = ChallengeLedger(root)
        first._progress_fingerprints = set()
        second = SolverAgent.__new__(SolverAgent)
        second._ledger = ChallengeLedger(root)
        second._progress_fingerprints = set()

        output = "HTTP/1.1 200 OK\nServer: demo"
        self.assertTrue(first._bash_has_new_progress(output))
        self.assertTrue(second._bash_has_new_progress(output))


class FlagEvidenceGateTests(unittest.TestCase):
    """submit 证据门：flag 必须出现在工具输出中，拦截纯猜测提交。"""

    def _make_agent(self, messages, compaction_summary=""):
        agent = SolverAgent.__new__(SolverAgent)
        agent.messages = messages
        agent._compaction_summary = compaction_summary
        return agent

    def _tool_exchange(self, call_id, tool_args_json, output):
        return [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": call_id, "type": "function",
                 "function": {"name": "bash", "arguments": tool_args_json}},
            ]},
            {"role": "tool", "tool_call_id": call_id, "content": output},
        ]

    def test_flag_from_target_output_is_evidence(self):
        # curl 输出里出现 flag，参数里没有 → 有证据
        msgs = self._tool_exchange("c1", '{"cmd": "curl http://target/flag.txt"}',
                                   "flag{real_flag_123}")
        agent = self._make_agent(msgs)
        self.assertTrue(agent._flag_has_evidence("flag{real_flag_123}"))

    def test_flag_from_computation_is_evidence(self):
        # python 解密输出 flag，参数里是脚本而不是 flag 本身 → 有证据
        msgs = self._tool_exchange("c1", '{"cmd": "python3 decrypt.py"}',
                                   "decrypted: flag{decrypted_abc}")
        agent = self._make_agent(msgs)
        self.assertTrue(agent._flag_has_evidence("flag{decrypted_abc}"))

    def test_pure_guess_is_blocked(self):
        msgs = self._tool_exchange("c1", '{"cmd": "curl http://target/"}',
                                   "hello world")
        agent = self._make_agent(msgs)
        self.assertFalse(agent._flag_has_evidence("flag{guessed}"))

    def test_echo_bypass_is_blocked(self):
        # solver 自己 echo 出来的 flag 不算证据
        msgs = self._tool_exchange("c1", '{"cmd": "echo flag{self_echo}"}',
                                   "flag{self_echo}")
        agent = self._make_agent(msgs)
        self.assertFalse(agent._flag_has_evidence("flag{self_echo}"))

    def test_compaction_summary_counts_as_evidence(self):
        agent = self._make_agent([], compaction_summary="已获取 flag{old_flag_9}，来自 /flag.txt")
        self.assertTrue(agent._flag_has_evidence("flag{old_flag_9}"))


class ApproachBudgetTests(unittest.TestCase):
    """分题型防爆破：只 block 当前目标 host，内网 host（横向移动）豁免。"""

    def _bind(self, target_url):
        base = tempfile.mkdtemp(prefix="approach-budget-")
        context = RunContext.create(base, "case", target_url=target_url)
        return ctx.bind(context)

    def test_target_host_is_strict(self):
        from solver.tools import bash_tool

        with self._bind("http://10.0.0.1:80"):
            self.assertTrue(bash_tool._url_targets_current_target("curl http://10.0.0.1/"))
            self.assertTrue(
                bash_tool._url_targets_current_target("curl http://10.0.0.1:80/api?aid=1")
            )

    def test_internal_host_is_exempt(self):
        from solver.tools import bash_tool

        with self._bind("http://10.0.0.1:80"):
            # 横向移动：访问内网其他 IP，不受防爆破 block
            self.assertFalse(
                bash_tool._url_targets_current_target("curl http://10.0.1.2:80/")
            )
            # shell 循环变量做 host（for ip in ...）也豁免
            self.assertFalse(
                bash_tool._url_targets_current_target(
                    "for ip in 10.0.1.2 10.0.1.3; do curl http://$ip:80/; done"
                )
            )

    def test_ssrf_probe_still_targets_host(self):
        from solver.tools import bash_tool

        with self._bind("http://10.0.0.1:80"):
            # SSRF 请求发往目标 host，仍受预算约束（防扫内网端口）
            self.assertTrue(
                bash_tool._url_targets_current_target(
                    "curl http://10.0.0.1/fetch?url=http://127.0.0.1:8080"
                )
            )


if __name__ == "__main__":
    unittest.main()
