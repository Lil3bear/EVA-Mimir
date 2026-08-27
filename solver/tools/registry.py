"""Validated tool ABI and opt-in extension loading."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass


ToolExecutor = Callable[[dict], str]


@dataclass(frozen=True)
class ToolSpec:
    definition: dict
    executor: ToolExecutor

    @property
    def name(self) -> str:
        try:
            name = self.definition["function"]["name"]
        except (KeyError, TypeError) as exc:
            raise ValueError("工具定义缺少 function.name") from exc
        if not isinstance(name, str) or not name:
            raise ValueError("工具 function.name 必须是非空字符串")
        if not callable(self.executor):
            raise ValueError(f"工具 {name} 的 executor 不可调用")
        return name


class ToolRegistry:
    def __init__(self, specs: Iterable[ToolSpec] = ()) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            if not isinstance(spec, ToolSpec):
                raise TypeError("工具插件的 TOOLS 只能包含 ToolSpec")
            if spec.name in self._specs:
                raise ValueError(f"工具名称重复：{spec.name}")
            self._specs[spec.name] = spec

    @property
    def definitions(self) -> list[dict]:
        return [spec.definition for spec in self._specs.values()]

    @property
    def executors(self) -> dict[str, ToolExecutor]:
        return {name: spec.executor for name, spec in self._specs.items()}

    @property
    def schemas(self) -> dict[str, dict]:
        return {
            name: spec.definition["function"].get("parameters", {})
            for name, spec in self._specs.items()
        }

    def extend(self, specs: Iterable[ToolSpec]) -> "ToolRegistry":
        return ToolRegistry([*self._specs.values(), *specs])


def load_plugin_tools(module_names: Iterable[str]) -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    for module_name in module_names:
        if not isinstance(module_name, str) or not module_name.strip():
            raise ValueError("solver.tool_plugins 必须是非空模块名列表")
        module = importlib.import_module(module_name.strip())
        exported = getattr(module, "TOOLS", None)
        if exported is None:
            raise ValueError(f"工具插件 {module_name} 必须导出 TOOLS")
        specs.extend(exported)
    return specs
