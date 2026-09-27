"""Typed action translation: the tool layer's vocabulary becomes driver input.

These tests are pure -- no driver, no platform -- because everything they cover
happens before a single byte reaches ``dcc-cua``. That is the point of the
module: an action this layer will not translate must be refused here rather than
becoming a click the operator did not ask for.
"""

from __future__ import annotations

import pytest

from dcc_mcp_capcut.cua.actions import (
    BUTTONS,
    COORDINATE_ACTIONS,
    KEYBOARD_ACTIONS,
    TYPED_ACTIONS,
    build_action,
)
from dcc_mcp_capcut.cua.errors import CuaActionRejected

#: A frame big enough that the boundary cases sit inside it.
SPACE = {"observation_width": 1920, "observation_height": 1080}


def test_every_action_is_either_coordinate_or_keyboard():
    """The two families partition the closed action set; nothing floats free."""
    assert set(TYPED_ACTIONS) == set(COORDINATE_ACTIONS) | set(KEYBOARD_ACTIONS)
    assert not set(COORDINATE_ACTIONS) & set(KEYBOARD_ACTIONS)


@pytest.mark.parametrize("action", ["click", "double_click", "right_click", "move"])
def test_a_coordinate_action_carries_its_coordinates(action):
    payload = build_action(action, {"x": 640, "y": 360}, **SPACE)
    assert payload == {"action": action, "x": 640, "y": 360}


def test_click_accepts_its_optional_shape():
    payload = build_action("click", {"x": 1, "y": 2, "button": "right", "count": 2}, **SPACE)
    assert payload["button"] == "right"
    assert payload["count"] == 2


@pytest.mark.parametrize("action", ["click", "double_click", "right_click", "move"])
def test_a_coordinate_action_needs_the_space_it_was_measured_in(action):
    """Coordinates are a fact about one frame; without it they are a guess."""
    with pytest.raises(CuaActionRejected, match="observation_width"):
        build_action(action, {"x": 640, "y": 360})


def test_coordinates_are_rejected_outside_the_captured_frame():
    """A pixel outside the frame would land somewhere nobody pointed at."""
    with pytest.raises(CuaActionRejected, match="outside the captured frame"):
        build_action("click", {"x": 1920, "y": 10}, **SPACE)
    with pytest.raises(CuaActionRejected, match="outside the captured frame"):
        build_action("click", {"x": 10, "y": 1080}, **SPACE)


def test_negative_coordinates_are_rejected():
    with pytest.raises(CuaActionRejected, match="non-negative"):
        build_action("click", {"x": -1, "y": 10}, **SPACE)


def test_non_integer_coordinates_are_rejected():
    with pytest.raises(CuaActionRejected, match="must be an integer"):
        build_action("click", {"x": 10.5, "y": 10}, **SPACE)


@pytest.mark.parametrize("action", ["click", "double_click", "right_click"])
def test_missing_coordinates_are_rejected(action):
    with pytest.raises(CuaActionRejected, match="missing required"):
        build_action(action, {"x": 10}, **SPACE)


def test_unknown_actions_are_refused_rather_than_forwarded():
    with pytest.raises(CuaActionRejected, match="unknown typed action"):
        build_action("shell_out", {})


def test_unexpected_parameters_are_refused():
    """A closed allow-list, so no stray key reaches the driver as input."""
    with pytest.raises(CuaActionRejected, match="unexpected parameter"):
        build_action("click", {"x": 1, "y": 2, "exec": "rm -rf /"}, **SPACE)


def test_unknown_buttons_are_refused():
    with pytest.raises(CuaActionRejected, match="unknown button"):
        build_action("click", {"x": 1, "y": 2, "button": "fourth"}, **SPACE)


def test_click_count_is_bounded():
    with pytest.raises(CuaActionRejected, match="between 1 and 3"):
        build_action("click", {"x": 1, "y": 2, "count": 9}, **SPACE)


