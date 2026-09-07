import json
import tempfile
import unittest
from pathlib import Path

from solver.runtime.harness import (
    HarnessScope,
    RefinementLog,
    classify_scope,
    shared_root,
)


def _tmp_challenge():
    return Path(tempfile.mkdtemp(prefix="challenge-"))


class ScopeTests(unittest.TestCase):
    def test_classify_shared_vs_private(self):
        challenge = _tmp_challenge()
        self.assertEqual(
            classify_scope(challenge, shared_root(challenge)),
            HarnessScope.CHALLENGE_SHARED,
        )
        self.assertEqual(
            classify_scope(challenge, challenge / "attempt-1"),
            HarnessScope.ATTEMPT_PRIVATE,
        )


class RefinementCrudTests(unittest.TestCase):
    def setUp(self):
        self.challenge = _tmp_challenge()
        self.shared = shared_root(self.challenge)
        self.log = RefinementLog(self.challenge)

    def test_create_records_event_and_writes_memory(self):
        entry, created, event = self.log.refine_add(
            self.shared, kind="fact", content="端口 8080 开放", reason="nmap 实测"
        )
        self.assertTrue(created)
        self.assertIsNotNone(event)
        self.assertEqual(event["action"], "create")
        self.assertEqual(event["scope"], HarnessScope.CHALLENGE_SHARED.value)
        self.assertEqual(event["after"]["content"], "端口 8080 开放")
        # Ledger is append-only and visible.
        self.assertEqual(len(self.log.list()), 1)

    def test_deduplicated_add_records_no_event(self):
        self.log.refine_add(self.shared, kind="fact", content="端口 8080 开放", reason="x")
        _, created, event = self.log.refine_add(
            self.shared, kind="fact", content="端口 8080 开放", reason="x"
        )
        self.assertFalse(created)
        self.assertIsNone(event)
        self.assertEqual(len(self.log.list()), 1)

    def test_update_records_before_and_after(self):
        entry, _, _ = self.log.refine_add(
            self.shared, kind="note", content="旧结论", reason="x"
        )
        ok, event = self.log.refine_update(
            self.shared, memory_id=entry.id, content="新结论", reason="被新证据推翻"
        )
        self.assertTrue(ok)
        self.assertEqual(event["before"]["content"], "旧结论")
        self.assertEqual(event["after"]["content"], "新结论")


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.challenge = _tmp_challenge()
        self.shared = shared_root(self.challenge)
        self.log = RefinementLog(self.challenge)

    def test_rollback_create_deletes_entry(self):
        entry, _, event = self.log.refine_add(
            self.shared, kind="note", content="临时结论", reason="x"
        )
        result = self.log.rollback(event["id"])
        self.assertTrue(result["ok"])
        # Entry is gone.
        self.assertIsNone(self.log._find_entry(self.shared, entry.id))

    def test_rollback_update_restores_content(self):
        entry, _, _ = self.log.refine_add(
            self.shared, kind="note", content="旧", reason="x"
        )
        _, event = self.log.refine_update(
            self.shared, memory_id=entry.id, content="新", reason="y"
        )
        self.log.rollback(event["id"])
        restored = self.log._find_entry(self.shared, entry.id)
        self.assertEqual(restored.content, "旧")

    def test_rollback_delete_restores_entry(self):
        entry, _, _ = self.log.refine_add(
            self.shared, kind="fact", content="端口 80", reason="x"
        )
        _, event = self.log.refine_delete(
            self.shared, memory_id=entry.id, reason="清理过时"
        )
        result = self.log.rollback(event["id"])
        self.assertTrue(result["ok"])
        # The restored entry keeps its ORIGINAL id so the audit chain stays
        # consistent (rollback re-creates verbatim, not with a fresh id).
        restored = self.log._find_entry(self.shared, entry.id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.id, entry.id)
        self.assertEqual(restored.content, "端口 80")
        self.assertEqual(result["memory_id"], entry.id)

    def test_rollback_promote_deletes_shared_entry(self):
        # A promoted memory (recorded with action="promote") must be rollback-
        # able just like a create.
        entry, _, _ = self.log.refine_add(
            self.shared, kind="fact", content="共享事实", reason="x"
        )
        promote_event = self.log.append({
            "action": "promote",
            "kind": "fact",
            "memory_id": entry.id,
            "scope": HarnessScope.CHALLENGE_SHARED.value,
            "root": str(self.shared),
            "before": None,
            "after": entry.__dict__,
        })
        result = self.log.rollback(promote_event["id"])
        self.assertTrue(result["ok"])
        self.assertIsNone(self.log._find_entry(self.shared, entry.id))

    def test_rollback_promote_refuses_evidence(self):
        entry, _, _ = self.log.refine_add(
            self.shared, kind="evidence", content="flag{x}", reason="实测"
        )
        promote_event = self.log.append({
            "action": "promote",
            "kind": "evidence",
            "memory_id": entry.id,
            "scope": HarnessScope.CHALLENGE_SHARED.value,
            "root": str(self.shared),
            "after": entry.__dict__,
        })
        result = self.log.rollback(promote_event["id"])
        self.assertFalse(result["ok"])
        self.assertIn("evidence", result["error"])

    def test_evidence_create_is_not_rollbackable(self):
        entry, _, event = self.log.refine_add(
            self.shared, kind="evidence", content="flag{test}", reason="实测"
        )
        result = self.log.rollback(event["id"])
        self.assertFalse(result["ok"])
        self.assertIn("evidence", result["error"])
        # Evidence survives.
        self.assertIsNotNone(self.log._find_entry(self.shared, entry.id))

    def test_double_rollback_is_rejected(self):
        entry, _, event = self.log.refine_add(
            self.shared, kind="note", content="x", reason="x"
        )
        self.assertTrue(self.log.rollback(event["id"])["ok"])
        self.assertFalse(self.log.rollback(event["id"])["ok"])


class ComplianceTests(unittest.TestCase):
    def test_ledger_lives_inside_challenge_dir(self):
        challenge = _tmp_challenge()
        log = RefinementLog(challenge)
        self.assertTrue(log.path.is_relative_to(challenge))
        # Cross-challenge isolation: two challenges never share the ledger.
        other = _tmp_challenge()
        self.assertNotEqual(log.path, RefinementLog(other).path)

    def test_events_are_json_lines(self):
        challenge = _tmp_challenge()
        log = RefinementLog(challenge)
        log.refine_add(shared_root(challenge), kind="fact", content="a", reason="r")
        raw = log.path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(raw), 1)
        self.assertEqual(json.loads(raw[0])["action"], "create")


if __name__ == "__main__":
    unittest.main()
