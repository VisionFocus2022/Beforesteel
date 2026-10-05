"""Part-level SolidWorks operations."""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

import pythoncom
from win32com.client import gencache

from solidworks_mcp.solidworks_api.app import SolidWorksApp, SolidWorksNotRunningError
from solidworks_mcp.solidworks_api.constants import (
    swDocPART,
    swFileSaveErrorNone,
    swSaveAsOptions_Silent,
)
from solidworks_mcp.solidworks_api.save_io import (
    persist_part_save,
    prepare_part_save,
)
from solidworks_mcp.solidworks_api.geometry import (
    latest_feature_name,
    mm_to_m,
    select_plane,
)
from solidworks_mcp.solidworks_api.sketch import extrude_boss, extrude_boss_draft
from solidworks_mcp.utils.common import error_response, success_response
from solidworks_mcp.utils.com import call_or_value
from solidworks_mcp.utils.security import ensure_sink_path, validate_output_file
from solidworks_mcp.utils.templates import get_part_template
from solidworks_mcp.utils.validation import finite_number, positive_number

# M-2 (2026-10-05): moved from mid-module to the top import block —
# part_support does not import part (no cycle), the old mid-file placement
# only existed to dodge a long-gone reorganisation.
from solidworks_mcp.solidworks_api.part_support import (
    MAX_FACE_WALK,
    PLANE_CANDIDATES,
    TOP_PLANE_CANDIDATES,
    _create_circle_sketch,
    _create_rectangle_sketch,
    _extrude_draft_sketch,
    _extrude_sketch,
    _get_or_create_part,
    _select_plane,
    _select_top_face,
)

logger = logging.getLogger(__name__)



