import json

from baremetal_harness.memory.consolidation import MemoryCandidate
from baremetal_harness.memory.events import search_events
from baremetal_harness.memory.store import SqliteMemoryStore
from baremetal_harness.observability.redaction import Redactor
from baremetal_harness.sessions.events import JsonlEventStore
from baremetal_harness.tools.types import (
    RegisteredTool,
    ToolCapabilities,
    ToolContext,
    ToolSpec,
)


def make_memory_tools(
    store: SqliteMemoryStore,
    event_store: JsonlEventStore,
    redactor: Redactor,
) -> tuple[RegisteredTool, ...]:
    async def remember(arguments, context: ToolContext) -> str:
        candidate = MemoryCandidate(
            str(arguments["text"]),
            f"run:{context.run_id}:tool:remember",
            tuple(str(tag) for tag in arguments.get("tags", [])),
            str(arguments["correction_of"]) if arguments.get("correction_of") else None,
        )
        _, memory_id = await store.add(candidate)
        return memory_id

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

    async def search_history(arguments, context: ToolContext) -> str:
        events = await event_store.load()
        hits = search_events(events, str(arguments["query"]), redactor=redactor)
        return json.dumps(list(hits), separators=(",", ":"))

    remember_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "correction_of": {"type": "string"},
        },
        "required": ["text"],
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
        RegisteredTool(
            ToolSpec(
                "search_history",
                "Search historical events (trace memory)",
                search_schema,
                ToolCapabilities(),
            ),
            search_history,
        ),
    )
