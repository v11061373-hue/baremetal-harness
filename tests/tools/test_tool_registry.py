
import pytest

from baremetal_harness.core.errors import ToolNotFound
from baremetal_harness.tools.registry import ToolRegistry
from baremetal_harness.tools.types import (
    RegisteredTool,
    ToolCapabilities,
    ToolContext,
    ToolSpec,
)


async def handler(arguments, context: ToolContext) -> str:
    return str(arguments["path"])


def make_tool() -> RegisteredTool:
    return RegisteredTool(
        ToolSpec(
            name="read_file",
            description="Read one file",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            capabilities=ToolCapabilities(filesystem="read"),
        ),
        handler,
    )


def test_registry_rejects_duplicate_names() -> None:
    registry = ToolRegistry()
    registry.register(make_tool())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(make_tool())


def test_registry_exposes_openai_specs_and_lookup() -> None:
    registry = ToolRegistry()
    registry.register(make_tool())

    assert registry.get("read_file") is make_tool() or registry.get("read_file").spec.name == "read_file"
    assert registry.specs()[0]["type"] == "function"
    with pytest.raises(ToolNotFound):
        registry.get("missing")
