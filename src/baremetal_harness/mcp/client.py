import asyncio
import contextlib
import json
import os
from collections.abc import Mapping, Sequence

from baremetal_harness.mcp.types import (
    McpError,
    McpServerClosed,
    McpServerInfo,
    McpTimeout,
    McpTool,
)

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "baremetal_harness", "version": "0.1.0"}
MAX_LINE_BYTES = 8 * 1024 * 1024


class StdioMcpClient:
    """Speak MCP to a local server over its stdin and stdout.

    The stdio transport is newline-delimited JSON-RPC 2.0. Responses may arrive
    out of order, so a single reader task correlates them to pending requests
    by id rather than assuming request/response lockstep.
    """

    def __init__(
        self,
        command: str,
        args: Sequence[str] = (),
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        timeout: float = 30.0,
        shutdown_grace_seconds: float = 1.0,
        allowed_environment: Sequence[str] = ("PATH",),
    ) -> None:
        self.command = command
        self.args = tuple(args)
        self.timeout = timeout
        self.shutdown_grace_seconds = shutdown_grace_seconds
        self.cwd = cwd
        environment = {
            name: value
            for name, value in os.environ.items()
            if name in set(allowed_environment)
        }
        environment.update(dict(env or {}))
        self.env = environment
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._counter = 0
        self.server_info: McpServerInfo | None = None

    async def start(self) -> McpServerInfo:
        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=self.env,
                cwd=self.cwd,
                limit=MAX_LINE_BYTES,
            )
        except (FileNotFoundError, PermissionError) as error:
            raise McpError(f"cannot start MCP server: {self.command}") from error
        self._reader = asyncio.create_task(self._read_loop())
        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        await self._notify("notifications/initialized", {})
        info = result.get("serverInfo")
        info = info if isinstance(info, dict) else {}
        self.server_info = McpServerInfo(
            str(info.get("name", self.command)),
            str(info.get("version", "unknown")),
            str(result.get("protocolVersion", PROTOCOL_VERSION)),
        )
        return self.server_info

    async def list_tools(self) -> tuple[McpTool, ...]:
        result = await self._request("tools/list", {})
        rows = result.get("tools")
        if not isinstance(rows, list):
            raise McpError("tools/list did not return a tool array")
        tools = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            schema = row.get("inputSchema")
            if not isinstance(name, str) or not name:
                continue
            # A server controls this schema, and the tool executor validates
            # arguments against it, so anything unusable is replaced rather
            # than trusted.
            if not isinstance(schema, dict) or schema.get("type") != "object":
                schema = {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                }
            annotations = row.get("annotations")
            tools.append(
                McpTool(
                    name,
                    str(row.get("description", "") or ""),
                    schema,
                    annotations if isinstance(annotations, dict) else {},
                )
            )
        return tuple(tools)

    async def call_tool(self, name: str, arguments: Mapping[str, object]) -> str:
        result = await self._request(
            "tools/call",
            {"name": name, "arguments": dict(arguments)},
        )
        text = _content_text(result.get("content"))
        if result.get("isError"):
            raise McpError(text or f"MCP tool failed: {name}")
        if text:
            return text
        structured = result.get("structuredContent")
        if structured is not None:
            return json.dumps(structured, separators=(",", ":"), sort_keys=True)
        return ""

    async def _read_loop(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            while True:
                try:
                    line = await self._process.stdout.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    # An over-long line means the framing is unusable.
                    break
                if not line:
                    break
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                identifier = message.get("id")
                if isinstance(identifier, int):
                    future = self._pending.pop(identifier, None)
                    if future is not None and not future.done():
                        future.set_result(message)
        finally:
            self._fail_pending(McpServerClosed("MCP server closed the connection"))

    def _fail_pending(self, error: Exception) -> None:
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    async def _write(self, message: dict[str, object]) -> None:
        if self._process is None or self._process.stdin is None:
            raise McpServerClosed("MCP server is not running")
        payload = json.dumps(message, separators=(",", ":")).encode() + b"\n"
        try:
            self._process.stdin.write(payload)
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as error:
            raise McpServerClosed("MCP server closed its input") from error

    async def _notify(self, method: str, params: dict[str, object]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _request(
        self,
        method: str,
        params: dict[str, object],
    ) -> dict[str, object]:
        self._counter += 1
        identifier = self._counter
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[identifier] = future
        await self._write(
            {
                "jsonrpc": "2.0",
                "id": identifier,
                "method": method,
                "params": params,
            }
        )
        try:
            message = await asyncio.wait_for(future, self.timeout)
        except TimeoutError as error:
            self._pending.pop(identifier, None)
            raise McpTimeout(f"MCP request timed out: {method}") from error
        error = message.get("error")
        if error is not None:
            detail = error.get("message") if isinstance(error, dict) else None
            raise McpError(f"MCP error in {method}: {detail or error}")
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    async def aclose(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
            self._reader = None
        self._fail_pending(McpServerClosed("MCP client closed"))
        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return
        # Escalate politely: closing stdin lets a well-behaved server exit,
        # SIGTERM handles one that is busy, SIGKILL handles one that ignores both.
        if process.stdin is not None:
            process.stdin.close()
        for stop in (None, process.terminate, process.kill):
            if stop is not None:
                try:
                    stop()
                except ProcessLookupError:
                    return
            try:
                await asyncio.wait_for(
                    asyncio.shield(process.wait()),
                    self.shutdown_grace_seconds,
                )
                return
            except TimeoutError:
                continue
        await process.wait()


def _content_text(content: object) -> str:
    if not isinstance(content, list):
        return ""
    parts = [
        item["text"]
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    ]
    return "\n".join(parts)
