from baremetal_harness.core.messages import (
    Message,
    ModelRequest,
    ResponseCompleted,
    TextContent,
    TextDelta,
)
from baremetal_harness.model.fake import FakeModel


async def test_fake_model_streams_scripted_events() -> None:
    provider = FakeModel(
        [TextDelta("hello"), TextDelta(" world"), ResponseCompleted("stop")]
    )
    request = ModelRequest(
        model="fake",
        messages=(Message("user", (TextContent("hi"),)),),
    )

    events = [event async for event in provider.stream(request)]

    assert events == [
        TextDelta("hello"),
        TextDelta(" world"),
        ResponseCompleted("stop"),
    ]
    assert provider.requests == [request]
