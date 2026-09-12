import pytest

from dcc_mcp_capcut.bootstrap import CapCutBindingError, select_capcut_window


def test_select_capcut_window_requires_one_visible_main_window():
    binding = select_capcut_window(
        [
            {
                "app_name": "CapCut.exe",
                "pid": 42,
                "window_id": 99,
                "title": "CapCut",
                "is_on_screen": True,
                "minimized": False,
                "bounds": {"width": 1920, "height": 1080},
            },
            {
                "app_name": "CapCut.exe",
                "pid": 42,
                "window_id": 100,
                "title": "版本更新",
                "is_on_screen": False,
                "minimized": False,
                "bounds": {"width": 400, "height": 300},
            },
        ]
    )
    assert binding.pid == 42
    assert binding.window_handle == 99


def test_select_capcut_window_fails_closed_on_ambiguity():
    windows = [
        {
            "app_name": "CapCut.exe",
            "pid": pid,
            "window_id": pid + 1,
            "title": "CapCut",
            "is_on_screen": True,
            "minimized": False,
            "bounds": {"width": 1920, "height": 1080},
        }
        for pid in (42, 84)
    ]
    with pytest.raises(CapCutBindingError, match="multiple"):
        select_capcut_window(windows)
