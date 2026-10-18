from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    text: str
    source_ref: str
    tags: tuple[str, ...]
    created_at: str
    supersedes: str | None = None
