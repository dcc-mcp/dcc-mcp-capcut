import os
import sys
import types
from dataclasses import dataclass

import pytest

from dcc_mcp_capcut import runtime_entry, shared_runtime
from dcc_mcp_capcut.__version__ import __version__

# The external runtime is a different product, so its version is a stub and
# must stay distinct from the adapter version: the handshake under test is
# supposed to carry two versions through side by side, and a stub that happens
# to equal __version__ would stop detecting a copy/paste swap between them.
STUB_RUNTIME_VERSION = "9.9.9"


def test_runtime_entry_is_callable():
    assert callable(runtime_entry.main)
    assert callable(runtime_entry.require_runtime)


@dataclass
class _Handshake:
    adapter_id: str = "capcut"
    adapter_version: str = __version__
    runtime_id: str = "dcc-mcp-external"
    runtime_version: str = STUB_RUNTIME_VERSION
    capabilities_fingerprint: str = "a" * 64


def _install_fake_runtime(monkeypatch, handshake: _Handshake) -> None:
    bootstrap = types.ModuleType("dcc_mcp_runtime.bootstrap")
    bootstrap.require_adapter = lambda adapter_id: types.SimpleNamespace(handshake=handshake)
    package = types.ModuleType("dcc_mcp_runtime")
    package.bootstrap = bootstrap
    monkeypatch.setitem(sys.modules, "dcc_mcp_runtime", package)
    monkeypatch.setitem(sys.modules, "dcc_mcp_runtime.bootstrap", bootstrap)


def test_shared_runtime_exports_verified_handshake_metadata(monkeypatch):
    _install_fake_runtime(monkeypatch, _Handshake())

    shared_runtime.require_runtime()

    assert os.environ["DCC_MCP_PYTHON_EXECUTABLE"] == sys.executable
    assert os.environ["DCC_MCP_RUNTIME_ID"] == "dcc-mcp-external"
    assert os.environ["DCC_MCP_RUNTIME_VERSION"] == STUB_RUNTIME_VERSION
    assert os.environ["DCC_MCP_RUNTIME_CAPABILITIES_FINGERPRINT"] == "a" * 64


def test_shared_runtime_rejects_stale_adapter_manifest(monkeypatch):
    _install_fake_runtime(monkeypatch, _Handshake(adapter_version="0.0.1"))
    with pytest.raises(RuntimeError, match="ADAPTER_VERSION_MISMATCH"):
        shared_runtime.require_runtime()
