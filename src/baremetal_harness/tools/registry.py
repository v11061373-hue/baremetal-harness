import re

from baremetal_harness.core.errors import ToolNotFound
from baremetal_harness.tools.types import RegisteredTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        name = tool.spec.name
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise ValueError(f"invalid tool name: {name}")
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = tool

    def get(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFound(f"tool not found: {name}") from exc

    def values(self) -> tuple[RegisteredTool, ...]:
        return tuple(self._tools.values())

    def subset(self, names: tuple[str, ...]) -> "ToolRegistry":
        registry = ToolRegistry()
        for name in dict.fromkeys(names):
            registry.register(self.get(name))
        return registry

    def specs(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "type": "function",
                "function": {
                    "name": tool.spec.name,
                    "description": tool.spec.description,
                    "parameters": tool.spec.parameters,
                },
            }
            for tool in self._tools.values()
        )
