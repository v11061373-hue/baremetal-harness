import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import Callable, Coroutine, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from baremetal_harness.cli.config import ReplConfig
from baremetal_harness.cli.config_commands import (
    add_config_subcommands,
    run_config_command,
)
from baremetal_harness.cli.config_wizard import (
    ConfigInteractionError,
    run_config_wizard,
)
from baremetal_harness.config import (
    BareMetalHarnessConfig,
    ConfigSecretProvider,
    SecretProvider,
    resolve_config,
)
from baremetal_harness.config_store import ConfigStore
from baremetal_harness.core.errors import (
    ApplicationConfigurationError,
    ModelProtocolError,
)
from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.core.messages import (
    Message,
    ModelRequest,
    ResponseCompleted,
    TextContent,
    TextDelta,
)
from baremetal_harness.model.base import ModelProvider
from baremetal_harness.model.openai_compat import OpenAICompatibleClient

if TYPE_CHECKING:
    from baremetal_harness.app import BareMetalHarnessApp


class Repl:
    def __init__(
        self,
        provider: ModelProvider,
        model: str,
        *,
        write: Callable[[str], None] = lambda text: print(
            text,
            end="",
            flush=True,
        ),
    ) -> None:
        self.provider = provider
        self.model = model
        self.write = write
        self.messages: list[Message] = []

    async def run_turn(self, text: str) -> None:
        previous_length = len(self.messages)
        self.messages.append(Message("user", (TextContent(text),)))
        answer: list[str] = []
        completed = False
        request = ModelRequest(self.model, tuple(self.messages))
        try:
            async for event in self.provider.stream(request):
                if isinstance(event, TextDelta):
                    answer.append(event.text)
                    self.write(event.text)
                elif isinstance(event, ResponseCompleted):
                    completed = True
                    break
        except BaseException:
            del self.messages[previous_length:]
            raise
        if not completed:
            del self.messages[previous_length:]
            raise ModelProtocolError("model stream ended without completion")
        self.messages.append(Message("assistant", (TextContent("".join(answer)),)))

    def handle_command(self, text: str) -> bool:
        if text == "/clear":
            self.messages.clear()
            return True
        return text in {"/exit", "/quit"}


class AppRepl:
    def __init__(
        self,
        app: "BareMetalHarnessApp",
        *,
        write: Callable[[str], None] = print,
        write_stream: Callable[[str], None] | None = None,
    ) -> None:
        self.app = app
        self.write = write
        self.write_stream = write_stream or (
            _write_terminal_stream if write is print else write
        )

    async def process(self, text: str) -> bool:
        command = await self.app.handle_command(text)
        if command.handled:
            if command.output:
                self.write(command.output)
            return command.exit_requested
        await self.app.run_prompt(
            text,
            trace_sinks=(_TextStreamSink(self.write_stream),),
        )
        return False


def _write_terminal_stream(text: str) -> None:
    print(text, end="", flush=True)


class _TextStreamSink:
    def __init__(self, write: Callable[[str], None]) -> None:
        self.write = write

    async def emit(self, event: EventEnvelope) -> None:
        if isinstance(event.payload, TextDelta):
            self.write(event.payload.text)


