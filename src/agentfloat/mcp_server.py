# -*- coding: utf-8 -*-
"""最小 MCP stdio 服务：只暴露 progress 工具，与 CLI 写同一份状态。"""
from __future__ import annotations

import json
import sys

from agentfloat.services.progress import store

TOOL = {
    "name": "progress",
    "description": "更新 AgentFloat 进度总线（plan/step/next/done/fail/need_input/cancel）",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session": {"type": "string"},
            "action": {"type": "string", "enum": ["plan", "step", "next", "done", "fail", "need_input", "cancel"]},
            "project": {"type": "string"},
            "title": {"type": "string"},
            "steps": {"type": "array", "items": {"type": "string"}},
            "error": {"type": "string"},
            "question": {"type": "string"},
            "window": {"type": "string"},
        },
        "required": ["action"],
    },
}


def _reply(rid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(msg):
    method = msg.get("method")
    rid = msg.get("id")
    if method == "initialize":
        _reply(rid, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                     "serverInfo": {"name": "af-mcp", "version": "1.0"}})
    elif method == "notifications/initialized":
        return
    elif method == "tools/list":
        _reply(rid, {"tools": [TOOL]})
    elif method == "tools/call":
        params = msg.get("params") or {}
        args = dict(params.get("arguments") or {})
        if params.get("name") != "progress":
            _reply(rid, error={"code": -32601, "message": "unknown tool"})
            return
        sid = str(args.pop("session", "") or store.DEFAULT_SESSION)
        try:
            data = store.update(sid, args)
        except Exception as exc:  # noqa: BLE001
            _reply(rid, error={"code": -32000, "message": str(exc)})
            return
        _reply(rid, {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]})
    elif rid is not None:
        _reply(rid, error={"code": -32601, "message": "method not found"})


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        handle(msg)


if __name__ == "__main__":
    main()
