"""Feature-tree tools (registry/features, N14) — moved verbatim from server.py."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from solidworks_mcp.solidworks_api.design import rebuild_csg_plan
from solidworks_mcp.solidworks_api.features import (
    apply_draft,
    delete_feature,
    get_feature_details,
    get_features,
    mirror_feature,
    rename_feature,
    set_dimension,
    set_dimension_angle,
    set_feature_suppression,
)

from .base import (
    DESTRUCTIVE,
    READ_ONLY,
    STATE_CHANGE,
    FiniteAngle,
    NonEmptyString,
    SignedMM,
    ToolResult,
    call_connected,
)


def solidworks_features_rebuild_csg(
    plan: Dict[str, Any],
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Rebuild a cross-engine CSG plan as an SW feature tree (v1: box/cylinder/cone/cut_cylinder stacking semantics; v2 adds polygon_prism and swept_arc ops)."""
    return call_connected(
        lambda sw: rebuild_csg_plan(sw, plan),
        launch_if_needed,
    )


def solidworks_features_mirror(
    feature_name: NonEmptyString,
    plane: Literal["right", "front", "top"] = "right",
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Mirror a body feature about a datum plane (right/front/top) for cut-symmetric geometry."""
    return call_connected(
        lambda sw: mirror_feature(sw, feature_name, plane),
        launch_if_needed,
    )


def solidworks_features_apply_draft(
    draft_face: NonEmptyString,
    neutral_face: NonEmptyString,
    angle_deg: FiniteAngle = 3.0,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Taper a named face by angle_deg using a second named face as the neutral plane (use list_faces to get names)."""
    return call_connected(
        lambda sw: apply_draft(sw, draft_face, neutral_face, angle_deg),
        launch_if_needed,
    )


def solidworks_features_list(
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """List feature names in the active document."""
    return call_connected(get_features, launch_if_needed)


def solidworks_features_get_details(
    feature_name: Optional[str] = None,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Type, dimensions (mm), and suppression per feature; null describes all. Large models require one COM round-trip per feature; expect slower responses on 1000+ feature parts."""
    return call_connected(
        lambda sw: get_feature_details(sw, feature_name),
        launch_if_needed,
    )


def solidworks_dimension_set(
    dimension_full_name: NonEmptyString,
    value_mm: SignedMM,
    configuration: Optional[NonEmptyString] = None,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Set a signed length dimension (mm) and rebuild; optional configuration name activates it first (per-configuration value)."""
    return call_connected(
        lambda sw: set_dimension(sw, dimension_full_name, value_mm, configuration),
        launch_if_needed,
    )


def solidworks_dimension_set_angle(
    dimension_full_name: NonEmptyString,
    value_deg: FiniteAngle,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Set an angle dimension in degrees (converted to radians on the wire) and rebuild."""
    return call_connected(
        lambda sw: set_dimension_angle(sw, dimension_full_name, value_deg),
        launch_if_needed,
    )


def solidworks_feature_delete(
    feature_name: NonEmptyString,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Delete one exactly matched feature from the tree (destructive, no undo guarantee)."""
    return call_connected(
        lambda sw: delete_feature(sw, feature_name),
        launch_if_needed,
    )


def solidworks_feature_rename(
    old_name: NonEmptyString,
    new_name: NonEmptyString,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Rename one exactly matched feature in the active document."""
    return call_connected(
        lambda sw: rename_feature(sw, old_name, new_name),
        launch_if_needed,
    )


def solidworks_feature_set_suppression(
    feature_name: NonEmptyString,
    suppressed: bool,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Suppress or unsuppress one exactly matched feature."""
    return call_connected(
        lambda sw: set_feature_suppression(sw, feature_name, suppressed),
        launch_if_needed,
    )


def register(mcp) -> None:
    mcp.tool(
        title="Rebuild CSG plan", annotations=DESTRUCTIVE, structured_output=True
    )(solidworks_features_rebuild_csg)
    mcp.tool(
        title="Mirror feature about plane", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_features_mirror)
    mcp.tool(
        title="Apply draft", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_features_apply_draft)
    mcp.tool(
        title="List features", annotations=READ_ONLY, structured_output=True
    )(solidworks_features_list)
    mcp.tool(
        title="Get feature details", annotations=READ_ONLY, structured_output=True
    )(solidworks_features_get_details)
    mcp.tool(
        title="Set dimension value", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_dimension_set)
    mcp.tool(
        title="Set angle dimension", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_dimension_set_angle)
    mcp.tool(
        title="Delete feature", annotations=DESTRUCTIVE, structured_output=True
    )(solidworks_feature_delete)
    mcp.tool(
        title="Rename feature", annotations=DESTRUCTIVE, structured_output=True
    )(solidworks_feature_rename)
    mcp.tool(
        title="Set feature suppression", annotations=DESTRUCTIVE, structured_output=True
    )(solidworks_feature_set_suppression)
