"""Path security and confirmation helpers."""

from __future__ import annotations

import ctypes
import logging
import os
from typing import Iterable, Optional

from solidworks_mcp.config import get_config

logger = logging.getLogger(__name__)


# Default allowed root directory. All file operations must be under this path
# unless explicitly relaxed by configuration.
#
# P-2 (2026-10-05): evaluated lazily per call — this used to freeze at
# import time, which made ``SOLIDWORKS_MCP_ALLOWED_ROOT`` set after import
# (and test monkeypatching) silently ineffective, contradicting the
# hot-read semantics of ``config.get_config()``. Both now read at call time.
def default_allowed_root() -> str:
    """The configured allowed root, read at call time (matches get_config)."""
    return os.path.normpath(get_config().allowed_root)


def _expand_long_path(path: str) -> str:
    """Expand 8.3 short-name segments (PROGRA~1) back to long names.

    On some hosts (GitHub-hosted runners) realpath resolves to the 8.3
    form of existing directories (RUNNER~1), which breaks equality with
    caller-supplied long-name paths and the allowed root. Only valid for
    existing paths; anything else returns the input unchanged.
    """
    try:
        kernel32 = ctypes.windll.kernel32
        size = len(path) + 260
        buffer = ctypes.create_unicode_buffer(size)
        # Always pass the buffer's real length (a mocked create call may
        # hand back something smaller than requested).
        result = kernel32.GetLongPathNameW(path, buffer, len(buffer))
        if 0 < result < len(buffer):
            return buffer.value
        if result >= len(buffer):
            # "Required size" signal: retry once with the exact buffer
            # (paths longer than len+260, e.g. deep \\?\ prefixes). The
            # retry is only trusted when it fits the buffer we actually
            # got — a mocked/undersized buffer still falls back.
            buffer = ctypes.create_unicode_buffer(result)
            retried = kernel32.GetLongPathNameW(path, buffer, len(buffer))
            if 0 < retried < len(buffer):
                return buffer.value
        return path
    except Exception:  # noqa: BLE001 —— non-Windows / kernel32 missing: no-op
        return path


def normalize_path(path: str) -> str:
    """Normalize an absolute path, resolving links/junctions with OS semantics.

    Resolution is component-wise and never lexically folds ``..`` across a
    link: each existing component is canonicalized via ``realpath`` (whose
    ``_getfinalpathname`` resolves junctions the way the file system does),
    and ``..`` pops the already-canonical prefix. This prevents
    ``root\\link\\..\\out`` from folding to ``root\\out`` when ``link``
    actually points outside the root. Existing components are additionally
    expanded from 8.3 short names (see ``_expand_long_path``).
    """
    expanded = os.path.expanduser(path)
    if os.path.lexists(expanded):
        return _expand_long_path(os.path.normpath(os.path.realpath(expanded)))
    if not os.path.isabs(expanded):
        expanded = os.getcwd() + os.sep + expanded
    drive, rest = os.path.splitdrive(expanded)
    parts: list = []
    for part in rest.split(os.sep):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
        candidate = drive + os.sep + os.sep.join(parts)
        if os.path.lexists(candidate):
            canonical_drive, canonical_rest = os.path.splitdrive(
                _expand_long_path(os.path.realpath(candidate))
            )
            drive = canonical_drive or drive
            parts = [p for p in canonical_rest.split(os.sep) if p not in ("", ".")]
    return os.path.normpath(drive + os.sep + os.sep.join(parts))


def is_path_allowed(
    path: str,
    allowed_root: Optional[str] = None,
) -> bool:
    """Check whether a path is within the allowed root directory.

    This prevents directory traversal attacks via ``..`` segments.
    """
    root = normalize_path(allowed_root or default_allowed_root())
    target = normalize_path(path)
    # os.path.commonpath can raise ValueError for mixed drive letters on Windows.
    try:
        common = os.path.commonpath([root, target])
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(root)


def ensure_sink_path(
    path: str,
    allowed_root: Optional[str] = None,
) -> tuple[bool, str, str]:
    """Re-check containment at the moment of writing (TOCTOU narrowing).

    Validation happens minutes before long modeling calls; the filesystem
    can change in between. This re-resolves the path and re-checks the
    allowed root right before the sink. Returns ``(ok, message, normalized)``
    where ``normalized`` is the path the caller must hand to SolidWorks.
    """
    normalized = normalize_path(path)
    if not is_path_allowed(normalized, allowed_root or default_allowed_root()):
        return (
            False,
            f"Path '{path}' resolves outside the allowed root at save time. "
            "The filesystem may have changed since validation; aborting.",
            normalized,
        )
    return True, "", normalized


def validate_path(
    path: str,
    allowed_root: Optional[str] = None,
    must_exist: bool = False,
    must_not_exist: bool = False,
    parent_must_exist: bool = False,
) -> tuple[bool, str]:
    """Validate a file path for safety.

    Returns:
        A tuple (is_valid, message). When invalid, message explains why.
    """
    if not path or not isinstance(path, str):
        return False, "Path must be a non-empty string"

    normalized = normalize_path(path)

    effective_root = allowed_root or default_allowed_root()

    if not is_path_allowed(normalized, effective_root):
        return (
            False,
            f"Path '{path}' is outside the allowed working directory. "
            f"Operations are restricted to '{effective_root}'.",
        )

    if must_exist and not os.path.exists(normalized):
        return False, f"Path does not exist: {path}"

    if must_not_exist and os.path.exists(normalized):
        return False, f"File already exists: {path}"

    if parent_must_exist:
        parent = os.path.dirname(normalized) or normalize_path(".")
        if not os.path.isdir(parent):
            return False, f"Parent directory does not exist: {parent}"

    return True, ""


def validate_extension(
    path: str,
    allowed_extensions: Iterable[str],
) -> tuple[bool, str]:
    """Require a file extension from an explicit allowlist."""
    allowed = {
        ext.lower() if ext.startswith(".") else f".{ext.lower()}"
        for ext in allowed_extensions
    }
    actual = os.path.splitext(path)[1].lower()
    if actual not in allowed:
        expected = ", ".join(sorted(allowed))
        return False, f"Expected file extension {expected}; got '{actual or '<none>'}'"
    return True, ""


def check_overwrite_confirm(
    path: str,
    overwrite_confirm: bool = False,
) -> tuple[bool, str]:
    """Check whether overwriting an existing file is allowed.

    In strict mode, ``overwrite_confirm`` must be True before an existing file
    can be overwritten. Returns (allowed, message).
    """
    normalized = normalize_path(path)
    if os.path.exists(normalized):
        if not overwrite_confirm:
            return (
                False,
                f"File already exists: {path}. "
                "Set overwrite_confirm=True to overwrite.",
            )
    return True, ""


def validate_output_file(
    path: str,
    allowed_extensions: Iterable[str],
    overwrite_confirm: bool = False,
    allowed_root: Optional[str] = None,
) -> tuple[bool, str]:
    """Validate a safe output path before any SolidWorks model is mutated."""
    valid, message = validate_path(
        path,
        allowed_root=allowed_root,
        parent_must_exist=True,
    )
    if not valid:
        return valid, message
    valid, message = validate_extension(path, allowed_extensions)
    if not valid:
        return valid, message
    return check_overwrite_confirm(path, overwrite_confirm)
