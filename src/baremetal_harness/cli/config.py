import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReplConfig:
    base_url: str
    api_key: str
    model: str

    @classmethod
    def from_environment(cls) -> "ReplConfig":
        required = ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")
        values = {name: os.environ.get(name, "") for name in required}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise SystemExit(f"missing required environment: {', '.join(missing)}")
        return cls(
            values["OPENAI_BASE_URL"],
            values["OPENAI_API_KEY"],
            values["OPENAI_MODEL"],
        )
