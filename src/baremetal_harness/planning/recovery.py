from collections.abc import Awaitable, Callable


class CompletedExecutionGuard:
    def __init__(self, completed_ids: tuple[str, ...]) -> None:
        self._completed = list(completed_ids)

    @property
    def completed_ids(self) -> tuple[str, ...]:
        return tuple(self._completed)

    async def execute(
        self,
        execution_id: str,
        operation: Callable[[], Awaitable[str]],
    ) -> tuple[str | None, bool]:
        if execution_id in self._completed:
            return None, True
        result = await operation()
        self._completed.append(execution_id)
        return result, False
