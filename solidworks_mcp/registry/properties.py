"""Material / custom-property / equation / configuration tools (registry/properties, N14) — moved verbatim from server.py."""

from __future__ import annotations

from typing import Annotated, Optional, Union

from pydantic import Field

from solidworks_mcp.solidworks_api.properties import (
    activate_configuration,
    add_configuration,
    add_equation,
    delete_equation,
    edit_equation,
    get_custom_properties,
    get_material,
    list_equations,
    set_custom_property,
    set_material,
)

from .base import (
    DESTRUCTIVE,
    READ_ONLY,
    STATE_CHANGE,
    NonEmptyString,
    ToolResult,
    call_connected,
)


def solidworks_part_set_material(
    material_name: NonEmptyString,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Assign a material from the SOLIDWORKS MATERIALS library (Chinese names, e.g. 合金钢)."""
    return call_connected(
        lambda sw: set_material(sw, material_name),
        launch_if_needed,
    )


def solidworks_part_get_material(
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Read the active part's material (name, database, configuration)."""
    return call_connected(get_material, launch_if_needed)


def solidworks_part_set_custom_property(
    name: NonEmptyString,
    value: NonEmptyString,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Set a document-level custom property (text type, overwrite)."""
    return call_connected(
        lambda sw: set_custom_property(sw, name, value),
        launch_if_needed,
    )


def solidworks_part_get_custom_properties(
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """List document-level custom properties with resolved values."""
    return call_connected(get_custom_properties, launch_if_needed)


def solidworks_part_add_equation(
    equation: NonEmptyString,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Append an equation or global variable, e.g. '"x" = 50'."""
    return call_connected(
        lambda sw: add_equation(sw, equation),
        launch_if_needed,
    )


def solidworks_part_list_equations(
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """List all equations and global variables with solved values."""
    return call_connected(list_equations, launch_if_needed)


def solidworks_part_add_configuration(
    name: NonEmptyString,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Add a derived configuration to the active document."""
    return call_connected(
        lambda sw: add_configuration(sw, name),
        launch_if_needed,
    )


def solidworks_part_activate_configuration(
    name: NonEmptyString,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Activate a named configuration (verified via ActiveConfiguration read-back)."""
    return call_connected(
        lambda sw: activate_configuration(sw, name),
        launch_if_needed,
    )


def solidworks_part_edit_equation(
    index: Annotated[int, Field(ge=0)],
    new_text: NonEmptyString,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Replace the equation text at a zero-based index (verified via read-back)."""
    return call_connected(
        lambda sw: edit_equation(sw, index, new_text),
        launch_if_needed,
    )


def solidworks_part_delete_equation(
    index_or_text: Annotated[
        Union[int, str],
        Field(description="Zero-based equation index or exact equation text"),
    ],
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Delete an equation by zero-based index or exact text (verified via GetCount)."""
    return call_connected(
        lambda sw: delete_equation(sw, index_or_text),
        launch_if_needed,
    )


def register(mcp) -> None:
    mcp.tool(
        title="Set material", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_set_material)
    mcp.tool(
        title="Get material", annotations=READ_ONLY, structured_output=True
    )(solidworks_part_get_material)
    mcp.tool(
        title="Set custom property", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_set_custom_property)
    mcp.tool(
        title="Get custom properties", annotations=READ_ONLY, structured_output=True
    )(solidworks_part_get_custom_properties)
    mcp.tool(
        title="Add equation", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_add_equation)
    mcp.tool(
        title="List equations", annotations=READ_ONLY, structured_output=True
    )(solidworks_part_list_equations)
    mcp.tool(
        title="Add configuration", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_add_configuration)
    mcp.tool(
        title="Activate configuration",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_part_activate_configuration)
    mcp.tool(
        title="Edit equation", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_edit_equation)
    mcp.tool(
        title="Delete equation", annotations=DESTRUCTIVE, structured_output=True
    )(solidworks_part_delete_equation)
