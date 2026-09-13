from dcc_mcp_core import skill_entry, skill_success

from dcc_mcp_capcut.qt_probe import inspect_qt_host


@skill_entry
def main():
    return skill_success("Read native Qt probe identity.", **inspect_qt_host())
