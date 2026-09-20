"""Stdio MCP server for TypeSafe Jev. Does not print the API key."""

import json
import sys

from jev_router.jev import JevUnavailable

from .classify import classify_task
from .pack import empty_pack, filled_roles, load_pack
from .secrets import load_key


def _read():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        decoded = line.decode("utf-8", errors="replace")
        if ":" not in decoded:
            continue
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length") or 0)
    if length <= 0:
        return None
    raw = sys.stdin.buffer.read(length)
    return json.loads(raw.decode("utf-8"))


def _write(payload):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw)
    sys.stdout.buffer.flush()


def _tools():
    return [
        {
            "name": "jev_classify",
            "description": "Classify a task with TypeSafe Jev into pack roles. Returns role, confidence, needs_korean. Not a chat model.",
            "inputSchema": {
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
            },
        }
    ]


def _call_classify(task):
    pack = load_pack()
    if not filled_roles(pack):
        pack = empty_pack()
    return classify_task(str(task or ""), pack, key=load_key(), timeout=8)


def main():
    while True:
        message = _read()
        if message is None:
            return 0
        method = message.get("method")
        msg_id = message.get("id")
        if method == "initialize":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "typesafe-jev", "version": "0.3.0"},
                    },
                }
            )
            continue
        if method == "notifications/initialized" or msg_id is None:
            continue
        if method == "tools/list":
            _write({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": _tools()}})
            continue
        if method == "tools/call":
            args = (message.get("params") or {}).get("arguments") or {}
            try:
                result = _call_classify(args.get("task"))
                _write(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
                    }
                )
            except (JevUnavailable, ValueError) as exc:
                _write(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "isError": True,
                            "content": [{"type": "text", "text": str(exc)}],
                        },
                    }
                )
            continue
        _write({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "method not found"}})


if __name__ == "__main__":
    raise SystemExit(main() or 0)
