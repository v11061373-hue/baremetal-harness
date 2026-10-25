import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from baremetal_harness.agent.limits import RunLimits
from baremetal_harness.agent.state import RunStatus, transition
from baremetal_harness.context.builder import ContextBuilder, sources_from_messages
from baremetal_harness.context.types import AgentContext, ContextBudget, ContextSource
from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.core.messages import (
    Message,
    ModelRequest,
    ResponseCompleted,
    TextContent,
    TextDelta,
    ToolCallDelta,
    ToolResultContent,
)
from baremetal_harness.model.base import ModelProvider
from baremetal_harness.observability.trace import TraceSink
from baremetal_harness.permissions.approval import InMemoryApprovalProvider
from baremetal_harness.permissions.policy import DefaultPermissionPolicy
from baremetal_harness.permissions.types import PermissionDecision, PermissionRequest
from baremetal_harness.sessions.checkpoints import FileCheckpointStore
from baremetal_harness.sessions.database import SessionRepository
from baremetal_harness.sessions.events import JsonlEventStore
from baremetal_harness.sessions.types import Checkpoint, RunRecord, SessionRecord
from baremetal_harness.tools.assembler import ToolCallAssembler
from baremetal_harness.tools.executor import ToolExecutor
from baremetal_harness.tools.registry import ToolRegistry
from baremetal_harness.tools.types import ToolContext


@dataclass(frozen=True, slots=True)
class RunStarted:
    prompt: str


@dataclass(frozen=True, slots=True)
class ContextBuilt:
    message_count: int
    estimated_tokens: int | None = None
    dropped_source_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelStreamStarted:
    turn: int


@dataclass(frozen=True, slots=True)
class RunCompleted:
    output: str


@dataclass(frozen=True, slots=True)
class VerificationFailed:
    output: str
    reason: str


@dataclass(frozen=True, slots=True)
class RunCancelled:
    reason: str = "cancelled"


@dataclass(frozen=True, slots=True)
class ApprovalRequested:
    request_id: str
    tool_call_id: str
    tool_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class ApprovalResolved:
    request_id: str
    approved: bool
    reason: str


@dataclass(frozen=True, slots=True)
class PermissionEvaluated:
    tool_name: str
    decision: str
    reason: str
    argument_digest: str


@dataclass(frozen=True, slots=True)
class BudgetExceeded:
    kind: str  # "turns" | "tool_calls" | "timeout"


class ContextProvider(Protocol):
    """Contribute extra context sources for one run, e.g. skills or memory."""

    async def build(self, prompt: str) -> tuple[ContextSource, ...]: ...


