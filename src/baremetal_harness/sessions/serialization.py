from collections.abc import Mapping
from dataclasses import fields
from datetime import UTC, datetime
from typing import get_origin

from baremetal_harness.context.types import AgentContext, ContextSource
from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.core.messages import (
    Message,
    TextContent,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    ToolResultContent,
)
from baremetal_harness.sessions.types import Checkpoint

CHECKPOINT_FORMAT_VERSION = 1
EVENT_FORMAT_VERSION = 1


class PersistenceError(ValueError):
    pass


def _encode_content(item: object) -> dict[str, object]:
    if isinstance(item, TextContent):
        return {"type": "text", "text": item.text}
    if isinstance(item, ToolCall):
        return {
            "type": "tool_call",
            "id": item.id,
            "name": item.name,
            "arguments": item.arguments,
        }
    if isinstance(item, ToolResultContent):
        return {
            "type": "tool_result",
            "tool_call_id": item.tool_call_id,
            "output": item.output,
            "is_error": item.is_error,
        }
    raise PersistenceError("unknown message content")


def _decode_content(payload: object) -> object:
    if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
        raise PersistenceError("invalid message content")
    content_type = payload["type"]
    try:
        if content_type == "text":
            return TextContent(str(payload["text"]))
        if content_type == "tool_call":
            arguments = payload["arguments"]
            if not isinstance(arguments, dict):
                raise TypeError
            return ToolCall(
                str(payload["id"]),
                str(payload["name"]),
                arguments,
            )
        if content_type == "tool_result":
            return ToolResultContent(
                str(payload["tool_call_id"]),
                str(payload["output"]),
                bool(payload["is_error"]),
            )
    except (KeyError, TypeError) as exc:
        raise PersistenceError("invalid message content") from exc
    raise PersistenceError("unknown message content type")


def encode_checkpoint(checkpoint: Checkpoint) -> dict[str, object]:
    return {
        "version": CHECKPOINT_FORMAT_VERSION,
        "checkpoint_id": checkpoint.checkpoint_id,
        "run_id": checkpoint.run_id,
        "session_id": checkpoint.session_id,
        "sequence": checkpoint.sequence,
        "status": checkpoint.status,
        "messages": [
            {
                "role": message.role,
                "content": [_encode_content(item) for item in message.content],
            }
            for message in checkpoint.messages
        ],
        "completed_tool_executions": list(
            checkpoint.completed_tool_executions
        ),
        "context_snapshot": (
            {
                "items": [
                    {
                        "source_id": item.source_id,
                        "text": item.text,
                        "priority": item.priority,
                        "required": item.required,
                    }
                    for item in checkpoint.context_snapshot.items
                ],
                "estimated_tokens": checkpoint.context_snapshot.estimated_tokens,
                "dropped_source_ids": list(
                    checkpoint.context_snapshot.dropped_source_ids
                ),
            }
            if checkpoint.context_snapshot is not None
            else None
        ),
    }


