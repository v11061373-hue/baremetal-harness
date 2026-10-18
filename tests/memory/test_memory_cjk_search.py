from baremetal_harness.memory.search import memory_score, query_terms
from baremetal_harness.memory.types import MemoryRecord


def _record(text: str, tags: tuple[str, ...] = ()) -> MemoryRecord:
    return MemoryRecord(
        "mem-1",
        text,
        "session:s1",
        tags,
        "2026-07-26T00:00:00+00:00",
    )


def test_query_terms_keeps_latin_words_whole() -> None:
    assert query_terms("Python project") == {"python", "project"}


def test_query_terms_splits_cjk_into_chars_and_bigrams() -> None:
    assert query_terms("编程语言") == {
        "编",
        "程",
        "语",
        "言",
        "编程",
        "程语",
        "语言",
    }


def test_query_terms_splits_mixed_script_run() -> None:
    terms = query_terms("使用python")
    assert "python" in terms
    assert "使" in terms
    assert "使用" in terms


def test_cjk_query_matches_overlapping_stored_memory() -> None:
    memory = _record("用户偏好使用Python作为主要开发语言进行开发工作")

    assert memory_score(memory, "你知道我喜欢什么编程语言吗") > 0


def test_cjk_query_matches_tag() -> None:
    memory = _record("用户开发偏好", tags=("编程语言",))

    assert memory_score(memory, "喜欢的编程语言") > 0
