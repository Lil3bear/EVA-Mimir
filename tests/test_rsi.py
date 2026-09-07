"""Tests for RSI packs, analyze, and skill harness."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from solver.rsi.analyze import analyze_workspace, write_report
from solver.rsi.packs import load_packs, pack_codes, resolve_only_codes
from solver.rsi.skill_harness import SkillRefinementLog


class RSIPackTests(unittest.TestCase):
    def test_load_web_pack_prefix(self):
        settings = {"rsi": {"packs_file": "config/regression_codes.json"}}
        from solver.rsi.packs import pack_prefix_filter

        self.assertEqual(pack_prefix_filter("web", settings), "c")
        self.assertEqual(pack_codes("web", settings), [])

    def test_resolve_only_codes_env_wins(self):
        settings = {"rsi": {"only_codes": ["c-03", "c-08"]}}
        env = {"SOLVER_ONLY_CODES": "a-01,b-02"}
        resolved = resolve_only_codes(settings, env)
        self.assertEqual(resolved, {"a-01", "b-02"})

    def test_resolve_from_prefix_pack(self):
        settings = {"rsi": {"packs_file": "config/regression_codes.json"}}
        from solver.rsi.packs import resolve_prefix_filter

        self.assertEqual(resolve_prefix_filter(settings, {}, pack_name="pentest"), "b")
        resolved = resolve_only_codes(settings, {}, pack_name="pentest")
        self.assertIsNone(resolved)

    def test_unstable6_explicit_codes(self):
        settings = {"rsi": {"packs_file": "config/regression_codes.json"}}
        codes = pack_codes("unstable6", settings)
        self.assertEqual(
            set(codes),
            {"a-03", "a-13", "a-18", "c-02", "c-08", "e3-04"},
        )
        resolved = resolve_only_codes(settings, {}, pack_name="unstable6")
        self.assertEqual(resolved, set(codes))

    def test_lastmile3_pack(self):
        settings = {"rsi": {"packs_file": "config/regression_codes.json"}}
        codes = pack_codes("lastmile3", settings)
        self.assertEqual(set(codes), {"a-03", "b-02", "f2-05"})


class RSIAnalyzeTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="test-rsi-")
        self.workspace = Path(self._tmpdir)

    def _write_challenge(self, code: str, score: int, *, completed: bool = False):
        d = self.workspace / code
        d.mkdir(parents=True)
        (d / ".cumulative_score").write_text(str(score), encoding="utf-8")
        (d / "challenge.json").write_text(
            json.dumps({"id": code, "difficulty": "hard", "category": "web"}),
            encoding="utf-8",
        )
        run_marker = self.workspace / ".ctf-run-id"
        run_marker.write_text("run123", encoding="utf-8")
        (d / ".ctf-run-id").write_text("run123", encoding="utf-8")
        if completed:
            (d / ".completed").write_text("1", encoding="utf-8")

    def test_analyze_expected_codes(self):
        self._write_challenge("c-03", 100, completed=True)
        self._write_challenge("c-08", 0)
        report = analyze_workspace(
            self.workspace,
            expected_codes=["c-03", "c-08", "c-99"],
            pack="web",
        )
        self.assertEqual(report.solved, 1)
        self.assertEqual(report.zero_score, 1)
        self.assertIn("c-99", report.missing)
        self.assertFalse(report.pass_regression)
        self.assertTrue(any(a["code"] == "c-08" for a in report.next_actions))

    def test_write_report_files(self):
        self._write_challenge("c-03", 100, completed=True)
        report = analyze_workspace(self.workspace, expected_codes=["c-03"])
        json_path, md_path = write_report(report, self.workspace)
        self.assertTrue(json_path.is_file())
        self.assertTrue(md_path.is_file())
        self.assertIn("RSI", md_path.read_text(encoding="utf-8"))


class SkillHarnessTests(unittest.TestCase):
    def test_record_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills = Path(tmp)
            skill_file = skills / "web" / "SKILL.md"
            skill_file.parent.mkdir(parents=True)
            skill_file.write_text("# web\n", encoding="utf-8")
            log = SkillRefinementLog(skills)
            event = log.record_edit(
                pack="web",
                reason="test",
                files=["web/SKILL.md"],
                evidence_codes=["c-05"],
            )
            self.assertEqual(event["action"], "skill_edit")
            events = log.list()
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0]["files"][0]["sha256"])


if __name__ == "__main__":
    unittest.main()