def decode_checkpoint(payload: Mapping[str, object]) -> Checkpoint:
    if payload.get("version") != CHECKPOINT_FORMAT_VERSION:
        raise PersistenceError("unknown checkpoint version")
    expected = {
        "version",
        "checkpoint_id",
        "run_id",
        "session_id",
        "sequence",
        "status",
        "messages",
        "completed_tool_executions",
    }
    if not expected.issubset(payload) or not set(payload).issubset(
        expected | {"context_snapshot"}
    ):
        raise PersistenceError("unknown checkpoint fields")
    try:
        raw_messages = payload["messages"]
        raw_completed = payload["completed_tool_executions"]
        raw_context = payload.get("context_snapshot")
        if not isinstance(raw_messages, list) or not isinstance(raw_completed, list):
            raise TypeError
        messages = []
        for raw in raw_messages:
            if not isinstance(raw, dict) or set(raw) != {"role", "content"}:
                raise TypeError
            content = raw["content"]
            if not isinstance(content, list):
                raise TypeError
            messages.append(
                Message(
                    raw["role"],
                    tuple(_decode_content(item) for item in content),
                )
            )
        context_snapshot = None
        if raw_context is not None:
            if not isinstance(raw_context, dict) or set(raw_context) != {
                "items",
                "estimated_tokens",
                "dropped_source_ids",
            }:
                raise TypeError
            raw_items = raw_context["items"]
            raw_dropped = raw_context["dropped_source_ids"]
            if not isinstance(raw_items, list) or not isinstance(raw_dropped, list):
                raise TypeError
            items = []
            for item in raw_items:
                if not isinstance(item, dict) or set(item) != {
                    "source_id",
                    "text",
                    "priority",
                    "required",
                }:
                    raise TypeError
                items.append(
                    ContextSource(
                        str(item["source_id"]),
                        str(item["text"]),
                        int(item["priority"]),
                        bool(item["required"]),
                    )
                )
            context_snapshot = AgentContext(
                tuple(items),
                int(raw_context["estimated_tokens"]),
                tuple(str(item) for item in raw_dropped),
            )
        return Checkpoint(
            str(payload["checkpoint_id"]),
            str(payload["run_id"]),
            str(payload["session_id"]),
            int(payload["sequence"]),
            str(payload["status"]),
            tuple(messages),
            tuple(str(item) for item in raw_completed),
            context_snapshot,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PersistenceError("invalid checkpoint") from exc


def _event_payload_types() -> dict[str, type]:
    from baremetal_harness.agent.loop import (
        ApprovalRequested,
        ApprovalResolved,
        ContextBuilt,
        ContextInjected,
        ModelStreamStarted,
        RunCancelled,
        RunCompleted,
        RunStarted,
        VerificationFailed,
    )
    from baremetal_harness.workspace.session import ArtifactApplied

    return {
        item.__name__: item
        for item in (
            RunStarted,
            ApprovalRequested,
            ApprovalResolved,
            ContextBuilt,
            ContextInjected,
            ModelStreamStarted,
            TextDelta,
            ToolCallDelta,
            RunCompleted,
            RunCancelled,
            ArtifactApplied,
            VerificationFailed,
        )
    }


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise PersistenceError("event timestamp must be UTC")
    return value.isoformat()


def encode_event(envelope: EventEnvelope) -> dict[str, object]:
    payload_type = envelope.payload.__class__.__name__
    if payload_type not in _event_payload_types():
        raise PersistenceError("unknown event payload type")
    return {
        "version": EVENT_FORMAT_VERSION,
        "event_id": envelope.event_id,
        "run_id": envelope.run_id,
        "session_id": envelope.session_id,
        "sequence": envelope.sequence,
        "timestamp": _utc_timestamp(envelope.timestamp),
        "payload_type": payload_type,
        "payload": {
            field.name: getattr(envelope.payload, field.name)
            for field in fields(envelope.payload)
        },
        "parent_event_id": envelope.parent_event_id,
    }


def decode_event(payload: Mapping[str, object]) -> EventEnvelope:
    expected = {
        "version",
        "event_id",
        "run_id",
        "session_id",
        "sequence",
        "timestamp",
        "payload_type",
        "payload",
        "parent_event_id",
    }
    if payload.get("version") != EVENT_FORMAT_VERSION or set(payload) != expected:
        raise PersistenceError("invalid event envelope")
    try:
        payload_type = payload["payload_type"]
        payload_values = payload["payload"]
        if not isinstance(payload_type, str) or not isinstance(payload_values, dict):
            raise TypeError
        payload_class = _event_payload_types().get(payload_type)
        if payload_class is None:
            raise PersistenceError("unknown event payload type")
        payload_fields = fields(payload_class)
        expected_fields = {field.name for field in payload_fields}
        if set(payload_values) != expected_fields:
            raise PersistenceError("invalid event payload fields")
        timestamp = datetime.fromisoformat(str(payload["timestamp"]))
        _utc_timestamp(timestamp)
        decoded_values = dict(payload_values)
        for field in payload_fields:
            value = decoded_values[field.name]
            if (
                isinstance(value, list)
                and (
                    isinstance(field.default, tuple)
                    or get_origin(field.type) is tuple
                )
            ):
                decoded_values[field.name] = tuple(value)
        event_payload = payload_class(**decoded_values)
        return EventEnvelope(
            str(payload["event_id"]),
            str(payload["run_id"]),
            str(payload["session_id"]),
            int(payload["sequence"]),
            timestamp,
            event_payload,
            (
                str(payload["parent_event_id"])
                if payload["parent_event_id"] is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PersistenceError("invalid event envelope") from exc
