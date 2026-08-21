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


if __name__ == "__main__":
    unittest.main()
