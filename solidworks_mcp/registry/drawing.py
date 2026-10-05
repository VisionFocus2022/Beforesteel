"""Drawing tools (registry/drawing, N14) — moved verbatim from server.py."""

from __future__ import annotations

from typing import List, Optional

from solidworks_mcp.solidworks_api.drawing import (
    create_drawing_from_part,
    export_drawing_pdf,
    export_drawing_png,
    insert_gtol,
    insert_model_dimensions,
    insert_note,
    insert_bom_table,
    insert_section_view,
    insert_surface_finish,
    organize_dimensions,
    set_tolerance,
)

from .base import (
    IDEMPOTENT_WRITE,
    STATE_CHANGE,
    NonEmptyString,
    ToolResult,
    call_connected,
)


def solidworks_drawing_create_from_part(
    part_path: NonEmptyString,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Create a drawing (GB A3 template) from a saved part and project three views. The part must be saved before creating the drawing; close the drawing (solidworks_file_close) when done to release file locks."""
    return call_connected(
        lambda sw: create_drawing_from_part(sw, part_path),
        launch_if_needed,
    )


def solidworks_drawing_insert_dimensions(
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Insert the model's dimensions into the active drawing's views."""
    return call_connected(insert_model_dimensions, launch_if_needed)


def solidworks_drawing_export_pdf(
    file_path: NonEmptyString,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Export the active drawing to PDF under allowed_root."""
    return call_connected(
        lambda sw: export_drawing_pdf(sw, file_path, overwrite_confirm),
        launch_if_needed,
    )


def solidworks_drawing_export_png(
    file_path: NonEmptyString,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Export the active drawing sheet to PNG (raster) under allowed_root."""
    return call_connected(
        lambda sw: export_drawing_png(sw, file_path, overwrite_confirm),
        launch_if_needed,
    )


def solidworks_drawing_organize_dimensions(
    view_name: str = "",
    mode: str = "dedupe_shift",
    shift_step_mm: float = 8.0,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Tidy overlapping dimensions in the active drawing: delete same-feature duplicates within each view, then stagger annotations closer than 2 mm apart by shift_step_mm (sheet mm). Run after solidworks_drawing_insert_dimensions; empty view_name processes every view."""
    return call_connected(
        lambda sw: organize_dimensions(
            sw, view_name or None, mode, shift_step_mm
        ),
        launch_if_needed,
    )


def solidworks_drawing_insert_section_view(
    source_view_name: NonEmptyString,
    cut_position_mm: float = 0.0,
    direction: str = "vertical",
    position_xy_mm: Optional[List[float]] = None,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Create a section view of source_view_name with a straight cut line (vertical/horizontal, offset cut_position_mm in sheet mm from the view anchor; the line is drawn in the blank strip below/left of the view — lines on top of a view never produce a section view). The section view lands 120 mm to the right unless position_xy_mm (sheet mm) is given; SolidWorks assigns the A/B/C label automatically."""
    return call_connected(
        lambda sw: insert_section_view(
            sw, source_view_name, cut_position_mm, direction, position_xy_mm
        ),
        launch_if_needed,
    )


def solidworks_drawing_set_tolerance(
    dimension_name: NonEmptyString,
    upper_mm: float,
    lower_mm: float,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Set +/- tolerances (PlusMinus type) on a drawing display dimension. dimension_name matches the FullName exactly or without its trailing part segment (e.g. 'D1@SketchName'); bounds are sheet millimetres and keep their sign (lower_mm=-0.05 renders as -0.05). Readback values are returned."""
    return call_connected(
        lambda sw: set_tolerance(sw, dimension_name, upper_mm, lower_mm),
        launch_if_needed,
    )


def solidworks_drawing_insert_surface_finish(
    value_um: float = 1.6,
    x_mm: float = 100.0,
    y_mm: float = 50.0,
    symbol: str = "remove_material",
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Insert a surface-finish symbol on the active drawing (default: remove-material Ra symbol). value_um is the Ra value in micrometres (0.008-100); x_mm/y_mm place the symbol in sheet millimetres; symbol picks the shape: basic / remove_material / no_remove_material."""
    return call_connected(
        lambda sw: insert_surface_finish(sw, value_um, x_mm, y_mm, symbol),
        launch_if_needed,
    )


def solidworks_drawing_insert_note(
    text: NonEmptyString,
    x_mm: float = 100.0,
    y_mm: float = 50.0,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Insert a plain text note (e.g. technical requirements) on the active drawing at x_mm/y_mm in sheet millimetres."""
    return call_connected(
        lambda sw: insert_note(sw, text, x_mm, y_mm),
        launch_if_needed,
    )


def solidworks_drawing_insert_gtol(
    characteristic: NonEmptyString,
    tolerance_mm: float,
    x_mm: float = 100.0,
    y_mm: float = 50.0,
    diameter: bool = False,
    material_condition: str = "none",
    datum_a: Optional[str] = None,
    datum_b: Optional[str] = None,
    datum_c: Optional[str] = None,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Insert a GD&T feature-control frame (form/orientation/location/runout/profile) on the active drawing. characteristic is one of flatness/straightness/circularity/cylindricity/parallelism/perpendicularity/angularity/position/concentricity/symmetry/profile_line/profile_surface/circular_runout/total_runout; tolerance_mm is the tolerance zone width in sheet millimetres; diameter adds the Ø modifier; material_condition picks none/mmc/rfs/lmc; datum_a/b/c are reference letters. x_mm/y_mm place the frame on the sheet."""
    return call_connected(
        lambda sw: insert_gtol(
            sw, characteristic, tolerance_mm, x_mm, y_mm,
            diameter, material_condition, datum_a, datum_b, datum_c,
        ),
        launch_if_needed,
    )


def solidworks_drawing_insert_bom_table(
    view_name: NonEmptyString,
    x_mm: float = 240.0,
    y_mm: float = 20.0,
    bom_type: str = "parts_only",
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Insert a BOM table (parts-only or top-level) on a named assembly drawing view."""
    return call_connected(
        lambda sw: insert_bom_table(sw, view_name, x_mm, y_mm, bom_type),
        launch_if_needed,
    )


def register(mcp) -> None:
    mcp.tool(
        title="Create drawing from part",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_drawing_create_from_part)
    mcp.tool(
        title="Insert model dimensions",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_drawing_insert_dimensions)
    mcp.tool(
        title="Export drawing PDF",
        annotations=IDEMPOTENT_WRITE,
        structured_output=True,
    )(solidworks_drawing_export_pdf)
    mcp.tool(
        title="Export drawing PNG",
        annotations=IDEMPOTENT_WRITE,
        structured_output=True,
    )(solidworks_drawing_export_png)
    mcp.tool(
        title="Organize drawing dimensions",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_drawing_organize_dimensions)
    mcp.tool(
        title="Insert section view",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_drawing_insert_section_view)
    mcp.tool(
        title="Set dimension tolerance",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_drawing_set_tolerance)
    mcp.tool(
        title="Insert surface finish symbol",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_drawing_insert_surface_finish)
    mcp.tool(
        title="Insert drawing note",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_drawing_insert_note)
    mcp.tool(
        title="Insert GD&T feature control frame",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_drawing_insert_gtol)
    mcp.tool(
        title="Insert BOM table",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_drawing_insert_bom_table)
