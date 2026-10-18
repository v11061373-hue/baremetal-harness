import asyncio
from dataclasses import replace
from typing import Protocol

from baremetal_harness.subagents.types import SubagentResult, SubagentSpec


class SubagentLimitExceeded(RuntimeError):
    pass


class AgentFactory(Protocol):
    async def run(self, spec: SubagentSpec) -> SubagentResult: ...


class SubagentRuntime:
    def __init__(
        self,
        factory: AgentFactory,
        *,
        max_depth: int,
        max_children: int,
        parent_allowed_tools: tuple[str, ...] = (),
    ) -> None:
        self.factory = factory
        self.max_depth = max_depth
        self.max_children = max_children
        self.parent_allowed_tools = parent_allowed_tools
        self._spawned = 0
        self._running: set[asyncio.Task[SubagentResult]] = set()

    @property
    def spawned_count(self) -> int:
        return self._spawned

    @property
    def running_count(self) -> int:
        return len(self._running)

    async def spawn(self, spec: SubagentSpec) -> SubagentResult:
        if spec.depth > self.max_depth:
            raise SubagentLimitExceeded("subagent depth exceeds limit")
        if self._spawned >= self.max_children:
            raise SubagentLimitExceeded("subagent child count exceeds limit")
        if spec.max_turns <= 0 or spec.max_tool_calls < 0:
            raise SubagentLimitExceeded("subagent budget must be positive")
        allowed = spec.allowed_tools
        if self.parent_allowed_tools:
            parent = set(self.parent_allowed_tools)
            allowed = tuple(name for name in allowed if name in parent)
        child_spec = replace(spec, allowed_tools=allowed)
        self._spawned += 1
        task = asyncio.create_task(self.factory.run(child_spec))
        self._running.add(task)
        try:
            return await task
        finally:
            self._running.discard(task)

    async def cancel_all(self) -> int:
        running = tuple(self._running)
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        return len(running)
