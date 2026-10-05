"""Parametric spherical-dome ring-light generator for SolidWorks."""

from __future__ import annotations

import json
import logging
import math
import pythoncom
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from solidworks_mcp.solidworks_api.app import SolidWorksApp, SolidWorksNotRunningError
from solidworks_mcp.solidworks_api.constants import (
    swFileSaveErrorNone,
    swSaveAsOptions_Silent,
)
from solidworks_mcp.solidworks_api.design import create_new_part
from solidworks_mcp.solidworks_api.geometry import (
    latest_feature_name as _latest_feature_name,
)
from solidworks_mcp.solidworks_api.geometry import (
    linspace,
    mm_to_m,
    select_plane,
)
from solidworks_mcp.solidworks_api.part import create_cylinder
from solidworks_mcp.solidworks_api.sketch import cut_feature, extrude_boss
from solidworks_mcp.utils.common import error_response, success_response
from solidworks_mcp.utils.security import (
    check_overwrite_confirm,
    ensure_sink_path,
    normalize_path,
    validate_output_file,
)
from solidworks_mcp.utils.validation import positive_number

logger = logging.getLogger(__name__)

_FRONT_PLANE_CANDIDATES = ("Front Plane", "前视基准面")

DEFAULT_ROW_COUNTS = tuple(range(21, 30))
DEFAULT_START_ANGLE_DEGREES = 30.0
DEFAULT_END_ANGLE_DEGREES = 60.0
DEFAULT_OUTER_DIAMETER_MM = 80.0
DEFAULT_CENTER_HOLE_DIAMETER_MM = 40.0
DEFAULT_CARRIER_THICKNESS_MM = 60.0
DEFAULT_LED_DIAMETER_MM = 2.6
DEFAULT_DOME_HEIGHT_MM = 16.0
DEFAULT_MOUNT_PCD_MM = 56.0
DEFAULT_MOUNT_HOLE_DIAMETER_MM = 3.0
DEFAULT_OUTER_MOUNT_PCD_MM = 74.0
DEFAULT_OUTER_MOUNT_HOLE_DIAMETER_MM = 3.65
DEFAULT_RADIAL_EDGE_MARGIN_MM = 2.0

Vector = Tuple[float, float, float]
Triangle = Tuple[Vector, Vector, Vector]


def _angular_distance_degrees(a: float, b: float) -> float:
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def _best_phase(count: int, blocked_angles: Sequence[float]) -> float:
    pitch = 360.0 / count
    candidates = [pitch * i / 72.0 for i in range(72)]
    best_phase = 0.0
    best_clearance = -1.0
    for phase in candidates:
        clearance = min(
            _angular_distance_degrees(phase + k * pitch, blocked)
            for k in range(count)
            for blocked in blocked_angles
        )
        if clearance > best_clearance:
            best_phase = phase
            best_clearance = clearance
    return best_phase


