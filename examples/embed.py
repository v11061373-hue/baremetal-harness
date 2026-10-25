"""嵌入 baremetal-harness 当库用：create_app → run_prompt → aclose。

完全离线，FakeModel 重放一个完成流，不需要 API Key。
运行：uv run python examples/embed.py
"""

import asyncio
import tempfile
from pathlib import Path

from baremetal_harness import BareMetalHarnessConfig, create_app
from baremetal_harness.core.messages import ResponseCompleted, TextDelta
from baremetal_harness.model.fake import FakeModel


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = BareMetalHarnessConfig(
            data_dir=Path(tmp) / "data",
            workspace=Path(tmp) / "workspace",
            model="fake",
        )
        app = await create_app(
            config,
            provider=FakeModel(
                [TextDelta("hello from baremetal"), ResponseCompleted("stop")]
            ),
        )
        try:
            result = await app.run_prompt("say hello")
            print(f"status={result.status.value}")
            print(f"output={result.output!r}")
        finally:
            await app.aclose()


if __name__ == "__main__":
    asyncio.run(main())
