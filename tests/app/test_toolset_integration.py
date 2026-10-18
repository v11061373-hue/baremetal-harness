import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from baremetal_harness.app import create_app
from baremetal_harness.config import BareMetalHarnessConfig
from baremetal_harness.mcp.config import McpConfigError, load_mcp_servers
from baremetal_harness.model.fake import FakeModel
from baremetal_harness.scheduler.store import SchedulerStore
from baremetal_harness.scheduler.types import ScheduledTask, ScheduledTaskStatus
from baremetal_harness.web.config import SearchConfigError, load_search_endpoint

SERVER = Path(__file__).parent.parent / "fixtures" / "mcp" / "echo_server.py"


async def _app(tmp_path: Path):
    workspace = tmp_path / "project"
    workspace.mkdir(exist_ok=True)
    return await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=FakeModel([]),
    )


def _write_mcp_config(workspace: Path, payload: dict) -> None:
    directory = workspace / ".baremetal_harness"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "mcp.json").write_text(json.dumps(payload))


# --- toolset wiring ----------------------------------------------------------


async def test_local_and_web_tools_are_registered(tmp_path: Path) -> None:
    app = await _app(tmp_path)
    names = {tool.spec.name for tool in app.tools.values()}
    await app.aclose()

    assert {"git_status", "git_log", "git_diff", "git_show"} <= names
    assert "fetch_url" in names
    # No endpoint configured, so the model is not offered a search it cannot do.
    assert "web_search" not in names


async def test_search_tool_appears_once_configured(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    (workspace / ".baremetal_harness").mkdir(parents=True)
    (workspace / ".baremetal_harness" / "search.json").write_text(
        json.dumps({"url": "https://search.invalid/v1"})
    )

    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace), provider=FakeModel([])
    )
    names = {tool.spec.name for tool in app.tools.values()}
    await app.aclose()

    assert "web_search" in names


def test_search_config_refuses_an_inline_credential(tmp_path: Path) -> None:
    directory = tmp_path / ".baremetal_harness"
    directory.mkdir(parents=True)
    (directory / "search.json").write_text(
        json.dumps({"url": "https://s.invalid", "api_key": "leaked"})
    )

    with pytest.raises(SearchConfigError, match="BAREMETAL_HARNESS_SEARCH_API_KEY"):
        load_search_endpoint(tmp_path)


# --- MCP configuration and startup -------------------------------------------


def test_mcp_config_is_parsed(tmp_path: Path) -> None:
    _write_mcp_config(
        tmp_path,
        {"servers": {"echo": {"command": "python", "args": ["s.py"]}}},
    )

    servers = load_mcp_servers(tmp_path, user_root=tmp_path / "nowhere")

    assert servers[0].name == "echo"
    assert servers[0].args == ("s.py",)
    assert servers[0].enabled is True


def test_mcp_config_accepts_the_common_alias(tmp_path: Path) -> None:
    _write_mcp_config(tmp_path, {"mcpServers": {"a": {"command": "x"}}})

    assert load_mcp_servers(tmp_path, user_root=tmp_path / "nowhere")[0].name == "a"


def test_mcp_config_rejects_a_server_without_a_command(tmp_path: Path) -> None:
    _write_mcp_config(tmp_path, {"servers": {"bad": {"args": []}}})

    with pytest.raises(McpConfigError, match="needs a command"):
        load_mcp_servers(tmp_path, user_root=tmp_path / "nowhere")


async def test_configured_server_tools_reach_the_registry(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    _write_mcp_config(
        workspace,
        {"servers": {"echo": {"command": sys.executable, "args": [str(SERVER), "ok"]}}},
    )

    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace), provider=FakeModel([])
    )
    try:
        names = {tool.spec.name for tool in app.tools.values()}
        status = json.loads((await app.handle_command("/mcp")).output)
    finally:
        await app.aclose()

    assert "mcp_echo_echo" in names
    assert status[0]["status"] == "ready"
    assert status[0]["version"] == "1.2.3"


async def test_a_broken_server_does_not_break_startup(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    _write_mcp_config(
        workspace,
        {"servers": {"missing": {"command": "/nonexistent/mcp-binary"}}},
    )

    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace), provider=FakeModel([])
    )
    try:
        status = json.loads((await app.handle_command("/mcp")).output)
        # The rest of the agent is fully usable.
        assert app.tools.get("read_file") is not None
    finally:
        await app.aclose()

    assert status[0]["status"] == "unavailable"
    assert status[0]["tools"] == []


async def test_disabled_server_is_not_started(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    _write_mcp_config(
        workspace,
        {
            "servers": {
                "echo": {
                    "command": sys.executable,
                    "args": [str(SERVER), "ok"],
                    "enabled": False,
                }
            }
        },
    )

    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace), provider=FakeModel([])
    )
    try:
        status = json.loads((await app.handle_command("/mcp")).output)
        names = {tool.spec.name for tool in app.tools.values()}
    finally:
        await app.aclose()

    assert status[0]["status"] == "disabled"
    assert not any(name.startswith("mcp_") for name in names)


