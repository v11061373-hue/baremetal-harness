from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BareMetalHarnessPaths:
    data: Path
    state_database: Path
    plans_database: Path
    scheduler_database: Path
    checkpoints: Path
    memory_sources: Path
    traces: Path
    sandboxes: Path

    @classmethod
    def create(cls, data_dir: Path) -> "BareMetalHarnessPaths":
        data = data_dir.resolve()
        data.mkdir(parents=True, exist_ok=True, mode=0o700)
        return cls(
            data,
            data / "state.db",
            data / "plans.db",
            data / "scheduler.db",
            data / "checkpoints",
            data / "memory-sources",
            data / "traces",
            data / "sandboxes",
        )
