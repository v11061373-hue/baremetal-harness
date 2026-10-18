import re
import unicodedata

from baremetal_harness.memory.types import MemoryRecord

_WORD = re.compile(r"\w+")
_CJK = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]"
)


def normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(normalized.split())


def _tokenize_run(run: str) -> set[str]:
    # A \w+ run can mix scripts (e.g. "使用python"). Latin/digit spans stay
    # whole words, but CJK has no whitespace between words, so emit each
    # character plus adjacent bigrams to get matchable terms without a
    # dedicated word segmenter.
    tokens: set[str] = set()
    latin: list[str] = []
    cjk: list[str] = []

    def flush_latin() -> None:
        if latin:
            tokens.add("".join(latin))
            latin.clear()

    def flush_cjk() -> None:
        for index, char in enumerate(cjk):
            tokens.add(char)
            if index + 1 < len(cjk):
                tokens.add(char + cjk[index + 1])
        cjk.clear()

    for char in run:
        if _CJK.match(char):
            flush_latin()
            cjk.append(char)
        else:
            flush_cjk()
            latin.append(char)
    flush_latin()
    flush_cjk()
    return tokens


def query_terms(query: str) -> set[str]:
    terms: set[str] = set()
    for run in _WORD.findall(normalize(query)):
        terms |= _tokenize_run(run)
    return terms


def memory_score(memory: MemoryRecord, query: str) -> int:
    terms = query_terms(query)
    tags: set[str] = set()
    for tag in memory.tags:
        tags |= query_terms(tag)
    text_terms = query_terms(memory.text)
    return 3 * len(terms & tags) + 2 * len(terms & text_terms)
