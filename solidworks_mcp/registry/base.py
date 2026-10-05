"""Shared plumbing for the per-domain tool registry (N14).

Everything a domain module needs to define one tool lives here: the
pydantic type aliases, the structured ToolResult contract, the tool
annotation presets, and the COM execution helpers. ``mcp`` itself stays
on the :mod:`solidworks_mcp.server` facade — A-3 (2026-10-05) removed
the old lazy ``base → server`` import: the facade now installs its
capabilities builder here via :func:`set_capabilities_provider` at
registration time, so this package never imports upward.
"""

from __future__ import annotations

import logging
import sys
from typing import (
    Annotated,
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    TypedDict,
)

from mcp.types import ToolAnnotations
from pydantic import Field

from solidworks_mcp import __version__
from solidworks_mcp.config import get_config
from solidworks_mcp.solidworks_api.app import get_solidworks_app
from solidworks_mcp.utils.com import call_or_value
from solidworks_mcp.utils.com_executor import (
    ComCallTimeoutError,
    ComExecutorPoisonedError,
    run_com,
)
from solidworks_mcp.utils.common import error_response, success_response

PositiveMM = Annotated[
    float,
    Field(gt=0, allow_inf_nan=False, description="Positive length in millimeters"),
]
FiniteMM = Annotated[
    float,
    Field(allow_inf_nan=False, description="Finite coordinate in millimeters"),
]
FiniteAngle = Annotated[
    float,
    Field(allow_inf_nan=False, description="Finite angle in degrees"),
]
SignedMM = Annotated[
    float,
    Field(allow_inf_nan=False, description="Signed finite length in millimeters (non-zero)"),
]
NonNegativeMM = Annotated[
    float,
    Field(ge=0, allow_inf_nan=False, description="Non-negative length in millimeters"),
]
NonEmptyString = Annotated[str, Field(min_length=1)]
MateType = Literal[
    "coincident", "concentric", "distance", "tangent", "angle", "width"
]
EntityType = Literal["AUTO", "FACE", "PLANE", "AXIS", "EDGE", "VERTEX"]


class ToolError(TypedDict):
    code: str
    details: Any


class ToolResult(TypedDict):
    success: bool
    data: Any
    message: str
    warning: Optional[str]
    error: Optional[ToolError]

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
STATE_CHANGE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
DESTRUCTIVE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)
IDEMPOTENT_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)

DOC_TYPES = {1: "part", 2: "assembly", 3: "drawing"}


def get_sw():
    return get_solidworks_app()


def com_timeout() -> Optional[float]:
    """COM call timeout in seconds; None keeps the historic no-timeout mode."""
    timeout = get_config().com_timeout_seconds
    return timeout if timeout > 0 else None


def _poisoned_response() -> dict:
    """Structured result for a poisoned COM executor with a recovery path.

    N3: a poisoned executor cannot recover in-process; every later tool
    call would fail. Return an actionable result, or exit outright when
    SOLIDWORKS_MCP_POISONED_EXIT=1 so the stdio host's supervisor can
    restart this server process.
    """
    if get_config().poisoned_exit:
        sys.exit(1)
    return error_response(
        "COM 执行器已毒化（超时线程未返回），所有工具将失败。"
        "恢复方法：重启 MCP 会话/服务器进程。",
        data={"recovery": "restart-mcp-session"},
        code="SW_EXECUTOR_POISONED",
    )


def call_connected(
    operation: Callable[[Any], dict],
    launch_if_needed: Optional[bool] = None,
) -> dict:
    """Connect and execute one operation in the dedicated COM apartment."""

    def invoke() -> dict:
        sw = get_sw()
        connection = sw.connect(launch_if_needed=launch_if_needed)
        if not connection["success"]:
            return connection
        return operation(sw)

    try:
        return run_com(invoke, timeout=com_timeout())
    except ComCallTimeoutError as exc:
        return error_response(str(exc), code="SW_TIMEOUT")
    except ComExecutorPoisonedError:
        return _poisoned_response()
    except Exception as exc:
        logging.getLogger(__name__).exception("Unhandled SolidWorks tool error")
        return error_response(
            "SolidWorks operation failed unexpectedly",
            code="SW_API_ERROR",
            details={"exception_type": type(exc).__name__},
        )


def active_document_data(sw: Any) -> dict:
    model = sw.get_active_document()
    if model is None:
        return success_response(data=None, message="No active document")
    doc_type = int(call_or_value(model, "GetType"))
    path = call_or_value(model, "GetPathName")
    return success_response(
        data={
            "title": call_or_value(model, "GetTitle"),
            "type": doc_type,
            "type_name": DOC_TYPES.get(doc_type, "unknown"),
            "path": path or None,
        },
        message="Active document retrieved",
    )


# A-3（2026-10-05）：capabilities 内容由门面（server.py）在 register_all
# 时注入——依赖方向保持向下（server → registry），base 不再向上 import。
_capabilities_provider: Optional[Callable[[], Dict[str, Any]]] = None


def set_capabilities_provider(
    provider: Callable[[], Dict[str, Any]]
) -> None:
    """Install the facade-owned capabilities builder (called by server.py)."""
    global _capabilities_provider
    _capabilities_provider = provider


def _capabilities() -> Dict[str, Any]:
    if _capabilities_provider is None:
        raise RuntimeError(
            "capabilities provider not installed — server.register_all "
            "must run before _capabilities() is callable"
        )
    return _capabilities_provider()


# -- M-1 compatibility aliases (2026-10-05) ---------------------------------
# Historical private names kept for in-flight branches; new code must use
# the public names above. Removal target: v0.5.0 (same as server re-exports).
_sw = get_sw
_com_timeout = com_timeout
_call_connected = call_connected
_active_document_data = active_document_data