def build_ring_light_layout(
    *,
    outer_diameter: float = DEFAULT_OUTER_DIAMETER_MM,
    center_hole_diameter: float = DEFAULT_CENTER_HOLE_DIAMETER_MM,
    carrier_thickness: float = DEFAULT_CARRIER_THICKNESS_MM,
    led_diameter: float = DEFAULT_LED_DIAMETER_MM,
    row_counts: Optional[Sequence[int]] = None,
    start_angle_degrees: float = DEFAULT_START_ANGLE_DEGREES,
    end_angle_degrees: float = DEFAULT_END_ANGLE_DEGREES,
    dome_height: float = DEFAULT_DOME_HEIGHT_MM,
    radial_edge_margin: float = DEFAULT_RADIAL_EDGE_MARGIN_MM,
) -> dict:
    """Return the deterministic 9-row ring-light layout in millimeters."""
    outer_diameter = positive_number("outer_diameter", outer_diameter)
    center_hole_diameter = positive_number("center_hole_diameter", center_hole_diameter)
    carrier_thickness = positive_number("carrier_thickness", carrier_thickness)
    led_diameter = positive_number("led_diameter", led_diameter)
    dome_height = positive_number("dome_height", dome_height)
    radial_edge_margin = positive_number("radial_edge_margin", radial_edge_margin)
    counts = tuple(DEFAULT_ROW_COUNTS if row_counts is None else row_counts)
    if not 1 <= len(counts) <= 64:
        raise ValueError("row_counts must contain between 1 and 64 rows")
    if any(int(c) <= 0 for c in counts):
        raise ValueError("row_counts must contain positive integers")
    counts = tuple(int(c) for c in counts)
    if center_hole_diameter >= outer_diameter:
        raise ValueError("center_hole_diameter must be smaller than outer_diameter")
    usable_radial_width = (outer_diameter - center_hole_diameter) / 2.0
    if usable_radial_width <= 2.0 * radial_edge_margin:
        raise ValueError("not enough radial width for the requested edge margins")

    row_angles = linspace(
        float(start_angle_degrees), float(end_angle_degrees), len(counts)
    )
    if not 0.0 < row_angles[0] < row_angles[-1] < 90.0:
        raise ValueError("row angles must satisfy 0 < start < end < 90 degrees")

    inner_row_radius = center_hole_diameter / 2.0 + radial_edge_margin
    sphere_radius = inner_row_radius / math.sin(math.radians(row_angles[0]))
    outer_row_radius = sphere_radius * math.sin(math.radians(row_angles[-1]))
    outer_radius = outer_diameter / 2.0
    if outer_row_radius + led_diameter / 2.0 > outer_radius:
        raise ValueError("spherical LED layout exceeds the carrier outer radius")

    sphere_center_z = -sphere_radius * math.cos(math.radians(row_angles[-1]))
    row_radii = [sphere_radius * math.sin(math.radians(angle)) for angle in row_angles]
    row_heights = [
        sphere_center_z + sphere_radius * math.cos(math.radians(angle))
        for angle in row_angles
    ]
    actual_dome_height = row_heights[0] - row_heights[-1]
    blocked_angles = [0.0, 45.0, 135.0, 225.0, 315.0]

    rows = []
    for index, (count, radius, z, angle) in enumerate(
        zip(counts, row_radii, row_heights, row_angles), start=1
    ):
        rows.append(
            {
                "row_index": index,
                "count": count,
                "radius_mm": round(radius, 6),
                "z_mm": round(z, 6),
                "angle_degrees": round(angle, 6),
                "phase_degrees": round(_best_phase(count, blocked_angles), 6),
            }
        )

    return {
        "outer_diameter_mm": outer_diameter,
        "center_hole_diameter_mm": center_hole_diameter,
        "carrier_thickness_mm": carrier_thickness,
        "led_diameter_mm": led_diameter,
        "dome_height_mm": round(actual_dome_height, 6),
        "requested_dome_height_mm": dome_height,
        "dome": {
            "profile": "spherical_cap",
            "sphere_radius_mm": round(sphere_radius, 6),
            "sphere_center_z_mm": round(sphere_center_z, 6),
            "inner_surface_z_mm": round(
                sphere_center_z
                + math.sqrt(
                    sphere_radius * sphere_radius
                    - (center_hole_diameter / 2.0) ** 2
                ),
                6,
            ),
            "outer_lip_z_mm": 0.0,
            "start_normal_angle_degrees": float(start_angle_degrees),
            "end_normal_angle_degrees": float(end_angle_degrees),
        },
        "row_counts": list(counts),
        "total_led_count": sum(counts),
        "rows": rows,
        "mounting": {
            "m3_pcd_mm": DEFAULT_MOUNT_PCD_MM,
            "m3_hole_diameter_mm": DEFAULT_MOUNT_HOLE_DIAMETER_MM,
            "outer_pcd_mm": DEFAULT_OUTER_MOUNT_PCD_MM,
            "outer_hole_diameter_mm": DEFAULT_OUTER_MOUNT_HOLE_DIAMETER_MM,
            "angles_degrees": [45.0, 135.0, 225.0, 315.0],
        },
        "cable_interface": {
            "angle_degrees": 0.0,
            "box_mm": {"length": 22.0, "width": 16.0, "height": 42.0},
        },
        "notes": [
            "LEDs are simplified dome bodies, not electrical package CAD.",
            "M3 and outer mounting holes are represented as through-hole geometry in the mesh body.",
            "Carrier front is a spherical cap; each LED axis follows the local surface normal.",
        ],
    }


