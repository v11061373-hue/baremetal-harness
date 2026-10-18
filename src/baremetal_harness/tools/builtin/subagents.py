from baremetal_harness.subagents.runtime import SubagentRuntime
from baremetal_harness.subagents.tools import make_delegate_tool


def make_builtin_subagent_tools(
    runtime: SubagentRuntime,
    allowed_tools: tuple[str, ...],
):
    return (make_delegate_tool(runtime, parent_allowed_tools=allowed_tools),)
