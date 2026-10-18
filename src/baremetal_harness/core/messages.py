from dataclasses import dataclass
from typing import Literal, TypeAlias

Role: TypeAlias = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class TextContent:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolResultContent:
    tool_call_id: str
    output: str
    is_error: bool = False


Content: TypeAlias = TextContent | ToolCall | ToolResultContent


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: tuple[Content, ...]


@dataclass(frozen=True, slots=True)
class ModelRequest:
    model: str
    messages: tuple[Message, ...]
    tools: tuple[dict[str, object], ...] = ()
    temperature: float = 0.0


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    index: int
    call_id: str | None = None
    name: str | None = None
    arguments_fragment: str = ""


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class ResponseCompleted:
    finish_reason: str
    usage: Usage | None = None


ModelEvent: TypeAlias = TextDelta | ToolCallDelta | ResponseCompleted
