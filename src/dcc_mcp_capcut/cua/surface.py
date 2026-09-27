"""The pixel execution surface: bind, snapshot, deliver input, verify.

This is the layer the roadmap item actually asks for -- the translation of one
typed action into the four-step loop that is all a pixel-grade target allows:

    exact PID/HWND binding -> pixel snapshot -> coordinate input -> verify

Each step is a separate call because each can fail independently, and the
failure has to be attributable: "the binding went stale" and "the click landed
but nothing changed" are different bugs with different fixes.

The verify step is where this layer earns its keep. The driver evaluates bounded
predicates and reports each as ``satisfied``, ``unsatisfied`` or ``unknown``.
**``unknown`` is not success, and this layer never lets it become one.** On a
target with no accessibility tree almost every element predicate is unknown, so
a caller that treated unknown as a pass would record confident successes for
state it never observed. A pixel difference is carried alongside the verdict as
*evidence* that the window changed -- never as proof that the intended state was
reached, because a dialog appearing and the requested edit landing look
identical from a pixel digest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..bootstrap import CapCutBindingError, select_capcut_window
from ..hosts import LINUX, get_provider
from . import cli
from .actions import build_action
from .errors import (
    CuaActionRejected,
    CuaBindingError,
    CuaDeliveryError,
    CuaUnsupportedPlatform,
    CuaVerificationError,
)

#: Predicate verdicts the driver can return. Anything else is treated as
#: unknown, because a verdict this layer does not recognise is not one it may
#: count as satisfied.
SATISFIED = "satisfied"
UNSATISFIED = "unsatisfied"
UNKNOWN = "unknown"

#: Expectations this layer will translate into driver predicates.
EXPECTATION_KEYS = ("window_exists", "window_bounds", "element_exists")

#: The most predicates the driver accepts in one verify call. Enforced on the
#: *expanded* list -- see :func:`build_expectations`.
MAX_PREDICATES = 8


@dataclass(frozen=True)
class CuaBinding:
    """One exact, live CapCut window.

    ``pid`` and ``window_handle`` are the pair every driver call takes: the
    driver refuses to act on a window it was not pointed at, which is what keeps
    a stale id from clicking into whatever CapCut window now occupies it.
    """

    pid: int
    window_handle: int
    title: str = ""
    app_name: str = ""
    bounds: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "window_handle": self.window_handle,
            "title": self.title,
            "app_name": self.app_name,
            "bounds": dict(self.bounds),
        }


@dataclass(frozen=True)
class CuaSnapshot:
    """One pixel capture of one exact window, with the space its pixels live in.

    ``observation_width``/``observation_height`` are the encoded PNG dimensions.
    They are the coordinate space both for input and for the operator's own
    measurements, and every coordinate action must be validated against them.
    """

    binding: CuaBinding
    observation_width: int = 0
    observation_height: int = 0
    image_path: str | None = None
    #: A digest of the pixels, so two captures can be compared for change
    #: without keeping either image in memory.
    content_digest: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def coordinate_space(self) -> tuple[int, int]:
        return (self.observation_width, self.observation_height)

    def as_dict(self) -> dict[str, Any]:
        return {
            "observation_width": self.observation_width,
            "observation_height": self.observation_height,
            "image_path": self.image_path,
            "content_digest": self.content_digest,
        }

    def to_screen(self, x: int, y: int) -> tuple[float, float]:
        """Map a pixel in this capture onto virtual-desktop coordinates.

        The driver maps input back the other way, but an operator reading a
        receipt needs to know *where* a click landed in terms they can point at.
        ``bounds`` is already in device pixels, so no display scale factor is
        applied -- the driver documents that applying one is wrong.
        """
        width = int(self.binding.bounds.get("width", 0) or 0)
        height = int(self.binding.bounds.get("height", 0) or 0)
        if not self.observation_width or not self.observation_height or not (width and height):
            return (float(x), float(y))
        origin_x = float(self.binding.bounds.get("x", 0) or 0)
        origin_y = float(self.binding.bounds.get("y", 0) or 0)
        return (
            origin_x + x * width / self.observation_width,
            origin_y + y * height / self.observation_height,
        )


@dataclass(frozen=True)
class CuaVerification:
    """The outcome of proving -- or failing to prove -- the final state."""

    ok: bool
    predicates: tuple[dict[str, Any], ...] = ()
    #: Names of predicates the driver could not evaluate. Carried separately so
    #: a receipt says "unproven" instead of the weaker "not ok".
    unknown: tuple[str, ...] = ()
    unsatisfied: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def proven(self) -> bool:
        """True only when every predicate was evaluated and satisfied."""
        return self.ok and not self.unknown

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "proven": self.proven,
            "predicates": [dict(item) for item in self.predicates],
            "unknown": list(self.unknown),
            "unsatisfied": list(self.unsatisfied),
        }


def require_interactive_platform() -> None:
    """Refuse to start on a platform that has no interactive-desktop route.

    Linux fails twice over: ByteDance publishes no desktop client for it, and CI
    runners have no interactive desktop. Stating both is better than letting a
    run get as far as a driver timeout and reporting that instead.
    """
    provider = get_provider()
    if provider.name == LINUX:
        raise CuaUnsupportedPlatform(
            f"pixel execution is unsupported on {provider.label}: {provider.unsupported_reason}. "
            "Unattended means unattended on an interactive Windows or macOS desktop; "
            "Linux CI is not in scope."
        )


def list_windows(*, timeout: float = cli.DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    """Read the read-only window inventory."""
    payload = cli.run_json(cli.list_args(), timeout=timeout)
    windows = payload.get("windows")
    if not isinstance(windows, list):
        # The CLI emits a bare array, but accept both shapes rather than depend
        # on which version happens to be installed.
        windows = payload if isinstance(payload, list) else None
    if not isinstance(windows, list):
        raise CuaBindingError("dcc-cua returned a window inventory that is not a list")
    return [dict(window) for window in windows]


def bind(
    *,
    pid: int | None = None,
    window_handle: int | None = None,
    timeout: float = cli.DEFAULT_TIMEOUT,
) -> CuaBinding:
    """Establish the exact PID/HWND pair every later call is scoped to.

    Selection is delegated to :func:`~dcc_mcp_capcut.bootstrap.select_capcut_window`
    so this layer cannot drift from the adapter's one definition of "exactly one
    visible CapCut main window": ambiguity stays an error rather than becoming a
    guess, and the flavour matching stays owned by the platform provider.
    """
    require_interactive_platform()
    windows = list_windows(timeout=timeout)
    try:
        selected = select_capcut_window(windows, pid=pid, window_handle=window_handle)
    except CapCutBindingError as error:
        raise CuaBindingError(str(error)) from error

    match = next(
        (
            window
            for window in windows
            if int(window.get("pid", 0) or 0) == selected.pid
            and int(window.get("window_id", 0) or 0) == selected.window_handle
        ),
        None,
    )
    bounds = match.get("bounds") if isinstance(match, dict) else None
    return CuaBinding(
        pid=selected.pid,
        window_handle=selected.window_handle,
        title=selected.title,
        app_name=str((match or {}).get("app_name", "") or ""),
        bounds=dict(bounds) if isinstance(bounds, dict) else {},
    )


def rebind(binding: CuaBinding, *, timeout: float = cli.DEFAULT_TIMEOUT) -> CuaBinding:
    """Re-resolve a binding against the live inventory.

    CapCut upgrades itself in place and can delete the install tree it was
    launched from, so a PID that was exact a minute ago may now name a different
    process. Rebinding by the *same* ids proves the window still exists rather
    than silently accepting a recycled PID.
    """
    return bind(pid=binding.pid, window_handle=binding.window_handle, timeout=timeout)


def snapshot(
    binding: CuaBinding,
    *,
    output: str | None = None,
    timeout: float = cli.DEFAULT_TIMEOUT,
) -> CuaSnapshot:
    """Capture the bound window's pixels and the space they live in."""
    payload = cli.run_json(
        cli.snapshot_args(pid=binding.pid, window_handle=binding.window_handle, output=output),
        timeout=timeout,
    )
    space = payload.get("coordinate_space")
    if not isinstance(space, dict):
        space = payload.get("bounds") if isinstance(payload.get("bounds"), dict) else {}
    width = int(space.get("width", 0) or 0)
    height = int(space.get("height", 0) or 0)
    image = payload.get("image") or payload.get("screenshot") or payload.get("png")
    path = payload.get("output") or payload.get("image_path") or output
    # Try the inline pixels first and fall back to the file the driver wrote,
    # so change detection works whichever shape the driver returns.
    digest = _digest(payload.get("image_base64") or payload.get("base64") or image)
    if digest is None and path:
        digest = _digest_file(path)
    return CuaSnapshot(
        binding=binding,
        observation_width=width,
        observation_height=height,
        image_path=str(path) if path else None,
        content_digest=digest,
        raw=payload,
    )


