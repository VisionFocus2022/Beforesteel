"""STEP-based concave ring-light v3 design path."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, List, Optional, Sequence

import pythoncom
import win32com.client

from solidworks_mcp.solidworks_api.app import SolidWorksApp, SolidWorksNotRunningError
from solidworks_mcp.solidworks_api.constants import (
    swDocPART,
    swOpenDocOptions_Silent,
    swSaveAsOptions_Silent,
)
from solidworks_mcp.solidworks_api.geometry import linspace, mm_to_m
from solidworks_mcp.solidworks_api.sketch import cut_feature, extrude_boss
from solidworks_mcp.utils.common import error_response, success_response
from solidworks_mcp.utils.com import call_or_value, make_error_variants
from solidworks_mcp.utils.security import (
    check_overwrite_confirm,
    ensure_sink_path,
    normalize_path,
    validate_output_file,
    validate_path,
)
from solidworks_mcp.utils.validation import positive_number


DEFAULT_ROW_COUNTS = tuple(range(21, 30))
DEFAULT_OUTER_DIAMETER_MM = 80.0
DEFAULT_CENTER_HOLE_DIAMETER_MM = 40.0
DEFAULT_LED_DIAMETER_MM = 2.6
DEFAULT_START_ANGLE_DEGREES = 30.0
DEFAULT_END_ANGLE_DEGREES = 60.0
DEFAULT_FRONT_FACE_Z_MM = 2.0
DEFAULT_BACK_FACE_Z_MM = -16.0
DEFAULT_OUTER_ROW_Z_MM = 1.5
DEFAULT_REFERENCE_TOTAL_DEPTH_MM = 18.0025
DEFAULT_NATIVE_INNER_LIP_MM = 1.13


def _mounting_holes() -> List[dict]:
    holes: List[dict] = []
    for radius_mm, hole_radius_mm, label in (
        (28.0, 1.25, "M3_PCD56"),
        (37.0, 1.825, "OUTER_PCD74"),
    ):
        for angle_degrees in (0.0, 90.0, 180.0, 270.0):
            angle = math.radians(angle_degrees)
            holes.append(
                {
                    "label": label,
                    "x_mm": round(radius_mm * math.cos(angle), 6),
                    "y_mm": round(radius_mm * math.sin(angle), 6),
                    "radius_mm": hole_radius_mm,
                }
            )
    return holes


def _distance_to_hole(row_radius_mm: float, angle_degrees: float, hole: dict) -> float:
    angle = math.radians(angle_degrees)
    return math.hypot(
        row_radius_mm * math.cos(angle) - hole["x_mm"],
        row_radius_mm * math.sin(angle) - hole["y_mm"],
    )


def _layout_row_angles(
    count: int,
    row_radius_mm: float,
    holes: Sequence[dict],
    led_radius_mm: float,
    clearance_mm: float = 1.5,
    rib_keepout_degrees: float = 8.0,
) -> List[float]:
    """Distribute a row over allowed arcs while preserving mounting-hole and rib keepouts."""
    resolution_degrees = 0.05
    sample_count = int(round(360.0 / resolution_degrees))
    allowed = []
    for index in range(sample_count):
        angle = index * resolution_degrees
        nearest_axis = min(
            abs((angle - cardinal + 180.0) % 360.0 - 180.0)
            for cardinal in (0.0, 90.0, 180.0, 270.0)
        )
        if nearest_axis < rib_keepout_degrees:
            continue
        if all(
            _distance_to_hole(row_radius_mm, angle, hole)
            >= led_radius_mm + hole["radius_mm"] + clearance_mm
            for hole in holes
        ):
            allowed.append(angle)
    if len(allowed) < count:
        raise ValueError(f"row with {count} LEDs has insufficient mounting-hole clearance")

    allowed_pitch = len(allowed) / count
    offset_candidates = max(24, min(240, int(math.ceil(allowed_pitch))))
    best_angles: List[float] = []
    best_score = (-math.inf, -math.inf)
    for offset_index in range(offset_candidates):
        offset = allowed_pitch * offset_index / offset_candidates
        angles = [
            allowed[int(round((offset + led_index * allowed_pitch) % len(allowed))) % len(allowed)]
            for led_index in range(count)
        ]
        hole_margin = min(
            _distance_to_hole(row_radius_mm, angle, hole)
            - led_radius_mm
            - hole["radius_mm"]
            for angle in angles
            for hole in holes
        )
        sorted_angles = sorted(angles)
        gaps = [
            (sorted_angles[(index + 1) % count] - sorted_angles[index]) % 360.0
            for index in range(count)
        ]
        center_spacing = min(
            2.0 * row_radius_mm * math.sin(math.radians(gap) / 2.0) for gap in gaps
        )
        score = (hole_margin, center_spacing)
        if score > best_score:
            best_score = score
            best_angles = sorted_angles
    if best_score[0] + 1e-6 < clearance_mm:
        raise ValueError(f"row with {count} LEDs cannot clear the STEP mounting holes")
    return [round(angle, 6) for angle in best_angles]


def build_ring_light_v3_layout(
    *,
    outer_diameter: float = DEFAULT_OUTER_DIAMETER_MM,
    center_hole_diameter: float = DEFAULT_CENTER_HOLE_DIAMETER_MM,
    led_diameter: float = DEFAULT_LED_DIAMETER_MM,
    row_counts: Optional[Sequence[int]] = None,
    start_angle_degrees: float = DEFAULT_START_ANGLE_DEGREES,
    end_angle_degrees: float = DEFAULT_END_ANGLE_DEGREES,
    front_face_z: float = DEFAULT_FRONT_FACE_Z_MM,
    back_face_z: float = DEFAULT_BACK_FACE_Z_MM,
    outer_row_z: float = DEFAULT_OUTER_ROW_Z_MM,
) -> dict:
    """Build the STEP-constrained concave dish layout in millimeters."""
    outer_diameter = positive_number("outer_diameter", outer_diameter)
    center_hole_diameter = positive_number("center_hole_diameter", center_hole_diameter)
    led_diameter = positive_number("led_diameter", led_diameter)
    counts = tuple(DEFAULT_ROW_COUNTS if row_counts is None else (int(v) for v in row_counts))
    if not 1 <= len(counts) <= 64 or any(value <= 0 for value in counts):
        raise ValueError("row_counts must contain between 1 and 64 positive integers")
    if center_hole_diameter >= outer_diameter:
        raise ValueError("center_hole_diameter must be smaller than outer_diameter")
    angles = linspace(
        float(start_angle_degrees), float(end_angle_degrees), len(counts)
    )
    if not 0.0 < angles[0] < angles[-1] < 90.0:
        raise ValueError("row angles must satisfy 0 < start < end < 90 degrees")
    if not back_face_z < outer_row_z < front_face_z:
        raise ValueError("outer_row_z must lie between the STEP back and front faces")

    inner_row_radius = center_hole_diameter / 2.0 + 2.0
    sphere_radius = inner_row_radius / math.sin(math.radians(angles[0]))
    outer_reference_angle = math.radians(angles[-1])
    outer_row_radius = sphere_radius * math.sin(outer_reference_angle)
    if outer_row_radius + led_diameter / 2.0 > outer_diameter / 2.0:
        raise ValueError("LED rows exceed the STEP outer diameter")

    holes = _mounting_holes()
    rows = []
    for row_index, (count, angle_degrees) in enumerate(zip(counts, angles), start=1):
        theta = math.radians(angle_degrees)
        radius = sphere_radius * math.sin(theta)
        z = outer_row_z + sphere_radius * (math.cos(outer_reference_angle) - math.cos(theta))
        led_angles = _layout_row_angles(count, radius, holes, led_diameter / 2.0)
        rows.append(
            {
                "row_index": row_index,
                "count": count,
                "radius_mm": round(radius, 6),
                "z_mm": round(z, 6),
                "angle_degrees": round(angle_degrees, 6),
                "phase_degrees": led_angles[0],
                "led_angles_degrees": led_angles,
                "sample_led_axis": [
                    round(-math.sin(theta), 9),
                    0.0,
                    round(math.cos(theta), 9),
                ],
            }
        )

    inner_radius = center_hole_diameter / 2.0
    inner_edge_z = outer_row_z + sphere_radius * math.cos(outer_reference_angle) - math.sqrt(
        sphere_radius * sphere_radius - inner_radius * inner_radius
    )
    minimum_back_thickness = inner_edge_z - back_face_z
    if minimum_back_thickness <= 0.0:
        raise ValueError("concave dish penetrates the STEP back face")

    return {
        "surface_profile": "spherical_concave_dish",
        "source_geometry": "MV-LRSS-H-80-W STEP/DXF",
        "outer_diameter_mm": outer_diameter,
        "center_hole_diameter_mm": center_hole_diameter,
        "reference_total_depth_mm": DEFAULT_REFERENCE_TOTAL_DEPTH_MM,
        "front_face_z_mm": front_face_z,
        "back_face_z_mm": back_face_z,
        "led_diameter_mm": led_diameter,
        "row_counts": list(counts),
        "total_led_count": sum(counts),
        "rows": rows,
        "dish": {
            "sphere_radius_mm": round(sphere_radius, 6),
            "outer_row_z_mm": outer_row_z,
            "inner_edge_z_mm": round(inner_edge_z, 6),
            "minimum_back_thickness_mm": round(minimum_back_thickness, 6),
            "front_recess_at_outer_row_mm": round(front_face_z - outer_row_z, 6),
            "normal_direction": "inward_toward_axis",
        },
        "mounting": {
            "holes": holes,
            "source": "STEP/DXF PCD56 and PCD74 cardinal axes",
        },
        "cable_interface": {"source": "preserved from STEP body"},
        "native_approximation": {
            "dish_band_count": 48,
            "dish_cut_style": "four_quadrant_sector_bands_with_cardinal_ribs",
            "cardinal_rib_keepout_degrees": 8.0,
            "inner_lip_width_mm": DEFAULT_NATIVE_INNER_LIP_MM,
            "inner_row_marker_style": "raised_boss",
            "inner_row_marker_height_mm": 0.3,
            "led_marker_depth_mm": 0.8,
        },
    }


def _concave_surface_z(layout: dict, radius_mm: float) -> float:
    sphere_radius = float(layout["dish"]["sphere_radius_mm"])
    outer_row_z = float(layout["dish"]["outer_row_z_mm"])
    end_angle = math.radians(float(layout["rows"][-1]["angle_degrees"]))
    return outer_row_z + sphere_radius * math.cos(end_angle) - math.sqrt(
        max(0.0, sphere_radius * sphere_radius - radius_mm * radius_mm)
    )


def build_concave_dish_bands(layout: dict, step_count: int = 48) -> List[dict]:
    """Return outer-to-inner blind-cut bands for the imported STEP front face."""
    if int(step_count) < 8:
        raise ValueError("step_count must be at least 8")
    inner_radius = (
        float(layout["center_hole_diameter_mm"]) / 2.0
        + float(layout.get("native_approximation", {}).get("inner_lip_width_mm", 0.0))
    )
    outer_radius = float(layout["rows"][-1]["radius_mm"])
    bounds = linspace(inner_radius, outer_radius, int(step_count) + 1)
    bands = []
    for band_index, index in enumerate(range(int(step_count) - 1, -1, -1), start=1):
        r0 = bounds[index]
        r1 = bounds[index + 1]
        sample = (r0 + r1) / 2.0
        bands.append(
            {
                "band_index": band_index,
                "inner_radius_mm": round(r0, 6),
                "outer_radius_mm": round(r1, 6),
                "sample_radius_mm": round(sample, 6),
                "cut_depth_mm": round(
                    float(layout["front_face_z_mm"]) - _concave_surface_z(layout, sample), 6
                ),
            }
        )
    return bands


_error_variants = make_error_variants


def _open_source_part(sw_app: SolidWorksApp, source_path: str):
    ext = Path(source_path).suffix.lower()
    errors, warnings = _error_variants()
    normalized = normalize_path(source_path)
    if ext == ".sldprt":
        model = sw_app.app.OpenDoc6(normalized, swDocPART, swOpenDocOptions_Silent, "", errors, warnings)
        return model, errors.value, warnings.value
    if ext not in {".stp", ".step"}:
        return None, -1, -1
    model = sw_app.app.OpenDoc6(normalized, swDocPART, swOpenDocOptions_Silent, "", errors, warnings)
    if model is not None:
        return model, errors.value, warnings.value
    import_data = sw_app.app.GetImportFileData(normalized)
    load_errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    loaded = sw_app.app.LoadFile4(normalized, "r", import_data, load_errors)
    part = loaded[0] if isinstance(loaded, tuple) else loaded
    return (sw_app.app.ActiveDoc if part is not None else None), load_errors.value, 0


def _select_front_face(
    model: Any, radius_mm: float, angle_degrees: float = 22.5
) -> bool:
    angle = math.radians(angle_degrees)
    model.ClearSelection2(True)
    return bool(
        model.Extension.SelectByRay(
            mm_to_m(radius_mm * math.cos(angle)),
            mm_to_m(radius_mm * math.sin(angle)),
            mm_to_m(10.0),
            0.0,
            0.0,
            -1.0,
            mm_to_m(0.15),
            2,
            False,
            0,
            0,
        )
    )


def _close_and_select_new_sketch(model: Any) -> bool:
    model.SketchManager.InsertSketch(True)
    model.ClearSelection2(True)
    feature = model.FeatureByPositionReverse(0)
    return feature is not None and bool(feature.Select2(False, 0))


def _blind_cut_selected_sketch(model: Any, depth_mm: float):
    return cut_feature(model, True, False, 0, mm_to_m(depth_mm))


def _boss_selected_sketch(model: Any, height_mm: float):
    return extrude_boss(model, mm_to_m(height_mm), reverse=False)


def _band_crosses_mount_zone(inner_radius_mm: float, outer_radius_mm: float) -> bool:
    return True


def _create_band_profile(
    model: Any,
    inner_radius_mm: float,
    outer_radius_mm: float,
    quadrant: Optional[int] = None,
) -> None:
    if quadrant is None:
        model.SketchManager.CreateCircleByRadius(
            0.0, 0.0, 0.0, mm_to_m(inner_radius_mm)
        )
        model.SketchManager.CreateCircleByRadius(
            0.0, 0.0, 0.0, mm_to_m(outer_radius_mm)
        )
        return

    keepout_half_angle = 8.0
    start = math.radians(quadrant * 90.0 + keepout_half_angle)
    end = math.radians((quadrant + 1) * 90.0 - keepout_half_angle)
    outer_start = (
        mm_to_m(outer_radius_mm * math.cos(start)),
        mm_to_m(outer_radius_mm * math.sin(start)),
    )
    outer_end = (
        mm_to_m(outer_radius_mm * math.cos(end)),
        mm_to_m(outer_radius_mm * math.sin(end)),
    )
    inner_start = (
        mm_to_m(inner_radius_mm * math.cos(start)),
        mm_to_m(inner_radius_mm * math.sin(start)),
    )
    inner_end = (
        mm_to_m(inner_radius_mm * math.cos(end)),
        mm_to_m(inner_radius_mm * math.sin(end)),
    )
    model.SketchManager.CreateArc(
        0.0, 0.0, 0.0,
        outer_start[0], outer_start[1], 0.0,
        outer_end[0], outer_end[1], 0.0,
        1,
    )
    model.SketchManager.CreateLine(
        outer_end[0], outer_end[1], 0.0,
        inner_end[0], inner_end[1], 0.0,
    )
    model.SketchManager.CreateArc(
        0.0, 0.0, 0.0,
        inner_end[0], inner_end[1], 0.0,
        inner_start[0], inner_start[1], 0.0,
        -1,
    )
    model.SketchManager.CreateLine(
        inner_start[0], inner_start[1], 0.0,
        outer_start[0], outer_start[1], 0.0,
    )


def _create_dish_bands(model: Any, layout: dict) -> Optional[List[str]]:
    names: List[str] = []
    for band in build_concave_dish_bands(layout, step_count=48):
        inner_radius = float(band["inner_radius_mm"])
        outer_radius = float(band["outer_radius_mm"])
        quadrants: Sequence[Optional[int]]
        if _band_crosses_mount_zone(inner_radius, outer_radius):
            quadrants = (0, 1, 2, 3)
        else:
            quadrants = (None,)

        for quadrant in quadrants:
            selection_angle = 22.5 if quadrant is None else quadrant * 90.0 + 45.0
            if not _select_front_face(
                model, float(band["sample_radius_mm"]), selection_angle
            ):
                raise RuntimeError(
                    f"dish band {band['band_index']} quadrant {quadrant} "
                    "front face selection failed"
                )
            model.SketchManager.InsertSketch(True)
            _create_band_profile(
                model,
                inner_radius,
                outer_radius,
                quadrant,
            )
            if not _close_and_select_new_sketch(model):
                raise RuntimeError(
                    f"dish band {band['band_index']} quadrant {quadrant} "
                    "sketch selection failed"
                )
            feature = _blind_cut_selected_sketch(
                model, float(band["cut_depth_mm"])
            )
            if feature is None:
                raise RuntimeError(
                    f"dish band {band['band_index']} quadrant {quadrant} "
                    "blind cut failed"
                )
            suffix = "" if quadrant is None else f"_Q{quadrant + 1}"
            feature.Name = (
                f"CONCAVE_DISH_BAND_{int(band['band_index']):02d}{suffix}"
            )
            names.append(feature.Name)
    return names


def _create_led_marker_rows(model: Any, layout: dict) -> Optional[List[str]]:
    names: List[str] = []
    led_radius = float(layout["led_diameter_mm"]) / 2.0
    for row in reversed(layout["rows"]):
        radius = float(row["radius_mm"])
        if not _select_front_face(model, radius):
            return None
        model.SketchManager.InsertSketch(True)
        count = int(row["count"])
        for angle_degrees in row["led_angles_degrees"]:
            angle = math.radians(float(angle_degrees))
            model.SketchManager.CreateCircleByRadius(
                mm_to_m(radius * math.cos(angle)),
                mm_to_m(radius * math.sin(angle)),
                0.0,
                mm_to_m(led_radius),
            )
        if not _close_and_select_new_sketch(model):
            return None
        row_index = int(row["row_index"])
        if row_index == 1:
            feature = _boss_selected_sketch(model, 0.3)
            feature_name = f"LED_ROW_{row_index:02d}_COUNT_{count}_RAISED"
        else:
            feature = _blind_cut_selected_sketch(model, 0.8)
            feature_name = f"LED_ROW_{row_index:02d}_COUNT_{count}"
        if feature is None:
            return None
        feature.Name = feature_name
        names.append(feature.Name)
    return list(reversed(names))


def create_ring_light_v3(
    sw_app: SolidWorksApp,
    source_path: str,
    save_path: str,
    overwrite_confirm: bool = False,
    row_counts: Optional[Sequence[int]] = None,
) -> dict:
    """Modify a STEP-derived part into the concave 9-row v3 design."""
    try:
        valid, message = validate_path(source_path, must_exist=True)
        if not valid:
            return error_response(message, code="INVALID_SOURCE_PATH")
        if Path(source_path).suffix.lower() not in {".stp", ".step", ".sldprt"}:
            return error_response("source_path must be STEP or SLDPRT", code="INVALID_SOURCE_PATH")
        valid, message = validate_output_file(save_path, {".sldprt"}, overwrite_confirm)
        if not valid:
            return error_response(message, code="INVALID_OUTPUT_PATH")
        layout_path = str(Path(normalize_path(save_path)).with_suffix(".layout.json"))
        allowed, message = check_overwrite_confirm(layout_path, overwrite_confirm)
        if not allowed:
            return error_response(message, code="INVALID_OUTPUT_PATH")

        layout = build_ring_light_v3_layout(row_counts=row_counts)
        model, open_errors, open_warnings = _open_source_part(sw_app, source_path)
        if model is None:
            return error_response("Could not open STEP-derived source part", code="SW_IMPORT_FAILED")
        ok, message, sink_path = ensure_sink_path(save_path)
        if not ok:
            return error_response(message, code="INVALID_OUTPUT_PATH")
        save_result = model.SaveAs3(sink_path, 0, swSaveAsOptions_Silent)
        if save_result != 0:
            return error_response(f"SaveAs3 failed with code {save_result}", code="SW_SAVE_FAILED")

        dish_features = _create_dish_bands(model, layout)
        if dish_features is None:
            return error_response("Could not create native concave dish bands", code="SW_API_ERROR")
        led_features = _create_led_marker_rows(model, layout)
        if led_features is None:
            return error_response("Could not create 9 native LED marker rows", code="SW_API_ERROR")
        model.ForceRebuild3(False)
        errors, warnings = _error_variants()
        saved = bool(model.Save3(swSaveAsOptions_Silent, errors, warnings))
        if not saved:
            return error_response("SolidWorks rejected final v3 save", code="SW_SAVE_FAILED")

        ok, message, sink_layout = ensure_sink_path(layout_path)
        if not ok:
            return error_response(message, code="INVALID_OUTPUT_PATH")
        Path(sink_layout).write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
        raised_count = int(layout["row_counts"][0])
        cut_count = int(layout["total_led_count"]) - raised_count
        return success_response(
            data={
                "saved_to": save_path,
                "source_path": source_path,
                "layout_json": layout_path,
                "title": call_or_value(model, "GetTitle"),
                "open_errors": open_errors,
                "open_warnings": open_warnings,
                "dish_features": dish_features,
                "led_features": led_features,
                "dish_band_count": len(dish_features),
                "row_counts": layout["row_counts"],
                "total_led_count": layout["total_led_count"],
                "minimum_back_thickness_mm": layout["dish"]["minimum_back_thickness_mm"],
            },
            message="Created STEP-based concave 9-row ring-light v3",
            warning=(
                "The native SLDPRT uses 48 four-quadrant blind-cut bands, "
                f"{cut_count} shallow LED marker cuts, and {raised_count} raised inner-row LED markers. "
                "Exact 30-60 degree inward axes are recorded in the layout JSON."
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc), code="SW_CONNECTION_FAILED")
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        return error_response(
            f"Failed to create ring-light v3: {exc}",
            code="SW_API_ERROR",
            details={"exception_type": type(exc).__name__},
        )