def _add_triangle(triangles: List[Triangle], a: Vector, b: Vector, c: Vector) -> None:
    triangles.append((a, b, c))


def _sub(a: Vector, b: Vector) -> Vector:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vector, b: Vector) -> Vector:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(v: Vector) -> Vector:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length <= 1e-12:
        return (0.0, 0.0, 1.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _scale(v: Vector, factor: float) -> Vector:
    return (v[0] * factor, v[1] * factor, v[2] * factor)


def _add(a: Vector, b: Vector) -> Vector:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _surface_z(layout: dict, radius: float) -> float:
    dome = layout["dome"]
    sphere_radius = float(dome["sphere_radius_mm"])
    sphere_center_z = float(dome["sphere_center_z_mm"])
    outer_row_radius = float(layout["rows"][-1]["radius_mm"])
    if radius <= outer_row_radius:
        radial = min(max(float(radius), 0.0), sphere_radius)
        return sphere_center_z + math.sqrt(
            max(0.0, sphere_radius * sphere_radius - radial * radial)
        )
    return float(dome["outer_lip_z_mm"])


def build_spherical_dome_bands(layout: dict, step_count: int = 48) -> List[dict]:
    """Return concentric annular bands that approximate the spherical cap."""
    if int(step_count) < 8:
        raise ValueError("step_count must be at least 8")
    inner_radius = float(layout["center_hole_diameter_mm"]) / 2.0
    outer_radius = float(layout["rows"][-1]["radius_mm"])
    bounds = linspace(inner_radius, outer_radius, int(step_count) + 1)
    bands = []
    for index, (r0, r1) in enumerate(zip(bounds, bounds[1:]), start=1):
        sample_radius = (r0 + r1) / 2.0
        bands.append(
            {
                "band_index": index,
                "inner_radius_mm": round(r0, 6),
                "outer_radius_mm": round(r1, 6),
                "extrusion_height_mm": round(
                    float(layout["carrier_thickness_mm"])
                    + _surface_z(layout, sample_radius),
                    6,
                ),
            }
        )
    return bands

def _hole_specs(layout: dict) -> List[Tuple[float, float, float]]:
    holes = []
    for angle in layout["mounting"]["angles_degrees"]:
        rad = math.radians(angle)
        holes.append(
            (
                layout["mounting"]["m3_pcd_mm"] / 2.0 * math.cos(rad),
                layout["mounting"]["m3_pcd_mm"] / 2.0 * math.sin(rad),
                layout["mounting"]["m3_hole_diameter_mm"] / 2.0,
            )
        )
        holes.append(
            (
                layout["mounting"]["outer_pcd_mm"] / 2.0 * math.cos(rad),
                layout["mounting"]["outer_pcd_mm"] / 2.0 * math.sin(rad),
                layout["mounting"]["outer_hole_diameter_mm"] / 2.0,
            )
        )
    return holes


def _inside_aux_hole(x: float, y: float, holes: Iterable[Tuple[float, float, float]]) -> bool:
    for hx, hy, hr in holes:
        if (x - hx) * (x - hx) + (y - hy) * (y - hy) < hr * hr:
            return True
    return False


def _add_ring_body(triangles: List[Triangle], layout: dict) -> None:
    outer_r = layout["outer_diameter_mm"] / 2.0
    inner_r = layout["center_hole_diameter_mm"] / 2.0
    back_z = -layout["carrier_thickness_mm"]
    radial_steps = 72
    angular_steps = 360
    holes = _hole_specs(layout)

    radii = [inner_r + (outer_r - inner_r) * i / radial_steps for i in range(radial_steps + 1)]
    angles = [2.0 * math.pi * j / angular_steps for j in range(angular_steps + 1)]

    def point(radius: float, angle: float, z: float) -> Vector:
        return (radius * math.cos(angle), radius * math.sin(angle), z)

    for i in range(radial_steps):
        r0 = radii[i]
        r1 = radii[i + 1]
        for j in range(angular_steps):
            a0 = angles[j]
            a1 = angles[j + 1]
            corners = [
                (r0 * math.cos(a0), r0 * math.sin(a0), r0, a0),
                (r1 * math.cos(a0), r1 * math.sin(a0), r1, a0),
                (r1 * math.cos(a1), r1 * math.sin(a1), r1, a1),
                (r0 * math.cos(a1), r0 * math.sin(a1), r0, a1),
            ]
            if any(_inside_aux_hole(x, y, holes) for x, y, _r, _a in corners):
                continue
            p0f = point(r0, a0, _surface_z(layout, r0))
            p1f = point(r1, a0, _surface_z(layout, r1))
            p2f = point(r1, a1, _surface_z(layout, r1))
            p3f = point(r0, a1, _surface_z(layout, r0))
            _add_triangle(triangles, p0f, p1f, p2f)
            _add_triangle(triangles, p0f, p2f, p3f)
            p0b = point(r0, a0, back_z)
            p1b = point(r1, a0, back_z)
            p2b = point(r1, a1, back_z)
            p3b = point(r0, a1, back_z)
            _add_triangle(triangles, p0b, p2b, p1b)
            _add_triangle(triangles, p0b, p3b, p2b)

    for boundary_r, reverse in ((inner_r, True), (outer_r, False)):
        for j in range(angular_steps):
            a0 = angles[j]
            a1 = angles[j + 1]
            p0 = point(boundary_r, a0, _surface_z(layout, boundary_r))
            p1 = point(boundary_r, a1, _surface_z(layout, boundary_r))
            p2 = point(boundary_r, a1, back_z)
            p3 = point(boundary_r, a0, back_z)
            if reverse:
                _add_triangle(triangles, p0, p2, p1)
                _add_triangle(triangles, p0, p3, p2)
            else:
                _add_triangle(triangles, p0, p1, p2)
                _add_triangle(triangles, p0, p2, p3)

    for hx, hy, hr in holes:
        segments = 36
        for j in range(segments):
            a0 = 2.0 * math.pi * j / segments
            a1 = 2.0 * math.pi * (j + 1) / segments
            x0, y0 = hx + hr * math.cos(a0), hy + hr * math.sin(a0)
            x1, y1 = hx + hr * math.cos(a1), hy + hr * math.sin(a1)
            z0 = _surface_z(layout, math.hypot(x0, y0))
            z1 = _surface_z(layout, math.hypot(x1, y1))
            p0 = (x0, y0, z0)
            p1 = (x1, y1, z1)
            p2 = (x1, y1, back_z)
            p3 = (x0, y0, back_z)
            _add_triangle(triangles, p0, p2, p1)
            _add_triangle(triangles, p0, p3, p2)


def _add_box(triangles: List[Triangle], x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> None:
    p000 = (x0, y0, z0)
    p001 = (x0, y0, z1)
    p010 = (x0, y1, z0)
    p011 = (x0, y1, z1)
    p100 = (x1, y0, z0)
    p101 = (x1, y0, z1)
    p110 = (x1, y1, z0)
    p111 = (x1, y1, z1)
    faces = [
        (p000, p100, p110, p010),
        (p001, p011, p111, p101),
        (p000, p001, p101, p100),
        (p010, p110, p111, p011),
        (p000, p010, p011, p001),
        (p100, p101, p111, p110),
    ]
    for a, b, c, d in faces:
        _add_triangle(triangles, a, b, c)
        _add_triangle(triangles, a, c, d)


def _add_led_domes(triangles: List[Triangle], layout: dict) -> None:
    led_radius = layout["led_diameter_mm"] / 2.0
    ring_segments = 12
    cap_segments = 8
    z_axis = (0.0, 0.0, 1.0)

    for row in layout["rows"]:
        count = row["count"]
        row_radius = row["radius_mm"]
        theta = math.radians(row["angle_degrees"])
        phase = math.radians(row["phase_degrees"])
        for led_index in range(count):
            phi = phase + 2.0 * math.pi * led_index / count
            radial = (math.cos(phi), math.sin(phi), 0.0)
            tangent = (-math.sin(phi), math.cos(phi), 0.0)
            axis = _norm((math.sin(theta) * radial[0], math.sin(theta) * radial[1], math.cos(theta)))
            e1 = tangent
            e2 = _norm(_cross(axis, e1))
            base = (row_radius * radial[0], row_radius * radial[1], row["z_mm"])
            grid: List[List[Vector]] = []
            for i in range(cap_segments + 1):
                polar = (math.pi / 2.0) * i / cap_segments
                ring = []
                for j in range(ring_segments):
                    az = 2.0 * math.pi * j / ring_segments
                    local = _add(
                        _add(_scale(e1, math.sin(polar) * math.cos(az)), _scale(e2, math.sin(polar) * math.sin(az))),
                        _scale(axis, math.cos(polar)),
                    )
                    ring.append(_add(base, _scale(local, led_radius)))
                grid.append(ring)
            for i in range(cap_segments):
                for j in range(ring_segments):
                    j2 = (j + 1) % ring_segments
                    p00 = grid[i][j]
                    p01 = grid[i][j2]
                    p10 = grid[i + 1][j]
                    p11 = grid[i + 1][j2]
                    _add_triangle(triangles, p00, p10, p11)
                    _add_triangle(triangles, p00, p11, p01)
            center = _add(base, _scale(axis, 0.02))
            equator = grid[-1]
            for j in range(ring_segments):
                _add_triangle(triangles, center, equator[(j + 1) % ring_segments], equator[j])


def _write_ascii_stl(
    triangles: Sequence[Triangle], stl_path: str, solid_name: str
) -> None:
    with open(stl_path, "w", encoding="ascii", newline="\n") as handle:
        handle.write(f"solid {solid_name}\n")
        for a, b, c in triangles:
            normal = _norm(_cross(_sub(b, a), _sub(c, a)))
            handle.write(f"  facet normal {normal[0]:.8e} {normal[1]:.8e} {normal[2]:.8e}\n")
            handle.write("    outer loop\n")
            for p in (a, b, c):
                handle.write(f"      vertex {p[0]:.8e} {p[1]:.8e} {p[2]:.8e}\n")
            handle.write("    endloop\n")
            handle.write("  endfacet\n")
        handle.write(f"endsolid {solid_name}\n")


def write_ring_light_stl(layout: dict, stl_path: str) -> dict:
    """Write the ring-light geometry as an ASCII STL in millimeters."""
    triangles: List[Triangle] = []
    _add_ring_body(triangles, layout)
    outer_r = layout["outer_diameter_mm"] / 2.0
    _add_box(
        triangles,
        outer_r - 1.0,
        outer_r + 22.0,
        -8.0,
        8.0,
        -layout["carrier_thickness_mm"],
        -18.0,
    )
    _add_led_domes(triangles, layout)
    rows = layout["rows"]
    solid_name = (
        f"ring_light_{len(rows)}row_{rows[0]['count']}_{rows[-1]['count']}_mm"
    )
    _write_ascii_stl(triangles, stl_path, solid_name)
    return {"triangle_count": len(triangles), "stl_path": stl_path}



def _select_latest_sketch(model: Any) -> bool:
    sketch_name = _latest_feature_name(model)
    if not sketch_name:
        return False
    model.ClearSelection2(True)
    return bool(
        model.Extension.SelectByID2(
            sketch_name,
            "SKETCH",
            0,
            0,
            0,
            False,
            0,
            pythoncom.Nothing,
            0,
        )
    )


def _cut_selected_sketch_through_all(model: Any, nominal_depth_mm: float) -> Any:
    return cut_feature(model, True, True, 1, mm_to_m(nominal_depth_mm))


def _extrude_selected_sketch(model: Any, height_mm: float) -> Any:
    return extrude_boss(model, mm_to_m(height_mm))


def _create_circle_sketch(model: Any, circles: Sequence[Tuple[float, float, float]]) -> bool:
    if not select_plane(model, list(_FRONT_PLANE_CANDIDATES)):
        return False
    model.SketchManager.InsertSketch(True)
    for x_mm, y_mm, radius_mm in circles:
        model.SketchManager.CreateCircleByRadius(mm_to_m(x_mm), mm_to_m(y_mm), 0, mm_to_m(radius_mm))
    model.SketchManager.InsertSketch(True)
    return _select_latest_sketch(model)


def _create_stepped_spherical_dome(
    model: Any, layout: dict, step_count: int = 48
) -> Optional[List[str]]:
    feature_names: List[str] = []
    for band in build_spherical_dome_bands(layout, step_count=step_count):
        circles = [
            (0.0, 0.0, float(band["inner_radius_mm"])),
            (0.0, 0.0, float(band["outer_radius_mm"])),
        ]
        if not _create_circle_sketch(model, circles):
            return None
        feature = _extrude_selected_sketch(
            model, float(band["extrusion_height_mm"])
        )
        if feature is None:
            return None
        feature.Name = (
            f"SPHERICAL_DOME_BAND_{int(band['band_index']):02d}_"
            f"R{float(band['inner_radius_mm']):.2f}_"
            f"TO_{float(band['outer_radius_mm']):.2f}"
        )
        feature_names.append(feature.Name)
    return feature_names

def _create_led_marker_boss(model: Any, layout: dict) -> Any:
    features = []
    led_radius = layout["led_diameter_mm"] / 2.0
    for row in layout["rows"]:
        circles: List[Tuple[float, float, float]] = []
        count = int(row["count"])
        row_radius = float(row["radius_mm"])
        phase = math.radians(float(row["phase_degrees"]))
        for index in range(count):
            angle = phase + 2.0 * math.pi * index / count
            circles.append((row_radius * math.cos(angle), row_radius * math.sin(angle), led_radius))
        if not _create_circle_sketch(model, circles):
            return None
        feature = _extrude_selected_sketch(
            model, float(layout["carrier_thickness_mm"]) + float(row["z_mm"]) + 1.2
        )
        if feature is None:
            return None
        feature.Name = f"LED_ROW_{int(row['row_index']):02d}_COUNT_{count}"
        features.append(feature.Name)
    return features


def _create_cable_interface_boss(model: Any, layout: dict) -> Any:
    outer_r = layout["outer_diameter_mm"] / 2.0
    if not select_plane(model, list(_FRONT_PLANE_CANDIDATES)):
        return None
    model.SketchManager.InsertSketch(True)
    model.SketchManager.CreateCornerRectangle(
        mm_to_m(outer_r - 1.0),
        mm_to_m(-8.0),
        0,
        mm_to_m(outer_r + 22.0),
        mm_to_m(8.0),
        0,
    )
    model.SketchManager.InsertSketch(True)
    if not _select_latest_sketch(model):
        return None
    feature = _extrude_selected_sketch(model, 42.0)
    if feature is not None:
        feature.Name = "CABLE_INTERFACE_PLACEHOLDER"
    return feature


def _save_native_fallback(sw_app: SolidWorksApp, layout: dict, save_path: str) -> dict:
    result = create_new_part(sw_app)
    if not result.get("success"):
        return result
    result = create_cylinder(
        sw_app,
        diameter=layout["outer_diameter_mm"],
        height=layout["carrier_thickness_mm"],
    )
    if not result.get("success"):
        return result
    model = sw_app.get_active_document()
    if model is None:
        return error_response("No active document after creating carrier cylinder", code="SW_API_ERROR")

    dome_feature_names = _create_stepped_spherical_dome(
        model, layout, step_count=24
    )
    if dome_feature_names is None:
        return error_response(
            "Could not create native stepped spherical dome",
            code="SW_API_ERROR",
        )

    holes: List[Tuple[float, float, float]] = [(0.0, 0.0, layout["center_hole_diameter_mm"] / 2.0)]
    for angle in layout["mounting"]["angles_degrees"]:
        rad = math.radians(float(angle))
        holes.append((layout["mounting"]["m3_pcd_mm"] / 2.0 * math.cos(rad), layout["mounting"]["m3_pcd_mm"] / 2.0 * math.sin(rad), layout["mounting"]["m3_hole_diameter_mm"] / 2.0))
        holes.append((layout["mounting"]["outer_pcd_mm"] / 2.0 * math.cos(rad), layout["mounting"]["outer_pcd_mm"] / 2.0 * math.sin(rad), layout["mounting"]["outer_hole_diameter_mm"] / 2.0))
    if not _create_circle_sketch(model, holes):
        return error_response("Could not create fallback interface hole sketch", code="SW_API_ERROR")
    hole_feature = _cut_selected_sketch_through_all(model, layout["carrier_thickness_mm"] + 20.0)
    if hole_feature is None:
        return error_response("Could not cut fallback interface holes", code="SW_API_ERROR")
    hole_feature.Name = "DXF_INTERFACE_HOLES"

    cable_feature = _create_cable_interface_boss(model, layout)
    if cable_feature is None:
        return error_response("Could not create fallback cable interface boss", code="SW_API_ERROR")
    led_feature = _create_led_marker_boss(model, layout)
    if led_feature is None:
        return error_response("Could not create fallback LED marker bosses", code="SW_API_ERROR")
    try:
        model.ForceRebuild3(False)
    except Exception:
        pass
    ok, message, sink_path = ensure_sink_path(save_path)
    if not ok:
        return error_response(message, code="INVALID_OUTPUT_PATH")
    save_result = model.SaveAs3(sink_path, 0, swSaveAsOptions_Silent)
    if save_result != swFileSaveErrorNone:
        return error_response(f"SaveAs3 failed with code {save_result}", code="SW_SAVE_FAILED")
    led_total = int(layout["total_led_count"])
    return success_response(
        data={
            "saved_to": save_path,
            "native_dome_model": True,
            "features": [
                "BASE_CYLINDER",
                *dome_feature_names,
                "DXF_INTERFACE_HOLES",
                "CABLE_INTERFACE_PLACEHOLDER",
                f"LED_MARKERS_{led_total}_DOME_HEIGHT",
            ],
            "total_led_count": layout["total_led_count"],
            "rows": layout["rows"],
            "dome": layout["dome"],
            "native_dome_approximation": {
                "type": "24_concentric_annular_bands",
                "band_count": len(dome_feature_names),
            },
        },
        message=(
            "Created native spherical-dome approximation with DXF interfaces "
            f"and {led_total} LED markers"
        ),
        warning=(
            "SolidWorks 2026 rejected FeatureRevolve2 in this late-bound COM "
            "environment, so the native carrier uses 24 concentric annular bands. "
            "The exact spherical surface and 30-60 degree LED axes are preserved "
            "in the generated STL and layout JSON."
        ),
    )

def create_ring_light(
    sw_app: SolidWorksApp,
    save_path: str,
    overwrite_confirm: bool = False,
    outer_diameter: float = DEFAULT_OUTER_DIAMETER_MM,
    center_hole_diameter: float = DEFAULT_CENTER_HOLE_DIAMETER_MM,
    carrier_thickness: float = DEFAULT_CARRIER_THICKNESS_MM,
    led_diameter: float = DEFAULT_LED_DIAMETER_MM,
    row_counts: Optional[Sequence[int]] = None,
    start_angle_degrees: float = DEFAULT_START_ANGLE_DEGREES,
    end_angle_degrees: float = DEFAULT_END_ANGLE_DEGREES,
) -> dict:
    """Create the confirmed 9-row ring-light part and save it as .SLDPRT."""
    try:
        valid, message = validate_output_file(save_path, {".sldprt"}, overwrite_confirm)
        if not valid:
            return error_response(message, code="INVALID_OUTPUT_PATH")

        layout = build_ring_light_layout(
            outer_diameter=outer_diameter,
            center_hole_diameter=center_hole_diameter,
            carrier_thickness=carrier_thickness,
            led_diameter=led_diameter,
            row_counts=row_counts,
            start_angle_degrees=start_angle_degrees,
            end_angle_degrees=end_angle_degrees,
        )
        save = Path(normalize_path(save_path))
        stl_path = str(save.with_suffix(".generated.stl"))
        metadata_path = str(save.with_suffix(".layout.json"))
        for derived in (stl_path, metadata_path):
            allowed, message = check_overwrite_confirm(derived, overwrite_confirm)
            if not allowed:
                return error_response(message, code="INVALID_OUTPUT_PATH")
            ok, message, derived = ensure_sink_path(derived)
            if not ok:
                return error_response(message, code="INVALID_OUTPUT_PATH")
        write_ring_light_stl(layout, stl_path)
        with open(metadata_path, "w", encoding="utf-8") as handle:
            json.dump(layout, handle, ensure_ascii=False, indent=2)
        return _save_native_fallback(sw_app, layout, save_path)
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc), code="SW_CONNECTION_FAILED")
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to create ring-light part")
        return error_response(
            f"Failed to create ring-light part: {exc}",
            code="SW_API_ERROR",
            details={"exception_type": type(exc).__name__},
        )



