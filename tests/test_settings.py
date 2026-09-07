import json
import tempfile
import unittest
from pathlib import Path

from solver.runtime.settings import apply_llm_gateway, load_settings


class SettingsTests(unittest.TestCase):
    def test_file_then_environment_override(self):
        root = Path(tempfile.mkdtemp(prefix="settings-"))
        path = root / "settings.json"
        path.write_text(
            json.dumps({"llm": {"base_url": "https://old.example/v1"}}),
            encoding="utf-8",
        )

        settings = load_settings(
            [path],
            {
                "LLM_BASE_URL": "https://api.example/v1",
                "LLM_MODEL": "model-x",
                "LLM_GATEWAY": "1",
                "SOLVER_MAX_ROUNDS": "42",
            },
        )

        self.assertEqual(
            settings["llm"]["base_url"],
            "http://api.example.tsecbench.gw/v1",
        )
        self.assertEqual(settings["llm"]["default_model"], "model-x")
        self.assertEqual(settings["solver"]["max_rounds"], 42)

    def test_providers_base_url_also_goes_through_gateway(self):
        root = Path(tempfile.mkdtemp(prefix="settings-"))
        path = root / "settings.json"
        path.write_text(
            json.dumps({
                "llm": {
                    "base_url": "https://api.deepseek.com/v1",
                    "providers": {
                        "tokenhub": {"base_url": "https://tokenhub.tencentmaas.com/v1"},
                    },
                }
            }),
            encoding="utf-8",
        )
        settings = load_settings([path], {"LLM_GATEWAY": "1"})
        self.assertEqual(
            settings["llm"]["providers"]["tokenhub"]["base_url"],
            "http://tokenhub.tencentmaas.com.tsecbench.gw/v1",
        )
        # Top-level is also rewritten so same-endpoint providers inherit keys.
        self.assertEqual(
            settings["llm"]["base_url"],
            "http://api.deepseek.com.tsecbench.gw/v1",
        )

    def test_existing_invalid_file_fails_loudly(self):
        root = Path(tempfile.mkdtemp(prefix="settings-"))
        path = root / "settings.json"
        path.write_text("{not-json", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "无法加载配置文件"):
            load_settings([path], {})

    def test_invalid_section_fails_loudly(self):
        root = Path(tempfile.mkdtemp(prefix="settings-"))
        path = root / "settings.json"
        path.write_text('{"solver": []}', encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "solver 必须是 JSON object"):
            load_settings([path], {})

    def test_gateway_keeps_disabled_url(self):
        url = "https://api.example/v1"
        self.assertEqual(apply_llm_gateway(url, {}), url)

    def test_local_overlays_base_settings(self):
        root = Path(tempfile.mkdtemp(prefix="settings-merge-"))
        base = root / "settings.json"
        local = root / "settings.local.json"
        base.write_text(
            json.dumps({
                "llm": {
                    "routing": {"hard_tier": "light", "escalate_rounds": 0},
                    "default_model": "base-model",
                },
            }),
            encoding="utf-8",
        )
        local.write_text(
            json.dumps({
                "llm": {
                    "api_key": "secret",
                    "routing": {"hard_tier": "heavy", "escalate_rounds": 3},
                },
            }),
            encoding="utf-8",
        )
        settings = load_settings([local, base], {})
        self.assertEqual(settings["llm"]["api_key"], "secret")
        self.assertEqual(settings["llm"]["default_model"], "base-model")
        self.assertEqual(settings["llm"]["routing"]["hard_tier"], "light")
        self.assertEqual(settings["llm"]["routing"]["escalate_rounds"], 0)
        self.assertTrue(settings.get("_routing_corrected"))

    def test_repo_stable_model_topology(self):
        """主路径 deepseek ≠ 兜底 glm，故障切换才有意义。"""
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / "settings.json").read_text(encoding="utf-8"))
        llm = data["llm"]
        light = llm["tiers"]["light"]["model"]
        fallback = list(llm.get("fallback_models") or [])
        self.assertTrue(light.startswith("deepseek-v4-flash"), light)
        self.assertEqual(llm["default_model"], light)
        self.assertTrue(fallback, "fallback_models must be non-empty")
        self.assertTrue(
            any(str(m).startswith("glm") for m in fallback),
            f"stable topology expects glm failover, got {fallback}",
        )
        self.assertNotIn(light, fallback)
        self.assertEqual(llm["routing"]["hard_tier"], "light")
        self.assertEqual(llm["routing"]["stuck_escalate_tier"], "light")
        self.assertEqual(llm["routing"]["escalate_rounds"], 0)
        self.assertEqual(llm.get("observer_model"), light)
        solver = data["solver"]
        self.assertFalse(solver.get("pro_enabled"))
        self.assertFalse(solver.get("hard_competing_hypotheses"))
        self.assertEqual(solver.get("observer_mode", "advisory"), "advisory")
        self.assertEqual(set(solver.get("lastmile_codes") or []), {"a-03", "f2-05", "b-02"})


if __name__ == "__main__":
    unittest.main()