async def _read_console_line(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    ready: asyncio.Future[str] = loop.create_future()
    file_descriptor = sys.stdin.fileno()
    print(prompt, end="", flush=True)

    def read_ready() -> None:
        if ready.done():
            return
        try:
            line = sys.stdin.readline()
        except BaseException as error:
            ready.set_exception(error)
            return
        if line == "":
            ready.set_exception(EOFError())
            return
        ready.set_result(line.removesuffix("\n"))

    loop.add_reader(file_descriptor, read_ready)
    try:
        return await ready
    finally:
        loop.remove_reader(file_descriptor)


async def run_interactive(repl: Repl) -> None:
    while True:
        try:
            text = await _read_console_line("\nyou> ")
        except (EOFError, KeyboardInterrupt):
            return
        if text in {"/exit", "/quit"}:
            return
        if text == "/clear":
            repl.handle_command(text)
            print("conversation cleared")
            continue
        if text.strip():
            print("baremetal_harness> ", end="", flush=True)
            await repl.run_turn(text)


async def run_app_interactive(repl: AppRepl) -> None:
    while True:
        try:
            text = await _read_console_line("\nyou> ")
        except (EOFError, KeyboardInterrupt):
            return
        if text.strip() and await repl.process(text):
            return


def _run_cli(coroutine: Coroutine[Any, Any, None]) -> int:
    try:
        asyncio.run(coroutine)
    except KeyboardInterrupt:
        print()
        return 130
    return 0


def simple_repl_main() -> int:
    config = ReplConfig.from_environment()
    client = OpenAICompatibleClient(config.base_url, config.api_key)
    repl = Repl(client, config.model)

    async def run() -> None:
        try:
            await run_interactive(repl)
        finally:
            await client.aclose()

    return _run_cli(run())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="baremetal_harness",
        description="Run the handwritten BareMetal Harness Agent Harness.",
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--docker-image")
    parser.add_argument("--max-turns")
    parser.add_argument("--max-tool-calls")
    parser.add_argument("--context-tokens")
    parser.add_argument("--reserve-output-tokens")
    parser.add_argument(
        "--require-strong-sandbox",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    add_config_subcommands(parser)
    return parser


def _run_application(
    config: BareMetalHarnessConfig,
    secrets: SecretProvider,
) -> int:
    async def run() -> None:
        from baremetal_harness.app import create_app

        app = await create_app(
            config,
            secret_provider=secrets,
        )
        try:
            await app.start_scheduler()
            await run_app_interactive(AppRepl(app))
        finally:
            await app.aclose()

    return _run_cli(run())


def _preflight_default_application(
    config: BareMetalHarnessConfig,
    secrets: SecretProvider,
) -> None:
    if not config.base_url:
        raise ApplicationConfigurationError(
            "base_url is required; run: "
            "baremetal_harness config set base_url <url> or set OPENAI_BASE_URL"
        )
    if not secrets.get("OPENAI_API_KEY"):
        raise ApplicationConfigurationError(
            "API key is required; run: "
            "baremetal_harness config set api_key or set OPENAI_API_KEY"
        )


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    input_fn: Callable[[str], str] | None = None,
    secret_input: Callable[[str], str] | None = None,
    stdin_isatty: Callable[[], bool] | None = None,
    application_runner: Callable[[BareMetalHarnessConfig, SecretProvider], int] | None = None,
) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exception:
        return exception.code if isinstance(exception.code, int) else 2
    input_fn = input if input_fn is None else input_fn
    secret_input = getpass.getpass if secret_input is None else secret_input
    stdin_isatty = sys.stdin.isatty if stdin_isatty is None else stdin_isatty
    try:
        store = ConfigStore(args.config)
    except (OSError, RuntimeError, ValueError):
        print("invalid config path", file=sys.stderr)
        return 2
    if args.command == "config":
        return run_config_command(
            args,
            store,
            input_fn=input_fn,
            secret_input=secret_input,
            write=print,
            error=lambda message: print(message, file=sys.stderr),
            is_tty=stdin_isatty,
        )

    try:
        if not store.exists():
            if not stdin_isatty():
                print(
                    "configuration is missing; run: baremetal_harness config init",
                    file=sys.stderr,
                )
                return 2
            with store.coordinate_first_run() as needs_initialization:
                if needs_initialization:
                    try:
                        run_config_wizard(
                            store,
                            input_fn=input_fn,
                            secret_input=secret_input,
                            write=print,
                            is_tty=stdin_isatty,
                        )
                    except (
                        ConfigInteractionError,
                        EOFError,
                        KeyboardInterrupt,
                    ):
                        print(
                            "configuration initialization cancelled",
                            file=sys.stderr,
                        )
                        return 2

        environment = os.environ if environ is None else environ
        document = store.read()
        secrets = ConfigSecretProvider(document, environment)
        config = resolve_config(
            document,
            environ=environment,
            overrides={
                "data_dir": args.data_dir,
                "workspace": args.workspace,
                "base_url": args.base_url,
                "model": args.model,
                "docker_image": args.docker_image,
                "max_turns": args.max_turns,
                "max_tool_calls": args.max_tool_calls,
                "context_tokens": args.context_tokens,
                "reserve_output_tokens": args.reserve_output_tokens,
                "require_strong_sandbox": args.require_strong_sandbox,
            },
        )
    except OSError:
        print("failed to read configuration", file=sys.stderr)
        return 2
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if config.model == "fake":
        print(
            "interactive CLI requires a real model; run: "
            "baremetal_harness config set model <name> or set OPENAI_MODEL",
            file=sys.stderr,
        )
        return 2

    if application_runner is not None:
        return application_runner(config, secrets)
    try:
        _preflight_default_application(config, secrets)
        return _run_application(config, secrets)
    except ApplicationConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2
