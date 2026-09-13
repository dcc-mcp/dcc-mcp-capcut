"""Bounded client for the optional, read-only in-process Qt probe."""

from __future__ import annotations

import json
import os
import re
import socket
from pathlib import Path
from typing import Any

MAX_RESPONSE = 8 * 1024 * 1024


def inspect_qt_host(
    *, operation: str = "host.describe", max_nodes: int = 500, max_depth: int = 8
) -> dict[str, Any]:
    """Read metadata from the configured host; never load a plugin or fall back."""
    if operation not in {"host.describe", "qt.inspect"}:
        raise ValueError("Unsupported Qt probe operation")
    if type(max_nodes) is not int or not 1 <= max_nodes <= 5000:
        raise ValueError("max_nodes must be an integer between 1 and 5000")
    if type(max_depth) is not int or not 0 <= max_depth <= 20:
        raise ValueError("max_depth must be an integer between 0 and 20")
    endpoint_path = os.environ.get("DCC_CAPCUT_PROBE_ENDPOINT")
    token = os.environ.get("DCC_CAPCUT_PROBE_TOKEN", "")
    expected_hash = os.environ.get("DCC_CAPCUT_PROBE_EXE_SHA256", "")
    expected_pid = os.environ.get("DCC_MCP_CAPCUT_PID", "")
    if not endpoint_path or len(token.encode()) < 32:
        raise RuntimeError("Qt probe is not configured; no native capabilities established")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or not expected_pid.isdecimal():
        raise RuntimeError("Qt probe requires an explicit host PID and executable SHA-256")
    with Path(endpoint_path).open("rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise RuntimeError("Qt probe endpoint exceeds size limit")
    endpoint = json.loads(raw)
    if not isinstance(endpoint, dict):
        raise RuntimeError("Invalid Qt probe endpoint")
    if (
        endpoint.get("protocol") != 1
        or endpoint.get("pid") != int(expected_pid)
        or endpoint.get("exe_sha256") != expected_hash
    ):
        raise RuntimeError("Qt probe endpoint does not match the bound host")
    port = endpoint.get("port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise RuntimeError("Invalid Qt probe port")
    request = {
        "protocol": 1,
        "pid": int(expected_pid),
        "token": token,
        "operation": operation,
        "max_nodes": max_nodes,
        "max_depth": max_depth,
    }
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.sendall(json.dumps(request).encode() + b"\n")
        with connection.makefile("rb") as stream:
            response = stream.readline(MAX_RESPONSE + 1)
    if len(response) > MAX_RESPONSE or not response.endswith(b"\n"):
        raise RuntimeError("Invalid or oversized Qt probe response")
    result = json.loads(response)
    if not isinstance(result, dict) or result.get("ok") is not True:
        # Do not echo arbitrary peer data, credentials or host text in errors.
        raise RuntimeError("Qt probe rejected the metadata request")
    if (
        result.get("protocol") != 1
        or result.get("pid") != int(expected_pid)
        or result.get("exe_sha256") != expected_hash
        or result.get("backend") != "qt-probe"
        or result.get("verification_scope") != "qt_metadata"
    ):
        raise RuntimeError("Qt probe response does not match the bound host")
    return result
