"""Part modelling tools (registry/part, N14).

Primitives, decorations, holes, patterns, sheet metal, mass properties,
and topology queries — moved verbatim from server.py.
"""

from __future__ import annotations

from typing import (
    Annotated,
    Any,
    Dict,
    List,
    Literal,
    Optional,
)

from pydantic import Field, ValidationError

from solidworks_mcp.solidworks_api.design import (
    create_box,
    create_cylinder,
    create_linear_holes,
    create_new_part,
    create_plate,
    cut_round_hole,
    cut_threaded_hole,
    execute_design_plan,
)
from solidworks_mcp.solidworks_api.decorations import (
    apply_chamfer,
    apply_dome,
    apply_fillet,
    apply_shell,
)
from solidworks_mcp.solidworks_api.features import cut_real_thread
from solidworks_mcp.solidworks_api.part import (
    create_cone,
    create_loft,
    create_polygon,
    create_ref_axis,
    create_ref_plane,
    create_revolved,
    create_rib,
    create_slot,
    create_swept,
    get_mass_properties,
)
from solidworks_mcp.solidworks_api.pattern_ui import (
    create_circular_pattern,
)
from solidworks_mcp.solidworks_api.pattern import (
    AnnularRing,
    build_annular_layout,
    create_annular_pattern,
)
from solidworks_mcp.solidworks_api.sheet_metal import create_base_flange
from solidworks_mcp.solidworks_api.topology import list_bodies, list_faces
from solidworks_mcp.utils.common import error_response, success_response

from .base import (
    DESTRUCTIVE,
    READ_ONLY,
    STATE_CHANGE,
    FiniteMM,
    NonEmptyString,
    NonNegativeMM,
    PositiveMM,
    ToolResult,
    _call_connected,
)

# Keep in sync with THREAD_SPECS in solidworks_api/constants.py —
# test_threaded_hole_spec_is_literal_enum pins the two together.
ThreadSpec = Literal[
    "M2",
    "M2.5",
    "M3",
    "M4",
    "M5",
    "M6",
    "M8",
    "M10",
    "M12",
    "M16",
    "M20",
]


