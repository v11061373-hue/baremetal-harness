from collections.abc import Callable

from baremetal_harness.config import coerce_config_value
from baremetal_harness.config_store import ConfigStore


class ConfigInteractionError(RuntimeError):
    """Raised when secure interactive configuration is unavailable."""


def _prompt_value(
    *,
    field: str,
    label: str,
    current: object | None,
    input_fn: Callable[[str], str],
    write: Callable[[str], None],
) -> str | None:
    while True:
        suffix = f" [{current}]" if current is not None else ""
        raw = input_fn(f"{label}{suffix}: ").strip()
        if not raw and current is not None:
            return None
        try:
            return str(coerce_config_value(field, raw))
        except ValueError as error:
            write(str(error))


def run_config_wizard(
    store: ConfigStore,
    *,
    input_fn: Callable[[str], str],
    secret_input: Callable[[str], str],
    write: Callable[[str], None],
    is_tty: Callable[[], bool],
) -> None:
    if not is_tty():
        raise ConfigInteractionError("config initialization requires a TTY")

    document = store.read()
    base_url = _prompt_value(
        field="base_url",
        label="Base URL",
        current=document.get("base_url"),
        input_fn=input_fn,
        write=write,
    )
    model = _prompt_value(
        field="model",
        label="Model",
        current=document.get("model"),
        input_fn=input_fn,
        write=write,
    )

    current_secret = document.get("api_key")
    while True:
        secret = secret_input("API key: ")
        if not secret and current_secret is not None:
            api_key = None
            break
        try:
            api_key = str(coerce_config_value("api_key", secret))
            break
        except ValueError as error:
            write(str(error))

    store.initialize(
        base_url=base_url,
        model=model,
        api_key=api_key,
    )
    write(f"configuration saved: {store.path}")
