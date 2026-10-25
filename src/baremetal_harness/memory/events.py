import json
from dataclasses import asdict, is_dataclass

from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.memory.search import query_terms
from baremetal_harness.observability.redaction import Redactor


def _payload_text(payload: object) -> str:
    if is_dataclass(payload) and not isinstance(payload, type):
        return json.dumps(asdict(payload), ensure_ascii=False, default=str)
    return str(payload)


def search_events(
    events: tuple[EventEnvelope, ...],
    query: str,
    *,
    limit: int = 10,
    redactor: Redactor | None = None,
) -> tuple[str, ...]:
    """deja-vu 式：transcripts 就是 memory。多词 AND，返回脱敏片段。无 LLM。"""
    qterms = query_terms(query)
    redactor = redactor or Redactor()
    scored: list[tuple[int, object, str]] = []
    for event in events:
        text = _payload_text(event.payload)
        matched = qterms & query_terms(text)
        if qterms and matched == qterms:
            snippet = redactor.redact(text)
            scored.append((
                len(matched),
                event.timestamp,
                f"[{event.run_id[:8]}] {event.payload.__class__.__name__}: {snippet[:200]}",
            ))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return tuple(snippet for _, _, snippet in scored[:limit])
