from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandResult:
    handled: bool
    output: str = ""
    exit_requested: bool = False


class CommandRouter:
    COMMANDS = (
        "/help",
        "/clear",
        "/exit",
        "/resume <session-id>",
        "/sessions",
        "/tasks",
        "/memory <query>",
        "/skills",
        "/agents",
        "/jobs",
        "/cancel <job-id>",
        "/trace on|off|show",
        "/metrics",
        "/sandbox",
        "/mcp",
        "/changes",
        "/apply <path>|--all",
    )

    def handle(self, text: str) -> CommandResult:
        if not text.startswith("/"):
            return CommandResult(False)
        command = text.split(maxsplit=1)[0]
        if command in {"/exit", "/quit"}:
            return CommandResult(True, exit_requested=True)
        if command == "/help":
            return CommandResult(True, "\n".join(self.COMMANDS))
        if command == "/clear":
            return CommandResult(True, "conversation cleared")
        known = {
            "/resume",
            "/sessions",
            "/tasks",
            "/memory",
            "/skills",
            "/agents",
            "/jobs",
            "/cancel",
            "/trace",
            "/metrics",
            "/sandbox",
            "/mcp",
            "/changes",
            "/apply",
        }
        if command in known:
            return CommandResult(True, f"{command} is available in the integrated app")
        return CommandResult(True, "unknown command; use /help")
