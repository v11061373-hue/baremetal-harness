from dataclasses import dataclass


class ContextBudgetExceeded(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ContextBudget:
    total: int
    reserve_output: int

    @property
    def input_limit(self) -> int:
        return self.total - self.reserve_output


@dataclass(frozen=True, slots=True)
class ContextSource:
    source_id: str
    text: str
    priority: int
    required: bool = False


@dataclass(frozen=True, slots=True)
class AgentContext:
    items: tuple[ContextSource, ...]
    estimated_tokens: int
    dropped_source_ids: tuple[str, ...]
