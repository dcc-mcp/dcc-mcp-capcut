import pytest

from dcc_mcp_capcut.bootstrap import CapCutBindingError, select_capcut_window


def test_select_capcut_window_requires_one_visible_main_window(pin_platform):
    pin_platform("windows")
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


def test_select_capcut_window_fails_closed_on_ambiguity(pin_platform):
    pin_platform("windows")
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


def test_explicit_binding_preserves_localized_dialog_title(pin_platform):
    pin_platform("windows")
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
def test_explicit_binding_rejects_invalid_identity(pin_platform, pid, handle):
    pin_platform("windows")
    with pytest.raises(CapCutBindingError):
        select_capcut_window([], pid=pid, window_handle=handle)


def test_select_capcut_window_binds_jianyingpro_main_window(pin_platform):
    """剪映专业版 (JianyingPro) is bindable: its titles are localised, so the
    executable name is the discriminator rather than a pinned window title."""
    pin_platform("windows")
    binding = select_capcut_window(
        [
            {
                "app_name": "JianyingPro.exe",
                "pid": 77,
                "window_id": 1234,
                "title": "剪映专业版",
                "is_on_screen": True,
                "minimized": False,
                "bounds": {"width": 1920, "height": 1080},
            }
        ]
    )
    assert binding.pid == 77
    assert binding.window_handle == 1234


def test_select_capcut_window_ignores_unrelated_processes(pin_platform):
    """Only ByteDance editor executables are ever bound."""
    pin_platform("windows")
    with pytest.raises(CapCutBindingError, match="no visible"):
        select_capcut_window(
            [
                {
                    "app_name": "explorer.exe",
                    "pid": 7,
                    "window_id": 8,
                    "title": "CapCut",
                    "is_on_screen": True,
                    "minimized": False,
                    "bounds": {"width": 1920, "height": 1080},
                }
            ]
        )


def test_select_capcut_window_binds_a_macos_bundle_process(pin_platform):
    """macOS inventory reports bundle names, not ``.exe`` names.

    The same selection rules apply -- one visible, restored main window -- but
    the flavour is matched on ``CapCut`` / ``剪映专业版`` rather than on a
    Windows executable name.
    """
    pin_platform("macos")
    binding = select_capcut_window(
        [
            {
                "app_name": "CapCut",
                "pid": 512,
                "window_id": 4096,
                "title": "CapCut",
                "is_on_screen": True,
                "minimized": False,
                "bounds": {"width": 1728, "height": 1117},
            }
        ]
    )
    assert (binding.pid, binding.window_handle) == (512, 4096)

    jianying = select_capcut_window(
        [
            {
                "app_name": "剪映专业版",
                "pid": 513,
                "window_id": 4097,
                "title": "剪映专业版",
                "is_on_screen": True,
                "minimized": False,
                "bounds": {"width": 1728, "height": 1117},
            }
        ]
    )
    assert (jianying.pid, jianying.window_handle) == (513, 4097)


def test_macos_inventory_never_matches_a_windows_executable_name(pin_platform):
    """A Windows-shaped name is not evidence of a macOS editor process."""
    pin_platform("macos")
    with pytest.raises(CapCutBindingError, match="no visible"):
        select_capcut_window(
            [
                {
                    "app_name": "CapCut.exe",
                    "pid": 42,
                    "window_id": 99,
                    "title": "CapCut",
                    "is_on_screen": True,
                    "minimized": False,
                    "bounds": {"width": 1920, "height": 1080},
                }
            ]
        )
