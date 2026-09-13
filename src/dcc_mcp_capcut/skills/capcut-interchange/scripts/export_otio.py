from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.interchange import export_otio


@skill_entry
def main(timeline: dict):
    return skill_success(
        "Portable OTIO created from supplied edit decisions.", **export_otio(timeline)
    )
