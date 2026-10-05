"""Assembly tools (registry/assembly, N14) — moved verbatim from server.py."""

from __future__ import annotations

from typing import Literal, Optional

from solidworks_mcp.solidworks_api.assembly import (
    add_component,
    add_mate,
    check_interference,
    delete_mate,
    explode,
    get_bom,
    get_components,
    move_component,
    new_assembly,
    rotate_component,
)

from .base import (
    DESTRUCTIVE,
    READ_ONLY,
    STATE_CHANGE,
    EntityType,
    FiniteAngle,
    FiniteMM,
    MateType,
    NonEmptyString,
    ToolResult,
    call_connected,
)


def solidworks_assembly_new(
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Create a new empty assembly document (GB template), optionally saving it."""
    return call_connected(
        lambda sw: new_assembly(sw, save_path, overwrite_confirm),
        launch_if_needed,
    )


def solidworks_assembly_check_interference(
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Report volume and components of every interference in the active assembly."""
    return call_connected(check_interference, launch_if_needed)


def solidworks_assembly_get_bom(
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Aggregate a bill of materials (part, configuration, instance count)."""
    return call_connected(get_bom, launch_if_needed)


def solidworks_assembly_add_component(
    file_path: NonEmptyString,
    x: FiniteMM = 0.0,
    y: FiniteMM = 0.0,
    z: FiniteMM = 0.0,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Insert a .sldprt or .sldasm component at an approximate millimeter position."""
    return call_connected(
        lambda sw: add_component(sw, file_path, x, y, z),
        launch_if_needed,
    )


def solidworks_assembly_list_components(
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """List component names in the active assembly."""
    return call_connected(get_components, launch_if_needed)


def solidworks_assembly_add_mate(
    mate_type: MateType,
    entity1: NonEmptyString,
    entity2: NonEmptyString,
    distance: Optional[FiniteMM] = None,
    entity1_type: EntityType = "AUTO",
    entity2_type: EntityType = "AUTO",
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Add a basic mate; AUTO tries face, plane, axis, edge, then vertex. distance is millimeters for distance mates and degrees for angle mates; entities are component-qualified names from list_components/list_faces."""
    return call_connected(
        lambda sw: add_mate(
            sw,
            mate_type,
            entity1,
            entity2,
            distance,
            entity1_type,
            entity2_type,
        ),
        launch_if_needed,
    )


def solidworks_assembly_delete_mate(
    mate_name: NonEmptyString,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Delete one exactly matched mate from the active assembly (destructive; success is judged by the mate leaving the tree, so verify with list_features afterwards if critical)."""
    return call_connected(
        lambda sw: delete_mate(sw, mate_name),
        launch_if_needed,
    )


def solidworks_assembly_move_component(
    component_name: NonEmptyString,
    dx: FiniteMM,
    dy: FiniteMM,
    dz: FiniteMM,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Translate one component by (dx, dy, dz) millimetres, composed onto its current transform; the assembly is rebuilt so an immediate check_interference reflects the new position."""
    return call_connected(
        lambda sw: move_component(sw, component_name, dx, dy, dz),
        launch_if_needed,
    )


def solidworks_assembly_rotate_component(
    component_name: NonEmptyString,
    axis: Literal["x", "y", "z"],
    angle_deg: FiniteAngle,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Rotate one component by angle_deg degrees about an assembly axis (x/y/z) through the origin; follow up with check_interference to verify the new pose."""
    return call_connected(
        lambda sw: rotate_component(sw, component_name, axis, angle_deg),
        launch_if_needed,
    )


def solidworks_assembly_explode(
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Create an automatic exploded view on the active assembly and switch to it."""
    return call_connected(explode, launch_if_needed)


def register(mcp) -> None:
    mcp.tool(
        title="New assembly", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_assembly_new)
    mcp.tool(
        title="Check interference", annotations=READ_ONLY, structured_output=True
    )(solidworks_assembly_check_interference)
    mcp.tool(title="Get BOM", annotations=READ_ONLY, structured_output=True)(
        solidworks_assembly_get_bom
    )
    mcp.tool(
        title="Add assembly component",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_assembly_add_component)
    mcp.tool(
        title="List assembly components",
        annotations=READ_ONLY,
        structured_output=True,
    )(solidworks_assembly_list_components)
    mcp.tool(
        title="Add assembly mate", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_assembly_add_mate)
    mcp.tool(
        title="Delete assembly mate", annotations=DESTRUCTIVE, structured_output=True
    )(solidworks_assembly_delete_mate)
    mcp.tool(
        title="Move component", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_assembly_move_component)
    mcp.tool(
        title="Rotate component", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_assembly_rotate_component)
    mcp.tool(
        title="Create exploded view",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_assembly_explode)
