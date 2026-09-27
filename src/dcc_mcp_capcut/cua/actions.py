"""Typed action -> dcc-cua action translation.

The tool layer keeps emitting one typed action per call, exactly as it does for
the host bridge. This module is where a typed action becomes input delivery, and
it is the whole of the "thin" in the thin execution adapter: nothing here
decides *what* to click, only how a click the caller already named is expressed
to the driver.

Two facts from the CapCut spike shape every rule below:

1. **CapCut's UI is one opaque QML canvas.** The inventory reports a single node
   with no children, and the driver treats a missing accessibility provider as
   *permanent* for the window class. Element addressing is therefore not merely
   unavailable, it is unavailable forever, so this module **rejects** element
   selectors outright instead of emitting an action that cannot resolve.
2. **Coordinates are the addressing mode, and they are build-specific.** The
   driver maps ``x``/``y`` through the last screenshot's coordinate space; that
   space is a function of the build, the display scale and the window size. A
   coordinate is a fact about one observed frame, not a stable handle, which is
   why :func:`build_action` demands the observation space it was measured in.
"""

from __future__ import annotations

from typing import Any, Mapping

from .errors import CuaActionRejected

#: Actions that address a pixel in the captured frame.
COORDINATE_ACTIONS = ("click", "double_click", "right_click", "move", "scroll")

#: Actions that address the keyboard.
KEYBOARD_ACTIONS = ("type", "press", "hotkey")

#: Every action this adapter will translate. Deliberately closed: a new action
#: is a contract change, not a string a caller can invent at run time.
TYPED_ACTIONS = COORDINATE_ACTIONS + KEYBOARD_ACTIONS

BUTTONS = ("left", "middle", "right")
MODIFIERS = ("cmd", "shift", "option", "alt", "ctrl")

#: Fields accepted per action. A closed allow-list is what stops an unexpected
#: key from being forwarded to the driver as input the operator never named.
_ALLOWED: dict[str, tuple[str, ...]] = {
    "click": ("x", "y", "button", "count", "modifier"),
    "double_click": ("x", "y", "button", "modifier"),
    "right_click": ("x", "y", "button", "modifier"),
    "move": ("x", "y"),
    "scroll": ("x", "y", "scroll_x", "scroll_y", "by"),
    "type": ("text",),
    "press": ("key", "modifier"),
    "hotkey": ("keys", "modifier"),
}

_REQUIRED: dict[str, tuple[str, ...]] = {
    "click": ("x", "y"),
    "double_click": ("x", "y"),
    "right_click": ("x", "y"),
    "move": ("x", "y"),
    "scroll": (),
    "type": ("text",),
    "press": ("key",),
    "hotkey": ("keys",),
}


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CuaActionRejected(f"{field} must be an integer, got {value!r}")
    return value


def _check_coordinate(
    action: str, field: str, value: Any, width: int | None, height: int | None
) -> int:
    """Validate one pixel coordinate against the space it was measured in."""
    number = _as_int(value, field)
    if number < 0:
        raise CuaActionRejected(f"{action}: {field} must be non-negative, got {number}")
    limit = width if field == "x" else height
    if limit is not None and number >= limit:
        # Refusing is the whole point: a coordinate outside the captured frame
        # would land somewhere the operator never pointed at.
        raise CuaActionRejected(
            f"{action}: {field}={number} is outside the captured frame "
            f"({field} < {limit}); re-snapshot and re-measure"
        )
    return number


