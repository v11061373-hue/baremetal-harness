import asyncio
import contextlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import httpx

from baremetal_harness.agent.limits import RunLimits
from baremetal_harness.agent.loop import AgentLoop, RunResult
from baremetal_harness.agent.state import RunStatus
from baremetal_harness.cli.commands import CommandResult, CommandRouter
from baremetal_harness.config import (
    BareMetalHarnessConfig,
    EnvironmentSecretProvider,
    SecretProvider,
)
from baremetal_harness.context.builder import ContextBuilder
from baremetal_harness.context.tokens import CharacterTokenEstimator
from baremetal_harness.context.types import ContextBudget
from baremetal_harness.core.errors import ApplicationConfigurationError
from baremetal_harness.core.messages import Message
from baremetal_harness.mcp.bridge import register_mcp_tools
from baremetal_harness.mcp.client import StdioMcpClient
from baremetal_harness.mcp.config import McpConfigError, load_mcp_servers
from baremetal_harness.mcp.types import McpError
from baremetal_harness.memory.context import MemoryContextProvider
from baremetal_harness.memory.store import SqliteMemoryStore
from baremetal_harness.model.base import ModelProvider
from baremetal_harness.model.openai_compat import OpenAICompatibleClient
from baremetal_harness.observability.metrics import metrics_from_events
from baremetal_harness.observability.redaction import Redactor
from baremetal_harness.observability.trace import JsonlTraceSink
from baremetal_harness.paths import BareMetalHarnessPaths
from baremetal_harness.permissions.approval import (
    CliApprovalProvider,
    UnattendedApprovalProvider,
)
from baremetal_harness.permissions.guard import DestructiveCommandGuard
from baremetal_harness.permissions.policy import DefaultPermissionPolicy
from baremetal_harness.permissions.types import ApprovalResolution, PermissionRequest
from baremetal_harness.planning.store import PlanStore
from baremetal_harness.sandbox.docker import DockerSandbox
from baremetal_harness.sandbox.process import ProcessSandbox
from baremetal_harness.sandbox.router import SandboxCapabilityUnavailable, SandboxRouter
from baremetal_harness.scheduler.agent_runner import AgentTaskRunner
from baremetal_harness.scheduler.clock import SystemClock
from baremetal_harness.scheduler.runtime import SchedulerRuntime
from baremetal_harness.scheduler.store import SchedulerStore
from baremetal_harness.sessions.checkpoints import FileCheckpointStore
from baremetal_harness.sessions.database import SessionRepository
from baremetal_harness.sessions.events import JsonlEventStore
from baremetal_harness.sessions.recovery import (
    RecoveryDecision,
    decide_recovery,
    pending_tool_executions,
)
from baremetal_harness.sessions.serialization import PersistenceError
from baremetal_harness.sessions.types import RunRecord
from baremetal_harness.skills.discovery import discover_skills
from baremetal_harness.skills.provider import SkillContextProvider
from baremetal_harness.skills.rules import ProjectRulesProvider
from baremetal_harness.subagents.factory import AgentLoopFactory
from baremetal_harness.subagents.runtime import SubagentRuntime
from baremetal_harness.tools.builtin.files import make_file_tools
from baremetal_harness.tools.builtin.memory import make_memory_tools
from baremetal_harness.tools.builtin.planning import make_builtin_planning_tools
from baremetal_harness.tools.builtin.scheduler import make_builtin_scheduler_tools
from baremetal_harness.tools.builtin.shell import make_run_command_tool
from baremetal_harness.tools.builtin.subagents import make_builtin_subagent_tools
from baremetal_harness.tools.builtin.toolsets import (
    make_local_inspection_tools,
    make_web_tools,
)
from baremetal_harness.tools.registry import ToolRegistry
from baremetal_harness.tools.types import RiskLevel, ToolCapabilities
from baremetal_harness.web.config import SEARCH_API_KEY_VARIABLE, load_search_endpoint
from baremetal_harness.workspace.diff import changed_paths, snapshot_files
from baremetal_harness.workspace.paths import WorkspaceEscape
from baremetal_harness.workspace.session import WorkspaceSession


class ApprovalProvider(Protocol):
    async def resolve(
        self,
        request: PermissionRequest,
    ) -> ApprovalResolution: ...


SCHEDULER_POLL_SECONDS = 1.0
SCHEDULER_CONCURRENCY = 2

