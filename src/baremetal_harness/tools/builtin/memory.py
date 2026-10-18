import json
from datetime import UTC, datetime

from baremetal_harness.memory.store import SqliteMemoryStore
from baremetal_harness.memory.types import MemoryRecord
from baremetal_harness.tools.types import (
    RegisteredTool,
    ToolCapabilities,
    ToolContext,
    ToolSpec,
)


def make_memory_tools(store: SqliteMemoryStore) -> tuple[RegisteredTool, ...]:
    async def remember(arguments, context: ToolContext) -> str:
        record = MemoryRecord(
            str(arguments["memory_id"]),
            str(arguments["text"]),
            str(arguments["source_ref"]),
            tuple(str(tag) for tag in arguments.get("tags", [])),
            datetime.now(UTC).isoformat(),
        )
        await store.put(record)
        return record.memory_id

    async def search_memory(arguments, context: ToolContext) -> str:
        records = await store.search(str(arguments["query"]))
        return json.dumps(
            [
                {
                    "memory_id": record.memory_id,
                    "text": record.text,
                    "source_ref": record.source_ref,
                }
                for record in records
            ],
            separators=(",", ":"),
        )

    remember_schema = {
        "type": "object",
        "properties": {
            "memory_id": {"type": "string"},
            "text": {"type": "string"},
            "source_ref": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["memory_id", "text", "source_ref"],
        "additionalProperties": False,
    }
    search_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    }
    return (
        RegisteredTool(
            ToolSpec(
                "remember",
                "Persist a sourced long-term memory",
                remember_schema,
                ToolCapabilities(side_effects=True),
            ),
            remember,
        ),
        RegisteredTool(
            ToolSpec(
                "search_memory",
                "Search sourced long-term memory",
                search_schema,
                ToolCapabilities(),
            ),
            search_memory,
        ),
    )
