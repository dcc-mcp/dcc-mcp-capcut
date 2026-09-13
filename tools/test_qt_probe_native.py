"""Exercise the actual plugin in a disposable Qt fixture, on each build platform."""

import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from dcc_mcp_capcut.qt_probe import inspect_qt_host


def main():
    fixture, plugins = (Path(arg).resolve() for arg in sys.argv[1:3])
    token = secrets.token_hex(32)
    with tempfile.TemporaryDirectory() as directory:
        endpoint = Path(directory) / "endpoint.json"
        settings = {
            "QT_PLUGIN_PATH": str(plugins),
            "QT_QPA_GENERIC_PLUGINS": "dcc-capcut-probe",
            "QT_QPA_PLATFORM": "offscreen",
            "DCC_CAPCUT_PROBE_TOKEN": token,
            "DCC_CAPCUT_PROBE_ENDPOINT": str(endpoint),
            "DCC_CAPCUT_PROBE_EXE_SHA256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        }
        process = subprocess.Popen([str(fixture)], env={**os.environ, **settings})
        try:
            deadline = time.monotonic() + 15
            while not endpoint.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Native plugin did not publish its endpoint")
                time.sleep(0.1)
            os.environ.update(settings, DCC_MCP_CAPCUT_PID=str(process.pid))
            identity = inspect_qt_host()
            assert identity["capabilities"] == ["host.describe", "qt.inspect"]
            tree = inspect_qt_host(operation="qt.inspect")
            assert any(node["object_name"] == "fixtureTrack" for node in tree["nodes"])
            assert inspect_qt_host(operation="qt.inspect", max_nodes=1)["truncated"]
            for operation, credential, error in [
                ("invoke", token, "unsupported_operation"),
                ("host.describe", "wrong", "unauthorized"),
            ]:
                with socket.create_connection(
                    ("127.0.0.1", json.loads(endpoint.read_text())["port"])
                ) as peer:
                    peer.sendall(
                        json.dumps(
                            {
                                "protocol": 1,
                                "pid": process.pid,
                                "operation": operation,
                                "token": credential,
                            }
                        ).encode()
                        + b"\n"
                    )
                    with peer.makefile("rb") as stream:
                        assert json.loads(stream.readline())["error"] == error
            print(
                json.dumps(
                    {
                        "native_fixture": "passed",
                        "qt_version": identity["qt_version"],
                        "node_count": len(tree["nodes"]),
                    }
                )
            )
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
