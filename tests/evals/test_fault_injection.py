import pytest

from baremetal_harness.core.messages import ModelRequest, ResponseCompleted, TextDelta
from baremetal_harness.evals.faults import DisconnectingModel
from baremetal_harness.model.fake import FakeModel


async def test_disconnect_fault_happens_after_configured_event() -> None:
    provider = DisconnectingModel(
        FakeModel((TextDelta("partial"), ResponseCompleted("stop"))),
        after_event=1,
    )

    stream = provider.stream(ModelRequest("fake", ()))
    assert await anext(stream) == TextDelta("partial")
    with pytest.raises(ConnectionError, match="injected"):
        await anext(stream)
