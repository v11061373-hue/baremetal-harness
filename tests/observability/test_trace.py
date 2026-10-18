import json
from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.agent.loop import AgentLoop
from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.core.messages import ResponseCompleted, TextDelta
from baremetal_harness.model.fake import FakeModel
from baremetal_harness.observability.trace import JsonlTraceSink


async def test_trace_sink_persists_redacted_event(tmp_path: Path) -> None:
    event = EventEnvelope(
        "event-1",
        "run-1",
        "session-1",
        1,
        datetime(2026, 7, 26, tzinfo=UTC),
        {"authorization": "Bearer test-value", "message": "safe"},
    )
    sink = JsonlTraceSink(tmp_path, secrets=("test-value",))
    await sink.emit(event)
    line = json.loads(next(tmp_path.glob("*.jsonl")).read_text().splitlines()[0])
    assert "test-value" not in json.dumps(line)
    assert line["event_id"] == "event-1"


async def test_agent_fans_out_every_event_to_trace(tmp_path: Path) -> None:
    sink = JsonlTraceSink(tmp_path)
    result = await AgentLoop(
        FakeModel((TextDelta("done"), ResponseCompleted("stop"))),
        "fake",
        trace_sinks=(sink,),
    ).run("hello")

    records = [
        json.loads(line)
        for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()
    ]
    assert [record["event_id"] for record in records] == [
        event.event_id for event in result.events
    ]
