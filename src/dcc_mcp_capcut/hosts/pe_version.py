"""Read a Windows PE version resource using the standard library only.

Windows is CapCut's primary platform and the one the acceptance record in
:mod:`dcc_mcp_capcut.hosts.versions` was measured on, but discovery used to
resolve no more than an ``.exe`` path: no version was ever read, so
``host_version`` stayed ``None`` and every doctor preflight graded the primary
platform ``undetermined``. A warning that never clears is noise, and noise
drowns the one signal the matrix exists to produce -- a version that *was* read
and is *not* in the matrix.

The version is already stamped into every shipped ``.exe`` as a
``VS_VERSIONINFO`` resource, and ``version.dll`` is part of Windows, so
:mod:`ctypes` reads it without adding a runtime dependency. That constraint is
deliberate: the adapter's only runtime dependency is ``dcc-mcp-core``, and a
version string is not worth a ``pywin32`` install.

The read is advisory. Every failure mode -- no path, a file with no version
resource, a denied handle, a truncated resource, or a platform with no
``version.dll`` -- returns ``None`` instead of raising, so discovery degrades to
"version could not be read" rather than failing or inventing a fact.
"""

from __future__ import annotations

import ctypes
import os
from typing import Any


#: ``VS_FIXEDFILEINFO``: the binary half of ``VS_VERSIONINFO``. The localisable
#: string tables are skipped on purpose -- the fixed stamp carries the full
#: four-part build (``9.4.0.4015``), which is the form the matrix records, and
#: it is the one field every shipped PE image sets.
class _FixedFileInfo(ctypes.Structure):
    _fields_ = [
        ("dwSignature", ctypes.c_uint32),
        ("dwStrucVersion", ctypes.c_uint32),
        ("dwFileVersionMS", ctypes.c_uint32),
        ("dwFileVersionLS", ctypes.c_uint32),
        ("dwProductVersionMS", ctypes.c_uint32),
        ("dwProductVersionLS", ctypes.c_uint32),
        ("dwFileFlagsMask", ctypes.c_uint32),
        ("dwFileFlags", ctypes.c_uint32),
        ("dwOS", ctypes.c_uint32),
        ("dwFileType", ctypes.c_uint32),
        ("dwFileSubtype", ctypes.c_uint32),
        ("dwFileDateMS", ctypes.c_uint32),
        ("dwFileDateLS", ctypes.c_uint32),
    ]


#: ``VS_FFI_SIGNATURE``. A block without this magic is not a fixed file info,
#: so the pointer must not be dereferenced as one.
FIXED_FILE_INFO_SIGNATURE = 0xFEEF04BD

#: The ``VerQueryValueW`` sub-block naming the fixed file info itself.
ROOT_SUB_BLOCK = "\\"


def _load_version_library() -> Any:
    """Bind ``version.dll``, or return None where no such library exists.

    This is a module-level function rather than an inline ``ctypes.WinDLL``
    call so the binding can be substituted: the real DLL only exists on
    Windows, and a reader the suite cannot exercise off Windows is a reader
    nobody has any evidence for.
    """
    if os.name != "nt":
        return None
    try:
        return ctypes.WinDLL("version")
    except (AttributeError, OSError):
        # AttributeError: ``ctypes`` only defines WinDLL on Windows, so the
        # guard above is not the only way to get here. OSError: the DLL is
        # absent or unloadable.
        return None


def read_pe_version(path: Any) -> str | None:
    """Return the four-part file version stamped into ``path``, or None.

    ``None`` is the honest answer for every way this can fail, and the caller
    grades it ``undetermined`` -- an explicit warning naming the gap -- instead
    of raising during discovery or inventing a version to match against.
    """
    try:
        text = os.fspath(path)
    except TypeError:
        return None
    if not text.strip():
        # Nothing to open, so nothing to ask the OS about.
        return None
    library = _load_version_library()
    if library is None:
        return None
    try:
        # Signatures are declared per call with explicit ctypes objects rather
        # than by assigning ``argtypes``: ``ctypes.WinDLL`` hands back a
        # process-wide cached object, and mutating it from here would be global
        # state shared with any other caller of ``version.dll``.
        size = int(library.GetFileVersionInfoSizeW(ctypes.c_wchar_p(text), None))
        if size <= 0:
            return None
        block = ctypes.create_string_buffer(size)
        if not library.GetFileVersionInfoW(
            ctypes.c_wchar_p(text), ctypes.c_uint32(0), ctypes.c_uint32(size), block
        ):
            return None
        pointer = ctypes.c_void_p()
        length = ctypes.c_uint32()
        if not library.VerQueryValueW(
            block, ctypes.c_wchar_p(ROOT_SUB_BLOCK), ctypes.byref(pointer), ctypes.byref(length)
        ):
            return None
        if not pointer.value or length.value < ctypes.sizeof(_FixedFileInfo):
            return None
        info = ctypes.cast(pointer, ctypes.POINTER(_FixedFileInfo)).contents
    except Exception:  # noqa: BLE001 - metadata is advisory, never fatal
        # Enumerating the failure modes is not viable: a missing file, a
        # non-PE file, a locked handle, a truncated resource and a surrogate in
        # the path each raise something different, and one of them must never
        # fail discovery.
        return None

    if info.dwSignature != FIXED_FILE_INFO_SIGNATURE:
        return None
    parts = (
        info.dwFileVersionMS >> 16,
        info.dwFileVersionMS & 0xFFFF,
        info.dwFileVersionLS >> 16,
        info.dwFileVersionLS & 0xFFFF,
    )
    if not any(parts):
        # The resource exists but no version was stamped into it. Reporting
        # "0.0.0.0" would name a build that was never shipped and grade it
        # ``unknown``; "could not be read" is what actually happened.
        return None
    return ".".join(str(part) for part in parts)


__all__ = ["FIXED_FILE_INFO_SIGNATURE", "ROOT_SUB_BLOCK", "read_pe_version"]