def solidworks_part_new(
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Create a blank part; save_path must end in .sldprt."""
    return _call_connected(
        lambda sw: create_new_part(sw, save_path, overwrite_confirm),
        launch_if_needed,
    )


def solidworks_part_create_plate(
    width: PositiveMM,
    depth: PositiveMM,
    thickness: PositiveMM,
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Add a centered rectangular plate boss to the active part, or create a part."""
    return _call_connected(
        lambda sw: create_plate(
            sw, width, depth, thickness, save_path, overwrite_confirm
        ),
        launch_if_needed,
    )


def solidworks_part_create_box(
    width: PositiveMM,
    depth: PositiveMM,
    height: PositiveMM,
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Add a centered rectangular boss to the active part, or create a part."""
    return _call_connected(
        lambda sw: create_box(sw, width, depth, height, save_path, overwrite_confirm),
        launch_if_needed,
    )


def solidworks_part_create_cylinder(
    diameter: PositiveMM,
    height: PositiveMM,
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Add a centered cylindrical boss to the active part, or create a part."""
    return _call_connected(
        lambda sw: create_cylinder(
            sw, diameter, height, save_path, overwrite_confirm
        ),
        launch_if_needed,
    )


def solidworks_part_cut_round_hole(
    diameter: PositiveMM,
    x: FiniteMM = 0.0,
    y: FiniteMM = 0.0,
    plane: NonEmptyString = "top",
    depth: Optional[PositiveMM] = None,
    through_all: bool = True,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Cut a round hole from top/front/right or an exact named plane."""
    return _call_connected(
        lambda sw: cut_round_hole(
            sw, diameter, x, y, plane, depth, through_all
        ),
        launch_if_needed,
    )


def solidworks_part_create_cone(
    bottom_diameter: PositiveMM,
    height: PositiveMM,
    top_diameter: NonNegativeMM = 0.0,
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Add a centered conical/frustum boss (drafted extrusion) to the active part."""
    return _call_connected(
        lambda sw: create_cone(
            sw, bottom_diameter, top_diameter, height, save_path, overwrite_confirm
        ),
        launch_if_needed,
    )


def solidworks_part_create_revolved(
    outer_diameter: PositiveMM,
    height: PositiveMM,
    bore_diameter: NonNegativeMM = 0.0,
    plane: Literal["front"] = "front",
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Revolved disc/ring/shaft segment (feature-tree based) around a sketch centerline."""
    return _call_connected(
        lambda sw: create_revolved(
            sw, outer_diameter, height, bore_diameter, plane, save_path,
            overwrite_confirm,
        ),
        launch_if_needed,
    )


def solidworks_part_create_swept(
    diameter_mm: PositiveMM,
    path_type: Literal["arc", "line"] = "arc",
    radius_mm: Optional[PositiveMM] = None,
    angle_deg: float = 90.0,
    length_mm: Optional[PositiveMM] = None,
    plane: Literal["front"] = "front",
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Solid swept protrusion: circular profile (diameter) along an arc or line sketch path."""
    return _call_connected(
        lambda sw: create_swept(
            sw,
            diameter_mm,
            path_type,
            radius_mm,
            angle_deg,
            length_mm,
            plane,
            save_path,
            overwrite_confirm,
        ),
        launch_if_needed,
    )


def solidworks_part_create_loft(
    profile_diameters_mm: List[PositiveMM],
    section_spacing_mm: PositiveMM,
    plane: Literal["front"] = "front",
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Lofted protrusion between circular sections on parallel planes (>=2 profiles)."""
    return _call_connected(
        lambda sw: create_loft(
            sw,
            profile_diameters_mm,
            section_spacing_mm,
            plane,
            save_path,
            overwrite_confirm,
        ),
        launch_if_needed,
    )


def solidworks_part_create_polygon(
    sides: int,
    circumradius_mm: PositiveMM,
    height_mm: PositiveMM,
    inscribed: bool = True,
    plane: Literal["front"] = "front",
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Regular N-sided prism (3-60 sides): polygon sketch + boss extrude."""
    return _call_connected(
        lambda sw: create_polygon(
            sw, sides, circumradius_mm, height_mm, inscribed, plane,
            save_path, overwrite_confirm,
        ),
        launch_if_needed,
    )


def solidworks_part_create_slot(
    length_mm: PositiveMM,
    width_mm: PositiveMM,
    height_mm: PositiveMM,
    plane: Literal["front"] = "front",
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Obround slot plate (centre-line length > width): straight-slot sketch + boss extrude."""
    return _call_connected(
        lambda sw: create_slot(
            sw, length_mm, width_mm, height_mm, plane,
            save_path, overwrite_confirm,
        ),
        launch_if_needed,
    )


def solidworks_part_create_ref_plane(
    offset_mm: PositiveMM,
    plane: Literal["front"] = "front",
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Reference plane parallel to the front plane at an offset distance (for sketching on)."""
    return _call_connected(
        lambda sw: create_ref_plane(sw, offset_mm, plane),
        launch_if_needed,
    )


def solidworks_part_create_ref_axis(
    face_name: NonEmptyString,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Reference axis from a named cylindrical face (names from list_faces)."""
    return _call_connected(
        lambda sw: create_ref_axis(sw, face_name),
        launch_if_needed,
    )


def solidworks_part_create_rib(
    length_mm: PositiveMM,
    height_mm: PositiveMM,
    thickness_mm: PositiveMM,
    base_z_mm: NonNegativeMM = 0.0,
    x_center_mm: float = 0.0,
    y_center_mm: float = 0.0,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Rib as a rectangular boss plate (math substitute — not wall-adaptive; InsertRib is unavailable)."""
    return _call_connected(
        lambda sw: create_rib(
            sw, length_mm, height_mm, thickness_mm, base_z_mm,
            x_center_mm, y_center_mm,
        ),
        launch_if_needed,
    )


def solidworks_part_apply_dome(
    face_name: NonEmptyString,
    height_mm: PositiveMM,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Raise a dome of the given height on the named planar/circular face (names from list_faces)."""
    return _call_connected(
        lambda sw: apply_dome(sw, face_name, height_mm),
        launch_if_needed,
    )


def solidworks_part_apply_fillet(
    face_names: List[NonEmptyString],
    radius_mm: PositiveMM,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Fillet all edges of the named faces (names from list_faces) with a constant radius."""
    return _call_connected(
        lambda sw: apply_fillet(sw, face_names, radius_mm),
        launch_if_needed,
    )


def solidworks_part_apply_chamfer(
    face_names: List[NonEmptyString],
    distance_mm: PositiveMM,
    angle_deg: float = 45.0,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Chamfer all edges of the named faces by distance and angle (0<angle<90)."""
    return _call_connected(
        lambda sw: apply_chamfer(sw, face_names, distance_mm, angle_deg),
        launch_if_needed,
    )


def solidworks_part_apply_shell(
    face_names: List[NonEmptyString],
    thickness_mm: PositiveMM,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Hollow the part keeping thickness_mm walls; the named faces are removed."""
    return _call_connected(
        lambda sw: apply_shell(sw, face_names, thickness_mm),
        launch_if_needed,
    )


def solidworks_part_cut_threaded_hole(
    spec: ThreadSpec,
    x: FiniteMM = 0.0,
    y: FiniteMM = 0.0,
    plane: NonEmptyString = "top",
    depth: Optional[PositiveMM] = None,
    through_all: bool = True,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Cut an ISO coarse-thread hole (M2-M20) at its tap-drill diameter with a cosmetic thread."""
    return _call_connected(
        lambda sw: cut_threaded_hole(
            sw, spec, x, y, plane, depth, through_all
        ),
        launch_if_needed,
    )


def solidworks_part_cut_real_thread(
    diameter: PositiveMM,
    pitch: PositiveMM,
    thread_length: PositiveMM,
    profile_dia: Optional[PositiveMM] = None,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Cut a true helical thread groove (swept cut along an InsertHelix curve, circular profile) on the active part."""
    return _call_connected(
        lambda sw: cut_real_thread(sw, diameter, pitch, thread_length, profile_dia),
        launch_if_needed,
    )


def solidworks_part_create_linear_holes(
    diameter: PositiveMM,
    x: FiniteMM,
    y: FiniteMM,
    plane: NonEmptyString = "top",
    count: Annotated[int, Field(ge=1, le=200)] = 2,
    spacing: PositiveMM = 10.0,
    direction: Literal["x", "y"] = "x",
    depth: Optional[PositiveMM] = None,
    through_all: bool = True,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Cut a linear row of round holes (non-native rebuilt primitives, not parametric-linked; native pattern API blocked on SW 2026)."""
    return _call_connected(
        lambda sw: create_linear_holes(
            sw, diameter, x, y, plane, count, spacing, direction, depth, through_all
        ),
        launch_if_needed,
    )


def solidworks_pattern_annular_layout(
    rings: List[AnnularRing],
    avoid_angles_degrees: Optional[List[float]] = None,
) -> ToolResult:
    """Compute ring positions, optimized phases, and overlap warnings without touching SolidWorks."""
    try:
        layout = build_annular_layout(rings, avoid_angles_degrees)
    except (ValueError, ValidationError) as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    return success_response(
        data=layout,
        message=(
            f"Annular layout: {layout['total_feature_count']} features "
            f"on {len(layout['rings'])} rings"
        ),
    )


def solidworks_part_circular_pattern(
    seed_feature: NonEmptyString,
    axis_feature: NonEmptyString,
    instance_count: int,
    angle_deg: float = 360.0,
    equal_spacing: bool = True,
    pattern_name: Optional[NonEmptyString] = None,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Circular pattern of a feature around an axis (drives the PM pane UI; needs a visible, maximized SolidWorks window and pywinauto)."""
    return _call_connected(
        lambda sw: create_circular_pattern(
            sw,
            seed_feature,
            axis_feature,
            instance_count,
            angle_deg,
            equal_spacing,
            pattern_name,
        ),
        launch_if_needed,
    )


def solidworks_part_create_annular_pattern(
    rings: List[AnnularRing],
    plane: NonEmptyString = "top",
    feature_kind: Literal["cut", "boss"] = "cut",
    depth: Optional[PositiveMM] = None,
    through_all: bool = True,
    avoid_angles_degrees: Optional[List[float]] = None,
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Cut or extrude concentric rings of circular features on a named plane (bosses always blind)."""
    return _call_connected(
        lambda sw: create_annular_pattern(
            sw,
            rings,
            plane=plane,
            feature_kind=feature_kind,
            depth=depth,
            through_all=through_all,
            avoid_angles_degrees=avoid_angles_degrees,
            save_path=save_path,
            overwrite_confirm=overwrite_confirm,
        ),
        launch_if_needed,
    )


def solidworks_sheet_metal_base_flange(
    width: PositiveMM,
    depth: PositiveMM,
    thickness: PositiveMM,
    radius: float = 0.0,
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Create a sheet-metal part from a centred rectangular base flange (GB, flat v1)."""
    return _call_connected(
        lambda sw: create_base_flange(
            sw, width, depth, thickness, radius, save_path, overwrite_confirm
        ),
        launch_if_needed,
    )


def solidworks_design_execute_plan(
    operations: List[Dict[str, Any]],
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Execute ordered design operations: new_part, box, plate, cylinder, cone, hole, threaded_hole, annular_pattern."""
    return _call_connected(
        lambda sw: execute_design_plan(
            sw, operations, save_path, overwrite_confirm
        ),
        launch_if_needed,
    )


def solidworks_part_get_mass_properties(
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Read volume, area, mass, center of mass, and their SI units."""
    return _call_connected(get_mass_properties, launch_if_needed)


def solidworks_part_list_faces(
    name_prefix: str = "Face",
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Enumerate solid faces (type/area mm2); unnamed faces get stable entity names for mating. Large models require one COM round-trip per face; expect slower responses on 1000+ face parts."""
    return _call_connected(
        lambda sw: list_faces(sw, name_prefix),
        launch_if_needed,
    )


def solidworks_part_list_bodies(
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """List solid bodies with names and face counts."""
    return _call_connected(list_bodies, launch_if_needed)


def register(mcp) -> None:
    mcp.tool(title="Create new part", annotations=STATE_CHANGE, structured_output=True)(
        solidworks_part_new
    )
    mcp.tool(
        title="Create rectangular plate", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_create_plate)
    mcp.tool(title="Create box", annotations=STATE_CHANGE, structured_output=True)(
        solidworks_part_create_box
    )
    mcp.tool(
        title="Create cylinder", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_create_cylinder)
    mcp.tool(title="Cut round hole", annotations=DESTRUCTIVE, structured_output=True)(
        solidworks_part_cut_round_hole
    )
    mcp.tool(title="Create cone", annotations=STATE_CHANGE, structured_output=True)(
        solidworks_part_create_cone
    )
    mcp.tool(
        title="Create revolved part", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_create_revolved)
    mcp.tool(
        title="Create swept part", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_create_swept)
    mcp.tool(
        title="Create lofted part", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_create_loft)
    mcp.tool(
        title="Create regular polygon prism",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_part_create_polygon)
    mcp.tool(
        title="Create slot plate", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_create_slot)
    mcp.tool(
        title="Create reference plane",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_part_create_ref_plane)
    mcp.tool(
        title="Create reference axis",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_part_create_ref_axis)
    mcp.tool(
        title="Create rib plate", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_create_rib)
    mcp.tool(
        title="Apply dome to face", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_apply_dome)
    mcp.tool(
        title="Apply fillet to faces", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_apply_fillet)
    mcp.tool(
        title="Apply chamfer to faces", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_apply_chamfer)
    mcp.tool(title="Shell part", annotations=STATE_CHANGE, structured_output=True)(
        solidworks_part_apply_shell
    )
    mcp.tool(title="Cut threaded hole", annotations=DESTRUCTIVE, structured_output=True)(
        solidworks_part_cut_threaded_hole
    )
    mcp.tool(
        title="Cut real helical thread", annotations=DESTRUCTIVE, structured_output=True
    )(solidworks_part_cut_real_thread)
    mcp.tool(
        title="Create linear hole row", annotations=DESTRUCTIVE, structured_output=True
    )(solidworks_part_create_linear_holes)
    mcp.tool(
        title="Preview annular pattern layout",
        annotations=READ_ONLY,
        structured_output=True,
    )(solidworks_pattern_annular_layout)
    mcp.tool(
        title="Create annular feature pattern",
        annotations=DESTRUCTIVE,
        structured_output=True,
    )(solidworks_part_create_annular_pattern)
    mcp.tool(
        title="Create circular pattern",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_part_circular_pattern)
    mcp.tool(
        title="Sheet-metal base flange", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_sheet_metal_base_flange)
    mcp.tool(
        title="Execute design plan", annotations=DESTRUCTIVE, structured_output=True
    )(solidworks_design_execute_plan)
    mcp.tool(
        title="Get mass properties", annotations=READ_ONLY, structured_output=True
    )(solidworks_part_get_mass_properties)
    mcp.tool(
        title="List and name faces", annotations=STATE_CHANGE, structured_output=True
    )(solidworks_part_list_faces)
    mcp.tool(
        title="List solid bodies", annotations=READ_ONLY, structured_output=True
    )(solidworks_part_list_bodies)
