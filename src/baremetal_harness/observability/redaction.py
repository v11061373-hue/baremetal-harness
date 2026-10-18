from collections.abc import Mapping


class Redactor:
    _sensitive_keys = {
        "authorization",
        "api_key",
        "token",
        "secret",
        "password",
        "cookie",
        "set-cookie",
    }

    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        self.secrets = tuple(secret for secret in secrets if secret)

    def redact(self, value: object, *, _depth: int = 0) -> object:
        if _depth >= 12:
            return "<max-depth>"
        if isinstance(value, bytes):
            return f"<bytes:{len(value)}>"
        if isinstance(value, str):
            result = value
            for secret in self.secrets:
                result = result.replace(secret, "[REDACTED]")
            if len(result) > 16 * 1024:
                return result[: 16 * 1024] + f"<truncated:{len(result)}>"
            return result
        if isinstance(value, Mapping):
            return {
                str(key): (
                    "[REDACTED]"
                    if str(key).casefold() in self._sensitive_keys
                    else self.redact(item, _depth=_depth + 1)
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [
                self.redact(item, _depth=_depth + 1)
                for item in value
            ]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return value.__class__.__name__
