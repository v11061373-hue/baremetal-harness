import asyncio
import sys
import tempfile
from pathlib import Path

from baremetal_harness.agent.loop import AgentLoop
from baremetal_harness.core.messages import ResponseCompleted, TextDelta, ToolCallDelta
from baremetal_harness.model.scripted import ScriptedModel
from baremetal_harness.sandbox.process import ProcessSandbox
from baremetal_harness.tools.builtin.files import make_file_tools
from baremetal_harness.tools.builtin.shell import make_run_command_tool
from baremetal_harness.tools.registry import ToolRegistry
from baremetal_harness.workspace.session import WorkspaceSession


async def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "source"
        source.mkdir()
        (source / "README.md").write_text("original")
        session = WorkspaceSession.create(root / "sandboxes", source)
        sandbox_results = []
        registry = ToolRegistry()
        for tool in make_file_tools():
            registry.register(tool)
        registry.register(
            make_run_command_tool(
                ProcessSandbox(),
                result_sink=sandbox_results.append,
            )
        )
        provider = ScriptedModel(
            (
                (
                    ToolCallDelta(
                        0,
                        "write-1",
                        "write_file",
                        '{"path":"notes.txt","content":"hello from sandbox"}',
                    ),
                    ResponseCompleted("tool_calls"),
                ),
                (
                    ToolCallDelta(
                        0,
                        "run-1",
                        "run_command",
                        (
                            '{"argv":'
                            f'["{sys.executable}","-c",'
                            "\"print('checked')\"]}"
                        ),
                    ),
                    ResponseCompleted("tool_calls"),
                ),
                (
                    ToolCallDelta(
                        0,
                        "escape-1",
                        "write_file",
                        '{"path":"../escape","content":"blocked"}',
                    ),
                    ResponseCompleted("tool_calls"),
                ),
                (TextDelta("finished"), ResponseCompleted("stop")),
            )
        )

        result = await AgentLoop(
            provider,
            "scripted",
            tools=registry,
            workspace=session.workspace,
        ).run("work only in the sandbox")

        escape_result = result.messages[-2].content[0]
        print(
            "source unchanged:",
            "yes" if (source / "README.md").read_text() == "original" else "no",
        )
        print("sandbox changes:")
        for path in session.manifest():
            if path != Path("README.md"):
                print(f"- {path}")
        print("path escape blocked:", "yes" if escape_result.is_error else "no")


if __name__ == "__main__":
    asyncio.run(main())
