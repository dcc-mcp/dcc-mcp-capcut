"""Entry point for the shared dcc-mcp-runtime deployment."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from .__version__ import __version__

_RUNTIME_METADATA_ENV = {
    "DCC_MCP_RUNTIME_ID": "runtime_id",
    "DCC_MCP_RUNTIME_VERSION": "runtime_version",
    "DCC_MCP_RUNTIME_CAPABILITIES_FINGERPRINT": "capabilities_fingerprint",
}


def require_runtime() -> object:
    """Validate the runtime/adapter manifest handshake before starting CapCut."""
    try:
        from dcc_mcp_runtime.bootstrap import require_adapter
    except ImportError as exc:  # pragma: no cover - deployment-only branch
        raise RuntimeError(
            "DCC_MCP_RUNTIME_MISSING: install dcc-mcp-runtime and the CapCut adapter wheel"
        ) from exc

    result = require_adapter("capcut")
    handshake = getattr(result, "handshake", None)
    if handshake is None or getattr(handshake, "adapter_id", None) != "capcut":
        raise RuntimeError("DCC_MCP_RUNTIME_HANDSHAKE_INVALID: missing CapCut handshake")

    manifest_version = getattr(handshake, "adapter_version", None)
    if manifest_version != __version__:
        raise RuntimeError(
            "DCC_MCP_RUNTIME_ADAPTER_VERSION_MISMATCH: "
            f"manifest={manifest_version!r} installed={__version__!r}"
        )

    os.environ["DCC_MCP_PYTHON_EXECUTABLE"] = sys.executable
    for environment_name, attribute_name in _RUNTIME_METADATA_ENV.items():
        value = getattr(handshake, attribute_name, None)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"DCC_MCP_RUNTIME_HANDSHAKE_INVALID: missing {attribute_name}")
        os.environ[environment_name] = value
    return result


def main(argv: Sequence[str] | None = None) -> None:
    """Start the exact-window CapCut adapter through the verified runtime."""
    require_runtime()
    from .bootstrap import main as bootstrap_main

    bootstrap_main(argv)


__all__ = ["main", "require_runtime"]
