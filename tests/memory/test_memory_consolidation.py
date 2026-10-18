from baremetal_harness.memory.consolidation import (
    ConsolidationAction,
    MemoryCandidate,
    MemoryConsolidator,
)
from baremetal_harness.memory.types import MemoryRecord


def record(text: str, source: str = "session:s1") -> MemoryRecord:
    return MemoryRecord(
        "mem-1",
        text,
        source,
        ("project",),
        "2026-07-26T00:00:00+00:00",
    )


def test_exact_duplicate_is_noop() -> None:
    candidate = MemoryCandidate("Python 3.12", "session:s1", ("project",))

    assert (
        MemoryConsolidator().decide(candidate, (record("Python 3.12"),))
        is ConsolidationAction.NOOP
    )


def test_correction_must_be_explicit_to_supersede() -> None:
    candidate = MemoryCandidate(
        "Python 3.13",
        "session:s2",
        ("project",),
        correction_of="mem-1",
    )

    assert (
        MemoryConsolidator().decide(candidate, (record("Python 3.12"),))
        is ConsolidationAction.SUPERSEDE
    )