async def test_closing_the_app_stops_mcp_servers(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    _write_mcp_config(
        workspace,
        {"servers": {"echo": {"command": sys.executable, "args": [str(SERVER), "ok"]}}},
    )
    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace), provider=FakeModel([])
    )
    process = app.mcp_clients[0]._process

    await app.aclose()

    assert process.returncode is not None


# --- cross-process scheduler claim -------------------------------------------


async def test_two_workers_cannot_claim_the_same_task(tmp_path: Path) -> None:
    database = tmp_path / "scheduler.db"
    first = SchedulerStore(database)
    await first.initialize()
    second = SchedulerStore(database)
    now = datetime.now(UTC)
    for index in range(4):
        await first.add(ScheduledTask.once(f"job-{index}", "work", now))

    claimed_a, claimed_b = await asyncio.gather(
        first.claim_due(now, 4, owner="worker-a"),
        second.claim_due(now, 4, owner="worker-b"),
    )

    ids_a = {task.task_id for task in claimed_a}
    ids_b = {task.task_id for task in claimed_b}
    assert not (ids_a & ids_b), "a task was claimed twice"
    assert len(ids_a | ids_b) == 4


async def test_claim_records_the_owning_worker(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path / "scheduler.db")
    await store.initialize()
    now = datetime.now(UTC)
    await store.add(ScheduledTask.once("job-1", "work", now))

    await store.claim_due(now, 1, owner="worker-a")

    assert (await store.get("job-1")).status is ScheduledTaskStatus.RUNNING
    with store._connect() as connection:
        owner = connection.execute(
            "SELECT owner FROM scheduled_tasks WHERE task_id = ?", ("job-1",)
        ).fetchone()["owner"]
    assert owner == "worker-a"


async def test_existing_database_gains_the_owner_column(tmp_path: Path) -> None:
    import sqlite3

    database = tmp_path / "scheduler.db"
    # A database created before the column existed.
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE scheduled_tasks (
                task_id TEXT PRIMARY KEY, task_text TEXT NOT NULL,
                run_at TEXT NOT NULL, status TEXT NOT NULL,
                attempts INTEGER NOT NULL, max_attempts INTEGER NOT NULL,
                idempotent INTEGER NOT NULL, parent_task_id TEXT,
                child_run_id TEXT, last_error TEXT
            )
            """
        )

    store = SchedulerStore(database)
    await store.initialize()
    now = datetime.now(UTC)
    await store.add(ScheduledTask.once("job-1", "work", now))

    assert len(await store.claim_due(now, 1, owner="w")) == 1


# --- unattended pre-authorization --------------------------------------------


async def test_background_run_denies_a_tool_that_was_not_pre_authorized(
    tmp_path: Path,
) -> None:
    from baremetal_harness.permissions.approval import UnattendedApprovalProvider
    from baremetal_harness.permissions.types import PermissionRequest
    from baremetal_harness.tools.types import ToolCapabilities

    request = PermissionRequest(
        "req-1", "run-1", "call-1", "fetch_url", "<redacted>",
        ToolCapabilities(network="unrestricted"), "unrestricted network",
    )

    resolution = await UnattendedApprovalProvider().resolve(request)

    assert resolution.approved is False


async def test_background_run_allows_only_the_named_tool(tmp_path: Path) -> None:
    from baremetal_harness.permissions.approval import UnattendedApprovalProvider
    from baremetal_harness.permissions.types import PermissionRequest
    from baremetal_harness.tools.types import ToolCapabilities

    provider = UnattendedApprovalProvider(("fetch_url",))

    def request(tool: str) -> PermissionRequest:
        return PermissionRequest(
            f"req-{tool}", "run-1", "call-1", tool, "<redacted>",
            ToolCapabilities(network="unrestricted"), "unrestricted network",
        )

    allowed = await provider.resolve(request("fetch_url"))
    refused = await provider.resolve(request("run_command"))

    assert allowed.approved is True
    assert "pre-authorized" in allowed.reason
    assert refused.approved is False


async def test_pre_authorization_reaches_the_scheduler_agent(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=FakeModel([]),
        unattended_approved_tools=("fetch_url",),
    )
    try:
        provider = app.scheduler_runtime.runner.agent.approval_provider
    finally:
        await app.aclose()

    assert provider.approved_tools == frozenset({"fetch_url"})


async def test_subagents_can_inspect_git_history(tmp_path: Path) -> None:
    from baremetal_harness.app import DEFAULT_SUBAGENT_TOOLS

    app = await _app(tmp_path)
    try:
        # The parent allowlist is what a child may ever request.
        child_tools = app.subagents.parent_allowed_tools
        registry_names = {tool.spec.name for tool in app.tools.values()}
    finally:
        await app.aclose()

    assert "git_log" in child_tools
    assert set(DEFAULT_SUBAGENT_TOOLS) <= registry_names
