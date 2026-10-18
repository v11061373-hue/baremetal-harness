from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentMessage:
    message_id: str
    sender_id: str
    recipient_id: str
    kind: str
    payload: dict[str, object]


def validate_message(message: AgentMessage) -> AgentMessage:
    if message.kind not in {"task", "progress", "result", "cancel"}:
        raise ValueError("unknown agent message kind")
    return message
