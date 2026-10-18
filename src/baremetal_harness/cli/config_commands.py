import argparse
from collections.abc import Callable

from baremetal_harness.cli.config_wizard import (
    ConfigInteractionError,
    run_config_wizard,
)
from baremetal_harness.config import CONFIG_FIELDS
from baremetal_harness.config_store import (
    ConfigPathError,
    ConfigPersistenceError,
    ConfigStore,
    redact_secret,
    render_config_view,
)


def add_config_subcommands(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="command")
    config = subparsers.add_parser(
        "config",
        help="Manage BareMetal Harness configuration.",
    )
    actions = config.add_subparsers(
        dest="config_action",
        required=True,
    )
    actions.add_parser("init")
    actions.add_parser("show")
    get_parser = actions.add_parser("get")
    get_parser.add_argument("key")
    set_parser = actions.add_parser("set")
    set_parser.add_argument("key")
    set_parser.add_argument("value", nargs=argparse.REMAINDER)
    unset_parser = actions.add_parser("unset")
    unset_parser.add_argument("key")
    actions.add_parser("path")


def _unknown_field_message(field: str) -> str:
    return f"unknown config field: {field}"


def _run_config_action(
    args: argparse.Namespace,
    store: ConfigStore,
    *,
    input_fn: Callable[[str], str],
    secret_input: Callable[[str], str],
    write: Callable[[str], None],
    error: Callable[[str], None],
    is_tty: Callable[[], bool],
) -> int:
    action = args.config_action
    if action == "path":
        write(str(store.path))
        return 0
    if action == "show":
        write(render_config_view(store).removesuffix("\n"))
        return 0
    if action == "get":
        if args.key not in CONFIG_FIELDS:
            error(_unknown_field_message(args.key))
            return 2
        value = store.resolved_view().get(args.key)
        if args.key == "api_key":
            write(redact_secret(value))
        elif value is None:
            write("not configured")
        else:
            write(str(value).lower() if isinstance(value, bool) else str(value))
        return 0
    if action == "set":
        if args.key not in CONFIG_FIELDS:
            error(_unknown_field_message(args.key))
            return 2
        values = args.value
        if args.key == "api_key":
            if values:
                error(
                    "api_key must be entered interactively: baremetal_harness config set api_key"
                )
                return 2
            if not is_tty():
                error("setting api_key requires a TTY")
                return 2
            value = secret_input("API key: ")
        else:
            if not values:
                error(f"value is required for {args.key}")
                return 2
            if len(values) != 1:
                error(f"exactly one value is required for {args.key}")
                return 2
            value = values[0]
        store.set(args.key, value)
        write(f"updated {args.key}")
        return 0
    if action == "unset":
        if args.key not in CONFIG_FIELDS:
            error(_unknown_field_message(args.key))
            return 2
        store.unset(args.key)
        write(f"unset {args.key}")
        return 0
    run_config_wizard(
        store,
        input_fn=input_fn,
        secret_input=secret_input,
        write=write,
        is_tty=is_tty,
    )
    return 0


def run_config_command(
    args: argparse.Namespace,
    store: ConfigStore,
    *,
    input_fn: Callable[[str], str],
    secret_input: Callable[[str], str],
    write: Callable[[str], None],
    error: Callable[[str], None],
    is_tty: Callable[[], bool],
) -> int:
    try:
        return _run_config_action(
            args,
            store,
            input_fn=input_fn,
            secret_input=secret_input,
            write=write,
            error=error,
            is_tty=is_tty,
        )
    except (EOFError, KeyboardInterrupt):
        error("config command cancelled")
    except ConfigInteractionError as exception:
        error(str(exception))
    except (ConfigPathError, ConfigPersistenceError) as exception:
        error(str(exception))
    except OSError:
        error("failed to read configuration")
    except ValueError as exception:
        if args.config_action == "set" and getattr(args, "key", None) == "api_key":
            error("invalid api_key value")
        else:
            error(str(exception))
    return 2
