from baremetal_harness.memory.search import BM25
from baremetal_harness.memory.types import MemoryRecord


def _record(mid: str, text: str, tags: tuple[str, ...] = ()) -> MemoryRecord:
    return MemoryRecord(
        mid, text, "inline-sha256:x", tags, "2026-01-01T00:00:00+00:00"
    )


def test_bm25_zero_when_no_overlap() -> None:
    bm25 = BM25()
    bm25.fit((_record("a", "python memory"),))
    assert bm25.score(_record("a", "python memory"), "zebra") == 0.0


def test_bm25_tag_match_boosts() -> None:
    bm25 = BM25()
    bm25.fit((_record("a", "irrelevant"), _record("b", "python code")))
    assert bm25.score(_record("a", "irrelevant", ("python",)), "python") > 0.0
    assert bm25.score(_record("b", "python code"), "python") > 0.0


def test_bm25_rare_term_outranks_common() -> None:
    bm25 = BM25()
    bm25.fit((
        _record("a", "rareword"),
        _record("b", "common common"),
        _record("c", "common"),
    ))
    assert bm25.score(_record("a", "rareword"), "rareword") > bm25.score(
        _record("b", "common common"), "common"
    )