class Verifier(Protocol):
    """Decide whether a completed output satisfies the task, before COMPLETED.

    Grounded check: inspect the task requirements and the *actual* resulting
    state inside `verify` via your own closure. Return `None` to pass, or a
    non-empty `str` naming why it failed.
    """

    async def verify(self, output: str, prompt: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ContextInjected:
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    session_id: str
    status: RunStatus
    output: str
    messages: tuple[Message, ...]
    events: tuple[EventEnvelope, ...]


class AgentLoop:
    def __init__(
        self,
        provider: ModelProvider,
        model: str,
        *,
        limits: RunLimits | None = None,
        tools: ToolRegistry | None = None,
        tool_executor: ToolExecutor | None = None,
        workspace: Path | None = None,
        session_repository: SessionRepository | None = None,
        checkpoint_store: FileCheckpointStore | None = None,
        event_store: JsonlEventStore | None = None,
        clock: Callable[[], datetime] | None = None,
        context_builder: ContextBuilder | None = None,
        context_budget: ContextBudget | None = None,
        permission_policy: DefaultPermissionPolicy | None = None,
        approval_provider: InMemoryApprovalProvider | None = None,
        trace_sinks: tuple[TraceSink, ...] = (),
        context_providers: tuple["ContextProvider", ...] = (),
        verifier: Verifier | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.limits = limits or RunLimits()
        self.tools = tools
        self.tool_executor = tool_executor or (
            ToolExecutor(tools) if tools is not None else None
        )
        self.workspace = workspace
        self.session_repository = session_repository
        self.checkpoint_store = checkpoint_store
        self.event_store = event_store
        self.clock = clock or (lambda: datetime.now(UTC))
        if (context_builder is None) != (context_budget is None):
            raise ValueError(
                "context_builder and context_budget must be configured together"
            )
        self.context_builder = context_builder
        self.context_budget = context_budget
        self.permission_policy = permission_policy
        self.approval_provider = approval_provider
        self.trace_sinks = trace_sinks
        self.context_providers = context_providers
        self.verifier = verifier

    async def run(
        self,
        prompt: str,
        *,
        history: tuple[Message, ...] = (),
        session_id: str | None = None,
        trace_sinks: tuple[TraceSink, ...] = (),
    ) -> RunResult:
        run_id = str(uuid4())
        session_id = session_id or str(uuid4())
        events: list[EventEnvelope] = []
        messages = [*history, Message("user", (TextContent(prompt),))]
        status = RunStatus.CREATED

        completed_tool_executions: list[str] = []
        context_snapshot: AgentContext | None = None

        async def emit(payload: object) -> None:
            envelope = EventEnvelope.create(
                run_id=run_id,
                session_id=session_id,
                sequence=len(events) + 1,
                payload=payload,
                parent_event_id=events[-1].event_id if events else None,
            )
            events.append(envelope)
            if self.event_store is not None:
                await self.event_store.append(envelope)
            for sink in (*self.trace_sinks, *trace_sinks):
                await sink.emit(envelope)

        async def checkpoint() -> None:
            if self.checkpoint_store is None:
                return
            await self.checkpoint_store.save(
                Checkpoint(
                    checkpoint_id=str(uuid4()),
                    run_id=run_id,
                    session_id=session_id,
                    sequence=len(events),
                    status=status.value,
                    messages=tuple(messages),
                    completed_tool_executions=tuple(completed_tool_executions),
                    context_snapshot=context_snapshot,
                )
            )

        if self.session_repository is not None:
            now = self.clock()
            if await self.session_repository.get_session(session_id) is None:
                await self.session_repository.create_session(
                    SessionRecord(session_id, now, now)
                )
            else:
                await self.session_repository.touch_session(session_id, now)
            await self.session_repository.create_run(
                RunRecord(run_id, session_id, status.value, now, now)
            )

        await emit(RunStarted(prompt))
        if self.limits.max_turns <= 0:
            status = transition(status, RunStatus.BUILDING_CONTEXT)
            await emit(ContextBuilt(len(messages)))
            await checkpoint()
            status = transition(status, RunStatus.CALLING_MODEL)
            status = transition(status, RunStatus.EXHAUSTED)
            await checkpoint()
            return RunResult(
                run_id,
                session_id,
                status,
                "",
                tuple(messages),
                tuple(events),
            )

        try:
            extra_sources: tuple[ContextSource, ...] = ()
            for provider in self.context_providers:
                extra_sources += await provider.build(prompt)
            extra_sources = tuple(
                source for source in extra_sources if source.text.strip()
            )
            if extra_sources:
                await emit(
                    ContextInjected(
                        tuple(source.source_id for source in extra_sources)
                    )
                )

            tool_calls_used = 0
            for turn in range(1, self.limits.max_turns + 1):
                if status in {
                    RunStatus.RECORDING_RESULTS,
                    RunStatus.RECORDING_TOOL_ERROR,
                } or status is RunStatus.CREATED:
                    status = transition(status, RunStatus.BUILDING_CONTEXT)
                request_messages = tuple(messages)
                selected_extra = extra_sources
                if self.context_builder is not None and self.context_budget is not None:
                    context_snapshot = self.context_builder.build(
                        (*extra_sources, *sources_from_messages(request_messages)),
                        self.context_budget,
                    )
                    selected_indices = {
                        int(item.source_id.removeprefix("message:"))
                        for item in context_snapshot.items
                        if item.source_id.startswith("message:")
                    }
                    selected_extra = tuple(
                        item
                        for item in context_snapshot.items
                        if not item.source_id.startswith("message:")
                    )
                    request_messages = tuple(
                        message
                        for index, message in enumerate(request_messages)
                        if index in selected_indices
                    )
                if selected_extra:
                    request_messages = (
                        Message(
                            "system",
                            tuple(
                                TextContent(item.text) for item in selected_extra
                            ),
                        ),
                        *request_messages,
                    )
                await emit(
                    ContextBuilt(
                        len(request_messages),
                        (
                            context_snapshot.estimated_tokens
                            if context_snapshot is not None
                            else None
                        ),
                        (
                            context_snapshot.dropped_source_ids
                            if context_snapshot is not None
                            else ()
                        ),
                    )
                )
                await checkpoint()
                status = transition(status, RunStatus.CALLING_MODEL)
                await emit(ModelStreamStarted(turn))
                answer: list[str] = []
                assembler = ToolCallAssembler()
                finish_reason: str | None = None
                async for event in self.provider.stream(
                    ModelRequest(
                        self.model,
                        request_messages,
                        self.tools.specs() if self.tools is not None else (),
                    )
                ):
                    if isinstance(event, TextDelta):
                        answer.append(event.text)
                        await emit(event)
                    elif isinstance(event, ToolCallDelta):
                        assembler.feed(event)
                        await emit(event)
                    elif isinstance(event, ResponseCompleted):
                        finish_reason = event.finish_reason
                        break
                if finish_reason == "stop":
                    output = "".join(answer)
                    messages.append(Message("assistant", (TextContent(output),)))
                    if self.verifier is not None:
                        try:
                            reason = await self.verifier.verify(output, prompt)
                        except Exception:
                            status = transition(status, RunStatus.FAILED)
                            await checkpoint()
                            return RunResult(
                                run_id,
                                session_id,
                                status,
                                output,
                                tuple(messages),
                                tuple(events),
                            )
                        if reason is not None:
                            await emit(VerificationFailed(output, reason))
                            messages.append(
                                Message(
                                    "user",
                                    (TextContent(f"上次输出未达标：{reason}，重试"),),
                                )
                            )
                            status = transition(status, RunStatus.RECORDING_RESULTS)
                            continue
                    status = transition(status, RunStatus.COMPLETED)
                    await emit(RunCompleted(output))
                    await checkpoint()
                    return RunResult(
                        run_id,
                        session_id,
                        status,
                        output,
                        tuple(messages),
                        tuple(events),
                    )
                if finish_reason != "tool_calls" or self.tool_executor is None:
                    status = transition(status, RunStatus.FAILED)
                    await checkpoint()
                    return RunResult(
                        run_id,
                        session_id,
                        status,
                        "".join(answer),
                        tuple(messages),
                        tuple(events),
                    )
                calls = assembler.complete()
                if tool_calls_used + len(calls) > self.limits.max_tool_calls:
                    status = transition(status, RunStatus.EXHAUSTED)
                    await checkpoint()
                    return RunResult(
                        run_id,
                        session_id,
                        status,
                        "".join(answer),
                        tuple(messages),
                        tuple(events),
                    )
                status = transition(status, RunStatus.VALIDATING_TOOLS)
                messages.append(Message("assistant", calls))
                await checkpoint()
                decisions: list[tuple[object, bool]] = []
                context = ToolContext(
                    run_id,
                    session_id,
                    self.workspace or Path.cwd(),
                )
                for call in calls:
                    allowed = True
                    if self.permission_policy is not None:
                        registered = self.tools.get(call.name)
                        evaluation = self.permission_policy.evaluate(
                            tool_name=call.name,
                            capabilities=registered.spec.capabilities,
                            arguments=call.arguments,
                        )
                        if evaluation.decision is PermissionDecision.DENY:
                            allowed = False
                        elif evaluation.decision is PermissionDecision.ASK:
                            if status is RunStatus.VALIDATING_TOOLS:
                                status = transition(
                                    status, RunStatus.AWAITING_APPROVAL
                                )
                            request_id = str(uuid4())
                            request = PermissionRequest(
                                request_id,
                                run_id,
                                call.id,
                                call.name,
                                "<redacted>",
                                registered.spec.capabilities,
                                evaluation.reason,
                            )
                            await emit(
                                ApprovalRequested(
                                    request_id,
                                    call.id,
                                    call.name,
                                    evaluation.reason,
                                )
                            )
                            if self.approval_provider is None:
                                allowed = False
                                resolution_reason = "approval provider unavailable"
                            else:
                                resolution = await self.approval_provider.resolve(
                                    request
                                )
                                allowed = resolution.approved
                                resolution_reason = resolution.reason
                            await emit(
                                ApprovalResolved(
                                    request_id,
                                    allowed,
                                    resolution_reason,
                                )
                            )
                    decisions.append((call, allowed))
                any_allowed = any(allowed for _, allowed in decisions)
                target = (
                    RunStatus.EXECUTING_TOOLS
                    if any_allowed
                    else RunStatus.RECORDING_TOOL_ERROR
                )
                status = transition(status, target)
                results = []
                for call, allowed in decisions:
                    if allowed:
                        results.append(
                            await self.tool_executor.execute(call, context)
                        )
                    else:
                        results.append(
                            ToolResultContent(
                                call.id,
                                "permission denied",
                                is_error=True,
                            )
                        )
                tool_calls_used += len(calls)
                for result in results:
                    messages.append(Message("tool", (result,)))
                    completed_tool_executions.append(result.tool_call_id)
                    await checkpoint()
                if status is RunStatus.EXECUTING_TOOLS:
                    status = transition(status, RunStatus.RECORDING_RESULTS)
            status = transition(status, RunStatus.EXHAUSTED)
            await checkpoint()
            return RunResult(
                run_id,
                session_id,
                status,
                "",
                tuple(messages),
                tuple(events),
            )
        except asyncio.CancelledError:
            status = transition(status, RunStatus.CANCELLED)
            await emit(RunCancelled())
            await checkpoint()
            raise
