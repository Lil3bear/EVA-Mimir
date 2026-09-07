import unittest

from solver.runtime.model_router import (
    ModelPurpose,
    ModelRouter,
    ModelSpec,
)


class _FakeClient:
    """Records the kwargs it was built with so we can assert provider wiring."""

    instances: list[dict] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _FakeClient.instances.append(kwargs)


def _router(settings, environ=None):
    return ModelRouter.from_settings(
        settings, environ or {}, client_factory=_FakeClient
    )


class LegacyCompatibilityTests(unittest.TestCase):
    def test_derives_light_and_heavy_from_legacy_keys(self):
        router = _router(
            {
                "llm": {
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key": "sk-x",
                    "default_model": "deepseek-v4-flash",
                    "pro_model": "deepseek-v4-pro",
                }
            }
        )
        self.assertEqual(router.tiers["light"].name, "deepseek-v4-flash")
        self.assertEqual(router.tiers["heavy"].name, "deepseek-v4-pro")
        # v4 models default to thinking enabled.
        self.assertTrue(router.tiers["light"].thinking_enabled)

    def test_heavy_falls_back_to_light_when_no_pro_model(self):
        router = _router(
            {"llm": {"base_url": "u", "default_model": "deepseek-v4-flash"}}
        )
        self.assertEqual(router.tiers["heavy"].name, "deepseek-v4-flash")

    def test_env_supplies_model_when_settings_empty(self):
        router = _router({"llm": {}}, {"LLM_MODEL": "kimi-k3", "LLM_BASE_URL": "u"})
        self.assertEqual(router.tiers["light"].name, "kimi-k3")
        # non-deepseek defaults to thinking disabled in legacy derivation.
        self.assertFalse(router.tiers["light"].thinking_enabled)


class MultiProviderTests(unittest.TestCase):
    def setUp(self):
        _FakeClient.instances = []
        self.router = _router(
            {
                "llm": {
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key": "sk-deepseek",
                    "providers": {
                        "deepseek": {
                            "base_url": "https://api.deepseek.com/v1",
                            "api_key": "sk-deepseek",
                        },
                        "tokenhub": {
                            "base_url": "https://tokenhub.tencentmaas.com/v1",
                            "api_key_env": "TOKENHUB_KEY",
                        },
                    },
                    "tiers": {
                        "light": {"model": "kimi-k3", "provider": "tokenhub"},
                        "heavy": {"model": "deepseek-v4-pro", "provider": "deepseek"},
                    },
                }
            },
            {"TOKENHUB_KEY": "sk-kimi"},
        )

    def test_tiers_bind_to_their_providers(self):
        self.assertEqual(self.router.tiers["light"].provider.base_url,
                         "https://tokenhub.tencentmaas.com/v1")
        self.assertEqual(self.router.tiers["light"].provider.api_key, "sk-kimi")
        self.assertEqual(self.router.tiers["heavy"].provider.api_key, "sk-deepseek")

    def test_clients_are_cached_per_provider(self):
        light = self.router.tiers["light"]
        heavy = self.router.tiers["heavy"]
        c1 = self.router.client_for(light)
        c2 = self.router.client_for(light)
        c3 = self.router.client_for(heavy)
        self.assertIs(c1, c2)
        self.assertIsNot(c1, c3)
        # One client per distinct (base_url, api_key).
        self.assertEqual(len(_FakeClient.instances), 2)
        self.assertEqual(c1.kwargs["base_url"], "https://tokenhub.tencentmaas.com/v1")


class ProviderKeyInheritanceTests(unittest.TestCase):
    def test_same_endpoint_provider_inherits_top_level_key(self):
        # providers.deepseek omits api_key but shares the top-level base_url,
        # so it inherits the top-level key; tokenhub (different endpoint,
        # no key, no env) stays empty.
        router = _router(
            {
                "llm": {
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key": "sk-top",
                    "providers": {
                        "deepseek": {"base_url": "https://api.deepseek.com/v1"},
                        "tokenhub": {"base_url": "https://tokenhub.tencentmaas.com/v1"},
                    },
                    "tiers": {
                        "light": {"model": "deepseek-v4-flash", "provider": "deepseek"},
                        "heavy": {"model": "kimi-k3", "provider": "tokenhub"},
                    },
                }
            }
        )
        self.assertEqual(router.tiers["light"].provider.api_key, "sk-top")
        self.assertEqual(router.tiers["heavy"].provider.api_key, "")


