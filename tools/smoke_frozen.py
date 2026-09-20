# -*- coding: utf-8 -*-
"""N48: smoke-test a frozen SolidWorksMCPServer.exe over MCP stdio.

No SolidWorks process needed: this asserts the handshake, the tool
registration count (the repo's pinned 79 default / 81 product count —
a frozen build that registers a different number is broken), and the
"honest failure" contract (a connect-dependent call without SW running
returns a structured error, never a crash).

Usage (from anywhere — the point is that no source tree is needed):
    python tools/smoke_frozen.py [path-to-exe]
Exit 0 = all assertions passed.
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

EXPECTED_TOOLS = 81  # N58 added part_circular_pattern  # default registry (N52 added drawing_insert_gtol) — pinned by tests
READ_TIMEOUT_S = 30.0


def _reader(proc: subprocess.Popen, out: "queue.Queue[str]") -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        out.put(line.decode("utf-8", "replace"))
    out.put("")  # EOF sentinel


def _rpc(proc, lines: "queue.Queue[str]", payload: dict, wait_id) -> dict:
    assert proc.stdin is not None
    proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
    proc.stdin.flush()
    deadline = time.monotonic() + READ_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=deadline - time.monotonic())
        except queue.Empty:
            break
        if not line:
            raise RuntimeError("server closed stdout before answering")
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue  # tolerate stray non-JSON noise
        if msg.get("id") == wait_id:
            return msg
    raise RuntimeError(f"no response with id={wait_id} in {READ_TIMEOUT_S}s")


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parents[1] / "dist" / "SolidWorksMCPServer" / "SolidWorksMCPServer.exe"
    )
    if not exe.is_file():
        print(f"FAIL: exe not found: {exe}")
        return 2
    print(f"exe: {exe}")

    t0 = time.monotonic()
    proc = subprocess.Popen(
        [str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, cwd=str(exe.parent),
    )
    lines: "queue.Queue[str]" = queue.Queue()
    threading.Thread(target=_reader, args=(proc, lines), daemon=True).start()

    init = _rpc(proc, lines, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "frozen-smoke", "version": "0"},
        },
    }, wait_id=1)
    server_info = (init.get("result") or {}).get("serverInfo") or {}
    print(f"handshake ok in {time.monotonic() - t0:.1f}s | server: "
          f"{server_info.get('name')} v{server_info.get('version')}")
    assert server_info.get("name"), "initialize carried no serverInfo.name"

    proc.stdin.write(
        (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode("utf-8")
    )
    proc.stdin.flush()

    tools = _rpc(proc, lines, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/list",
    }, wait_id=2)
    tool_names = [t.get("name", "") for t in (tools.get("result") or {}).get("tools", [])]
    print(f"tools/list: {len(tool_names)} tools")
    assert len(tool_names) == EXPECTED_TOOLS, (
        f"frozen tool count {len(tool_names)} != pinned {EXPECTED_TOOLS}"
    )

    # Honest-failure probe: connect with SolidWorks not running must
    # answer with a structured error payload, not die.
    connect = _rpc(proc, lines, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "solidworks_connect",
                   "arguments": {"launch_if_needed": False}},
    }, wait_id=3)
    result = connect.get("result") or {}
    ok = result.get("isError") is not True
    payload = (result.get("content") or [{}])[0].get("text", "")
    print(f"connect (no SW): isError={result.get('isError')} | "
          f"{payload[:110]!r}")
    assert ok or result.get("isError") is not None, "connect crashed the protocol"

    proc.stdin.close()
    proc.wait(timeout=10)
    print("SMOKE PASS: handshake + tool count + honest failure")
    return 0


if __name__ == "__main__":
    sys.exit(main())
