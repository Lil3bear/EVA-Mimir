import unittest

from solver.runtime.lane_budget import LaneBudget


class LaneBudgetTests(unittest.TestCase):
    def test_default_split_reserves_base_per_container(self):
        budget = LaneBudget(total_lanes=4, base_lanes=3)
        self.assertEqual(budget.base_lanes, 3)
        self.assertEqual(budget.extra_lanes, 1)

    def test_total_never_below_base(self):
        budget = LaneBudget(total_lanes=1, base_lanes=3)
        self.assertEqual(budget.total_lanes, 3)
        self.assertEqual(budget.extra_lanes, 0)

    def test_three_containers_share_one_extra_lane(self):
        # 3 题并行：每题拿到 1 个 base lane，只有 1 个额外 lane 可分配，
        # 所以同一时刻只有一道题能开第 2 路（其余各 1 路）。
        budget = LaneBudget(total_lanes=4, base_lanes=3)
        self.assertTrue(budget.acquire_primary(timeout=1))
        self.assertTrue(budget.acquire_primary(timeout=1))
        self.assertTrue(budget.acquire_primary(timeout=1))
        # 三个 base lane 用满后，额外池只剩 1 个：第一个难题拿到，第二个拿不到。
        self.assertTrue(budget.try_acquire_extra())
        self.assertFalse(budget.try_acquire_extra())

    def test_extra_lane_released_is_reusable(self):
        budget = LaneBudget(total_lanes=5, base_lanes=3)
        self.assertTrue(budget.try_acquire_extra())
        self.assertTrue(budget.try_acquire_extra())
        self.assertFalse(budget.try_acquire_extra())
        budget.release_extra()
        self.assertTrue(budget.try_acquire_extra())

    def test_no_extra_pool_when_total_equals_base(self):
        budget = LaneBudget(total_lanes=3, base_lanes=3)
        self.assertFalse(budget.try_acquire_extra())

    def test_primary_lane_blocks_when_exhausted(self):
        budget = LaneBudget(total_lanes=2, base_lanes=2)
        self.assertTrue(budget.acquire_primary(timeout=1))
        self.assertTrue(budget.acquire_primary(timeout=1))
        # 两个 base lane 已用满，第三个 primary 在超时内拿不到。
        self.assertFalse(budget.acquire_primary(timeout=0.05))
        budget.release_primary()
        self.assertTrue(budget.acquire_primary(timeout=1))


if __name__ == "__main__":
    unittest.main()
