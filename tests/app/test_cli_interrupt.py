import errno
import os
import pty
import select
import signal
import sys
import time

_INTERRUPT_PROBE = """
from pathlib import Path

import baremetal_harness.app

from baremetal_harness.cli.repl import _run_application
from baremetal_harness.config import BareMetalHarnessConfig


class RecordingApp:
    async def start_scheduler(self) -> None:
        pass

    async def aclose(self) -> None:
        print("APP_CLOSED", flush=True)


class EmptySecrets:
    def get(self, name: str) -> str | None:
        return None


async def create_app(config, *, secret_provider):
    return RecordingApp()


baremetal_harness.app.create_app = create_app
status = _run_application(
    BareMetalHarnessConfig(Path("data"), Path("workspace")),
    EmptySecrets(),
)
print(f"STATUS:{status}", flush=True)
raise SystemExit(status)
"""


def _read_available(fd: int, output: bytearray, timeout: float) -> None:
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return
    try:
        output.extend(os.read(fd, 4096))
    except OSError as error:
        if error.errno != errno.EIO:
            raise


def _wait_for_output(
    fd: int,
    output: bytearray,
    expected: bytes,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + timeout
    while expected not in output and time.monotonic() < deadline:
        _read_available(fd, output, 0.05)
    return expected in output


def _wait_for_exit(
    pid: int,
    fd: int,
    output: bytearray,
    timeout: float,
) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _read_available(fd, output, 0.05)
        exited_pid, status = os.waitpid(pid, os.WNOHANG)
        if exited_pid:
            return status
    return None


def test_ctrl_c_at_prompt_closes_app_and_exits_without_traceback() -> None:
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(
            sys.executable,
            [sys.executable, "-c", _INTERRUPT_PROBE],
        )

    output = bytearray()
    status: int | None = None
    exited_after_interrupt = False
    try:
        assert _wait_for_output(fd, output, b"you> ", 2.0)

        os.write(fd, b"\x03")
        status = _wait_for_exit(pid, fd, output, 1.0)
        exited_after_interrupt = status is not None
    finally:
        if status is None:
            os.write(fd, b"\n")
            status = _wait_for_exit(pid, fd, output, 1.0)
        if status is None:
            os.kill(pid, signal.SIGKILL)
            _, status = os.waitpid(pid, 0)
        while True:
            previous_length = len(output)
            _read_available(fd, output, 0.05)
            if len(output) == previous_length:
                break
        os.close(fd)

    rendered = output.decode(errors="replace")
    assert exited_after_interrupt, rendered
    assert os.waitstatus_to_exitcode(status) == 130
    assert "APP_CLOSED" in rendered
    assert "STATUS:130" in rendered
    assert "Traceback" not in rendered
