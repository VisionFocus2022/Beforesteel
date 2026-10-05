"""Session, capabilities, and measurement tools (registry/misc, N14).

``solidworks_connect`` reuses :func:`call_connected` (N14 step 4) so the
poisoned/timeout/unexpected-error handling lives in one place; the second
``connect`` returns the cached-connection result, so a successful call
reports "Already connected" with the live version data.
``solidworks_measure_distance`` is a pure computation (N14 step 4): it
never touches COM, so it works with no SolidWorks running at all.
"""

from __future__ import annotations

from typing import List, Optional

from solidworks_mcp.solidworks_api.measure import (
    get_bounding_box,
    measure_distance,
)
from solidworks_mcp.utils.common import success_response

from .base import (
    READ_ONLY,
    STATE_CHANGE,
    FiniteMM,
    ToolResult,
    active_document_data,
    call_connected,
    _capabilities,
)


def solidworks_connect(launch_if_needed: Optional[bool] = None) -> ToolResult:
    """Connect to SolidWorks; null uses SOLIDWORKS_MCP_AUTO_START."""
    return call_connected(
        lambda sw: sw.connect(launch_if_needed=launch_if_needed),
        launch_if_needed,
    )


def solidworks_get_active_document(
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Return the active document title, path, numeric type, and type name."""
    return call_connected(active_document_data, launch_if_needed)


def solidworks_design_capabilities() -> ToolResult:
    """Return supported design operations, units, safety rules, and limitations."""
    return success_response(
        data=_capabilities(),
        message="SolidWorks MCP capabilities retrieved",
    )


def solidworks_measure_distance(
    point1: List[FiniteMM],
    point2: List[FiniteMM],
) -> ToolResult:
    """Distance (mm) between two model-space [x, y, z] points given in mm."""
    return measure_distance(point1, point2)


def solidworks_get_bounding_box(
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Merged solid-body bounding box in mm (min/max/size/center)."""
    return call_connected(get_bounding_box, launch_if_needed)


def register(mcp) -> None:
    mcp.tool(
        title="Connect to SolidWorks",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_connect)
    mcp.tool(
        title="Get active document", annotations=READ_ONLY, structured_output=True
    )(solidworks_get_active_document)
    mcp.tool(
        title="Get design capabilities", annotations=READ_ONLY, structured_output=True
    )(solidworks_design_capabilities)
    mcp.tool(
        title="Measure distance between two points",
        annotations=READ_ONLY,
        structured_output=True,
    )(solidworks_measure_distance)
    mcp.tool(
        title="Get bounding box", annotations=READ_ONLY, structured_output=True
    )(solidworks_get_bounding_box)