DEFAULT_SUBAGENT_TOOLS = (
    "read_file",
    "write_file",
    "search_memory",
    "list_tasks",
    "git_status",
    "git_log",
    "git_diff",
    "git_show",
)

# Nothing is pre-authorized for background runs by default: granting a tool
# here lets a scheduled task perform it with no human in the loop.
DEFAULT_UNATTENDED_APPROVED_TOOLS: tuple[str, ...] = ()


@dataclass(slots=True)
class BareMetalHarnessApp:
    config: BareMetalHarnessConfig
    paths: BareMetalHarnessPaths
    agent: AgentLoop
    tools: ToolRegistry
    sessions: SessionRepository
    checkpoints: FileCheckpointStore
    memory: SqliteMemoryStore
    plans: PlanStore
    scheduler: SchedulerStore
    subagents: SubagentRuntime
    skills: tuple[object, ...]
    trace_sink: JsonlTraceSink
    workspace_session: WorkspaceSession
    provider: ModelProvider
    sandbox: SandboxRouter
    command_router: CommandRouter
    scheduler_runtime: SchedulerRuntime | None = None
    mcp_clients: tuple[StdioMcpClient, ...] = ()
    mcp_status: tuple[dict[str, object], ...] = ()
    web_closeables: tuple[object, ...] = ()
    last_result: RunResult | None = None
    conversation: tuple[Message, ...] = ()
    scheduler_worker: asyncio.Task | None = None
    session_id: str | None = None

    async def start_scheduler(
        self,
        *,
        poll_interval: float = SCHEDULER_POLL_SECONDS,
    ) -> None:
        if self.scheduler_runtime is None or self.scheduler_worker is not None:
            return
        # A previous process may have died mid-task; requeue or quarantine
        # anything still marked running before accepting new work.
        completed = tuple(
            run.run_id
            for run in await self.sessions.list_runs()
            if run.status == RunStatus.COMPLETED.value
        )
        await self.scheduler.recover_running(completed_child_runs=completed)
        self.scheduler_worker = asyncio.create_task(
            self.scheduler_runtime.run_forever(poll_interval)
        )

    async def stop_scheduler(self) -> None:
        worker = self.scheduler_worker
        if worker is None:
            return
        self.scheduler_worker = None
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker

    async def run_prompt(
        self,
        prompt: str,
        *,
        trace_sinks=(),
    ) -> RunResult:
        self.last_result = await self.agent.run(
            prompt,
            history=self.conversation,
            session_id=self.session_id,
            trace_sinks=trace_sinks,
        )
        self.session_id = self.last_result.session_id
        self.conversation = self.last_result.messages
        return self.last_result

    async def handle_command(self, text: str) -> CommandResult:
        routed = self.command_router.handle(text)
        if not routed.handled or routed.exit_requested:
            return routed
        command, _, argument = text.partition(" ")
        argument = argument.strip()
        if command == "/clear":
            self.last_result = None
            self.conversation = ()
            # Detach from the old session so history cannot leak back in.
            self.session_id = None
            return routed
        if command == "/sessions":
            sessions = await self.sessions.list_sessions()
            return CommandResult(
                True,
                json.dumps(
                    [
                        {
                            "session_id": session.session_id,
                            "updated_at": session.updated_at.isoformat(),
                            "current": session.session_id == self.session_id,
                        }
                        for session in sessions
                    ],
                    separators=(",", ":"),
                ),
            )
        if command == "/resume":
            return await self._resume_status(argument)
        if command == "/tasks":
            return CommandResult(True, await self._list_tasks())
        if command == "/memory":
            if not argument:
                return CommandResult(True, "usage: /memory <query>")
            records = await self.memory.search(argument)
            return CommandResult(
                True,
                json.dumps(
                    [
                        {
                            "memory_id": record.memory_id,
                            "text": record.text,
                            "source_ref": record.source_ref,
                        }
                        for record in records
                    ],
                    separators=(",", ":"),
                ),
            )
        if command == "/skills":
            return CommandResult(
                True,
                json.dumps(
                    [
                        {
                            "name": skill.name,
                            "scope": skill.scope,
                            "source_id": skill.source_id,
                        }
                        for skill in self.skills
                    ],
                    separators=(",", ":"),
                ),
            )
        if command == "/agents":
            return CommandResult(
                True,
                json.dumps(
                    {
                        "spawned": self.subagents.spawned_count,
                        "running": self.subagents.running_count,
                    },
                    separators=(",", ":"),
                ),
            )
        if command == "/jobs":
            tasks = await self.scheduler.list()
            return CommandResult(
                True,
                json.dumps(
                    {
                        "worker": (
                            "running"
                            if self.scheduler_worker is not None
                            else "stopped"
                        ),
                        "tasks": [
                            {
                                "task_id": task.task_id,
                                "status": task.status.value,
                                "run_at": task.run_at.isoformat(),
                                "child_run_id": task.child_run_id,
                            }
                            for task in tasks
                        ],
                    },
                    separators=(",", ":"),
                ),
            )
        if command == "/cancel":
            if not argument:
                return CommandResult(True, "usage: /cancel <job-id>")
            return CommandResult(
                True,
                json.dumps(
                    {"cancelled": await self.scheduler.cancel(argument)},
                    separators=(",", ":"),
                ),
            )
        if command == "/trace":
            return self._trace_command(argument)
        if command == "/metrics":
            metrics = (
                metrics_from_events(self.last_result.events)
                if self.last_result is not None
                else metrics_from_events(())
            )
            return CommandResult(
                True,
                json.dumps(asdict(metrics), separators=(",", ":")),
            )
        if command == "/sandbox":
            return CommandResult(True, await self._sandbox_status())
        if command == "/changes":
            return CommandResult(True, self._changes_report())
        if command == "/apply":
            return await self._apply_command(argument)
        if command == "/mcp":
            return CommandResult(
                True,
                json.dumps(list(self.mcp_status), separators=(",", ":"))
                if self.mcp_status
                else "no MCP servers configured",
            )
        return routed

    async def _resume_status(self, session_id: str) -> CommandResult:
        if not session_id:
            return CommandResult(True, "usage: /resume <session-id>")
        run = await self.sessions.latest_run_for_session(session_id)
        if run is None:
            return CommandResult(True, f"session not found: {session_id}")
        try:
            checkpoint = await self.checkpoints.latest_for_run(run.run_id)
        except PersistenceError as error:
            return self._resume_result(
                session_id,
                run,
                None,
                RecoveryDecision.UNRECOVERABLE,
                str(error),
            )

        pending = (
            pending_tool_executions(checkpoint.messages, self.tools)
            if checkpoint is not None
            else ()
        )
        decision = decide_recovery(
            checkpoint_valid=checkpoint is not None,
            executions=pending,
        )
        reason = "restored from checkpoint"
        if decision is RecoveryDecision.UNRECOVERABLE:
            reason = "no usable checkpoint for this session"
        elif decision is RecoveryDecision.REQUIRES_APPROVAL:
            # Replaying a non-idempotent tool could duplicate a side effect,
            # so a human decides whether this history may be resumed.
            approved = await self._approve_resume(run, pending)
            if not approved:
                return self._resume_result(
                    session_id,
                    run,
                    checkpoint,
                    decision,
                    "resume denied: unfinished non-idempotent tool calls",
                )
            reason = "approved despite unfinished non-idempotent tool calls"

        if decision is RecoveryDecision.UNRECOVERABLE:
            return self._resume_result(
                session_id, run, checkpoint, decision, reason
            )
        assert checkpoint is not None
        self.session_id = session_id
        self.conversation = checkpoint.messages
        self.last_result = None
        return self._resume_result(
            session_id,
            run,
            checkpoint,
            decision,
            reason,
            resumed=True,
        )

    async def _approve_resume(self, run: RunRecord, pending) -> bool:
        if self.agent.approval_provider is None:
            return False
        request_id = str(uuid4())
        resolution = await self.agent.approval_provider.resolve(
            PermissionRequest(
                request_id,
                run.run_id,
                pending[0].tool_call_id,
                "resume_session",
                "<redacted>",
                ToolCapabilities(risk_level=RiskLevel.HIGH, idempotent=False),
                f"{len(pending)} unfinished non-idempotent tool call(s)",
            )
        )
        return resolution.approved

    def _resume_result(
        self,
        session_id: str,
        run: RunRecord,
        checkpoint,
        decision: RecoveryDecision,
        reason: str,
        *,
        resumed: bool = False,
    ) -> CommandResult:
        return CommandResult(
            True,
            json.dumps(
                {
                    "session_id": session_id,
                    "run_id": run.run_id,
                    "status": run.status,
                    "checkpoint_id": (
                        checkpoint.checkpoint_id if checkpoint else None
                    ),
                    "decision": decision.value,
                    "resumed": resumed,
                    "restored_messages": (
                        len(checkpoint.messages) if resumed and checkpoint else 0
                    ),
                    "reason": reason,
                },
                separators=(",", ":"),
            ),
        )

    async def _list_tasks(self) -> str:
        tasks = await self.plans.list_tasks()
        return json.dumps(
            [
                {
                    "plan_id": plan_id,
                    "task_id": task.task_id,
                    "title": task.title,
                    "status": task.status.value,
                }
                for plan_id, task in tasks
            ],
            separators=(",", ":"),
        )

    def _trace_command(self, argument: str) -> CommandResult:
        if argument == "show":
            files = tuple(sorted(self.paths.traces.glob("*.jsonl")))
            return CommandResult(
                True,
                "\n".join(str(path) for path in files) or "no traces",
            )
        if argument in {"on", "off"}:
            return CommandResult(
                True,
                "trace collection is always on in this version",
            )
        return CommandResult(True, "usage: /trace on|off|show")

    async def _sandbox_status(self) -> str:
        process = await self.sandbox.process.capabilities()
        strong = await self.sandbox.strong.capabilities()
        return json.dumps(
            {
                "selected": (
                    "strong" if self.config.require_strong_sandbox else "process"
                ),
                "process": asdict(process),
                "strong": asdict(strong),
            },
            separators=(",", ":"),
            default=str,
        )

    def workspace_changes(self) -> tuple[Path, ...]:
        """Files that differ between the sandbox copy and the real project."""
        return changed_paths(
            snapshot_files(self.config.workspace),
            snapshot_files(self.workspace_session.workspace),
        )

    def _changes_report(self) -> str:
        changes = self.workspace_changes()
        if not changes:
            return "no changes in the sandbox workspace"
        source = snapshot_files(self.config.workspace)
        lines = [f"sandbox: {self.workspace_session.workspace}", ""]
        for path in changes:
            state = "modified" if path in source else "new"
            lines.append(f"  {state:>8}  {path.as_posix()}")
        lines.append("")
        lines.append("apply with: /apply <path> [...]  or  /apply --all")
        return "\n".join(lines)

    async def _apply_command(self, argument: str) -> CommandResult:
        changes = self.workspace_changes()
        if not argument:
            return CommandResult(
                True,
                "usage: /apply <path> [...] | /apply --all\n"
                "run /changes first to see what the agent wrote",
            )
        if argument == "--all":
            selected = changes
        else:
            requested = tuple(Path(part) for part in argument.split())
            unknown = [
                path.as_posix() for path in requested if path not in set(changes)
            ]
            if unknown:
                return CommandResult(
                    True, f"not changed in the sandbox: {', '.join(unknown)}"
                )
            selected = requested
        if not selected:
            return CommandResult(True, "no changes in the sandbox workspace")
        try:
            applied = await self.apply_artifacts(self.config.workspace, selected)
        except PermissionError as error:
            return CommandResult(True, str(error))
        except (WorkspaceEscape, OSError) as error:
            return CommandResult(True, f"apply failed: {error}")
        return CommandResult(
            True,
            "applied to "
            f"{self.config.workspace}:\n"
            + "\n".join(f"  {path.as_posix()}" for path in applied),
        )

    async def apply_artifacts(
        self,
        destination: Path,
        approved_paths: tuple[Path, ...],
    ) -> tuple[Path, ...]:
        return await self.workspace_session.apply_artifacts_approved(
            destination,
            approved_paths,
            approval_provider=self.agent.approval_provider,
            event_store=self.agent.event_store,
        )

    async def aclose(self) -> None:
        await self.stop_scheduler()
        await self.subagents.cancel_all()
        # Every external resource gets a close attempt even if an earlier one
        # fails, so one broken MCP server cannot leak the rest.
        for resource in (*self.mcp_clients, *self.web_closeables, self.provider):
            close = getattr(resource, "aclose", None)
            if close is None:
                continue
            try:
                await close()
            except Exception:
                continue


