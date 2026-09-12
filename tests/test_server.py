from dcc_mcp_capcut import CapCutMcpServer


def test_server_is_external_bridge_gui_instance():
    server = CapCutMcpServer(0)
    assert server._dcc_name == "capcut"
    assert server._options.instance_type == "gui"
    assert server.bridge.port > 0
    assert server.is_running is False


def test_server_binds_exact_capcut_host_identity():
    server = CapCutMcpServer(0, dcc_pid=31776, dcc_window_handle=452536410)
    assert server._options.diagnostics.dcc_pid == 31776
    assert server._options.diagnostics.window_handle == 452536410
    assert server._options.execution.mode.bridge is not None