def create_cylinder_on_face(
    sw_app: SolidWorksApp,
    diameter: float,
    height: float,
) -> dict:
    """Stack a cylinder on the current body's top face (CSG v1 op)."""
    try:
        diameter = positive_number("diameter", diameter)
        height = positive_number("height", height)
        model = sw_app.get_active_document()
        if model is None or call_or_value(model, "GetType") != swDocPART:
            return error_response("No active part document")
        top = _select_top_face(model)
        if top is None:
            return error_response(
                "No top face to stack on (the document has no solid body)",
                code="SW_API_ERROR",
            )
        model.SketchManager.InsertSketch(True)
        model.SketchManager.CreateCircleByRadius(0, 0, 0, mm_to_m(diameter) / 2.0)
        model.SketchManager.InsertSketch(True)
        feature = extrude_boss(model, mm_to_m(height))
        if feature is None:
            return error_response(
                "Stacked extrusion feature creation failed", code="SW_API_ERROR"
            )
        return success_response(
            data={"feature_name": feature.Name},
            message=f"Stacked cylinder Ø{diameter}×{height}mm on the top face",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to stack cylinder")
        return error_response(f"Failed to stack cylinder: {exc}")


def create_cone_on_face(
    sw_app: SolidWorksApp,
    bottom_diameter: float,
    top_diameter: float,
    height: float,
) -> dict:
    """Stack a drafted cone on the current body's top face (CSG v1 op).

    Draft semantics mirror ``create_cone`` (real-machine contract):
    angle = ``atan2(|r_top - r_bottom|, height)``; outward draft when the
    top is wider.
    """
    try:
        bottom_diameter = positive_number("bottom_diameter", bottom_diameter)
        top_diameter = positive_number("top_diameter", top_diameter)
        height = positive_number("height", height)
        model = sw_app.get_active_document()
        if model is None or call_or_value(model, "GetType") != swDocPART:
            return error_response("No active part document")
        top = _select_top_face(model)
        if top is None:
            return error_response(
                "No top face to stack on (the document has no solid body)",
                code="SW_API_ERROR",
            )
        r_bottom = bottom_diameter / 2.0
        r_top = top_diameter / 2.0
        draft_angle_rad = math.atan2(abs(r_top - r_bottom), height)
        model.SketchManager.InsertSketch(True)
        model.SketchManager.CreateCircleByRadius(0, 0, 0, mm_to_m(bottom_diameter) / 2.0)
        model.SketchManager.InsertSketch(True)
        feature = extrude_boss_draft(
            model,
            mm_to_m(height),
            top_diameter != bottom_diameter,
            r_top > r_bottom,
            draft_angle_rad,
        )
        if feature is None:
            return error_response(
                "Stacked drafted extrusion feature creation failed",
                code="SW_API_ERROR",
            )
        return success_response(
            data={
                "feature_name": feature.Name,
                "draft_angle_degrees": round(math.degrees(draft_angle_rad), 4),
            },
            message=(
                f"Stacked cone Ø{bottom_diameter}→Ø{top_diameter}×{height}mm "
                "on the top face"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to stack cone")
        return error_response(f"Failed to stack cone: {exc}")

def create_cylinder(
    sw_app: SolidWorksApp,
    diameter: float,
    height: float,
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
) -> dict:
    """Create a cylinder with the given diameter and height (in mm)."""
    try:
        diameter = positive_number("diameter", diameter)
        height = positive_number("height", height)
        message = prepare_part_save(save_path, overwrite_confirm)
        if message:
            return error_response(message, code="INVALID_OUTPUT_PATH")

        model, _was_created = _get_or_create_part(sw_app)

        plane_name = _select_plane(model)
        if plane_name is None:
            return error_response("Could not select a reference plane (tried: Front Plane, 前视基准面)")

        radius = mm_to_m(diameter) / 2.0
        height_m = mm_to_m(height)

        _create_circle_sketch(model, radius)
        feature = _extrude_sketch(model, height_m)

        if feature is None:
            return error_response("Extrusion feature creation failed")

        result = {"feature_name": feature.Name}

        code, message = persist_part_save(model, save_path, result)
        if code:
            return error_response(message, code=code)

        return success_response(
            data=result,
            message=f"Created cylinder with diameter={diameter}mm, height={height}mm",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to create cylinder")
        return error_response(f"Failed to create cylinder: {exc}")


def create_box(
    sw_app: SolidWorksApp,
    width: float,
    depth: float,
    height: float,
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
) -> dict:
    """Create a box with the given width, depth, and height (in mm)."""
    try:
        width = positive_number("width", width)
        depth = positive_number("depth", depth)
        height = positive_number("height", height)
        message = prepare_part_save(save_path, overwrite_confirm)
        if message:
            return error_response(message, code="INVALID_OUTPUT_PATH")

        model, _was_created = _get_or_create_part(sw_app)

        plane_name = _select_plane(model)
        if plane_name is None:
            return error_response("Could not select a reference plane (tried: Front Plane, 前视基准面)")

        width_m = mm_to_m(width)
        depth_m = mm_to_m(depth)
        height_m = mm_to_m(height)

        _create_rectangle_sketch(model, width_m, depth_m)
        feature = _extrude_sketch(model, height_m)

        if feature is None:
            return error_response("Extrusion feature creation failed")

        result = {"feature_name": feature.Name}

        code, message = persist_part_save(model, save_path, result)
        if code:
            return error_response(message, code=code)

        return success_response(
            data=result,
            message=(
                f"Created box with width={width}mm, depth={depth}mm, "
                f"height={height}mm"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to create box")
        return error_response(f"Failed to create box: {exc}")


def create_cone(
    sw_app: SolidWorksApp,
    bottom_diameter: float,
    top_diameter: float,
    height: float,
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
) -> dict:
    """Create a cone/frustum from a bottom-radius circle with a drafted extrusion.

    The draft form follows the real-machine contract probed on SW 2026:
    the draft angle is ``atan2(|r_top - r_bottom|, height)`` in radians
    and ``Ddir1`` widens the far end, so ``top_diameter > bottom_diameter``
    grows an expanding frustum. ``top_diameter=0`` requests a pointed
    cone (SolidWorks may refuse a fully degenerate apex; prefer a small
    positive top diameter for machined parts).
    """
    try:
        bottom_diameter = positive_number("bottom_diameter", bottom_diameter)
        height = positive_number("height", height)
        top_diameter = finite_number("top_diameter", top_diameter)
        if top_diameter < 0:
            return error_response(
                "top_diameter must be a non-negative number",
                code="INVALID_PARAMETER",
            )
        message = prepare_part_save(save_path, overwrite_confirm)
        if message:
            return error_response(message, code="INVALID_OUTPUT_PATH")

        model, _was_created = _get_or_create_part(sw_app)

        plane_name = _select_plane(model)
        if plane_name is None:
            return error_response("Could not select a reference plane (tried: Front Plane, 前视基准面)")

        radius = mm_to_m(bottom_diameter) / 2.0
        height_m = mm_to_m(height)
        r_bottom = bottom_diameter / 2.0
        r_top = top_diameter / 2.0
        draft_angle_rad = math.atan2(abs(r_top - r_bottom), height)
        draft_check = top_diameter != bottom_diameter
        draft_outward = r_top > r_bottom

        _create_circle_sketch(model, radius)
        feature = _extrude_draft_sketch(
            model, height_m, draft_check, draft_outward, draft_angle_rad
        )

        if feature is None:
            return error_response("Drafted extrusion feature creation failed")

        result = {
            "feature_name": feature.Name,
            "draft_angle_degrees": round(math.degrees(draft_angle_rad), 4),
        }

        code, message = persist_part_save(model, save_path, result)
        if code:
            return error_response(message, code=code)

        return success_response(
            data=result,
            message=(
                f"Created cone with bottom_diameter={bottom_diameter}mm, "
                f"top_diameter={top_diameter}mm, height={height}mm"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to create cone")
        return error_response(f"Failed to create cone: {exc}")


def create_revolved(
    sw_app: SolidWorksApp,
    outer_diameter: float,
    height: float,
    bore_diameter: float = 0.0,
    plane: str = "front",
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
) -> dict:
    """Create a revolved disc/ring/shaft segment with a real feature tree.

    Sketch on the front plane: a construction centerline along sketch-y is
    the revolve axis; the rectangle profile spans [bore/2, outer/2] in
    radius and ±height/2. The part therefore revolves around the model Y
    axis (diameter in X/Z, height along Y). FeatureRevolve2 takes the
    full-circle angle in radians (real-machine contract, T6 probe).
    """
    try:
        outer_diameter = positive_number("outer_diameter", outer_diameter)
        height = positive_number("height", height)
        bore_diameter = finite_number("bore_diameter", bore_diameter)
        if bore_diameter < 0 or bore_diameter >= outer_diameter:
            return error_response(
                "bore_diameter must be in [0, outer_diameter)",
                code="INVALID_PARAMETER",
            )
        if plane != "front":
            return error_response(
                "Only the front plane revolve is supported",
                code="INVALID_PARAMETER",
            )
        message = prepare_part_save(save_path, overwrite_confirm)
        if message:
            return error_response(message, code="INVALID_OUTPUT_PATH")

        model, _was_created = _get_or_create_part(sw_app)

        plane_name = _select_plane(model)
        if plane_name is None:
            return error_response("Could not select a reference plane (tried: Front Plane, 前视基准面)")

        half_height_m = mm_to_m(height) / 2.0
        outer_radius_m = mm_to_m(outer_diameter) / 2.0
        bore_radius_m = mm_to_m(bore_diameter) / 2.0

        model.SketchManager.InsertSketch(True)
        axis = model.SketchManager.CreateLine(
            0, -half_height_m, 0, 0, half_height_m, 0
        )
        axis.ConstructionGeometry = True
        model.SketchManager.CreateCornerRectangle(
            bore_radius_m, -half_height_m, 0,
            outer_radius_m, half_height_m, 0,
        )
        model.SketchManager.InsertSketch(True)

        feature = model.FeatureManager.FeatureRevolve2(
            True,   # SingleDir
            True,   # IsSolid
            False,  # IsThin
            False,  # IsCut
            False,  # ReverseDir
            False,  # BothDirectionUpToSameEntity
            0,      # Dir1Type = swEndCondBlind
            0,      # Dir2Type
            2 * math.pi,  # Dir1Angle（弧度，全周）
            0.0,    # Dir2Angle
            False,  # OffsetReverse1
            False,  # OffsetReverse2
            0.0,    # OffsetDistance1
            0.0,    # OffsetDistance2
            0,      # ThinType
            0.0,    # ThinThickness1
            0.0,    # ThinThickness2
            True,   # Merge
            True,   # UseFeatScope
            True,   # UseAutoSelect
        )
        if feature is None:
            return error_response("Revolve feature creation failed")

        result = {"feature_name": feature.Name}

        code, message = persist_part_save(model, save_path, result)
        if code:
            return error_response(message, code=code)

        return success_response(
            data=result,
            message=(
                f"Created revolved part with outer_diameter={outer_diameter}mm, "
                f"bore_diameter={bore_diameter}mm, height={height}mm"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to create revolved part")
        return error_response(f"Failed to create revolved part: {exc}")

def get_mass_properties(sw_app: SolidWorksApp) -> dict:
    """Read mass properties of the active part."""
    try:
        model = sw_app.get_active_document()
        if model is None:
            return error_response("No active document")

        bodies = model.GetBodies2(0, False)  # swAllBodies = 0
        if not bodies:
            return error_response("No bodies found in active document")

        mass_prop = call_or_value(model.Extension, "CreateMassProperty")
        if mass_prop is None:
            return error_response("Could not create mass property object")

        return success_response(
            data={
                "volume": mass_prop.Volume,
                "surface_area": mass_prop.SurfaceArea,
                "mass": mass_prop.Mass,
                "center_of_mass": list(mass_prop.CenterOfMass),
                "units": {
                    "volume": "m^3",
                    "surface_area": "m^2",
                    "mass": "kg",
                    "center_of_mass": "m",
                },
            },
            message="Mass properties computed",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to get mass properties")
        return error_response(f"Failed to get mass properties: {exc}")


# ---- N35 facade re-exports -------------------------------------------------
# The advanced feature families live in their own modules; part.py remains
# the stable import surface (registry/design/e2e/probes all use part.*).
# Must sit at the END of this file: the modules above import part's
# helpers, which are fully defined by this point (no import cycle).
from solidworks_mcp.solidworks_api.part_advanced import (  # noqa: E402,F401
    create_loft,
    create_polygon,
    create_rib,
    create_slot,
    create_swept,
)
from solidworks_mcp.solidworks_api.part_refgeom import (  # noqa: E402,F401
    _cylindrical_face_by_name,
    create_ref_axis,
    create_ref_plane,
)