async def _start_mcp_servers(
    tools: ToolRegistry,
    workspace: Path,
) -> tuple[tuple[StdioMcpClient, ...], tuple[dict[str, object], ...]]:
    """Start configured MCP servers, degrading instead of failing startup.

    A third-party server that is missing, slow or broken must not stop the
    agent from running; it is reported as unavailable and its tools are absent.
    """
    try:
        configured = load_mcp_servers(workspace)
    except McpConfigError as error:
        return (), ({"server": "<config>", "status": "invalid", "detail": str(error)},)

    clients: list[StdioMcpClient] = []
    status: list[dict[str, object]] = []
    for server in configured:
        if not server.enabled:
            status.append({"server": server.name, "status": "disabled", "tools": []})
            continue
        client = StdioMcpClient(
            server.command,
            server.args,
            env=server.env,
            cwd=str(workspace),
            timeout=server.timeout,
        )
        try:
            info = await client.start()
            names = await register_mcp_tools(tools, client, server.name)
        except (McpError, OSError) as error:
            await client.aclose()
            status.append(
                {
                    "server": server.name,
                    "status": "unavailable",
                    "detail": str(error),
                    "tools": [],
                }
            )
            continue
        clients.append(client)
        status.append(
            {
                "server": server.name,
                "status": "ready",
                "version": info.version,
                "tools": list(names),
            }
        )
    return tuple(clients), tuple(status)


