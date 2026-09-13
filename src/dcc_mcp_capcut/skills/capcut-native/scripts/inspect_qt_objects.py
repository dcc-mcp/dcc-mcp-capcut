from dcc_mcp_core import skill_entry, skill_success

from dcc_mcp_capcut.qt_probe import inspect_qt_host


@skill_entry
def main(max_nodes=500, max_depth=8):
    return skill_success(
        "Read native Qt object metadata.",
        **inspect_qt_host(operation="qt.inspect", max_nodes=max_nodes, max_depth=max_depth),
    )
