"""Advanced part features: swept/lofted profiles, rib plate, polygon
and slot primitives (N28-N30 feature families, split from part.py in N35)."""

from __future__ import annotations

import logging
import math
from typing import Optional

import pythoncom

from solidworks_mcp.solidworks_api.app import SolidWorksApp, SolidWorksNotRunningError
from solidworks_mcp.solidworks_api.constants import (
    swFileSaveErrorNone,
    swSaveAsOptions_Silent,
)
from solidworks_mcp.solidworks_api.save_io import (
    persist_part_save,
    prepare_part_save,
)
from solidworks_mcp.solidworks_api.geometry import latest_feature_name, mm_to_m, select_plane
from solidworks_mcp.solidworks_api.part_support import (
    TOP_PLANE_CANDIDATES,
    _create_circle_sketch,
    _extrude_sketch,
    _get_or_create_part,
    _select_plane,
)
from solidworks_mcp.utils.common import error_response, success_response
from solidworks_mcp.utils.com import typed_or_dynamic


from solidworks_mcp.utils.security import ensure_sink_path, validate_output_file
from solidworks_mcp.utils.validation import finite_number, positive_number


def _typed_doc2(model):
    """One-arg local form of utils.com.typed_or_dynamic (IModelDoc2)."""
    return typed_or_dynamic(model, "IModelDoc2")



logger = logging.getLogger(__name__)


def _sweep_path_sketch(model: Any, path_type: str, radius_mm, angle_deg, length_mm) -> None:
    """Draw the sweep path sketch on the currently selected plane."""
    model.SketchManager.InsertSketch(True)
    if path_type == "arc":
        radius_m = mm_to_m(radius_mm)
        end_angle = math.radians(angle_deg)
        model.SketchManager.CreateArc(
            0.0, 0.0, 0.0,
            radius_m, 0.0, 0.0,
            radius_m * math.cos(end_angle), radius_m * math.sin(end_angle), 0.0,
            1,
        )
    else:
        model.SketchManager.CreateLine(
            0.0, 0.0, 0.0, mm_to_m(length_mm), 0.0, 0.0
        )
    model.SketchManager.InsertSketch(True)


