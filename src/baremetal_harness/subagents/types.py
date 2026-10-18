from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SubagentSpec:
    agent_id: str
    task: str
    depth: int
    max_turns: int
    max_tool_calls: int
    allowed_tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SubagentResult:
    agent_id: str
    status: str
    summary: str
    evidence: tuple[str, ...]
    child_run_id: str
