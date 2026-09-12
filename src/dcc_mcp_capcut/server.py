"""CapCut MCP server lifecycle."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from dcc_mcp_core import DccServerOptions, HostExecutionBridge
from dcc_mcp_core.server_base import DccServerBase

from .__version__ import __version__
from .bridge import CapCutBridge

DEFAULT_PORT = 0
_server: Optional["CapCutMcpServer"] = None


class CapCutMcpServer(DccServerBase):
    """External-bridge adapter for CapCut Desktop."""

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        *,
        dcc_pid: int | None = None,
        dcc_window_handle: int | None = None,
        dcc_window_title: str = "CapCut",
        **kwargs: Any,
    ) -> None:
        self.bridge = CapCutBridge()
        if dcc_pid is not None:
            os.environ["DCC_MCP_CAPCUT_PID"] = str(dcc_pid)
            os.environ["DCC_MCP_UI_CONTROL_PROCESS_ID"] = str(dcc_pid)
        if dcc_window_handle is not None:
            os.environ["DCC_MCP_CAPCUT_WINDOW_HANDLE"] = str(dcc_window_handle)
            os.environ["DCC_MCP_UI_CONTROL_WINDOW_HANDLE"] = str(dcc_window_handle)
        options = DccServerOptions.from_env(
            "capcut",
            Path(__file__).resolve().parent / "skills",
            port=port,
            server_name="dcc-mcp-capcut",
            server_version=__version__,
            instance_type="gui",
            dcc_pid=dcc_pid,
            dcc_window_handle=dcc_window_handle,
            dcc_window_title=os.environ.get("DCC_MCP_CAPCUT_WINDOW_TITLE", dcc_window_title),
            execution_bridge=HostExecutionBridge(dispatcher=None),
            adapter_version=__version__,
            **kwargs,
        )
        super().__init__(options=options)

    def start(self, **kwargs):
        self.bridge.start()
        return super().start(**kwargs)

    def stop(self) -> None:
        super().stop()
        self.bridge.stop()

    def _version_string(self) -> str:
        return os.environ.get("DCC_MCP_CAPCUT_VERSION", "unknown")


def start_server(
    port: Optional[int] = None,
    *,
    dcc_pid: int | None = None,
    dcc_window_handle: int | None = None,
    dcc_window_title: str = "CapCut",
    **kwargs: Any,
) -> CapCutMcpServer:
    global _server
    if _server is None or not _server.is_running:
        _server = CapCutMcpServer(
            port if port is not None else DEFAULT_PORT,
            dcc_pid=dcc_pid,
            dcc_window_handle=dcc_window_handle,
            dcc_window_title=dcc_window_title,
            **kwargs,
        )
        _server.register_builtin_actions()
        _server.start()
    return _server


def stop_server() -> None:
    global _server
    if _server is not None:
        _server.stop()
        _server = None
