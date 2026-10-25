from baremetal_harness.permissions.types import (
    PermissionDecision,
    PermissionEvaluation,
)

_DESTRUCTIVE_ARGV: frozenset[tuple[str, ...]] = frozenset({
    ("rm", "-rf", "/"),
    ("rm", "-fr", "/"),
    ("rm", "-rf", "/*"),
    ("rm", "-rf", "/", "--no-preserve-root"),
    ("rm", "-rf", "~"),
})
_FORK_BOMB = ":(){ :|:& };:"


class DestructiveCommandGuard:
    """Deny obviously destructive shell commands before the sandbox. Fail-open.

    ponytail: exact-argv match only; sandbox (workspace-write, no network)
    bounds everything else. Extend _DESTRUCTIVE_ARGV if a real bypass shows up.
    """

    def evaluate(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
    ) -> PermissionEvaluation | None:
        if tool_name != "run_command":
            return None
        raw = arguments.get("argv")
        if not isinstance(raw, list) or not all(isinstance(a, str) for a in raw):
            return None
        argv = tuple(raw)
        if argv in _DESTRUCTIVE_ARGV or _FORK_BOMB in " ".join(argv):
            return PermissionEvaluation(
                PermissionDecision.DENY,
                f"destructive command blocked by guard: {' '.join(argv)[:80]}",
            )
        return None
