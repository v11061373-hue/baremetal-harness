from baremetal_harness.agent.loop import RunCompleted
from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.memory.events import search_events
from baremetal_harness.observability.redaction import Redactor


def _event(run_id: str, output: str) -> EventEnvelope:
    return EventEnvelope.create(
        run_id=run_id, session_id="s", sequence=1, payload=RunCompleted(output)
    )


def test_search_events_requires_all_terms() -> None:
    events = (
        _event("r1", "wrote config file"),
        _event("r2", "ran tests"),
    )
    assert search_events(events, "config tests") == ()
    assert len(search_events(events, "config")) == 1
    assert len(search_events(events, "tests")) == 1


def test_search_events_redacts_secret() -> None:
    events = (_event("r1", "key sk-123 leaked"),)
    hits = search_events(events, "sk-123", redactor=Redactor(("sk-123",)))
    assert hits and "sk-123" not in hits[0]
