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


def test_explicit_binding_preserves_localized_dialog_title():
    windows = [
        {
            "app_name": "CapCut.exe",
            "pid": 42,
            "window_id": handle,
            "title": title,
            "is_on_screen": True,
            "minimized": False,
            "bounds": {"width": 800, "height": 600},
        }
        for handle, title in [(99, "CapCut"), (100, "推荐功能")]
    ]
    binding = select_capcut_window(windows, pid=42, window_handle=100)
    assert (binding.pid, binding.window_handle, binding.title) == (42, 100, "推荐功能")
    with pytest.raises(CapCutBindingError):
        select_capcut_window(windows, pid=43, window_handle=100)
    with pytest.raises(CapCutBindingError):
        select_capcut_window(windows, pid=42, window_handle=101)
    windows[1]["app_name"] = "Other.exe"
    with pytest.raises(CapCutBindingError):
        select_capcut_window(windows, pid=42, window_handle=100)


@pytest.mark.parametrize("pid,handle", [(42, None), (None, 100), (0, 100), (42, -1)])
def test_explicit_binding_rejects_invalid_identity(pid, handle):
    with pytest.raises(CapCutBindingError):
        select_capcut_window([], pid=pid, window_handle=handle)
