"""CapCut Desktop MCP adapter."""

from .server import CapCutMcpServer, start_server, stop_server

__all__ = ["CapCutMcpServer", "start_server", "stop_server"]
