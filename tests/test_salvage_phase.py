"""Benchmark-relative salvage phase (360-min) tests."""

import unittest

from solver.runtime.salvage import (
    BENCHMARK_MINUTES_DEFAULT,
    SALVAGE_REMAINING_AT_360,
    resolve_salvage_phase,
)


class SalvagePhaseTests(unittest.TestCase):
    def test_normal_before_140min_on_360_benchmark(self):
        # elapsed 200 → benchmark_remaining 160, run_remaining 160
        plan = resolve_salvage_phase(
            elapsed_min=200,
            remaining_min=160,
            total_timeout_min=360,
            round_idx=2,
        )
        self.assertEqual(plan.phase, "normal")
        self.assertFalse(plan.late_game_mode)

    def test_salvage_at_140min_remaining(self):
        plan = resolve_salvage_phase(
            elapsed_min=220,
            remaining_min=140,
            total_timeout_min=360,
            round_idx=2,
        )
        self.assertEqual(plan.phase, "salvage")
        self.assertTrue(plan.cut_long_hard)
        self.assertTrue(plan.salvage_enabled)

    def test_critical_at_72min(self):
        plan = resolve_salvage_phase(
            elapsed_min=288,
            remaining_min=72,
            total_timeout_min=360,
            round_idx=3,
        )
        self.assertEqual(plan.phase, "critical")
        self.assertTrue(plan.skip_hard_new)

    def test_final_at_36min(self):
        plan = resolve_salvage_phase(
            elapsed_min=324,
            remaining_min=36,
            total_timeout_min=360,
            round_idx=3,
        )
        self.assertEqual(plan.phase, "final")
        self.assertTrue(plan.salvage_only)

    def test_round_one_never_salvage(self):
        plan = resolve_salvage_phase(
            elapsed_min=300,
            remaining_min=60,
            total_timeout_min=360,
            round_idx=1,
        )
        self.assertEqual(plan.phase, "normal")

    def test_benchmark_clock_triggers_before_run_remaining(self):
        # run timeout 360 but only 130 min left on deadline; benchmark still 140 → salvage
        plan = resolve_salvage_phase(
            elapsed_min=220,
            remaining_min=130,
            total_timeout_min=360,
            round_idx=2,
        )
        self.assertNotEqual(plan.phase, "normal")

    def test_lastmile_and_partial_protected_until_final(self):
        from types import SimpleNamespace
        from solver.runtime.salvage import long_hard_cut_codes

        challenges = [
            SimpleNamespace(
                unique_code="a-03",
                difficulty="hard",
                flag_count=1,
                correct_flag_count=0,
                is_completed=False,
            ),
            SimpleNamespace(
                unique_code="b-02",
                difficulty="hard",
                flag_count=6,
                correct_flag_count=2,
                is_completed=False,
            ),
            SimpleNamespace(
                unique_code="f2-05",
                difficulty="hard",
                flag_count=1,
                correct_flag_count=0,
                is_completed=False,
            ),
            SimpleNamespace(
                unique_code="c-99",
                difficulty="hard",
                flag_count=1,
                correct_flag_count=0,
                is_completed=False,
            ),
        ]
        settings = {"solver": {"lastmile_codes": ["a-03", "f2-05", "b-02"]}}
        salvage_cut = long_hard_cut_codes(
            challenges, phase="salvage", settings=settings
        )
        self.assertNotIn("a-03", salvage_cut)
        self.assertNotIn("f2-05", salvage_cut)
        self.assertNotIn("b-02", salvage_cut)  # partial
        self.assertIn("c-99", salvage_cut)

        final_cut = long_hard_cut_codes(
            challenges, phase="final", settings=settings
        )
        self.assertIn("a-03", final_cut)
        self.assertIn("f2-05", final_cut)
        self.assertNotIn("b-02", final_cut)  # still protect partial


if __name__ == "__main__":
    unittest.main()
