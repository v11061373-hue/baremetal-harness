import re

from baremetal_harness.sandbox.types import (
    Command,
    SandboxCapabilityError,
    SandboxPolicy,
    SandboxResourceExceeded,
    SandboxTimeout,
)
from baremetal_harness.tools.types import (
    RegisteredTool,
    RiskLevel,
    ToolCapabilities,
    ToolContext,
    ToolSpec,
)
from baremetal_harness.workspace.paths import WorkspaceEscape, resolve_workspace_path

# A revision may reach git's argv, so it must never look like an option and
# must stay inside the characters git revisions actually use.
REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/^~@{}-]{0,127}")
MAX_LOG_LIMIT = 200

# Read-only git still reads user and system config, which can carry pagers and
# fsmonitor hooks. Neutralize both so the subcommand is what it says it is.
GIT_ENVIRONMENT = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
}
GIT_ALLOWED_ENVIRONMENT = ("PATH", *GIT_ENVIRONMENT)

READ_ONLY_INSPECTION = ToolCapabilities(
    filesystem="read",
    network="deny",
    subprocess=True,
    risk_level=RiskLevel.LOW,
    side_effects=False,
    idempotent=True,
)


def _relative_path(context: ToolContext, raw: object) -> str:
    resolved = resolve_workspace_path(context.workspace, str(raw))
    return resolved.relative_to(context.workspace.resolve()).as_posix()


def _revision(raw: object) -> str:
    value = str(raw)
    if not REVISION.fullmatch(value):
        raise ValueError("invalid git revision")
    return value


def make_git_tools(
    sandbox,
    *,
    timeout_seconds: float = 15.0,
    max_output_bytes: int = 64 * 1024,
) -> tuple[RegisteredTool, ...]:
    async def run_git(argv: tuple[str, ...], context: ToolContext) -> str:
        try:
            result = await sandbox.execute(
                Command(
                    ("git", "--no-pager", *argv),
                    context.workspace,
                    dict(GIT_ENVIRONMENT),
                ),
                SandboxPolicy(
                    context.workspace,
                    "read",
                    "deny",
                    GIT_ALLOWED_ENVIRONMENT,
                    timeout_seconds,
                    max_output_bytes,
                ),
            )
        except FileNotFoundError:
            return "git is not installed"
        except SandboxTimeout:
            return "git timed out"
        except SandboxResourceExceeded:
            return "git output exceeded the size limit"
        except SandboxCapabilityError as error:
            return f"git could not run: {error}"
        if result.exit_code != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            reason = detail[0] if detail else f"exit code {result.exit_code}"
            return f"git {argv[0]} failed: {reason}"
        return result.stdout

    async def git_status(arguments, context: ToolContext) -> str:
        return await run_git(("status", "--porcelain=v1", "--branch"), context)

    async def git_log(arguments, context: ToolContext) -> str:
        limit = int(arguments.get("limit", 20))
        if not 1 <= limit <= MAX_LOG_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LOG_LIMIT}")
        argv = ["log", "--oneline", "--no-decorate", "-n", str(limit)]
        if arguments.get("path") is not None:
            # "--" keeps a path from ever being parsed as an option.
            argv += ["--", _relative_path(context, arguments["path"])]
        return await run_git(tuple(argv), context)

    async def git_diff(arguments, context: ToolContext) -> str:
        argv = ["diff"]
        if bool(arguments.get("staged", False)):
            argv.append("--staged")
        if arguments.get("path") is not None:
            argv += ["--", _relative_path(context, arguments["path"])]
        return await run_git(tuple(argv), context)

    async def git_show(arguments, context: ToolContext) -> str:
        return await run_git(
            ("show", "--stat", "--patch", _revision(arguments["revision"])),
            context,
        )

    optional_path = {"type": "string"}
    definitions = (
        (
            "git_status",
            "Show the working tree status of the workspace repository",
            {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            git_status,
        ),
        (
            "git_log",
            "List recent commits, optionally for one path",
            {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "path": optional_path,
                },
                "required": [],
                "additionalProperties": False,
            },
            git_log,
        ),
        (
            "git_diff",
            "Show unstaged or staged changes, optionally for one path",
            {
                "type": "object",
                "properties": {
                    "staged": {"type": "boolean"},
                    "path": optional_path,
                },
                "required": [],
                "additionalProperties": False,
            },
            git_diff,
        ),
        (
            "git_show",
            "Show one commit with its stat summary and patch",
            {
                "type": "object",
                "properties": {"revision": {"type": "string"}},
                "required": ["revision"],
                "additionalProperties": False,
            },
            git_show,
        ),
    )
    return tuple(
        RegisteredTool(
            ToolSpec(name, description, schema, READ_ONLY_INSPECTION),
            handler,
        )
        for name, description, schema, handler in definitions
    )


__all__ = ["make_git_tools", "REVISION", "READ_ONLY_INSPECTION", "WorkspaceEscape"]
