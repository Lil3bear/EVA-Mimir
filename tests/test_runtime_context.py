import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from shared.data import ideas, memory
from solver.runtime.context import RunContext, ctx
from solver.tools import file_tools, memory_tools


class RunContextTests(unittest.TestCase):
    def tearDown(self):
        ctx.reset()

    def test_attempts_share_blackboard_but_isolate_files(self):
        root = tempfile.mkdtemp(prefix="runtime-context-")
        base = RunContext.create(root, "hard-01")
        aggressive = base.for_attempt("aggressive")
        steady = base.for_attempt("steady")

        with ctx.bind(aggressive):
            file_tools.write_file({"path": "exploit.py", "content": "aggressive"})
            memory.add_memory(
                Path(ctx.challenge_dir), "fact", "service is nginx",
                attempt_id=ctx.attempt_id,
            )
            ideas.add_idea(
                Path(ctx.challenge_dir), "test request smuggling",
                owner_attempt_id=ctx.attempt_id,
            )

        with ctx.bind(steady):
            file_tools.write_file({"path": "exploit.py", "content": "steady"})
            memories = memory.list_memory(Path(ctx.challenge_dir))
            shared_ideas = ideas.list_ideas(Path(ctx.challenge_dir))

        self.assertEqual((Path(aggressive.attempt_dir) / "exploit.py").read_text(), "aggressive")
        self.assertEqual((Path(steady.attempt_dir) / "exploit.py").read_text(), "steady")
        self.assertEqual(memories[0].attempt_id, "aggressive")
        self.assertEqual(shared_ideas[0].owner_attempt_id, "aggressive")

    def test_thread_contexts_do_not_leak(self):
        root = tempfile.mkdtemp(prefix="runtime-threads-")
        base = RunContext.create(root, "hard-02")
        observed = []
        lock = threading.Lock()

        def worker(name):
            with ctx.bind(base.for_attempt(name)):
                with lock:
                    observed.append((ctx.attempt_id, ctx.attempt_dir))

        threads = [threading.Thread(target=worker, args=(name,)) for name in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual({item[0] for item in observed}, {"a", "b"})
        self.assertEqual(len({item[1] for item in observed}), 2)

    def test_concurrent_duplicate_memory_is_written_once(self):
        challenge_dir = Path(tempfile.mkdtemp(prefix="memory-lock-"))

        def add(_):
            return memory.add_memory(challenge_dir, "fact", "shared discovery").id

        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(add, range(24)))

        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(memory.list_memory(challenge_dir)), 1)

    def test_legacy_memory_defaults_to_primary_attempt(self):
        challenge_dir = Path(tempfile.mkdtemp(prefix="memory-legacy-"))
        entries_dir = challenge_dir / "memory" / "entries"
        entries_dir.mkdir(parents=True)
        entries_dir.joinpath("1-mem_old.json").write_text(
            '{"id":"mem_old","kind":"fact","content":"legacy",'
            '"created_at":1,"refs":[],"source":"solver"}',
            encoding="utf-8",
        )

        self.assertEqual(memory.list_memory(challenge_dir)[0].attempt_id, "primary")

    def test_fuzzy_dedup_keeps_distinct_structured_values(self):
        challenge_dir = Path(tempfile.mkdtemp(prefix="memory-values-"))
        first = memory.add_memory(challenge_dir, "fact", "current host is 10.1.2.3")
        second = memory.add_memory(challenge_dir, "fact", "current host is 10.1.2.4")

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(memory.list_memory(challenge_dir)), 2)

    def test_fuzzy_dedup_keeps_changed_ports_credentials_and_tokens(self):
        cases = [
            (
                "The authenticated admin service is confirmed reachable on port 8080 using the current session",
                "The authenticated admin service is confirmed reachable on port 8081 using the current session",
            ),
            (
                "Confirmed credential for admin dashboard is password AlphaValue and login succeeds",
                "Confirmed credential for admin dashboard is password BetaValue and login succeeds",
            ),
            (
                "Confirmed secret token value is abcdefghijklmnop for the current api user account",
                "Confirmed secret token value is zyxwvutsrqponmlk for the current api user account",
            ),
        ]

        for old, new in cases:
            with self.subTest(new=new):
                challenge_dir = Path(tempfile.mkdtemp(prefix="memory-critical-value-"))
                first = memory.add_memory(challenge_dir, "fact", old)
                second = memory.add_memory(challenge_dir, "fact", new)
                self.assertNotEqual(first.id, second.id)
                self.assertEqual(len(memory.list_memory(challenge_dir)), 2)

    def test_memory_tool_reports_existing_content_on_fuzzy_duplicate(self):
        root = tempfile.mkdtemp(prefix="memory-tool-duplicate-")
        run = RunContext.create(root, "web-01")
        old = "confirmed admin dashboard service is reachable using current session"
        new = "confirmed admin dashboard service is reachable with current session"

        with ctx.bind(run):
            first = memory_tools.memory_add({"kind": "fact", "content": old})
            second = memory_tools.memory_add({"kind": "fact", "content": new})

        self.assertIn("已记录", first)
        self.assertIn("已存在，未新增", second)
        self.assertIn(old, second)
        self.assertNotIn(new, second)
        self.assertEqual(len(memory.list_memory(Path(run.challenge_dir))), 1)

if __name__ == "__main__":
    unittest.main()
