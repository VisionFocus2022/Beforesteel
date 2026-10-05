"""File import/export tools (registry/file_io, N14) — moved verbatim from server.py."""

from __future__ import annotations

from typing import Optional

from solidworks_mcp.solidworks_api.file_io import (
    close_document,
    export_dxf,
    export_step,
    export_stl,
    import_step,
    open_document,
)

from .base import (
    DESTRUCTIVE,
    IDEMPOTENT_WRITE,
    STATE_CHANGE,
    NonEmptyString,
    ToolResult,
    call_connected,
)


def solidworks_file_open(
    file_path: NonEmptyString,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Open an existing document under allowed_root."""
    return call_connected(lambda sw: open_document(sw, file_path), launch_if_needed)


def solidworks_file_close(
    save_changes: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Close the active document; unsaved edits are discarded unless save_changes=true."""
    return call_connected(
        lambda sw: close_document(sw, save_changes),
        launch_if_needed,
    )


def solidworks_file_import_step(
    file_path: NonEmptyString,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Import an existing .step or .stp file under allowed_root."""
    return call_connected(lambda sw: import_step(sw, file_path), launch_if_needed)


def solidworks_file_export_step(
    file_path: NonEmptyString,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Export the active document to .step or .stp under allowed_root."""
    return call_connected(
        lambda sw: export_step(sw, file_path, overwrite_confirm),
        launch_if_needed,
    )


def solidworks_file_export_stl(
    file_path: NonEmptyString,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Export the active part to .stl under allowed_root."""
    return call_connected(
        lambda sw: export_stl(sw, file_path, overwrite_confirm),
        launch_if_needed,
    )


def solidworks_file_export_dxf(
    file_path: NonEmptyString,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Export the active drawing to ASCII .dxf (AC1015) under allowed_root. SolidWorks returns a warning code for DXF saves; success is judged by a valid SECTION header in the written file."""
    return call_connected(
        lambda sw: export_dxf(sw, file_path, overwrite_confirm),
        launch_if_needed,
    )


def register(mcp) -> None:
    mcp.tool(
        title="Open document", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_file_open)
    mcp.tool(
        title="Close document", annotations=DESTRUCTIVE, structured_output=True
    )(solidworks_file_close)
    mcp.tool(
        title="Import STEP", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_file_import_step)
    mcp.tool(
        title="Export STEP", annotations=IDEMPOTENT_WRITE, structured_output=True
    )(solidworks_file_export_step)
    mcp.tool(
        title="Export STL", annotations=IDEMPOTENT_WRITE, structured_output=True
    )(solidworks_file_export_stl)
    mcp.tool(
        title="Export DXF", annotations=IDEMPOTENT_WRITE, structured_output=True
    )(solidworks_file_export_dxf)
