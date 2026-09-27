"""Error taxonomy for the dcc-cua execution adapter.

Every failure this layer raises carries a stable ``code`` so a caller can branch
on the failure instead of parsing prose. Codes fall into two families, and
keeping them visually distinct is the point:

``cua_*``
    Invented here: the adapter could not even reach the driver, or it refused a
    request before handing it over.
bare ``snake_case``
    The driver's own vocabulary, reproduced verbatim from the ``dcc-cua`` error
    envelope. A caller that already knows ``dcc-cua`` knows these.

The driver reports a window-class fact that a caller must never retry:
``no_accessibility_provider`` is **permanent** for the whole window class, not a
transient miss. CapCut's UI is one opaque QML canvas, so retrying the semantic
tree -- or silently falling back to it -- would burn real time on a route the
driver has already closed. :attr:`CuaError.permanent` marks that class of error
so the adapter can refuse to retry instead of hoping.
"""

from __future__ import annotations


class CuaError(RuntimeError):
    """Base class for every failure raised by the execution adapter.

    The message is operator-facing and safe to surface; it is truncated by the
    caller that builds it so a driver message can never smuggle host text, a
    path the operator did not ask about, or a credential into an operator log.
    """

    code = "cua_error"

    #: True when retrying -- or retrying by another route -- cannot help. A
    #: caller must surface a permanent error, never paper over it.
    permanent = False

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def as_dict(self) -> dict[str, object]:
        """A JSON-serialisable copy, for receipts and the doctor."""
        return {"code": self.code, "message": str(self), "permanent": self.permanent}


class CuaUnavailable(CuaError):
    """The ``dcc-cua`` CLI is not installed or not resolvable on PATH."""

    code = "cua_unavailable"


class CuaUnsupportedPlatform(CuaError):
    """No interactive-desktop execution route exists on this platform.

    Linux carries this verdict twice over: ByteDance publishes no desktop
    client, and CI runners have no interactive desktop to drive. Both are
    reasons to say so up front rather than to attempt a run and fail later.
    """

    code = "cua_unsupported_platform"
    permanent = True


class CuaBindingError(CuaError):
    """No exact, live PID/HWND pair could be established or revalidated."""

    code = "cua_binding_error"


class CuaDesktopUnavailable(CuaError):
    """The driver has no interactive desktop session to drive.

    This is the honest shape of the "not headless" boundary. Unattended means
    unattended *on an interactive Windows or macOS desktop*; a locked workstation
    or a Linux CI runner is not that, and is reported as such rather than as a
    generic failure.
    """

    code = "interactive_desktop_unavailable"


class CuaActionRejected(CuaError):
    """The adapter refused to translate a typed action.

    Raised before any input is delivered, so a malformed action can never
    become a click the operator did not ask for.
    """

    code = "cua_action_rejected"


class CuaBackgroundUnavailable(CuaError):
    """Background input delivery cannot work for this target.

    The driver's contract is that ``background`` is the mandatory first attempt
    and that only the driver may say it is impossible. This error is therefore
    the one signal that justifies escalating to ``foreground`` -- a caller must
    never front a window pre-emptively on a guess about the target's toolkit.
    """

    code = "background_unavailable"


class CuaDeliveryError(CuaError):
    """Input was not delivered by either delivery mode."""

    code = "cua_delivery_error"


class CuaVerificationError(CuaError):
    """The final state could not be proven.

    Raised when a predicate came back ``unsatisfied`` *or* ``unknown``. The two
    are different facts and both are failures: a predicate the driver could not
    evaluate is not a predicate that passed, and reporting otherwise is how an
    unverified click gets recorded as a completed edit.
    """

    code = "cua_verification_error"


class CuaNoAccessibility(CuaError):
    """The window exposes no accessibility provider, permanently.

    The semantic route is closed for this window class, so automation is
    pixel-and-coordinate grade and must be built and maintained as such.
    """

    code = "no_accessibility_provider"
    permanent = True


#: Driver error codes mapped onto this taxonomy. Unlisted codes fall through to
#: :class:`CuaError` with the driver's own code attached, so a new driver
#: release degrades into an unclassified-but-named failure instead of a bare
#: ``RuntimeError``.
DRIVER_CODE_ERRORS: dict[str, type[CuaError]] = {
    "interactive_desktop_unavailable": CuaDesktopUnavailable,
    "no_window_target": CuaBindingError,
    "window_target_mismatch": CuaBindingError,
    "target_minimized": CuaBindingError,
    "target_unavailable": CuaBindingError,
    "stale_observation": CuaBindingError,
    "fresh_observation_required": CuaBindingError,
    "background_unavailable": CuaBackgroundUnavailable,
    "no_accessibility_provider": CuaNoAccessibility,
    "element_not_found": CuaActionRejected,
    "element_not_found_on_click": CuaActionRejected,
}


def classify(code: str | None, message: str) -> CuaError:
    """Turn one driver error envelope into the matching exception.

    The code is preserved on the instance even when several codes share a class,
    because "no window target" and "stale observation" are the same *severity*
    and different *remediations*.
    """
    if not code:
        return CuaError(message)
    error_class = DRIVER_CODE_ERRORS.get(code, CuaError)
    return error_class(message, code=code)


__all__ = [
    "DRIVER_CODE_ERRORS",
    "CuaActionRejected",
    "CuaBackgroundUnavailable",
    "CuaBindingError",
    "CuaDeliveryError",
    "CuaDesktopUnavailable",
    "CuaError",
    "CuaNoAccessibility",
    "CuaUnavailable",
    "CuaUnsupportedPlatform",
    "CuaVerificationError",
    "classify",
]
