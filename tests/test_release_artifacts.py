import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

_PATH = Path(__file__).parents[1] / "tools" / "build_panel_archive.py"
_SPEC = importlib.util.spec_from_file_location("build_panel_archive", _PATH)
assert _SPEC and _SPEC.loader
build_panel_archive = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_panel_archive)

FILES = build_panel_archive.FILES
build = build_panel_archive.build


def test_panel_archive_is_deterministic_and_versioned(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    build(first, "0.1.0")
    build(second, "0.1.0")

    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest == {
            "adapter": "capcut",
            "version": "0.1.0",
            "files": list(FILES),
        }
        assert set(archive.namelist()) == {
            "manifest.json",
            *(f"panel/{name}" for name in FILES),
        }
