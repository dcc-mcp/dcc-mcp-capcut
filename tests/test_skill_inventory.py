from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1] / "src" / "dcc_mcp_capcut" / "skills"


def test_all_declared_skill_sources_exist():
    expected = {
        "inspect_project",
        "create_project",
        "save_project",
        "import_media",
        "create_timeline",
        "add_clip",
        "add_text",
        "auto_captions",
        "add_audio",
        "apply_effect",
        "export_video",
        "build_vlog_demo",
        "remove_background",
        "auto_setup_capcut",
        "import_subtitles",
    }
    found = set()
    for tools_file in ROOT.glob("*/tools.yaml"):
        assert (tools_file.parent / "SKILL.md").exists()
        data = yaml.safe_load(tools_file.read_text(encoding="utf-8"))
        for tool in data.get("tools", []):
            found.add(tool["name"])
            assert (tools_file.parent / tool["source_file"]).exists()
    assert expected <= found