async def create_app(
    config: BareMetalHarnessConfig,
    *,
    provider: ModelProvider | None = None,
    secret_provider: SecretProvider | None = None,
    approval_provider: ApprovalProvider | None = None,
    unattended_approved_tools: tuple[str, ...] = DEFAULT_UNATTENDED_APPROVED_TOOLS,
) -> BareMetalHarnessApp:
    trace_secrets: tuple[str, ...] = ()
    api_key: str | None = None
    internal_provider: ModelProvider | None = None
    if provider is None:
        secrets = secret_provider or EnvironmentSecretProvider()
        api_key = secrets.get("OPENAI_API_KEY")
        if not config.base_url:
            raise ApplicationConfigurationError("base_url is required for a real model")
        if api_key is None or not api_key.strip():
            raise ApplicationConfigurationError(
                "API key is required for a real model; "
                "run: baremetal_harness config set api_key or set OPENAI_API_KEY"
            )

    process_sandbox = ProcessSandbox()
    docker_sandbox = DockerSandbox(
        image=config.docker_image,
        allowed_images=(config.docker_image,),
    )
    sandbox = SandboxRouter(process=process_sandbox, strong=docker_sandbox)
    try:
        selected_sandbox = await sandbox.select(
            ToolCapabilities(subprocess=True),
            require_strong=config.require_strong_sandbox,
        )
    except SandboxCapabilityUnavailable as error:
        raise ApplicationConfigurationError(str(error)) from error

    if provider is None:
        assert config.base_url is not None
        assert api_key is not None
        try:
            provider = OpenAICompatibleClient(config.base_url, api_key)
        except httpx.InvalidURL as error:
            raise ApplicationConfigurationError(
                "base_url must be a valid HTTP(S) URL"
            ) from error
        internal_provider = provider
        trace_secrets = (api_key,)

    try:
        paths = BareMetalHarnessPaths.create(config.data_dir)
        config.workspace.mkdir(parents=True, exist_ok=True)
        workspace_session = WorkspaceSession.create(paths.sandboxes, config.workspace)
        sessions = SessionRepository(paths.state_database)
        await sessions.initialize()
        checkpoints = FileCheckpointStore(paths.checkpoints, sessions)
        memory = SqliteMemoryStore(paths.state_database, paths.memory_sources)
        await memory.initialize()
        plans = PlanStore(paths.plans_database)
        await plans.initialize()
        scheduler = SchedulerStore(paths.scheduler_database)
        await scheduler.initialize()

        trace_sink = JsonlTraceSink(paths.traces, secrets=trace_secrets)
        event_store = JsonlEventStore(paths.data / "events.jsonl")
        context_builder = ContextBuilder(CharacterTokenEstimator())
        context_budget = ContextBudget(
            config.context_tokens,
            config.reserve_output_tokens,
        )
        permission_policy = DefaultPermissionPolicy()
        guard = DestructiveCommandGuard()
        resolved_approval = approval_provider or CliApprovalProvider()
        skills = discover_skills(config.workspace)
        context_providers = (
            SkillContextProvider(skills),
            MemoryContextProvider(memory),
            ProjectRulesProvider.load(config.workspace),
        )

        tools = ToolRegistry()
        for tool in make_file_tools():
            tools.register(tool)
        tools.register(make_run_command_tool(selected_sandbox))
        for tool in make_memory_tools(memory, event_store, Redactor(trace_secrets)):
            tools.register(tool)
        for tool in make_builtin_planning_tools(plans):
            tools.register(tool)
        child_factory = AgentLoopFactory(
            provider,
            config.model,
            workspace=workspace_session.workspace,
            context_builder=context_builder,
            context_budget=context_budget,
            permission_policy=permission_policy,
            approval_provider=resolved_approval,
            session_repository=sessions,
            checkpoint_store=checkpoints,
            event_store=event_store,
            trace_sinks=(trace_sink,),
            max_depth=2,
        )
        subagents = SubagentRuntime(
            child_factory,
            max_depth=2,
            max_children=4,
            parent_allowed_tools=DEFAULT_SUBAGENT_TOOLS,
        )
        child_factory.runtime = subagents
        for tool in make_builtin_subagent_tools(subagents, DEFAULT_SUBAGENT_TOOLS):
            tools.register(tool)
        for tool in make_builtin_scheduler_tools(scheduler):
            tools.register(tool)
        for tool in make_local_inspection_tools(selected_sandbox):
            tools.register(tool)
        search_endpoint = load_search_endpoint(config.workspace)
        web_tools, web_closeables = make_web_tools(
            search_endpoint=search_endpoint,
            # Only ask for a credential that has somewhere to be used.
            search_api_key=(
                (secret_provider or EnvironmentSecretProvider()).get(
                    SEARCH_API_KEY_VARIABLE
                )
                if search_endpoint is not None
                else None
            ),
        )
        for tool in web_tools:
            tools.register(tool)
        mcp_clients, mcp_status = await _start_mcp_servers(
            tools, config.workspace
        )
        child_factory.tools = tools

        agent = AgentLoop(
            provider,
            config.model,
            limits=RunLimits(config.max_turns, config.max_tool_calls),
            tools=tools,
            workspace=workspace_session.workspace,
            session_repository=sessions,
            checkpoint_store=checkpoints,
            event_store=event_store,
            context_builder=context_builder,
            context_budget=context_budget,
            permission_policy=permission_policy,
            guard=guard,
            approval_provider=resolved_approval,
            trace_sinks=(trace_sink,),
            context_providers=context_providers,
        )
        # Scheduled work runs without a human, so it gets its own loop whose
        # approval provider denies anything the policy wants to ask about.
        # It also loses delegate_task: children are built by a factory holding
        # the interactive approval provider, which would otherwise let a
        # background run reach a human prompt through its child.
        unattended_tools = tools.subset(
            tuple(
                tool.spec.name
                for tool in tools.values()
                if tool.spec.name != "delegate_task"
            )
        )
        scheduler_agent = AgentLoop(
            provider,
            config.model,
            limits=RunLimits(config.max_turns, config.max_tool_calls),
            tools=unattended_tools,
            workspace=workspace_session.workspace,
            session_repository=sessions,
            checkpoint_store=checkpoints,
            event_store=event_store,
            context_builder=context_builder,
            context_budget=context_budget,
            permission_policy=permission_policy,
            guard=guard,
            approval_provider=UnattendedApprovalProvider(unattended_approved_tools),
            trace_sinks=(trace_sink,),
            context_providers=context_providers,
        )
        scheduler_runtime = SchedulerRuntime(
            scheduler,
            AgentTaskRunner(scheduler_agent),
            SystemClock(),
            max_concurrency=SCHEDULER_CONCURRENCY,
        )
        return BareMetalHarnessApp(
            config,
            paths,
            agent,
            tools,
            sessions,
            checkpoints,
            memory,
            plans,
            scheduler,
            subagents,
            skills,
            trace_sink,
            workspace_session,
            provider,
            sandbox,
            CommandRouter(),
            scheduler_runtime,
            mcp_clients,
            mcp_status,
            web_closeables,
        )
    except BaseException:
        if internal_provider is not None:
            close = getattr(internal_provider, "aclose", None)
            if close is not None:
                with contextlib.suppress(BaseException):
                    await close()
        raise
