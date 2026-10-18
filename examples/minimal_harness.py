import asyncio

from baremetal_harness.core.messages import (
    Message,
    ModelRequest,
    ResponseCompleted,
    TextContent,
    TextDelta,
)
from baremetal_harness.model.fake import FakeModel


async def run() -> None:
    provider = FakeModel(
        [TextDelta("BareMetal Harness is alive."), ResponseCompleted("stop")]
    )
    request = ModelRequest(
        "fake",
        (Message("user", (TextContent("hello"),)),),
    )
    async for event in provider.stream(request):
        if isinstance(event, TextDelta):
            print(event.text, end="")
    print()


if __name__ == "__main__":
    asyncio.run(run())