def test_keyboard_actions_need_no_coordinate_space():
    """Text and keys address no pixel, so a frame is not required for them."""
    assert build_action("type", {"text": "hello"}) == {"action": "type", "text": "hello"}
    assert build_action("press", {"key": "enter"}) == {"action": "press", "key": "enter"}


def test_hotkey_accepts_one_key_or_many():
    assert build_action("hotkey", {"keys": "ctrl"})["keys"] == ["ctrl"]
    assert build_action("hotkey", {"keys": ["ctrl", "s"]})["keys"] == ["ctrl", "s"]


def test_empty_text_and_keys_are_refused():
    """Empty input is a bug, not a no-op worth delivering."""
    with pytest.raises(CuaActionRejected, match="must not be empty"):
        build_action("type", {"text": ""})
    with pytest.raises(CuaActionRejected, match="non-empty"):
        build_action("hotkey", {"keys": []})


def test_modifiers_are_validated_and_normalised():
    payload = build_action("press", {"key": "s", "modifier": "ctrl"}, **SPACE)
    assert payload["modifier"] == ["ctrl"]
    with pytest.raises(CuaActionRejected, match="unknown modifier"):
        build_action("press", {"key": "s", "modifier": "hyper"}, **SPACE)


def test_scroll_accepts_deltas_and_units():
    payload = build_action("scroll", {"x": 10, "y": 20, "scroll_y": -3, "by": "page"}, **SPACE)
    assert payload["scroll_y"] == -3
    assert payload["by"] == "page"


@pytest.mark.parametrize("action", COORDINATE_ACTIONS)
def test_element_addressing_is_refused_for_every_coordinate_action(action):
    """CapCut renders one opaque QML canvas, so element addressing is closed.

    This is permanent for the window class, not a transient miss: the driver
    says so and the spike measured ``node_count=1``. Translating an element
    selector anyway would emit an action that can never resolve.
    """
    with pytest.raises(CuaActionRejected, match="opaque"):
        build_action(action, {"x": 1, "y": 2, "element_index": 3}, **SPACE)


def test_params_must_be_a_mapping():
    with pytest.raises(CuaActionRejected, match="must be a mapping"):
        build_action("click", ["x", "y"], **SPACE)


def test_every_button_is_a_real_mouse_button():
    assert set(BUTTONS) == {"left", "middle", "right"}


def test_scroll_without_coordinates_still_needs_no_space():
    """Scroll is coordinate-ish, but a window-wide scroll has no target pixel."""
    payload = build_action("scroll", {"scroll_y": 5})
    assert payload["scroll_y"] == 5


def test_scroll_with_coordinates_needs_the_frame_like_any_other_pixel():
    """The invariant tracks addressing a pixel, not the action's name.

    A window-wide scroll names no pixel; the moment it carries x/y it is
    addressing one, and must be measured against the frame like a click is.
    """
    with pytest.raises(CuaActionRejected, match="observation_width"):
        build_action("scroll", {"x": 5000, "y": 5000})
    with pytest.raises(CuaActionRejected, match="observation_width"):
        build_action("scroll", {"x": 1})


def test_a_window_wide_scroll_still_needs_no_frame():
    """No coordinates, no pixel to validate -- the original intent holds."""
    assert build_action("scroll", {"scroll_y": 5}) == {"action": "scroll", "scroll_y": 5}
    assert build_action("scroll", {"scroll_x": 1, "scroll_y": 2, "by": "line"})["by"] == "line"


@pytest.mark.parametrize("action", ["click", "move", "right_click", "double_click", "scroll"])
def test_coordinates_are_checked_inside_the_frame_for_every_pixel_action(action):
    """No coordinate action, scroll included, may name a pixel outside the frame."""
    with pytest.raises(CuaActionRejected, match="outside the captured frame"):
        build_action(action, {"x": 1920, "y": 10}, **SPACE)
