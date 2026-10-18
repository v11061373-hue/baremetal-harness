import re
from dataclasses import dataclass
from typing import Protocol

from baremetal_harness.core.messages import Message, TextContent


@dataclass(frozen=True, slots=True)
class CompactionRequest:
    messages: tuple[Message, ...]
    target_tokens: int


class Compactor(Protocol):
    async def compact(self, request: CompactionRequest) -> Message: ...


class DeterministicCompactor:
    async def compact(self, request: CompactionRequest) -> Message:
        text = " ".join(
            item.text
            for message in request.messages
            for item in message.content
            if isinstance(item, TextContent)
        ).strip()
        sentences = [
            sentence.strip()
            for sentence in re.findall(r"[^.!?]+[.!?]?", text)
            if sentence.strip()
        ]
        if not sentences:
            summary = "[summary]"
        elif len(sentences) == 1:
            summary = f"[summary] {sentences[0]}"
        else:
            summary = f"[summary] {sentences[0]} {sentences[-1]}"
        return Message("assistant", (TextContent(summary),))
