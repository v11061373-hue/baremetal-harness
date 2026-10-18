import pytest

from baremetal_harness.sandbox.docker import DockerSandbox
from baremetal_harness.sandbox.router import SandboxCapabilityUnavailable, SandboxRouter
from baremetal_harness.sandbox.types import Command, SandboxPolicy
from baremetal_harness.tools.types import ToolCapabilities


async def test_docker_capability_has_public_reason() -> None:
    capabilities = await DockerSandbox().capabilities()
    assert capabilities.reason


async def test_router_never_silently_downgrades_strong() -> None:
    docker = DockerSandbox(
        image="image-that-is-not-present:baremetal_harness",
        allowed_images=("image-that-is-not-present:baremetal_harness",),
    )
    router = SandboxRouter(strong=docker)

    with pytest.raises(SandboxCapabilityUnavailable):
        await router.select(ToolCapabilities(subprocess=True), require_strong=True)


async def test_docker_executor_when_available(tmp_path) -> None:
    docker = DockerSandbox()
    capabilities = await docker.capabilities()
    if not capabilities.available:
        pytest.skip(f"strong sandbox unavailable: {capabilities.reason}")

    result = await docker.execute(
        Command(("python", "-c", "print('ok')"), tmp_path, {}),
        SandboxPolicy(
            tmp_path,
            "workspace-write",
            "deny",
            (),
            2.0,
            4096,
        ),
    )

    assert result.stdout.strip() == "ok"
