import unittest
from types import SimpleNamespace
from unittest.mock import patch

from solver.tools.registry import ToolRegistry, ToolSpec, load_plugin_tools


def _definition(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {"type": "object", "properties": {}},
        },
    }


class ToolRegistryTests(unittest.TestCase):
    def test_rejects_duplicate_tool_names(self):
        spec = ToolSpec(_definition("echo"), lambda args: "ok")
        with self.assertRaisesRegex(ValueError, "工具名称重复"):
            ToolRegistry([spec, spec])

    def test_loads_explicit_plugin_contract(self):
        spec = ToolSpec(_definition("plugin_echo"), lambda args: str(args))
        module = SimpleNamespace(TOOLS=[spec])

        with patch(
            "solver.tools.registry.importlib.import_module", return_value=module
        ):
            registry = ToolRegistry(load_plugin_tools(["demo_plugin"]))

        self.assertIn("plugin_echo", registry.executors)
        self.assertEqual(registry.definitions[0]["function"]["name"], "plugin_echo")


if __name__ == "__main__":
    unittest.main()
