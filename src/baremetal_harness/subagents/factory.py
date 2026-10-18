from pathlib import Path

from baremetal_harness.agent.limits import RunLimits
from baremetal_harness.agent.loop import AgentLoop
from baremetal_harness.agent.state import RunStatus
from baremetal_harness.context.builder import ContextBuilder
from baremetal_harness.context.types import ContextBudget
from baremetal_harness.core.messages import ToolResultContent
from baremetal_harness.model.base import ModelProvider
from baremetal_harness.observability.trace import TraceSink
from baremetal_harness.subagents.tools import make_delegate_tool
from baremetal_harness.subagents.types import SubagentResult, SubagentSpec
from baremetal_harness.tools.registry import ToolRegistry

CHILD_STATUS = {
    RunStatus.COMPLETED: "completed",
    RunStatus.FAILED: "failed",
    RunStatus.EXHAUSTED: "exhausted",
    RunStatus.CANCELLED: "cancelled",
}


class AgentLoopFactory:
    """Run a delegated task in a real, isolated child AgentLoop.

    The child gets its own run, its own message history and a tool registry
    narrowed to the delegated allowlist. Permission policy, approval provider
    and sandbox stay shared so a child can never widen the parent's authority.
    """

    def __init__(
        self,
        provider: ModelProvider,
        model: str,
        *,
        workspace: Path,
        context_builder: ContextBuilder | None = None,
        context_budget: ContextBudget | None = None,
        permission_policy=None,
        approval_provider=None,
        session_repository=None,
        checkpoint_store=None,
        event_store=None,
        trace_sinks: tuple[TraceSink, ...] = (),
        max_depth: int = 2,
    ) -> None:
        self.provider = provider
        self.model = model
        self.workspace = workspace
        self.context_builder = context_builder
        self.context_budget = context_budget
        self.permission_policy = permission_policy
        self.approval_provider = approval_provider
        self.session_repository = session_repository
        self.checkpoint_store = checkpoint_store
        self.event_store = event_store
        self.trace_sinks = trace_sinks
        self.max_depth = max_depth
        # Bound after the parent registry exists, because the parent's
        # delegate_task tool needs the runtime that owns this factory.
        self.tools: ToolRegistry | None = None
        self.runtime = None

    def _child_tools(self, spec: SubagentSpec) -> ToolRegistry:
        if self.tools is None:
            raise RuntimeError("subagent factory has no tool registry bound")
        allowed = tuple(
            name for name in spec.allowed_tools if name != "delegate_task"
        )
        registry = self.tools.subset(allowed)
        if (
            "delegate_task" in spec.allowed_tools
            and spec.depth < self.max_depth
            and self.runtime is not None
        ):
            registry.register(
                make_delegate_tool(
                    self.runtime,
                    parent_allowed_tools=allowed,
                    child_depth=spec.depth + 1,
                )
            )
        return registry

    async def run(self, spec: SubagentSpec) -> SubagentResult:
        tools = self._child_tools(spec)
        loop = AgentLoop(
            self.provider,
            self.model,
            limits=RunLimits(spec.max_turns, spec.max_tool_calls),
            tools=tools,
            workspace=self.workspace,
            session_repository=self.session_repository,
            checkpoint_store=self.checkpoint_store,
            event_store=self.event_store,
            context_builder=self.context_builder,
            context_budget=self.context_budget,
            permission_policy=self.permission_policy,
            approval_provider=self.approval_provider,
            trace_sinks=self.trace_sinks,
        )
        result = await loop.run(_child_prompt(spec))
        return SubagentResult(
            spec.agent_id,
            CHILD_STATUS.get(result.status, result.status.value),
            result.output or f"child ended with status {result.status.value}",
            _evidence(result.messages),
            result.run_id,
        )


def _child_prompt(spec: SubagentSpec) -> str:
    tools = ", ".join(spec.allowed_tools) or "none"
    return (
        f"You are subagent '{spec.agent_id}' working on one bounded task.\n"
        f"Task: {spec.task}\n"
        f"You may only use these tools: {tools}.\n"
        "Report the outcome and cite the evidence you inspected."
    )


def _evidence(messages) -> tuple[str, ...]:
    return tuple(
        item.output
        for message in messages
        for item in message.content
        if isinstance(item, ToolResultContent) and not item.is_error
    )
