"""A minimal MCP stdio server used to test the handwritten client offline.

Behaviours are selected with argv so one script can cover the success path and
the failure paths a real server can produce.
"""

import json
import sys
import time

TOOLS = [
    {
        "name": "echo",
        "description": "Echo the given text",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "danger",
        "description": "Pretend to delete things",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "annotations": {"destructiveHint": True, "openWorldHint": True},
    },
    {
        "name": "broken-schema",
        "description": "Advertises an unusable schema",
        "inputSchema": "not an object",
    },
]


def write(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        method = request.get("method")
        identifier = request.get("id")
        if method == "notifications/initialized":
            continue
        if method == "initialize":
            write(
                {
                    "jsonrpc": "2.0",
                    "id": identifier,
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "echo-server", "version": "1.2.3"},
                    },
                }
            )
        elif method == "tools/list":
            write({"jsonrpc": "2.0", "id": identifier, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = request.get("params", {})
            name = params.get("name")
            arguments = params.get("arguments", {})
            if mode == "hang":
                time.sleep(30)
            if mode == "crash":
                return 1
            if name == "echo":
                write(
                    {
                        "jsonrpc": "2.0",
                        "id": identifier,
                        "result": {
                            "content": [
                                {"type": "text", "text": arguments.get("text", "")}
                            ]
                        },
                    }
                )
            elif name == "danger":
                write(
                    {
                        "jsonrpc": "2.0",
                        "id": identifier,
                        "result": {
                            "content": [{"type": "text", "text": "refused"}],
                            "isError": True,
                        },
                    }
                )
            else:
                write(
                    {
                        "jsonrpc": "2.0",
                        "id": identifier,
                        "error": {"code": -32601, "message": f"unknown tool: {name}"},
                    }
                )
        else:
            write(
                {
                    "jsonrpc": "2.0",
                    "id": identifier,
                    "error": {"code": -32601, "message": "method not found"},
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