class RoutingSelectionTests(unittest.TestCase):
    def setUp(self):
        # Explicit heavy escalate so unit tests still cover the window logic;
        # production settings.json sets escalate_rounds=0 / hard_tier=light.
        self.router = _router(
            {
                "llm": {
                    "base_url": "u",
                    "default_model": "deepseek-v4-flash",
                    "pro_model": "deepseek-v4-pro",
                    "routing": {
                        "hard_tier": "heavy",
                        "stuck_escalate_tier": "heavy",
                        "escalate_rounds": 3,
                        "escalate_max_consecutive": 12,
                    },
                }
            }
        )

    def test_summary_and_observer_stay_light(self):
        self.assertEqual(
            self.router.resolve(ModelPurpose.SUMMARY).tier, "light"
        )
        self.assertEqual(
            self.router.resolve(ModelPurpose.OBSERVER).tier, "light"
        )

    def test_fast_lane_main_is_light_even_when_stuck(self):
        sel = self.router.resolve(
            ModelPurpose.MAIN, round_num=5, lane="fast", stuck=True
        )
        self.assertEqual(sel.tier, "light")

    def test_deep_lane_default_is_light(self):
        sel = self.router.resolve(
            ModelPurpose.MAIN, round_num=3, lane="deep", stuck=False
        )
        self.assertEqual(sel.tier, "light")

    def test_stuck_escalates_then_falls_back(self):
        # Round 10 stuck -> escalate for escalate_rounds (default 3): 10..13.
        s10 = self.router.resolve(ModelPurpose.MAIN, round_num=10, lane="deep", stuck=True)
        self.assertEqual(s10.tier, "heavy")
        # Not stuck anymore but still inside the window -> stays heavy.
        s12 = self.router.resolve(ModelPurpose.MAIN, round_num=12, lane="deep", stuck=False)
        self.assertEqual(s12.tier, "heavy")
        # Window closed -> back to light.
        s14 = self.router.resolve(ModelPurpose.MAIN, round_num=14, lane="deep", stuck=False)
        self.assertEqual(s14.tier, "light")

    def test_persistent_stuck_is_capped(self):
        router = _router(
            {
                "llm": {
                    "base_url": "u",
                    "default_model": "flash",
                    "pro_model": "pro",
                    "routing": {
                        "stuck_escalate_tier": "heavy",
                        "escalate_rounds": 2,
                        "escalate_max_consecutive": 5,
                    },
                }
            }
        )
        tiers = []
        for r in range(0, 12):
            tiers.append(
                router.resolve(ModelPurpose.MAIN, round_num=r, lane="deep", stuck=True).tier
            )
        # After the consecutive cap (5 rounds from first stuck) heavy must stop
        # even though the stuck signal keeps firing.
        self.assertIn("heavy", tiers)
        self.assertEqual(tiers[-1], "light")

    def test_production_defaults_disable_high_escalation(self):
        # DEFAULT_ROUTING: hard_tier=light, escalate_rounds=0.
        router = _router(
            {
                "llm": {
                    "base_url": "u",
                    "default_model": "deepseek-v4-flash",
                    "pro_model": "deepseek-v4-pro",
                }
            }
        )
        hard = router.resolve(
            ModelPurpose.MAIN, round_num=1, lane="deep", stuck=False, difficulty="hard"
        )
        stuck = router.resolve(
            ModelPurpose.MAIN, round_num=10, lane="deep", stuck=True, difficulty="medium"
        )
        self.assertEqual(hard.tier, "light")
        self.assertEqual(stuck.tier, "light")
        self.assertEqual(router.tiers["light"].reasoning_effort, "medium")


class DifficultyTierTests(unittest.TestCase):
    def setUp(self):
        self.router = _router(
            {
                "llm": {
                    "base_url": "u",
                    "default_model": "deepseek-v4-flash",
                    "pro_model": "deepseek-v4-pro",
                    "routing": {
                        "hard_tier": "heavy",
                        "stuck_escalate_tier": "heavy",
                        "escalate_rounds": 3,
                    },
                }
            }
        )

    def test_hard_difficulty_uses_configured_hard_tier(self):
        sel = self.router.resolve(
            ModelPurpose.MAIN, round_num=1, lane="deep", stuck=False, difficulty="hard"
        )
        self.assertEqual(sel.tier, "heavy")
        # Even on a fast lane, hard difficulty wins when hard_tier is heavy.
        sel2 = self.router.resolve(
            ModelPurpose.MAIN, round_num=1, lane="fast", stuck=False, difficulty="difficult"
        )
        self.assertEqual(sel2.tier, "heavy")

    def test_easy_and_medium_stay_light_by_default(self):
        self.assertEqual(
            self.router.resolve(
                ModelPurpose.MAIN, round_num=1, lane="fast", stuck=False, difficulty="easy"
            ).tier,
            "light",
        )
        self.assertEqual(
            self.router.resolve(
                ModelPurpose.MAIN, round_num=1, lane="deep", stuck=False, difficulty="medium"
            ).tier,
            "light",
        )

    def test_medium_stuck_escalates_to_heavy(self):
        sel = self.router.resolve(
            ModelPurpose.MAIN, round_num=10, lane="deep", stuck=True, difficulty="medium"
        )
        self.assertEqual(sel.tier, "heavy")


class ValidationTests(unittest.TestCase):
    def test_unknown_provider_reference_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, "provider"):
            _router(
                {
                    "llm": {
                        "base_url": "u",
                        "tiers": {"light": {"model": "m", "provider": "nope"}},
                    }
                }
            )

    def test_unknown_routing_tier_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, "routing"):
            _router(
                {
                    "llm": {
                        "base_url": "u",
                        "default_model": "flash",
                        "routing": {"summary_tier": "ghost"},
                    }
                }
            )

    def test_tier_missing_model_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, "缺少 model"):
            _router({"llm": {"base_url": "u", "tiers": {"light": {}}}})


if __name__ == "__main__":
    unittest.main()
