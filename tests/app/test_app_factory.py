from pathlib import Path

import httpx
import pytest

from baremetal_harness.app import create_app
from baremetal_harness.config import BareMetalHarnessConfig, SecretProvider
from baremetal_harness.core.errors import ApplicationConfigurationError
from baremetal_harness.model.fake import FakeModel


async def test_app_factory_wires_required_modules(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = await create_app(
        BareMetalHarnessConfig(data_dir=tmp_path / "data", workspace=workspace),
        provider=FakeModel([]),
    )

    assert app.agent is not None
    assert app.tools.get("read_file").spec.capabilities.filesystem == "read"
    assert app.sessions is not None
    assert app.memory is not None
    assert app.scheduler is not None
    assert app.trace_sink is not None


async def test_final_tool_catalog_contains_product_tools(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = await create_app(
        BareMetalHarnessConfig(tmp_path / "data", workspace),
        provider=FakeModel([]),
    )
    required = {
        "read_file",
        "write_file",
        "run_command",
        "remember",
        "search_memory",
        "create_plan",
        "list_tasks",
        "start_task",
        "complete_task",
        "fail_task",
        "delegate_task",
        "schedule_task",
        "list_scheduled_tasks",
        "cancel_scheduled_task",
    }
    assert required.issubset({tool.spec.name for tool in app.tools.values()})


async def test_app_factory_reads_api_key_from_secret_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []
    client_arguments: list[tuple[str, str]] = []

    class RecordingSecretProvider:
        def get(self, name: str) -> str | None:
            requested.append(name)
            return "provider-secret-1234"

    def make_client(base_url: str, api_key: str) -> FakeModel:
        client_arguments.append((base_url, api_key))
        return FakeModel([])

    monkeypatch.setattr("baremetal_harness.app.OpenAICompatibleClient", make_client)
    workspace = tmp_path / "project"
    workspace.mkdir()
    config = BareMetalHarnessConfig(
        data_dir=tmp_path / "data",
        workspace=workspace,
        model="demo-model",
        base_url="https://model.invalid/v1",
    )
    secrets: SecretProvider = RecordingSecretProvider()

    app = await create_app(config, secret_provider=secrets)

    assert requested == ["OPENAI_API_KEY"]
    assert client_arguments == [("https://model.invalid/v1", "provider-secret-1234")]
    assert not hasattr(config, "api_key")
    await app.aclose()


async def test_app_factory_preserves_valid_api_key_whitespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "  provider-secret-1234 \t"
    client_arguments: list[tuple[str, str]] = []

    def make_client(base_url: str, received_api_key: str) -> FakeModel:
        client_arguments.append((base_url, received_api_key))
        return FakeModel([])

    monkeypatch.setattr("baremetal_harness.app.OpenAICompatibleClient", make_client)

    app = await create_app(
        BareMetalHarnessConfig(
            data_dir=tmp_path / "data",
            workspace=tmp_path / "workspace",
            model="demo-model",
            base_url="https://model.invalid/v1",
        ),
        secret_provider=StaticSecretProvider(api_key),
    )

    assert client_arguments == [("https://model.invalid/v1", api_key)]
    await app.aclose()


async def test_app_factory_rejects_missing_runtime_config_before_state_creation(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    config = BareMetalHarnessConfig(
        data_dir=data_dir,
        workspace=workspace,
        model="demo-model",
        base_url=None,
    )

    with pytest.raises(ApplicationConfigurationError, match="base_url"):
        await create_app(config, secret_provider=EmptySecretProvider())

    assert not data_dir.exists()
    assert not workspace.exists()


async def test_app_factory_rejects_whitespace_default_environment_secret_before_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"
    secret = " \t "
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    async def fail_sandbox_select(*args: object, **kwargs: object) -> object:
        pytest.fail("secret preflight must run before sandbox selection")

    monkeypatch.setattr(
        "baremetal_harness.app.SandboxRouter.select",
        fail_sandbox_select,
    )

    with pytest.raises(ApplicationConfigurationError, match="API key"):
        await create_app(
            BareMetalHarnessConfig(
                data_dir=data_dir,
                workspace=workspace,
                model="demo-model",
                base_url="https://model.invalid/v1",
            )
        )

    assert not data_dir.exists()
    assert not workspace.exists()


@pytest.mark.parametrize("secret", [None, "", " ", " \t\n "])
async def test_app_factory_rejects_injected_blank_secret_before_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret: str | None,
) -> None:
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"

    async def fail_sandbox_select(*args: object, **kwargs: object) -> object:
        pytest.fail("secret preflight must run before sandbox selection")

    monkeypatch.setattr(
        "baremetal_harness.app.SandboxRouter.select",
        fail_sandbox_select,
    )

    with pytest.raises(ApplicationConfigurationError, match="API key"):
        await create_app(
            BareMetalHarnessConfig(
                data_dir=data_dir,
                workspace=workspace,
                model="demo-model",
                base_url="https://model.invalid/v1",
            ),
            secret_provider=StaticSecretProvider(secret),
        )

    assert not data_dir.exists()
    assert not workspace.exists()


class EmptySecretProvider:
    def get(self, name: str) -> str | None:
        return None


class RecordingProvider:
    def __init__(self, *, close_error: BaseException | None = None) -> None:
        self.closed = 0
        self.close_error = close_error

    async def aclose(self) -> None:
        self.closed += 1
        if self.close_error is not None:
            raise self.close_error


@pytest.mark.parametrize("failure_point", ["workspace", "database", "tool"])
async def test_app_factory_closes_internal_provider_after_later_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    provider = RecordingProvider()
    workspace = tmp_path / "workspace"
    config = BareMetalHarnessConfig(
        data_dir=tmp_path / "data",
        workspace=workspace,
        model="demo-model",
        base_url="https://model.invalid/v1",
    )
    monkeypatch.setattr(
        "baremetal_harness.app.OpenAICompatibleClient",
        lambda base_url, api_key: provider,
    )

    if failure_point == "workspace":
        original_mkdir = Path.mkdir

        def fail_workspace_mkdir(
            path: Path,
            mode: int = 0o777,
            parents: bool = False,
            exist_ok: bool = False,
        ) -> None:
            if path == workspace:
                raise RuntimeError("workspace initialization failed")
            original_mkdir(
                path,
                mode=mode,
                parents=parents,
                exist_ok=exist_ok,
            )

        monkeypatch.setattr(Path, "mkdir", fail_workspace_mkdir)
    elif failure_point == "database":

        async def fail_database_initialize(self: object) -> None:
            raise RuntimeError("database initialization failed")

        monkeypatch.setattr(
            "baremetal_harness.app.SessionRepository.initialize",
            fail_database_initialize,
        )
    else:

        def fail_tool_register(self: object, tool: object) -> None:
            raise RuntimeError("tool initialization failed")

        monkeypatch.setattr(
            "baremetal_harness.app.ToolRegistry.register",
            fail_tool_register,
        )

    with pytest.raises(RuntimeError, match=f"{failure_point} initialization failed"):
        await create_app(
            config,
            secret_provider=StaticSecretProvider("provider-secret-1234"),
        )

    assert provider.closed == 1


async def test_app_factory_preserves_initialization_error_when_internal_close_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RecordingProvider(close_error=RuntimeError("close failure"))
    monkeypatch.setattr(
        "baremetal_harness.app.OpenAICompatibleClient",
        lambda base_url, api_key: provider,
    )

    async def fail_database_initialize(self: object) -> None:
        raise RuntimeError("database initialization failed")

    monkeypatch.setattr(
        "baremetal_harness.app.SessionRepository.initialize",
        fail_database_initialize,
    )

    with pytest.raises(RuntimeError, match="database initialization failed"):
        await create_app(
            BareMetalHarnessConfig(
                data_dir=tmp_path / "data",
                workspace=tmp_path / "workspace",
                model="demo-model",
                base_url="https://model.invalid/v1",
            ),
            secret_provider=StaticSecretProvider("provider-secret-1234"),
        )

    assert provider.closed == 1


async def test_app_factory_does_not_close_injected_provider_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RecordingProvider()

    async def fail_database_initialize(self: object) -> None:
        raise RuntimeError("database initialization failed")

    monkeypatch.setattr(
        "baremetal_harness.app.SessionRepository.initialize",
        fail_database_initialize,
    )

    with pytest.raises(RuntimeError, match="database initialization failed"):
        await create_app(
            BareMetalHarnessConfig(
                data_dir=tmp_path / "data",
                workspace=tmp_path / "workspace",
            ),
            provider=provider,  # type: ignore[arg-type]
        )

    assert provider.closed == 0


async def test_app_factory_translates_invalid_client_url_without_state_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    workspace = tmp_path / "workspace"

    def reject_invalid_url(base_url: str, api_key: str) -> RecordingProvider:
        raise httpx.InvalidURL("unsafe URL detail")

    monkeypatch.setattr("baremetal_harness.app.OpenAICompatibleClient", reject_invalid_url)

    with pytest.raises(ApplicationConfigurationError, match="base_url") as error:
        await create_app(
            BareMetalHarnessConfig(
                data_dir=data_dir,
                workspace=workspace,
                model="demo-model",
                base_url="https://model.invalid:not-a-port/v1",
            ),
            secret_provider=StaticSecretProvider("provider-secret-1234"),
        )

    assert "unsafe URL detail" not in str(error.value)
    assert not data_dir.exists()
    assert not workspace.exists()


class StaticSecretProvider:
    def __init__(self, value: str | None) -> None:
        self.value = value

    def get(self, name: str) -> str | None:
        return self.value if name == "OPENAI_API_KEY" else None