def _check_modifiers(action: str, value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise CuaActionRejected(f"{action}: modifier must be a string or a list of strings")
    unknown = [item for item in value if item not in MODIFIERS]
    if unknown:
        raise CuaActionRejected(
            f"{action}: unknown modifier {unknown}; expected one of {', '.join(MODIFIERS)}"
        )
    return list(value)


def build_action(
    action: str,
    params: Mapping[str, Any] | None = None,
    *,
    observation_width: int | None = None,
    observation_height: int | None = None,
) -> dict[str, Any]:
    """Translate one typed action into a dcc-cua action payload.

    ``observation_width``/``observation_height`` are the coordinate space of the
    frame the caller measured its coordinates in. Passing them is what makes a
    coordinate checkable; omitting them is allowed only for keyboard actions,
    which address no pixel.

    Raises :class:`CuaActionRejected` for anything it will not translate -- and
    it raises *before* any input is delivered, so a malformed action can never
    become a click.
    """
    if action not in TYPED_ACTIONS:
        raise CuaActionRejected(
            f"unknown typed action {action!r}; expected one of {', '.join(TYPED_ACTIONS)}"
        )
    given: Mapping[str, Any] = params or {}
    if not isinstance(given, Mapping):
        raise CuaActionRejected(f"{action}: params must be a mapping, got {type(given).__name__}")

    # Element addressing is closed for this window class -- see module docstring.
    # Checked *before* the allow-list, so a caller that reaches for an element
    # selector gets the reason it cannot work rather than a bare "unexpected
    # parameter" that invites them to go looking for another spelling.
    element_keys = {"element_index", "element_token", "element"}
    if element_keys & set(given):
        raise CuaActionRejected(
            f"{action}: element addressing is unavailable; CapCut renders as one opaque "
            "QML canvas with no accessibility provider, so address pixels instead"
        )

    unknown = sorted(set(given) - set(_ALLOWED[action]))
    if unknown:
        raise CuaActionRejected(f"{action}: unexpected parameter(s) {', '.join(unknown)}")
    missing = [field for field in _REQUIRED[action] if field not in given]
    if missing:
        raise CuaActionRejected(f"{action}: missing required parameter(s) {', '.join(missing)}")

    needs_space = action in COORDINATE_ACTIONS and action != "scroll"
    if needs_space and (observation_width is None or observation_height is None):
        raise CuaActionRejected(
            f"{action}: a coordinate action needs the observation_width/observation_height "
            "of the frame its coordinates were measured in"
        )

    payload: dict[str, Any] = {"action": action}

    for field in ("x", "y"):
        if field in given:
            payload[field] = _check_coordinate(
                action, field, given[field], observation_width, observation_height
            )

    if "button" in given:
        button = given["button"]
        if button not in BUTTONS:
            raise CuaActionRejected(
                f"{action}: unknown button {button!r}; expected one of {', '.join(BUTTONS)}"
            )
        payload["button"] = button

    if "count" in given:
        count = _as_int(given["count"], f"{action}.count")
        if not 1 <= count <= 3:
            raise CuaActionRejected(f"{action}: count must be between 1 and 3, got {count}")
        payload["count"] = count

    if "modifier" in given:
        payload["modifier"] = _check_modifiers(action, given["modifier"])

    for field in ("scroll_x", "scroll_y"):
        if field in given:
            payload[field] = _as_int(given[field], f"{action}.{field}")

    if "by" in given:
        if given["by"] not in ("line", "page"):
            raise CuaActionRejected(f"{action}: by must be 'line' or 'page', got {given['by']!r}")
        payload["by"] = given["by"]

    if "text" in given:
        text = given["text"]
        if not isinstance(text, str):
            raise CuaActionRejected(f"{action}: text must be a string, got {type(text).__name__}")
        if not text:
            raise CuaActionRejected(f"{action}: text must not be empty")
        payload["text"] = text

    if "key" in given:
        key = given["key"]
        if not isinstance(key, str) or not key.strip():
            raise CuaActionRejected(f"{action}: key must be a non-empty string")
        payload["key"] = key

    if "keys" in given:
        keys = given["keys"]
        if isinstance(keys, str):
            keys = [keys]
        if not isinstance(keys, (list, tuple)) or not keys:
            raise CuaActionRejected(f"{action}: keys must be a non-empty string or list of strings")
        for key in keys:
            if not isinstance(key, str) or not key.strip():
                raise CuaActionRejected(f"{action}: every hotkey must be a non-empty string")
        payload["keys"] = list(keys)

    return payload


__all__ = [
    "BUTTONS",
    "COORDINATE_ACTIONS",
    "KEYBOARD_ACTIONS",
    "MODIFIERS",
    "TYPED_ACTIONS",
    "build_action",
]
