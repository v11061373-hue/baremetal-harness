import asyncio
import os
import tempfile
from pathlib import Path

from baremetal_harness.agent.loop import AgentLoop
from baremetal_harness.config import EnvironmentSecretProvider
from baremetal_harness.model.openai_compat import OpenAICompatibleClient
from baremetal_harness.observability.trace import JsonlTraceSink
from baremetal_harness.tools.builtin.files import make_file_tools
from baremetal_harness.tools.registry import ToolRegistry


async def run() -> None:
    base_url = os.environ["OPENAI_BASE_URL"]
    model = os.environ["OPENAI_MODEL"]
    api_key = EnvironmentSecretProvider().get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "README.md").write_text("BareMetal Harness real-model smoke.\n")
        tools = ToolRegistry()
        tools.register(make_file_tools()[0])
        trace = JsonlTraceSink(root / "traces", secrets=(api_key,))
        client = OpenAICompatibleClient(base_url, api_key)
        try:
            result = await AgentLoop(
                client,
                model,
                tools=tools,
                workspace=workspace,
                trace_sinks=(trace,),
            ).run(
                "Read README.md using the available read-only tool, then reply "
                "with a short summary."
            )
        finally:
            await client.aclose()

        if not result.output.strip():
            raise SystemExit("real-model smoke returned an empty response")
        trace_text = "\n".join(
            path.read_text() for path in (root / "traces").glob("*.jsonl")
        )
        if api_key in trace_text:
            raise SystemExit("real-model smoke leaked OPENAI_API_KEY into trace")
        print("real-model read-only smoke passed")


if __name__ == "__main__":
    asyncio.run(run())
