from dataclasses import dataclass
from enum import StrEnum

from baremetal_harness.memory.search import normalize
from baremetal_harness.memory.types import MemoryRecord


class ConsolidationAction(StrEnum):
    CREATE = "create"
    NOOP = "noop"
    SUPERSEDE = "supersede"


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    text: str
    source_ref: str
    tags: tuple[str, ...]
    correction_of: str | None = None


class MemoryConsolidator:
    def decide(
        self,
        candidate: MemoryCandidate,
        matches: tuple[MemoryRecord, ...],
    ) -> ConsolidationAction:
        if any(
            normalize(memory.text) == normalize(candidate.text)
            and memory.source_ref == candidate.source_ref
            for memory in matches
        ):
            return ConsolidationAction.NOOP
        if candidate.correction_of is not None and any(
            memory.memory_id == candidate.correction_of for memory in matches
        ):
            return ConsolidationAction.SUPERSEDE
        return ConsolidationAction.CREATE
