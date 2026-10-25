import math
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


class BM25:
    """BM25 over text + boosted tag matches. No deps. Tokenizer unchanged."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._df: dict[str, int] = {}
        self._avgdl = 0.0
        self._n = 0

    def fit(self, records: tuple[MemoryRecord, ...]) -> None:
        self._n = len(records)
        docs = [query_terms(r.text) for r in records]
        for doc in docs:
            for term in doc:
                self._df[term] = self._df.get(term, 0) + 1
        self._avgdl = sum(len(d) for d in docs) / max(self._n, 1)

    def _weight(self, term: str, present: bool, dl: int) -> float:
        df = self._df.get(term, 0)
        if df == 0:
            return 0.0
        idf = math.log((self._n - df + 0.5) / (df + 0.5) + 1.0)
        tf = 1.0 if present else 0.0
        denom = tf + self.k1 * (1 - self.b + self.b * dl / max(self._avgdl, 1.0))
        return idf * (tf * (self.k1 + 1.0)) / denom

    def score(self, record: MemoryRecord, query: str) -> float:
        qterms = query_terms(query)
        text_terms = query_terms(record.text)
        dl = len(text_terms)
        total = sum(self._weight(t, t in text_terms, dl) for t in qterms)
        tag_terms: set[str] = set()
        for tag in record.tags:
            tag_terms |= query_terms(tag)
        for t in qterms:
            if t in tag_terms and t in self._df:
                df = self._df[t]
                total += 2.0 * math.log((self._n - df + 0.5) / (df + 0.5) + 1.0)
        return total
