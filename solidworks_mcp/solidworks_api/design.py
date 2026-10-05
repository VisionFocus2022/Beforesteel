"""Parametric design operations for SolidWorks parts."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

import pythoncom

from solidworks_mcp.solidworks_api.app import SolidWorksApp, SolidWorksNotRunningError
from solidworks_mcp.solidworks_api.constants import (
    THREAD_SPECS,
    swDocPART,
    swFileSaveErrorNone,
    swSaveAsOptions_Silent,
)
from solidworks_mcp.solidworks_api.geometry import (
    latest_feature_name as _latest_feature_name,
)
from solidworks_mcp.solidworks_api.geometry import (
    mm_to_m,
    select_plane,
    walk_feature_names,
)
from solidworks_mcp.solidworks_api.save_io import (
    persist_part_save,
    prepare_part_save,
)
from solidworks_mcp.solidworks_api.part import (
    create_box,
    create_cone,
    create_cylinder,
)
from solidworks_mcp.solidworks_api import part as part_module
from solidworks_mcp.solidworks_api.features import rename_feature
from solidworks_mcp.solidworks_api.sketch import cut_feature
from solidworks_mcp.utils.common import error_response, success_response
from solidworks_mcp.utils.com import call_or_value
from solidworks_mcp.utils.security import ensure_sink_path, validate_output_file
from solidworks_mcp.utils.templates import get_part_template
from solidworks_mcp.utils.validation import finite_number, parse_bool, positive_number

logger = logging.getLogger(__name__)

PLANE_ALIASES = {
    "front": ["Front Plane", "前视基准面"],
    "top": ["Top Plane", "上视基准面"],
    "right": ["Right Plane", "右视基准面"],
}

# Canonical design-plan operation vocabulary (single source of truth for
# execute_design_plan, server capabilities, and docstrings).
DESIGN_PLAN_OPERATIONS = (
    "new_part",
    "box",
    "plate",
    "cylinder",
    "cone",
    "hole",
    "threaded_hole",
    "annular_pattern",
)

# Hole-feature sketch planes: everything this repo models grows +Z from
# a Front-Plane sketch (part.PLANE_CANDIDATES: box/plate/cylinder/cone),
# so the "top" of such a part is its +Z face and a hole asked for plane
# "top" must be drilled along Z through that face. Resolving "top" to
# SW's native Top Plane (XZ sketch, Y normal) instead drills sideways
# through the plate flank -- verified on the real machine
# (tools/probe_hole_plane_context.py: a requested top hole landed
# axis -Y on the y=+40 flank, and 4 of 6 annular holes missed the
# plate entirely). Same form as aicad channel B (sw_rebuild.py
# real-machine contract: front-plane sketch + cut Dir=True).
HOLE_PLANE_ALIASES = {
    "front": ["Front Plane", "前视基准面"],
    "top": ["Front Plane", "前视基准面"],
    "right": ["Right Plane", "右视基准面"],
}


def _hole_sketch_plane(plane: str) -> str:
    """User-facing hole-plane alias -> the SW plane the sketch lands on."""
    key = plane.strip().lower()
    return "front" if key in ("top", "front") else key


def _get_active_part(sw_app: SolidWorksApp) -> Any:
    model = sw_app.get_active_document()
    if model is None or call_or_value(model, "GetType") != swDocPART:
        raise RuntimeError("No active part document")
    return model


def _select_hole_plane(model: Any, plane: str) -> Optional[str]:
    """Resolve a hole-plane alias (top means the +Z face, see above)."""
    candidates = HOLE_PLANE_ALIASES.get(plane.lower(), [plane])
    return select_plane(model, candidates)


def _select_plane(model: Any, plane: str) -> Optional[str]:
    candidates = PLANE_ALIASES.get(plane.lower(), [plane])
    return select_plane(model, candidates)


def _save_active_model(
    model: Any,
    save_path: Optional[str],
    overwrite_confirm: bool,
    result: Dict[str, Any],
) -> Optional[dict]:
    if not save_path:
        return None

    msg = prepare_part_save(save_path, overwrite_confirm)
    if msg:
        return error_response(msg, code="INVALID_OUTPUT_PATH")

    code, message = persist_part_save(model, save_path, result)
    if code:
        return error_response(message, code=code)
    return None


def create_new_part(
    sw_app: SolidWorksApp,
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
) -> dict:
    """Create a blank part document using the configured SolidWorks template."""
    try:
        message = prepare_part_save(save_path, overwrite_confirm)
        if message:
            return error_response(message, code="INVALID_OUTPUT_PATH")
        template = get_part_template()
        if not template:
            return error_response("Could not find a valid SolidWorks part template (.prtdot)")

        model = sw_app.app.NewDocument(template, 0, 0, 0)
        if model is None:
            return error_response("NewDocument returned None")

        data: Dict[str, Any] = {
            "title": call_or_value(model, "GetTitle"),
            "template": template,
        }
        save_error = _save_active_model(model, save_path, overwrite_confirm, data)
        if save_error:
            return save_error

        return success_response(data=data, message="Created new part document")
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to create new part")
        return error_response(f"Failed to create new part: {exc}")


def create_plate(
    sw_app: SolidWorksApp,
    width: float,
    depth: float,
    thickness: float,
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
) -> dict:
    """Create a rectangular plate using width/depth/thickness in millimeters."""
    try:
        width = positive_number("width", width)
        depth = positive_number("depth", depth)
        thickness = positive_number("thickness", thickness)
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    return create_box(sw_app, width, depth, thickness, save_path, overwrite_confirm)


def cut_round_hole(
    sw_app: SolidWorksApp,
    diameter: float,
    x: float,
    y: float,
    plane: str = "top",
    depth: Optional[float] = None,
    through_all: bool = True,
) -> dict:
    """Cut a round hole from a named base plane or user-supplied plane name."""
    try:
        diameter = positive_number("diameter", diameter)
        x = finite_number("x", x)
        y = finite_number("y", y)
        through_all = parse_bool("through_all", through_all)
        if not isinstance(plane, str) or not plane.strip():
            return error_response("plane must be a non-empty string", code="INVALID_PARAMETER")
        if not through_all:
            if depth is None:
                return error_response(
                    "depth is required when through_all is False",
                    code="INVALID_PARAMETER",
                )
            depth = positive_number("depth", depth)

        model = _get_active_part(sw_app)
        selected_plane = _select_hole_plane(model, plane)
        if selected_plane is None:
            return error_response(f"Could not select plane: {plane}")

        radius = mm_to_m(diameter) / 2.0
        model.SketchManager.InsertSketch(True)
        model.SketchManager.CreateCircleByRadius(mm_to_m(x), mm_to_m(y), 0, radius)
        model.SketchManager.InsertSketch(True)

        sketch_name = _latest_feature_name(model)
        if not sketch_name:
            return error_response("Could not identify the hole sketch")

        model.ClearSelection2(True)
        selected = model.Extension.SelectByID2(
            sketch_name,
            "SKETCHCONTOUR",
            0,
            0,
            0,
            True,
            4,
            pythoncom.Nothing,
            0,
        )
        if not selected:
            selected = model.Extension.SelectByID2(
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
        if not selected:
            return error_response(f"Could not select hole sketch: {sketch_name}")

        # C-9（2026-10-05）：through_all 时 cut_depth 仅是占位值——实际行为
        # 由 end_condition=1（swEndCondThroughAll）决定，diameter 分支只是
        # "无深度可传"时的填充，语义上与直径无关（此前一行表达式易误读）。
        if through_all or depth is None:
            placeholder_depth = diameter  # ignored when end_condition=1
        else:
            placeholder_depth = depth
        cut_depth = mm_to_m(placeholder_depth)
        end_condition = 1 if through_all else 0
        feature = cut_feature(model, True, through_all, end_condition, cut_depth)
        if feature is None:
            return error_response("Cut feature creation failed")

        return success_response(
            data={
                "feature_name": feature.Name,
                "diameter": diameter,
                "center": [x, y],
                "plane": selected_plane,
                "through_all": through_all,
                "depth": None if through_all else depth,
            },
            message="Created round cut hole",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to cut round hole")
        return error_response(f"Failed to cut round hole: {exc}")


def create_linear_holes(
    sw_app: SolidWorksApp,
    diameter: float,
    x: float,
    y: float,
    plane: str = "top",
    count: int = 2,
    spacing: float = 10.0,
    direction: str = "x",
    depth: Optional[float] = None,
    through_all: bool = True,
) -> dict:
    """Cut a linear row of round holes (non-native rebuilt primitives).

    SW 2026 exposes no working COM path for FeatureLinearPattern4 on this
    machine (13-probe evidence, tools/probe_part/probe_n9_unblock.py), so
    this loops the native cut primitive instead of creating a parametric
    pattern feature — NOT parametric-linked to a seed feature.
    """
    try:
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = -1
        if count < 1 or count > 200:
            return error_response(
                "count must be between 1 and 200", code="INVALID_PARAMETER"
            )
        if direction not in ("x", "y"):
            return error_response(
                "direction must be 'x' or 'y'", code="INVALID_PARAMETER"
            )
        spacing = positive_number("spacing", spacing)

        cut: List[Dict[str, Any]] = []
        for i in range(count):
            hx = x + i * spacing if direction == "x" else x
            hy = y + i * spacing if direction == "y" else y
            result = cut_round_hole(
                sw_app, diameter, hx, hy, plane, depth, through_all
            )
            if not result.get("success"):
                return error_response(
                    f"Hole {i + 1}/{count} failed: "
                    f"{result.get('message')}",
                    code=(result.get("error") or {}).get(
                        "code", "SW_API_ERROR"
                    ),
                )
            cut.append({"index": i + 1, "x": hx, "y": hy})

        return success_response(
            data={
                "holes": cut,
                "count": count,
                "direction": direction,
                "spacing": spacing,
                "diameter": diameter,
                "native": False,
            },
            message=(
                f"Cut {count} holes along {direction} at {spacing}mm spacing"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to create linear holes")
        return error_response(f"Failed to create linear holes: {exc}")


# Through-all hole mouths sit at unknown distances along the sketch-plane
# normal (they meet the part surfaces, not the sketch plane), so the
# coordinate-based EDGE pick sweeps these offsets in metres.
_NORMAL_OFFSETS_THROUGH_ALL_M = (
    0.0, 0.002, -0.002, 0.005, -0.005, 0.01, -0.01,
    0.02, -0.02, 0.04, -0.04, 0.08, -0.08, 0.16, -0.16, 0.32, -0.32,
)


def _mouth_point_model_coords(
    x_m: float, y_m: float, plane: str, normal_m: float
) -> tuple:
    """Map the 45-degree sketch-space mouth point into MODEL coordinates.

    Sketch (x, y) live on the named base plane; SelectByID2 wants model
    (X, Y, Z). Blind-hole mouths sit on the sketch plane itself (offset 0);
    through-all mouths sit wherever the hole meets the part surfaces.
    """
    key = plane.strip().lower()
    if key == "top":  # sketch x->X, sketch y->Z, normal along Y
        return (x_m, normal_m, y_m)
    if key == "right":  # sketch x->Y, sketch y->Z, normal along X
        return (normal_m, x_m, y_m)
    # front (and unknown planes): sketch x->X, sketch y->Y, normal along Z
    return (x_m, y_m, normal_m)


def _stamp_cosmetic_thread(
    model: Any,
    spec: str,
    drill_diameter: float,
    x: float,
    y: float,
    depth: Optional[float],
    plane: str = "front",
) -> bool:
    """Best-effort cosmetic thread on the hole-mouth edge (never fatal).

    The circular edge is picked by coordinates at 45 degrees off the
    sketch axes, mapped into model space for the sketch plane (real-machine
    probe contract); the major diameter comes from the spec name itself
    ("M8" -> 8 mm). The created feature is NOT enumerable over
    FirstFeature/GetNextFeature, so callers must verify via the returned
    boolean, never via a tree walk.
    """
    radius_m = mm_to_m(drill_diameter) / 2.0
    diagonal = radius_m * math.cos(math.pi / 4.0)
    # Blind holes carry their real depth; through holes fall back to the
    # nominal diameter as a conservative annotation length.
    major_m = float(spec[1:]) / 1000.0
    depth_m = mm_to_m(depth) if depth else major_m
    note = f"{spec}x{THREAD_SPECS[spec][1]:g}"
    sx = mm_to_m(x) + diagonal
    sy = mm_to_m(y) + diagonal
    offsets = (0.0,) if depth else _NORMAL_OFFSETS_THROUGH_ALL_M
    sketch_plane = _hole_sketch_plane(plane)
    model.ClearSelection2(True)
    picked = False
    for offset in offsets:
        px, py, pz = _mouth_point_model_coords(sx, sy, sketch_plane, offset)
        picked = model.Extension.SelectByID2(
            "",
            "EDGE",
            px,
            py,
            pz,
            False,
            0,
            pythoncom.Nothing,
            0,
        )
        if picked:
            break
    if not picked:
        logger.debug("thread mouth edge for %s not selected", spec)
        return False
    try:
        created = model.FeatureManager.InsertCosmeticThread2(
            0,
            major_m,
            depth_m,
            note,
        )
    except Exception:
        logger.debug("InsertCosmeticThread2 failed", exc_info=True)
        return False
    return created is not None


def cut_threaded_hole(
    sw_app: SolidWorksApp,
    spec: str,
    x: float,
    y: float,
    plane: str = "top",
    depth: Optional[float] = None,
    through_all: bool = True,
) -> dict:
    """Cut an ISO coarse-thread hole at its tap-drill diameter with a cosmetic thread.

    The hole itself is a plain ``cut_round_hole`` at the ISO 273 tap-drill
    diameter; the thread is stamped as a best-effort cosmetic annotation
    (HoleWizard requires interactive panels this channel cannot drive).
    """
    try:
        if not isinstance(spec, str) or not spec.strip():
            return error_response(
                "spec must be a non-empty string like 'M6'",
                code="INVALID_PARAMETER",
            )
        spec_key = spec.strip().upper()
        thread_spec = THREAD_SPECS.get(spec_key)
        if thread_spec is None:
            supported = ", ".join(sorted(THREAD_SPECS))
            return error_response(
                f"Unsupported thread spec: {spec}. Supported: {supported}",
                code="INVALID_PARAMETER",
            )
        drill_diameter, pitch = thread_spec

        cut = cut_round_hole(sw_app, drill_diameter, x, y, plane, depth, through_all)
        if not cut.get("success"):
            return cut

        stamped = _stamp_cosmetic_thread(
            _get_active_part(sw_app), spec_key, drill_diameter, x, y, depth, plane
        )

        data: Dict[str, Any] = dict(cut.get("data") or {})
        data["thread"] = {
            "spec": spec_key,
            "tap_drill_diameter": drill_diameter,
            "pitch": pitch,
            "cosmetic_thread_stamped": stamped,
        }
        return success_response(
            data=data,
            message=(
                f"Created {spec_key} threaded hole "
                f"(tap drill {drill_diameter}mm on plane {plane})"
            ),
            warning=(
                None
                if stamped
                else "Cosmetic thread annotation was skipped (hole mouth edge not selectable)."
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to cut threaded hole")
        return error_response(f"Failed to cut threaded hole: {exc}")


def execute_design_plan(
    sw_app: SolidWorksApp,
    operations: List[Dict[str, Any]],
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
    atomic: bool = True,
) -> dict:
    """Execute a small ordered design plan made of supported operations.

    With ``atomic=True`` (default) any failed operation triggers a rollback:
    features added since the plan started are deleted in reverse tree order,
    so retrying a plan never stacks half-applied features. Rollback failures
    never mask the original error — they surface as ``rollback_warning``.
    """
    # C-5（2026-10-05）：先类型后空检查——None 报类型错误（不是"空列表"），
    # 传字符串等其他容器报 list 错误，消息各自准确。
    if not isinstance(operations, list):
        return error_response(
            f"operations must be a list, got "
            f"{type(operations).__name__ or 'None'}",
            code="INVALID_PARAMETER",
        )
    if not operations:
        return error_response(
            "operations must contain at least one operation",
            code="INVALID_PARAMETER",
        )
    if save_path:
        valid, message = validate_output_file(
            save_path, {".sldprt"}, overwrite_confirm
        )
        if not valid:
            return error_response(message, code="INVALID_OUTPUT_PATH")

    initial_model = sw_app.get_active_document()
    before = _snapshot_feature_names(initial_model)
    results: List[dict] = []
    applied: List[int] = []
    for index, operation in enumerate(operations, start=1):
        try:
            op_type = (
                str(operation.get("type", "")).lower()
                if isinstance(operation, dict)
                else ""
            )
            if not isinstance(operation, dict):
                # N10: parameter errors flow through the unified failure
                # path below so atomic rollback (and shell close) still runs —
                # a bare return here used to leak the op-1 shell document.
                result = error_response(
                    f"Operation {index} must be an object",
                    code="INVALID_PARAMETER",
                )
            elif op_type in {"box", "block", "plate"}:
                thickness = operation.get("thickness", operation.get("height"))
                if thickness is None:
                    result = error_response(
                        f"Operation {index} requires thickness or height"
                    )
                else:
                    result = create_plate(
                        sw_app,
                        float(operation["width"]),
                        float(operation["depth"]),
                        float(thickness),
                    )
            elif op_type == "cylinder":
                result = create_cylinder(
                    sw_app,
                    float(operation["diameter"]),
                    float(operation["height"]),
                )
            elif op_type in {"hole", "round_hole", "cut_hole"}:
                result = cut_round_hole(
                    sw_app,
                    diameter=float(operation["diameter"]),
                    x=float(operation.get("x", 0.0)),
                    y=float(operation.get("y", 0.0)),
                    plane=str(operation.get("plane", "top")),
                    depth=(
                        None
                        if operation.get("depth") is None
                        else float(operation.get("depth"))
                    ),
                    through_all=parse_bool(
                        "through_all", operation.get("through_all", True)
                    ),
                )
            elif op_type == "cone":
                result = create_cone(
                    sw_app,
                    float(operation["bottom_diameter"]),
                    float(operation.get("top_diameter", 0.0)),
                    float(operation["height"]),
                )
            elif op_type in {"threaded_hole", "thread_hole"}:
                result = cut_threaded_hole(
                    sw_app,
                    spec=str(operation["spec"]),
                    x=float(operation.get("x", 0.0)),
                    y=float(operation.get("y", 0.0)),
                    plane=str(operation.get("plane", "top")),
                    depth=(
                        None
                        if operation.get("depth") is None
                        else float(operation.get("depth"))
                    ),
                    through_all=parse_bool(
                        "through_all", operation.get("through_all", True)
                    ),
                )
            elif op_type in {"annular_pattern", "ring_pattern"}:
                # Imported here (not at module top) because pattern.py itself
                # imports plane aliases and save helpers from this module.
                from solidworks_mcp.solidworks_api.pattern import create_annular_pattern

                rings = operation.get("rings")
                if not isinstance(rings, list) or not rings:
                    result = error_response(
                        f"Operation {index} requires a non-empty 'rings' list",
                        code="INVALID_PARAMETER",
                    )
                else:
                    result = create_annular_pattern(
                        sw_app,
                        rings,
                        plane=str(operation.get("plane", "top")),
                        feature_kind=str(operation.get("feature_kind", "cut")),
                        depth=(
                            None
                            if operation.get("depth") is None
                            else float(operation.get("depth"))
                        ),
                        through_all=parse_bool(
                            "through_all", operation.get("through_all", True)
                        ),
                        avoid_angles_degrees=operation.get("avoid_angles_degrees"),
                    )
            elif op_type == "new_part":
                result = create_new_part(sw_app)
            else:
                result = error_response(
                    f"Unsupported operation at index {index}: {op_type}. "
                    f"Supported types: {', '.join(DESIGN_PLAN_OPERATIONS)}."
                )
        except KeyError as exc:
            result = error_response(
                f"Operation {index} is missing required key: {exc}",
                code="INVALID_PARAMETER",
            )
        except (TypeError, ValueError) as exc:
            result = error_response(
                f"Operation {index} has invalid parameter values: {exc}",
                code="INVALID_PARAMETER",
            )

        results.append({"index": index, "operation": op_type, "result": result})
        if not result.get("success"):
            data = {
                "completed": results,
                "applied": applied,
                "failed": index,
                "rolled_back": None,
            }
            if atomic:
                rolled_back, warning = _delete_new_features(sw_app, before)
                data["rolled_back"] = rolled_back
                if warning:
                    data["rollback_warning"] = warning
                if initial_model is None:
                    # N10: the document was implicitly created by the plan
                    # itself; closing it discards any rollback leftovers in
                    # one shot. Real-machine note (probe_n10_shell): a fresh
                    # SW document's tree already holds ~17 inherent folder
                    # nodes (收藏/注解/基准面…) rollback can never delete,
                    # so a warning-free shell rollback is impossible — the
                    # close must not depend on the warning being absent.
                    data["shell_closed"] = _close_plan_created_shell(sw_app)
            stopped_code = (result.get("error") or {}).get("code")
            return error_response(
                f"Design plan stopped at operation {index}: {result.get('message')}",
                data=data,
                code=stopped_code,
            )
        applied.append(index)

    active = sw_app.get_active_document()
    if active is not None and save_path:
        save_error = _save_active_model(active, save_path, overwrite_confirm, {})
        if save_error:
            return save_error

    return success_response(
        data={"operations": results, "saved_to": save_path},
        message=f"Executed {len(operations)} design operations",
    )


def _close_plan_created_shell(sw_app: SolidWorksApp) -> bool:
    """Close the empty shell document implicitly created by the plan.

    N10 leak fix: ``new_part`` opens a blank document; when an atomic plan
    rolls back to empty, that blank shell would linger in the SW session
    forever. Only called when rollback completed without a warning and the
    plan started with no active document. Best-effort: failures return
    False, never raise.
    """
    try:
        model = sw_app.get_active_document()
        if model is None:
            return False
        title = call_or_value(model, "GetTitle")
        if not isinstance(title, str) or not title.strip():
            return False
        sw_app.app.CloseDoc(title)
        return True
    except Exception:
        logger.debug("Failed to close plan-created shell document", exc_info=True)
        return False


def _snapshot_feature_names(model: Optional[Any]) -> set:
    """Snapshot the feature-name set for later diffing (atomic plans)."""
    if model is None:
        return set()
    return set(walk_feature_names(model))


_ROLLBACK_LIST_CAP = 200  # keep responses/logs bounded under pathological trees


def _cap_names(names: List[str]) -> List[str]:
    if len(names) > _ROLLBACK_LIST_CAP:
        return names[:_ROLLBACK_LIST_CAP] + [f"…and {len(names) - _ROLLBACK_LIST_CAP} more"]
    return names


# Inherent features every new SW document ships with (N10 probe_n10_shell
# evidence): not plan-created, not deletable (EditDelete silently fails on
# them yet SelectByID2 still picks them — a deleted-list false positive).
# Excluded so a plan that starts from no document can roll back to "empty".
_INHERENT_FEATURE_NAMES = {"原点", "Origin"}


def _delete_new_features(
    sw_app: SolidWorksApp, before: set
) -> tuple:
    """Delete every feature added after the snapshot, in reverse tree order.

    Selection tries BODYFEATURE first and SKETCH second — real-machine
    evidence (T10): a plate step creates a sketch plus an extrusion, and
    SelectByID2 only resolves sketches under the "SKETCH" type (an empty
    type string does not wildcard).
    Returns ``(deleted_names, warning)``; both are capped so a pathological
    tree cannot explode the response payload; the warning never masks the
    original plan error.
    """
    deleted: List[str] = []
    try:
        model = sw_app.get_active_document()
        if model is None:
            return deleted, None
        new_names = [
            n
            for n in walk_feature_names(model)
            if n not in before and n not in _INHERENT_FEATURE_NAMES
        ]
        for name in reversed(new_names):
            picked = False
            for type_string in ("BODYFEATURE", "SKETCH"):
                model.ClearSelection2(True)
                picked = model.Extension.SelectByID2(
                    name, type_string, 0, 0, 0, False, 0, pythoncom.Nothing, 0
                )
                if picked:
                    break
            if not picked:
                continue
            call_or_value(model, "EditDelete")
            deleted.append(name)
        remaining = [
            n
            for n in walk_feature_names(model)
            if n not in before and n not in _INHERENT_FEATURE_NAMES
        ]
        warning = (
            "rollback incomplete, "
            f"{len(remaining)} feature(s) left in tree: {_cap_names(remaining)}"
            if remaining
            else None
        )
        return _cap_names(deleted), warning
    except Exception as exc:
        logger.exception("Design-plan rollback failed")
        return _cap_names(deleted), f"rollback error: {exc}"


# --- T16: cross-engine CSG rebuild (contract v1, docs/csg-plan-v1.md) ---

# Contract versions rebuild_csg_plan accepts (docs/csg-plan-v1.md).
CSG_VERSIONS = (1, 2)
CSG_V2_OPS = ("polygon_prism", "swept_arc")
CSG_OPS = ("box", "cylinder", "cone", "cut_cylinder") + CSG_V2_OPS
_Z_TOLERANCE = 1e-6


def _validate_csg_plan(plan: Any) -> Optional[str]:
    """Manual contract validation; returns the first problem or None."""
    if not isinstance(plan, dict):
        return "plan must be a dict"
    version = plan.get("version")
    if version not in CSG_VERSIONS:
        return (f"unsupported plan version {version!r} "
                f"(expected one of {', '.join(str(v) for v in CSG_VERSIONS)})")
    if plan.get("units") != "mm":
        return "units must be 'mm'"
    ops = plan.get("operations")
    if not isinstance(ops, list) or not ops:
        return "operations must be a non-empty list"
    names = set()
    for index, op in enumerate(ops):
        if not isinstance(op, dict):
            return f"operation[{index}] must be a dict"
        kind = op.get("op")
        if kind not in CSG_OPS:
            return (f"operation[{index}]: unknown op {kind!r} "
                    f"(supported: {', '.join(CSG_OPS)})")
        if kind in CSG_V2_OPS and version != 2:
            return (f"operation[{index}]: {kind} requires version 2 "
                    f"(plan is version {version})")
        name = op.get("name")
        if not isinstance(name, str) or not name:
            return f"operation[{index}]: name must be a non-empty string"
        if name in names:
            return (f"operation[{index}]: feature names must be unique "
                    f"({name!r})")
        names.add(name)
        at = op.get("at")
        if (
            not isinstance(at, (list, tuple))
            or len(at) != 3
            or not all(isinstance(v, (int, float)) for v in at)
        ):
            return f"operation[{index}]: at must be three numbers [x, y, z]"

        def _positive(key):
            value = op.get(key)
            # bool is an int subclass and NaN/inf compare oddly — exclude all
            # three so the contract matches validation.finite_number.
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                return f"operation[{index}]: {kind} needs a positive {key}"
            return None

        if kind == "box":
            size = op.get("size")
            if (
                not isinstance(size, (list, tuple))
                or len(size) != 3
                or not all(isinstance(v, (int, float)) and v > 0 for v in size)
            ):
                return ("operation[{index}]: box needs size=[width, depth, "
                        "height] with positive numbers")
        elif kind == "cylinder":
            problem = _positive("diameter") or _positive("height")
            if problem:
                return problem
        elif kind == "cone":
            problem = (
                _positive("bottom_diameter")
                or _positive("top_diameter")
                or _positive("height")
            )
            if problem:
                return problem
        elif kind == "cut_cylinder":
            problem = _positive("diameter")
            if problem:
                return problem
            depth = op.get("depth")
            if depth is not None and (
                not isinstance(depth, (int, float)) or depth <= 0
            ):
                return ("operation[{index}]: cut_cylinder depth must be "
                        "positive or null")
            if depth is None and not op.get("through"):
                return ("operation[{index}]: cut_cylinder needs depth or "
                        "through=true")
        if kind == "polygon_prism":
            sides = op.get("sides")
            if (
                not isinstance(sides, int)
                or isinstance(sides, bool)
                or not 3 <= sides <= 60
            ):
                return (f"operation[{index}]: polygon_prism sides must be "
                        f"an integer in [3, 60]")
            problem = _positive("circumradius") or _positive("height")
            if problem:
                return problem
            inscribed = op.get("inscribed", True)
            if not isinstance(inscribed, bool):
                return (f"operation[{index}]: polygon_prism inscribed must "
                        f"be a boolean")
        elif kind == "swept_arc":
            problem = _positive("diameter") or _positive("arc_radius")
            if problem:
                return problem
            angle = op.get("angle_deg", 90.0)
            if not isinstance(angle, (int, float)) or not 0 < angle <= 360:
                return (f"operation[{index}]: swept_arc angle_deg must be in "
                        f"(0, 360]")
    return None


class _CsgPlanError(Exception):
    """Plan-level rejection (INVALID_PARAMETER, no rollback)."""


def _csg_op_box(sw_app, op, index, plan, stack_top):
    x, y, z = (float(v) for v in op["at"])
    if index != 0 or abs(x) > 1e-9 or abs(y) > 1e-9 or abs(z) > 1e-9:
        raise _CsgPlanError(
            "operation[0]: v1 requires the box to be the first op "
            "at [0, 0, 0] (stacking starts at the origin)"
        )
    width, depth, height = (float(v) for v in op["size"])
    result = part_module.create_box(sw_app, width, depth, height)
    return result, height


def _csg_op_polygon_prism(sw_app, op, index, plan, stack_top):
    x, y, z = (float(v) for v in op["at"])
    if index != 0 or abs(x) > 1e-9 or abs(y) > 1e-9 or abs(z) > 1e-9:
        raise _CsgPlanError(
            f"operation[{index}]: v2 polygon_prism is a first op only "
            "at [0, 0, 0]"
        )
    result = part_module.create_polygon(
        sw_app,
        op["sides"],
        float(op["circumradius"]),
        float(op["height"]),
        inscribed=op.get("inscribed", True),
    )
    return result, float(op["height"])


def _csg_op_swept_arc(sw_app, op, index, plan, stack_top):
    x, y, z = (float(v) for v in op["at"])
    if index != 0 or abs(x) > 1e-9 or abs(y) > 1e-9 or abs(z) > 1e-9:
        raise _CsgPlanError(
            f"operation[{index}]: v2 swept_arc is a first op only "
            "at [0, 0, 0]"
        )
    if len(plan["operations"]) != 1:
        raise _CsgPlanError(
            f"operation[{index}]: swept_arc admits no "
            "following operations (no stacking axis)"
        )
    result = part_module.create_swept(
        sw_app,
        float(op["diameter"]),
        "arc",
        float(op["arc_radius"]),
        float(op.get("angle_deg", 90.0)),
    )
    return result, None  # a torus segment has no stacking axis


def _csg_op_stacked_solid(sw_app, op, index, plan, stack_top):
    kind = op["op"]
    x, y, z = (float(v) for v in op["at"])
    if stack_top is None:
        raise _CsgPlanError(
            f"operation[{index}]: nothing stacks on a swept_arc"
        )
    if abs(x) > 1e-9 or abs(y) > 1e-9:
        raise _CsgPlanError(
            f"operation[{index}]: v1 stacks solids on the axis "
            "(at.x/at.y must be 0)"
        )
    if abs(z - stack_top) > _Z_TOLERANCE:
        raise _CsgPlanError(
            f"operation[{index}]: at.z={z} does not match the "
            f"current stack top {stack_top} (v1 supports "
            "stacking only)"
        )
    if kind == "cylinder":
        builder = (
            part_module.create_cylinder
            if stack_top == 0.0
            else part_module.create_cylinder_on_face
        )
        result = builder(sw_app, op["diameter"], op["height"])
    else:
        builder = (
            part_module.create_cone
            if stack_top == 0.0
            else part_module.create_cone_on_face
        )
        result = builder(
            sw_app,
            op["bottom_diameter"],
            op["top_diameter"],
            op["height"],
        )
    return result, z + float(op["height"])


def _csg_op_cut_cylinder(sw_app, op, index, plan, stack_top):
    x, y, _z = (float(v) for v in op["at"])
    if stack_top is None:
        raise _CsgPlanError(
            f"operation[{index}]: cut_cylinder needs a stack "
            "top (nothing follows a swept_arc)"
        )
    result = cut_round_hole(
        sw_app,
        op["diameter"],
        x,
        y,
        "top",
        op.get("depth"),
        bool(op.get("through")),
    )
    return result, stack_top  # cuts never move the stack top


#: op -> handler (N38, review M-3): every handler owns its stack-top
#: precondition (a missed None check can no longer hide in a long elif
#: chain), unknown ops hit the explicit fallback below, and each entry
#: keeps the exact validation messages the contract tests pin.
_CSG_HANDLERS = {
    "box": _csg_op_box,
    "polygon_prism": _csg_op_polygon_prism,
    "swept_arc": _csg_op_swept_arc,
    "cylinder": _csg_op_stacked_solid,
    "cone": _csg_op_stacked_solid,
    "cut_cylinder": _csg_op_cut_cylinder,
}


def rebuild_csg_plan(sw_app: SolidWorksApp, plan: dict) -> dict:
    """Rebuild a cross-engine CSG plan (contract v1) as an SW feature tree.

    v1 semantics (docs/csg-plan-v1.md): operations apply sequentially;
    solid ops stack on the axis -- ``at.z`` must equal the current stack
    top (box first at the origin; later solids sketch on the body's top
    face, real-machine verified exact). ``cut_cylinder`` supports x/y
    offsets and cuts from the top. Failures roll back atomically (T10
    machinery). Ops dispatch to the existing part primitives; each new
    feature is renamed to the contract's ``name``.
    """
    try:
        problem = _validate_csg_plan(plan)
        if problem:
            return error_response(problem, code="INVALID_PARAMETER")

        model = sw_app.get_active_document()
        if model is None or call_or_value(model, "GetType") != swDocPART:
            try:
                model, _created = part_module._get_or_create_part(sw_app)
            except Exception as exc:
                return error_response(
                    f"Could not create a part document: {exc}",
                    code="SW_API_ERROR",
                )
        before = _snapshot_feature_names(model)

        applied = []
        stack_top = 0.0  # None after swept_arc: nothing stacks on it

        def _fail(result):
            rolled_back, warning = _delete_new_features(sw_app, before)
            data = {
                "applied_before_failure": applied,
                "rolled_back": rolled_back,
            }
            if warning:
                data["rollback_warning"] = warning
            return error_response(
                f"CSG plan stopped at operation {len(applied)}: "
                f"{result.get('message')}",
                data=data,
            )

        for index, op in enumerate(plan["operations"]):
            kind = op["op"]
            name = op["name"]
            handler = _CSG_HANDLERS.get(kind)
            if handler is None:
                # _validate_csg_plan rejects unknowns first; this explicit
                # fallback keeps dispatch safe even if the two ever drift.
                return error_response(
                    f"operation[{index}]: unknown op {kind!r} "
                    f"(supported: {', '.join(CSG_OPS)})",
                    code="INVALID_PARAMETER",
                )
            try:
                result, stack_top = handler(
                    sw_app, op, index, plan, stack_top
                )
            except _CsgPlanError as exc:
                return error_response(str(exc), code="INVALID_PARAMETER")
            if not result.get("success"):
                return _fail(result)

            feature_name = (result.get("data") or {}).get("feature_name")
            final_name = name
            if isinstance(feature_name, str) and feature_name != name:
                renamed = rename_feature(sw_app, feature_name, name)
                if not renamed.get("success"):
                    final_name = feature_name
            applied.append(final_name)

        return success_response(
            data={
                "applied": applied,
                "feature_count": len(applied),
                "stack_top_mm": (
                    round(stack_top, 6) if stack_top is not None else None
                ),
                "rolled_back": False,
            },
            message=(
                f"Rebuilt {len(applied)} CSG features (stack top "
                f"{round(stack_top, 3) if stack_top is not None else 'n/a'}mm)"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to rebuild CSG plan")
        return error_response(f"Failed to rebuild CSG plan: {exc}")
