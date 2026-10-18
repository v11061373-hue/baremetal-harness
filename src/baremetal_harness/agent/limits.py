from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunLimits:
    max_turns: int = 16
    max_tool_calls: int = 32
    timeout_seconds: float = 300.0