def _digest(payload: Any) -> str | None:
    """A stable digest of the pixels, for change detection between captures.

    Accepts either shape the driver may return: the pixels inline, or a path to
    the file it wrote. Change detection is advertised as a real signal, so it
    must not silently go dark just because the driver chose the other shape --
    and an unreadable file degrades to None the same way a missing inline field
    does, which the caller already reports honestly.
    """
    if payload is None:
        return None
    if isinstance(payload, bytes):
        return hashlib.sha256(payload).hexdigest()
    if isinstance(payload, str):
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _digest_file(path: str | Path) -> str | None:
    """Hash the pixels a driver wrote to disk, for change detection.

    Some responses carry only a path instead of inline bytes. An unreadable or
    absent file yields None -- the same fact as a missing inline field, which the
    caller already reports honestly rather than inferring "nothing changed".
    """
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except (OSError, ValueError):
        return None


def act(
    binding: CuaBinding,
    action: str,
    params: Mapping[str, Any] | None = None,
    *,
    observation: CuaSnapshot | None = None,
    delivery_mode: str = "background",
    allow_foreground: bool = True,
    timeout: float = cli.DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Deliver one typed action to the bound window.

    The driver's contract is that ``background`` is the **mandatory first
    attempt**: fronting a window steals the operator's focus, and only the
    driver knows when background delivery is impossible for a given target. So
    this function always tries background first and escalates to foreground
    *only* when the driver answers ``background_unavailable``.

    ``observation`` is the frame the coordinates were measured in. It is
    required for coordinate actions: an act against a stale or unstated frame is
    a click at a place the caller never looked.
    """
    if delivery_mode not in ("background", "foreground"):
        raise CuaActionRejected(
            f"delivery_mode must be 'background' or 'foreground', got {delivery_mode!r}"
        )
    space = observation.coordinate_space if observation is not None else (None, None)
    payload = build_action(
        action,
        params,
        observation_width=space[0],
        observation_height=space[1],
    )
    payload["pid"] = binding.pid
    payload["window_id"] = binding.window_handle
    payload["delivery_mode"] = delivery_mode

    attempts = [delivery_mode]
    if allow_foreground and delivery_mode == "background":
        # Escalation is the driver's call, so it is queued here but only spent
        # if the first attempt comes back background_unavailable.
        attempts.append("foreground")

    for index, mode in enumerate(attempts):
        payload["delivery_mode"] = mode
        try:
            result = cli.run_json(
                cli.act_args(
                    pid=binding.pid,
                    window_handle=binding.window_handle,
                    action_json=json.dumps(payload),
                    observation_width=space[0],
                    observation_height=space[1],
                ),
                timeout=timeout,
            )
        except Exception as error:  # noqa: BLE001 - re-raised below, never swallowed
            # Escalate only on the driver's own say-so, only from a background
            # attempt, and only when escalation is actually permitted -- the
            # operator may have forbidden fronting a window outright, in which
            # case there is no route left and this fails with its cause intact.
            if (
                getattr(error, "code", None) == "background_unavailable"
                and index == 0
                and allow_foreground
            ):
                continue
            # One exception type for "the input did not land", whatever the
            # driver's reason. The original is chained, not flattened, so a
            # caller that needs the driver's code still has it on __cause__.
            raise CuaDeliveryError(f"input was not delivered: {error}") from error
        return {
            "action": action,
            "params": {key: value for key, value in payload.items() if key != "pid"},
            "delivery_mode": mode,
            "escalated": mode == "foreground" and index > 0,
            "result": result,
        }
    raise CuaDeliveryError("input was not delivered: no delivery mode was attempted")


# --- verification ----------------------------------------------------------


def _window_predicate(expectation: Mapping[str, Any]) -> dict[str, Any] | None:
    """Translate the window-shape half of one expectation."""
    predicate: dict[str, Any] = {}
    if "window_exists" in expectation:
        exists = expectation["window_exists"]
        if not isinstance(exists, bool):
            raise CuaActionRejected("window_exists must be a boolean")
        if exists is not True:
            # The driver cannot prove absence either, so asking for it would
            # produce an unknown that this layer would then have to fail on.
            raise CuaActionRejected(
                "window_exists=false cannot be verified; assert a positive expectation instead"
            )
        predicate["exists"] = True
    if "window_bounds" in expectation:
        bounds = expectation["window_bounds"]
        if not isinstance(bounds, Mapping):
            raise CuaActionRejected("window_bounds must be a mapping")
        missing = [key for key in ("x", "y", "width", "height") if key not in bounds]
        if missing:
            raise CuaActionRejected(f"window_bounds is missing {', '.join(missing)}")
        shape: dict[str, Any] = {key: int(bounds[key]) for key in ("x", "y", "width", "height")}
        tolerance = bounds.get("tolerance_px", 0)
        shape["tolerance_px"] = max(0, min(100, int(tolerance)))
        predicate["bounds"] = shape
    return {"window": predicate} if predicate else None


def _element_predicate(expectation: Mapping[str, Any]) -> dict[str, Any] | None:
    """Translate the element half of one expectation.

    Accepted for completeness -- a target that *does* expose a tree can be
    verified semantically -- but on CapCut these predicates come back unknown and
    fail closed, which is the honest outcome rather than a silent skip.
    """
    element = expectation.get("element_exists")
    if element is None:
        return None
    if isinstance(element, str):
        element = {"label_contains": element}
    if not isinstance(element, Mapping):
        raise CuaActionRejected("element_exists must be a mapping or a label string")
    selector = {key: element[key] for key in ("role", "label_contains") if key in element}
    if not selector:
        raise CuaActionRejected("element_exists needs a role or label_contains selector")
    predicate: dict[str, Any] = {"selector": selector, "exists": True}
    for key in ("enabled", "selected", "value_equals"):
        if key in element:
            predicate[key] = element[key]
    return {"element": predicate}


def build_expectations(expectations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Translate adapter expectations into driver predicates."""
    if not expectations:
        raise CuaActionRejected("verification needs at least one expectation")

    predicates: list[dict[str, Any]] = []
    for expectation in expectations:
        if not isinstance(expectation, Mapping):
            raise CuaActionRejected("each expectation must be a mapping")
        unsupported = sorted(set(expectation) - set(EXPECTATION_KEYS))
        if unsupported:
            raise CuaActionRejected(
                f"unsupported expectation(s) {', '.join(unsupported)}; "
                f"expected one of {', '.join(EXPECTATION_KEYS)}"
            )
        for translate in (_window_predicate, _element_predicate):
            predicate = translate(expectation)
            if predicate is not None:
                predicates.append(predicate)
    if not predicates:
        raise CuaActionRejected("no verifiable expectation was supplied")
    # Count predicates, not expectations. One expectation can expand into two --
    # a window predicate and an element predicate -- so capping the input would
    # still hand the driver more than it accepts, and silently truncating an
    # operator's expectations would verify less than was asked.
    if len(predicates) > MAX_PREDICATES:
        raise CuaActionRejected(
            f"these expectations expand to {len(predicates)} predicates; at most "
            f"{MAX_PREDICATES} are supported per verify call"
        )
    return predicates


def verify(
    binding: CuaBinding,
    expectations: Sequence[Mapping[str, Any]],
    *,
    timeout_ms: int | None = None,
    stable_samples: int | None = None,
    timeout: float = cli.DEFAULT_TIMEOUT,
) -> CuaVerification:
    """Prove the final state, or fail closed saying it could not be proven.

    Returns a :class:`CuaVerification` whose ``ok`` is true only when *every*
    predicate came back ``satisfied``. Raises :class:`CuaVerificationError` when
    any predicate was ``unsatisfied`` or ``unknown``, because a caller that
    never sees a failure cannot be expected to handle one -- and an unverified
    click reported as success is worse than a refused one.
    """
    predicates = build_expectations(expectations)
    payload = cli.run_json(
        cli.verify_args(
            pid=binding.pid,
            window_handle=binding.window_handle,
            expect_json=json.dumps({"expect": predicates}),
            timeout_ms=timeout_ms,
            stable_samples=stable_samples,
        ),
        timeout=timeout,
    )
    results = payload.get("results")
    if not isinstance(results, list):
        results = payload.get("predicates") if isinstance(payload.get("predicates"), list) else []
    if not results:
        raise CuaVerificationError(
            "dcc-cua returned no predicate results; the final state is unproven"
        )
    # A verdict count that does not match the predicates sent is a driver that
    # evaluated less than was asked -- most likely by silently truncating. Those
    # missing predicates never reach the unknown list, so without this check a
    # partly-evaluated verify reports itself fully proven: "unobserved"
    # laundered into "proven", which is the one thing this layer exists to
    # prevent. The input-side cap is only half the guard; this is the other half.
    if len(results) != len(predicates):
        raise CuaVerificationError(
            f"dcc-cua evaluated {len(results)} of {len(predicates)} predicates; "
            f"{len(predicates) - len(results)} were never evaluated, so the final "
            "state is unproven"
        )

    verdicts: list[dict[str, Any]] = []
    unknown: list[str] = []
    unsatisfied: list[str] = []
    for index, result in enumerate(results):
        if not isinstance(result, Mapping):
            verdicts.append({"index": index, "status": UNKNOWN})
            unknown.append(f"#{index}")
            continue
        status = str(result.get("status") or result.get("result") or UNKNOWN).casefold()
        name = str(result.get("name") or result.get("predicate") or f"#{index}")
        if status not in (SATISFIED, UNSATISFIED):
            status = UNKNOWN
        verdicts.append({"index": index, "name": name, "status": status})
        if status == UNSATISFIED:
            unsatisfied.append(name)
        elif status == UNKNOWN:
            unknown.append(name)

    ok = not unsatisfied and not unknown
    verification = CuaVerification(
        ok=ok,
        predicates=tuple(verdicts),
        unknown=tuple(unknown),
        unsatisfied=tuple(unsatisfied),
        raw=payload,
    )
    if not ok:
        raise CuaVerificationError(
            "the final state could not be verified: "
            + "; ".join(
                part
                for part in (
                    f"unsatisfied: {', '.join(unsatisfied)}" if unsatisfied else "",
                    f"unknown: {', '.join(unknown)}" if unknown else "",
                )
                if part
            )
        )
    return verification


__all__ = [
    "EXPECTATION_KEYS",
    "SATISFIED",
    "UNSATISFIED",
    "UNKNOWN",
    "CuaBinding",
    "CuaSnapshot",
    "CuaVerification",
    "act",
    "bind",
    "build_expectations",
    "list_windows",
    "rebind",
    "require_interactive_platform",
    "snapshot",
    "verify",
]