def create_swept(
    sw_app: SolidWorksApp,
    diameter_mm: float,
    path_type: str = "arc",
    radius_mm: Optional[float] = None,
    angle_deg: float = 90.0,
    length_mm: Optional[float] = None,
    plane: str = "front",
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
) -> dict:
    """Swept protrusion: circular profile along an arc or line sketch path.

    Real-machine contract (N28 probe, 2026-09-01): the path sketch is
    selected as SKETCH with mark=4, and the boss call is
    InsertProtrusionSwept4 with Alignment=False and CircularProfile=True,
    so the diameter rides the call and no profile sketch is needed."""
    try:
        diameter_mm = positive_number("diameter_mm", diameter_mm)
        if path_type not in ("arc", "line"):
            return error_response(
                "path_type must be 'arc' or 'line'", code="INVALID_PARAMETER"
            )
        if plane != "front":
            return error_response(
                "Only the front plane sweep is supported",
                code="INVALID_PARAMETER",
            )
        if path_type == "arc":
            if radius_mm is None or not math.isfinite(radius_mm) or radius_mm <= 0:
                return error_response(
                    "arc path needs radius_mm > 0", code="INVALID_PARAMETER"
                )
            if not math.isfinite(angle_deg) or not 0 < abs(angle_deg) <= 360:
                return error_response(
                    "angle_deg must be in (0, 360]", code="INVALID_PARAMETER"
                )
        else:
            if length_mm is None or not math.isfinite(length_mm) or length_mm <= 0:
                return error_response(
                    "line path needs length_mm > 0", code="INVALID_PARAMETER"
                )
        message = prepare_part_save(save_path, overwrite_confirm)
        if message:
            return error_response(message, code="INVALID_OUTPUT_PATH")

        model, _was_created = _get_or_create_part(sw_app)
        if _select_plane(model) is None:
            return error_response("Could not select a reference plane")

        _sweep_path_sketch(model, path_type, radius_mm, angle_deg, length_mm)

        model.ClearSelection2(True)
        sketch_name = latest_feature_name(model)
        if not model.Extension.SelectByID2(
            sketch_name, "SKETCH", 0, 0, 0, False, 4, pythoncom.Nothing, 0
        ):
            return error_response(
                f"Could not select sweep path sketch {sketch_name!r}",
                code="SW_API_ERROR",
            )

        feature = model.FeatureManager.InsertProtrusionSwept4(
            False,  # Propagate
            False,  # Alignment — False is the unlock for sketch paths (N28 probe)
            0,      # TwistCtrlOption = swTwistControlFollowPath
            False,  # KeepTangency
            False,  # BAdvancedSmoothing
            0,      # StartMatchingType
            0,      # EndMatchingType
            False,  # IsThinBody
            0.0,    # Thickness1
            0.0,    # Thickness2
            0,      # ThinType
            0,      # PathAlign
            True,   # Merge
            True,   # UseFeatScope
            True,   # UseAutoSelect
            0.0,    # TwistAngle
            True,   # BMergeSmoothFaces
            True,   # CircularProfile — no profile sketch needed
            mm_to_m(diameter_mm),  # CircularProfileDiameter
            True,   # Direction
        )
        if feature is None:
            return error_response(
                "Swept feature creation rejected", code="SW_API_ERROR"
            )

        result = {"feature_name": feature.Name}
        code, message = persist_part_save(model, save_path, result)
        if code:
            return error_response(message, code=code)

        return success_response(
            data=result,
            message=(
                f"Created swept protrusion diameter={diameter_mm}mm along "
                f"a {path_type} path"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to create swept protrusion")
        return error_response(f"Failed to create swept protrusion: {exc}")


def create_loft(
    sw_app: SolidWorksApp,
    profile_diameters_mm,
    section_spacing_mm,
    plane: str = "front",
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
) -> dict:
    """Lofted protrusion between circular sections on parallel planes.

    Real-machine contract (N28 probe, 2026-09-01): SW names a loft a
    "blend" — the boss call is IModelDoc2.InsertProtrusionBlend2(Closed,
    KeepTangency, ForceNonRational) with the sections selected as SKETCH
    mark=1, accumulating. Intermediate planes are FeatureManager.
    InsertRefPlane(8, distance) offsets parallel to the base plane."""
    try:
        if len(profile_diameters_mm) < 2:
            return error_response(
                "loft needs at least 2 profile sections",
                code="INVALID_PARAMETER",
            )
        for diameter in profile_diameters_mm:
            positive_number("profile_diameters_mm", diameter)
        section_spacing_mm = positive_number(
            "section_spacing_mm", section_spacing_mm
        )
        if plane != "front":
            return error_response(
                "Only the front plane loft is supported",
                code="INVALID_PARAMETER",
            )
        message = prepare_part_save(save_path, overwrite_confirm)
        if message:
            return error_response(message, code="INVALID_OUTPUT_PATH")

        model, _was_created = _get_or_create_part(sw_app)
        base_plane = _select_plane(model)
        if base_plane is None:
            return error_response("Could not select a reference plane")

        section_names = []
        for index, diameter in enumerate(profile_diameters_mm):
            if index == 0:
                plane_name = base_plane
            else:
                model.ClearSelection2(True)
                if not model.Extension.SelectByID2(
                    base_plane, "PLANE", 0, 0, 0, False, 0, pythoncom.Nothing, 0
                ):
                    return error_response(
                        f"Could not re-select {base_plane!r} for offset",
                        code="SW_API_ERROR",
                    )
                if model.FeatureManager.InsertRefPlane(
                    8, mm_to_m(section_spacing_mm * index), 0, 0, 0, 0
                ) is None:
                    return error_response(
                        "Offset reference plane rejected", code="SW_API_ERROR"
                    )
                plane_name = latest_feature_name(model)
            model.ClearSelection2(True)
            if not model.Extension.SelectByID2(
                plane_name, "PLANE", 0, 0, 0, False, 0, pythoncom.Nothing, 0
            ):
                return error_response(
                    f"Could not select section plane {plane_name!r}",
                    code="SW_API_ERROR",
                )
            _create_circle_sketch(model, mm_to_m(diameter) / 2.0)
            section_names.append(latest_feature_name(model))

        model.ClearSelection2(True)
        for position, name in enumerate(section_names):
            if not model.Extension.SelectByID2(
                name, "SKETCH", 0, 0, 0, position > 0, 1, pythoncom.Nothing, 0
            ):
                return error_response(
                    f"Could not select loft section {name!r}",
                    code="SW_API_ERROR",
                )

        # Blend2's return value is unreliable (returns None on success —
        # same family as FeatureFillet, quirks 17): the verdict is the tree.
        before = latest_feature_name(model)
        _typed_doc2(model).InsertProtrusionBlend2(False, False, False)
        after = latest_feature_name(model)
        if after == before:
            return error_response(
                "Loft feature creation rejected", code="SW_API_ERROR"
            )

        result = {"feature_name": after}
        code, message = persist_part_save(model, save_path, result)
        if code:
            return error_response(message, code=code)

        return success_response(
            data=result,
            message=(
                f"Created lofted protrusion with {len(profile_diameters_mm)} "
                f"circular sections, spacing {section_spacing_mm}mm"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to create lofted protrusion")
        return error_response(f"Failed to create lofted protrusion: {exc}")


def create_rib(
    sw_app: SolidWorksApp,
    length_mm: float,
    height_mm: float,
    thickness_mm: float,
    base_z_mm: float = 0.0,
    x_center_mm: float = 0.0,
    y_center_mm: float = 0.0,
) -> dict:
    """Rib as a rectangular boss plate — MATH SUBSTITUTE for the native rib.

    The InsertRib family is BLOCKED on this machine (13 direct-call
    variants all silently rejected, T8 family; no Rib entry in
    swFeatureNameID_e so the FeatureData route is closed — ADR-0011).
    The plate is sketched on the top plane (or an offset reference plane
    at ``base_z_mm``) and boss-extruded upward, so it IS parameter
    linked, but unlike a true rib it does not adapt to adjacent walls."""
    try:
        length_mm = positive_number("length_mm", length_mm)
        height_mm = positive_number("height_mm", height_mm)
        thickness_mm = positive_number("thickness_mm", thickness_mm)
        base_z_mm = finite_number("base_z_mm", base_z_mm)
        x_center_mm = finite_number("x_center_mm", x_center_mm)
        y_center_mm = finite_number("y_center_mm", y_center_mm)
        if base_z_mm < 0:
            return error_response(
                "base_z_mm must be non-negative", code="INVALID_PARAMETER"
            )
        model, _was_created = _get_or_create_part(sw_app)

        if base_z_mm > 0:
            top_name = select_plane(model, TOP_PLANE_CANDIDATES)
            if top_name is None:
                return error_response(
                    "Could not select a reference plane "
                    "(tried: Top Plane, 上视基准面)"
                )
            model.ClearSelection2(True)
            if not model.Extension.SelectByID2(
                top_name, "PLANE", 0, 0, 0, False, 0, pythoncom.Nothing, 0
            ):
                return error_response(
                    f"Could not re-select {top_name!r} as the offset reference",
                    code="SW_API_ERROR",
                )
            if model.FeatureManager.InsertRefPlane(
                8, mm_to_m(base_z_mm), 0, 0, 0, 0
            ) is None:
                return error_response(
                    "Offset reference plane rejected", code="SW_API_ERROR"
                )
            plane_name = latest_feature_name(model)
            model.ClearSelection2(True)
            if not model.Extension.SelectByID2(
                plane_name, "PLANE", 0, 0, 0, False, 0, pythoncom.Nothing, 0
            ):
                return error_response(
                    f"Could not select sketch plane {plane_name!r}",
                    code="SW_API_ERROR",
                )
        else:
            if select_plane(model, TOP_PLANE_CANDIDATES) is None:
                return error_response(
                    "Could not select a reference plane "
                    "(tried: Top Plane, 上视基准面)"
                )

        x1 = mm_to_m(x_center_mm - length_mm / 2.0)
        y1 = mm_to_m(y_center_mm - thickness_mm / 2.0)
        x2 = mm_to_m(x_center_mm + length_mm / 2.0)
        y2 = mm_to_m(y_center_mm + thickness_mm / 2.0)
        model.SketchManager.InsertSketch(True)
        model.SketchManager.CreateCornerRectangle(x1, y1, 0, x2, y2, 0)
        model.SketchManager.InsertSketch(True)

        feature = _extrude_sketch(model, mm_to_m(height_mm))
        if feature is None:
            return error_response(
                "Extrusion feature creation failed", code="SW_API_ERROR"
            )

        return success_response(
            data={"feature_name": feature.Name},
            message=(
                f"Created rib plate {length_mm}x{thickness_mm}x{height_mm}mm "
                f"at z={base_z_mm}mm (math substitute — not wall-adaptive, "
                "ADR-0011)"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to create rib")
        return error_response(f"Failed to create rib: {exc}")


def create_polygon(
    sw_app: SolidWorksApp,
    sides: int,
    circumradius_mm: float,
    height_mm: float,
    inscribed: bool = True,
    plane: str = "front",
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
) -> dict:
    """Regular N-sided prism: polygon sketch + boss extrude (merged).

    Real-machine contract (N30 probe): ISketchManager.CreatePolygon takes 8
    scalars — the edge reference point is (circumradius, 0). Inscribed=True
    makes the polygon inscribed in that circle (volume = N/2·R²·sin(2π/N)·h);
    False circumscribes it (R is then the inradius)."""
    try:
        if not isinstance(sides, int) or isinstance(sides, bool) or not 3 <= sides <= 60:
            return error_response(
                "sides must be an integer in [3, 60]", code="INVALID_PARAMETER"
            )
        circumradius_mm = positive_number("circumradius_mm", circumradius_mm)
        height_mm = positive_number("height_mm", height_mm)
        if plane != "front":
            return error_response(
                "Only the front plane polygon is supported",
                code="INVALID_PARAMETER",
            )
        message = prepare_part_save(save_path, overwrite_confirm)
        if message:
            return error_response(message, code="INVALID_OUTPUT_PATH")

        model, _was_created = _get_or_create_part(sw_app)
        if _select_plane(model) is None:
            return error_response("Could not select a reference plane")

        model.SketchManager.InsertSketch(True)
        model.SketchManager.CreatePolygon(
            0.0, 0.0, 0.0,
            mm_to_m(circumradius_mm), 0.0, 0.0,
            sides, inscribed,
        )
        model.SketchManager.InsertSketch(True)

        feature = _extrude_sketch(model, mm_to_m(height_mm))
        if feature is None:
            return error_response(
                "Extrusion feature creation failed", code="SW_API_ERROR"
            )

        result = {"feature_name": feature.Name}
        code, message = persist_part_save(model, save_path, result)
        if code:
            return error_response(message, code=code)

        return success_response(
            data=result,
            message=(
                f"Created {sides}-sided prism (circumradius {circumradius_mm}mm, "
                f"height {height_mm}mm)"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to create polygon prism")
        return error_response(f"Failed to create polygon prism: {exc}")


def create_slot(
    sw_app: SolidWorksApp,
    length_mm: float,
    width_mm: float,
    height_mm: float,
    plane: str = "front",
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
) -> dict:
    """Obround (slot) plate: straight-slot sketch + boss extrude (merged).

    Real-machine contract (N30 probe): CreateSketchSlot line-type(0) /
    center-center(0); the slot area is length·width + π(width/2)² — the
    centre-line length includes the end radii, so length must exceed
    width."""
    try:
        length_mm = positive_number("length_mm", length_mm)
        width_mm = positive_number("width_mm", width_mm)
        height_mm = positive_number("height_mm", height_mm)
        if length_mm <= width_mm:
            return error_response(
                "length_mm must exceed width_mm (the centre line includes the "
                "end radii)",
                code="INVALID_PARAMETER",
            )
        if plane != "front":
            return error_response(
                "Only the front plane slot is supported",
                code="INVALID_PARAMETER",
            )
        message = prepare_part_save(save_path, overwrite_confirm)
        if message:
            return error_response(message, code="INVALID_OUTPUT_PATH")

        model, _was_created = _get_or_create_part(sw_app)
        if _select_plane(model) is None:
            return error_response("Could not select a reference plane")

        half_length_m = mm_to_m(length_mm) / 2.0
        width_m = mm_to_m(width_mm)
        model.SketchManager.InsertSketch(True)
        model.SketchManager.CreateSketchSlot(
            0, 0, width_m,
            0.0, -half_length_m, 0.0,
            0.0, half_length_m, 0.0,
            width_m / 2.0, 0.0, 0.0,
            1, False,
        )
        model.SketchManager.InsertSketch(True)

        feature = _extrude_sketch(model, mm_to_m(height_mm))
        if feature is None:
            return error_response(
                "Extrusion feature creation failed", code="SW_API_ERROR"
            )

        result = {"feature_name": feature.Name}
        code, message = persist_part_save(model, save_path, result)
        if code:
            return error_response(message, code=code)

        return success_response(
            data=result,
            message=(
                f"Created slot plate {length_mm}x{width_mm}mm (centre line), "
                f"height {height_mm}mm"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to create slot plate")
        return error_response(f"Failed to create slot plate: {exc}")


