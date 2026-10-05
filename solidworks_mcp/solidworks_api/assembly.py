"""Assembly-level SolidWorks operations."""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Dict, List, Optional

import pythoncom
import win32com.client

from solidworks_mcp.solidworks_api.app import SolidWorksApp, SolidWorksNotRunningError
from solidworks_mcp.solidworks_api.constants import (
    swDocASSEMBLY,
    swMateANGLE,
    swMateCOINCIDENT,
    swMateCONCENTRIC,
    swMateDISTANCE,
    swMateTANGENT,
    swMateWIDTH,
    swSaveAsOptions_Silent,
)
from solidworks_mcp.solidworks_api import file_io
from solidworks_mcp.utils.common import error_response, success_response
from solidworks_mcp.utils.com import call_or_value
from solidworks_mcp.utils.security import (
    ensure_sink_path,
    validate_extension,
    validate_output_file,
    validate_path,
)
from solidworks_mcp.utils.templates import get_assembly_template
from solidworks_mcp.utils.validation import finite_number

logger = logging.getLogger(__name__)

MAX_INTERFERENCES = 50
MAX_COMPONENTS = 500
MAX_TREE_WALK = 500
IDENTITY_XFORM = (
    1.0, 0.0, 0.0,
    0.0, 1.0, 0.0,
    0.0, 0.0, 1.0,
    0.0, 0.0, 0.0,
    1.0,
    0.0, 0.0, 0.0,
)

ENTITY_TYPES = ("FACE", "PLANE", "AXIS", "EDGE", "VERTEX")
REFERENCE_PLANE_ALIASES = {
    "Front Plane": "前视基准面",
    "Top Plane": "上视基准面",
    "Right Plane": "右视基准面",
    "前视基准面": "Front Plane",
    "上视基准面": "Top Plane",
    "右视基准面": "Right Plane",
}


def _get_or_create_assembly(sw_app: SolidWorksApp) -> Any:
    """Return the active assembly document, creating a new one if necessary."""
    model = sw_app.get_active_document()
    if model is not None and call_or_value(model, "GetType") == swDocASSEMBLY:
        return model

    template = get_assembly_template()
    if not template:
        raise RuntimeError(
            "Could not find a valid SolidWorks assembly template (.asmdot)"
        )

    model = sw_app.app.NewDocument(template, 0, 0, 0)
    if model is None:
        raise RuntimeError("NewDocument returned None for assembly")
    return model


def new_assembly(
    sw_app: SolidWorksApp,
    save_path: Optional[str] = None,
    overwrite_confirm: bool = False,
) -> dict:
    """Create a new empty assembly document (GB template).

    Real machine (T11 probe): ``AddComponent4`` silently returns None unless
    the component's document is already open in the session — the component
    tools below pre-open parts via OpenDoc6.
    """
    try:
        template = get_assembly_template()
        if not template:
            return error_response(
                "No assembly template found; set SOLIDWORKS_MCP_ASSEMBLY_TEMPLATE "
                "to a .asmdot file",
                code="TEMPLATE_NOT_FOUND",
            )
        model = sw_app.app.NewDocument(template, 0, 0, 0)
        if model is None:
            return error_response(
                "SolidWorks rejected creating the assembly document",
                code="SW_API_ERROR",
            )

        saved_path = None
        if save_path:
            valid, msg = validate_output_file(
                save_path, {".sldasm"}, overwrite_confirm
            )
            if not valid:
                return error_response(msg, code="INVALID_OUTPUT_PATH")
            ok, message, sink_path = ensure_sink_path(save_path)
            if not ok:
                return error_response(message, code="INVALID_OUTPUT_PATH")
            result = model.SaveAs3(sink_path, 0, swSaveAsOptions_Silent)
            if result != 0:
                return error_response(f"Saving assembly failed with code {result}")
            saved_path = save_path

        return success_response(
            data={
                "title": call_or_value(model, "GetTitle"),
                "template": template,
                "type": swDocASSEMBLY,
                "saved_path": saved_path,
            },
            message="Created new assembly document",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to create assembly")
        return error_response(f"Failed to create assembly: {exc}")


def _preopen_component_document(sw_app: SolidWorksApp, file_path: str) -> Optional[str]:
    """Open the component document before AddComponent4 (real-machine rule).

    Returns None on success or an error message.
    """
    try:
        doc_type = file_io._guess_document_type(file_path)
        model, error_code, _ = file_io._open_doc6(sw_app.app, file_path, doc_type)
    except Exception as exc:
        return f"could not open component document ({exc})"
    if model is None:
        return (
            "SolidWorks would not open the component document "
            f"(load error {error_code}); AddComponent4 requires the part to "
            "be open in the session"
        )
    return None


def _document_is_open(sw_app: SolidWorksApp, file_path: str) -> bool:
    """Return True when the document is already open in the SW session.

    Uses ``GetOpenDocumentByName`` (NOT the ...Name2 variant): the makepy
    typed wrapper shipped with real SW sessions has no ``...Name2`` method
    (N10 probe evidence), and matching is by FULL PATH only — the document
    title ("comp0.SLDPRT") does not match.
    """
    try:
        return sw_app.app.GetOpenDocumentByName(file_path) is not None
    except Exception:
        return False


def _close_preopened_component(sw_app: SolidWorksApp, file_path: str) -> None:
    """Close a document this tool pre-opened for AddComponent4 (best-effort).

    Only meaningful on the FAILED-insert path: once an assembly references
    the part, CloseDoc is silently ignored (SW holds the document until the
    assembly closes — N10 probe_n10_asmclose evidence: count 3→3, doc still
    queryable). With no reference, CloseDoc(full path) works (probe #1).
    Never raises: a failed close must not mask the add failure.
    """
    try:
        sw_app.app.CloseDoc(file_path)
    except Exception:
        logger.debug(
            "Failed to close pre-opened component document: %s",
            file_path,
            exc_info=True,
        )


def add_component(
    sw_app: SolidWorksApp,
    file_path: str,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    config_name: str = "",
) -> dict:
    """Insert a component into the active assembly."""
    try:
        valid, msg = validate_path(file_path, must_exist=True)
        if not valid:
            return error_response(msg)
        valid, msg = validate_extension(file_path, {".sldprt", ".sldasm"})
        if not valid:
            return error_response(msg, code="INVALID_PARAMETER")

        x = finite_number("x", x)
        y = finite_number("y", y)
        z = finite_number("z", z)
        # Grab the assembly BEFORE pre-opening the component: OpenDoc6
        # switches the active document to the part, so resolving the
        # assembly afterwards would create a NEW empty assembly every call
        # and the component would land in the wrong document (real-machine
        # two-component probe, N32 — components silently vanished).
        model = _get_or_create_assembly(sw_app)
        was_open = _document_is_open(sw_app, file_path)
        preopen_error = _preopen_component_document(sw_app, file_path)
        if preopen_error:
            return error_response(preopen_error, code="SW_API_ERROR")
        # AddComponent4(path, configName, x, y, z)
        component = model.AddComponent4(file_path, config_name, x / 1000.0, y / 1000.0, z / 1000.0)
        if component is None:
            # Failed insert: nothing references the pre-opened document yet,
            # so close it or it lingers in the session forever (N10 fix —
            # real-machine rule: after a SUCCESSFUL insert the assembly holds
            # the document and CloseDoc is silently ignored; on failure there
            # is no reference and CloseDoc(full path) works).
            if not was_open:
                _close_preopened_component(sw_app, file_path)
            return error_response(f"Failed to add component: {file_path}")

        # The pre-open switched the active document to the part; switch
        # back so subsequent tools act on the assembly (best-effort).
        try:
            sw_app.app.ActivateDoc3(model.GetTitle, True, 0, 0)
        except Exception:  # noqa: BLE001 —— 激活失败不掩盖成功的插入
            logger.debug("ActivateDoc3 back to assembly failed", exc_info=True)

        return success_response(
            data={
                "component_name": component.Name2,
                "file_path": file_path,
                "position": [x, y, z],
            },
            message=f"Added component: {os.path.basename(file_path)}",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to add component")
        return error_response(f"Failed to add component: {exc}")


def add_mate(
    sw_app: SolidWorksApp,
    mate_type: str,
    entity1: str,
    entity2: str,
    distance: Optional[float] = None,
    entity1_type: str = "AUTO",
    entity2_type: str = "AUTO",
) -> dict:
    """Add a mate between two named entities in the active assembly.

    Args:
        mate_type: One of "coincident", "concentric", "distance", "tangent",
            "angle", "width". Real machine (T11 probe): coincident/distance/
            angle verified — angle mates must pass the value through the
            ``Angle`` slot (parameter 10) in radians; tangent verified via
            the IEntity face-selection path (N8 probe_tangent_width);
            width needs a 4-selection slot/tab fixture and remains
            unverified (N15).
        entity1: Name of the first face/plane/axis (e.g. "Front Plane@Part1-1").
        entity2: Name of the second face/plane/axis.
        distance: Distance in mm (distance mate) or angle in degrees
            (angle mate). Entity names must be component-qualified and are
            selected as "<name>@<assembly title>" first — bare names can
            mis-select on the real machine.
    """
    try:
        model = sw_app.get_active_document()
        if model is None or call_or_value(model, "GetType") != swDocASSEMBLY:
            return error_response("No active assembly document")

        mate_type_map = {
            "coincident": swMateCOINCIDENT,
            "concentric": swMateCONCENTRIC,
            "distance": swMateDISTANCE,
            "tangent": swMateTANGENT,
            "angle": swMateANGLE,
            "width": swMateWIDTH,
        }
        mate_type_val = mate_type_map.get(mate_type.lower())
        if mate_type_val is None:
            return error_response(
                f"Unsupported mate type: {mate_type}. "
                "Use: coincident, concentric, distance, tangent, angle, width"
            )
        if mate_type_val in (swMateDISTANCE, swMateANGLE):
            if distance is None:
                return error_response(
                    f"distance is required for a {mate_type} mate "
                    "(mm for distance, degrees for angle)",
                    code="INVALID_PARAMETER",
                )
            distance = finite_number("distance", distance)
            # C-4（2026-10-05）：distance mate 的偏移必须非负；angle mate
            # 的 distance 参数承载角度（度，SignedMM 语义）——负角合法，
            # 仅要求 finite（finite_number 已保证），不得误拒。
            if mate_type_val == swMateDISTANCE and distance < 0:
                return error_response(
                    "distance must be zero or greater",
                    code="INVALID_PARAMETER",
                )

        assembly_title = os.path.splitext(call_or_value(model, "GetTitle"))[0]

        def select_entity(name: str, requested_type: str, append: bool) -> Optional[str]:
            candidates = (
                ENTITY_TYPES
                if requested_type.upper() == "AUTO"
                else (requested_type.upper(),)
            )
            base_names = [name]
            plane_name, separator, component_name = name.partition("@")
            alias = REFERENCE_PLANE_ALIASES.get(plane_name)
            if alias:
                base_names.append(
                    f"{alias}@{component_name}" if separator else alias
                )
            names = []
            for base_name in base_names:
                if base_name.count("@") == 1:
                    names.append(f"{base_name}@{assembly_title}")
                names.append(base_name)
            for selection_name in names:
                for entity_type in candidates:
                    if entity_type not in ENTITY_TYPES:
                        continue
                    if model.Extension.SelectByID2(
                        selection_name,
                        entity_type,
                        0,
                        0,
                        0,
                        append,
                        1,
                        pythoncom.Nothing,
                        0,
                    ):
                        return entity_type
            return None

        model.ClearSelection2(True)
        selected_type1 = select_entity(entity1, entity1_type, False)
        selected_type2 = select_entity(entity2, entity2_type, True)
        if selected_type1 is None or selected_type2 is None:
            model.ClearSelection2(True)
            return error_response(
                f"Could not select both entities: {entity1}, {entity2}"
            )

        # Angle mates carry their value in the Angle slot (parameter 10,
        # radians); distance mates in the Distance slot (metres).
        if mate_type_val == swMateANGLE:
            dist_m = 0.0
            angle_val = math.radians(distance)
        else:
            dist_m = (distance / 1000.0) if distance is not None else 0.0
            angle_val = 0.0
        mate_error = win32com.client.VARIANT(
            pythoncom.VT_BYREF | pythoncom.VT_I4, 0
        )
        mate = model.AddMate5(
            mate_type_val,
            0,  # align
            False,  # flip
            dist_m,
            dist_m,
            dist_m,
            0,  # gear ratio numerator
            0,  # gear ratio denominator
            angle_val,
            angle_val,
            angle_val,
            False,  # for positioning only
            False,  # lock rotation
            0,  # width mate option
            mate_error,
        )
        model.ClearSelection2(True)

        if mate is None:
            return error_response(
                f"Failed to create mate (SolidWorks error {mate_error.value})",
                code="SW_API_ERROR",
            )

        return success_response(
            data={
                "mate_name": mate.Name,
                "type": mate_type,
                "entity_types": [selected_type1, selected_type2],
                "error_status": mate_error.value,
            },
            message=f"Created {mate_type} mate between '{entity1}' and '{entity2}'",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to add mate")
        return error_response(f"Failed to add mate: {exc}")


def get_components(sw_app: SolidWorksApp) -> dict:
    """List components in the active assembly."""
    try:
        model = sw_app.get_active_document()
        if model is None or call_or_value(model, "GetType") != swDocASSEMBLY:
            return error_response("No active assembly document")

        components = model.GetComponents(False)
        names = [comp.Name2 for comp in components] if components else []

        return success_response(
            data={"components": names, "count": len(names)},
            message=f"Found {len(names)} components",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to get components")
        return error_response(f"Failed to get components: {exc}")


def check_interference(sw_app: SolidWorksApp) -> dict:
    """Check pairwise interference between components in the active assembly.

    Real machine (T11 probe): overlapping boxes → one interference with
    ``Volume`` in m³ and ``Components`` as a component array; separated
    parts → empty. ``TreatCoincidenceAsInterference`` is settable;
    ``TreatSubBodiesAsInterference`` is rejected on this machine and is
    skipped.
    """
    try:
        model = sw_app.get_active_document()
        if model is None or call_or_value(model, "GetType") != swDocASSEMBLY:
            return error_response("No active assembly document")

        mgr = call_or_value(model, "InterferenceDetectionManager")
        if mgr is None:
            return error_response(
                "SolidWorks refused to provide the interference detector",
                code="SW_API_ERROR",
            )
        try:
            mgr.TreatCoincidenceAsInterference = False
        except Exception:
            logger.debug("TreatCoincidenceAsInterference not settable", exc_info=True)

        interferences = call_or_value(mgr, "GetInterferences") or []
        rows: List[Dict[str, Any]] = []
        for inter in list(interferences)[:MAX_INTERFERENCES]:
            volume = call_or_value(inter, "Volume")
            comps = call_or_value(inter, "Components") or []
            names = [
                n
                for c in list(comps)[:MAX_COMPONENTS]
                if isinstance((n := call_or_value(c, "Name2")), str)
            ]
            center_mm, bbox_mm = _interference_spatial(inter)
            rows.append(
                {
                    "volume_mm3": round(volume * 1e9, 3)
                    if isinstance(volume, (int, float))
                    else None,
                    "center_mm": center_mm,
                    "bbox_mm": bbox_mm,
                    "components": names,
                }
            )

        return success_response(
            data={
                "interference_count": len(rows),
                "has_interference": bool(rows),
                "interferences": rows,
            },
            message=(
                f"Found {len(rows)} interference(s)"
                if rows
                else "No interferences detected"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to check interference")
        return error_response(f"Failed to check interference: {exc}")


def _interference_spatial(inter: Any) -> tuple:
    """(center_mm, bbox_mm) for one interference (N8 probe).

    Path: ``GetInterferenceBody()`` -> IBody2; ``GetBodyBox()`` returns the
    6-value box in metres, ``GetMassProperties(1000)[0:3]`` the centroid in
    metres. Returns (None, None) when the body is unavailable — spatial
    facts must never break the interference report itself.
    """
    center_mm: Optional[List[float]] = None
    bbox_mm: Optional[List[float]] = None
    try:
        body = call_or_value(inter, "GetInterferenceBody")
        if body is not None:
            box = call_or_value(body, "GetBodyBox")
            if (
                isinstance(box, (list, tuple))
                and len(box) >= 6
                and all(isinstance(v, (int, float)) for v in box[:6])
            ):
                bbox_mm = [round(v * 1000.0, 3) for v in box[:6]]
            props = body.GetMassProperties(1000.0)
            if (
                isinstance(props, (list, tuple))
                and len(props) >= 3
                and all(isinstance(v, (int, float)) for v in props[:3])
            ):
                center_mm = [round(v * 1000.0, 3) for v in props[:3]]
    except Exception:
        logger.debug("interference body facts unavailable", exc_info=True)
    return center_mm, bbox_mm


def _walk_feature_names(model: Any, max_nodes: int = MAX_TREE_WALK) -> set:
    """Feature names from the tree incl. one level of sub-features.

    Mates live inside the MateGroup folder (N8 probe); a top-level-only
    walk never sees them, so delete rechecks must descend one level. The
    walk is bounded and bails on non-string names (degenerate proxy).
    """
    names = set()
    feat = call_or_value(model, "FirstFeature")
    steps = 0
    while feat is not None and steps < max_nodes:
        name = call_or_value(feat, "Name")
        if not isinstance(name, str):
            break
        names.add(name)
        sub = call_or_value(feat, "GetFirstSubFeature")
        sub_steps = 0
        while sub is not None and sub_steps < max_nodes:
            sub_name = call_or_value(sub, "Name")
            if not isinstance(sub_name, str):
                break
            names.add(sub_name)
            sub = call_or_value(sub, "GetNextSubFeature")
            sub_steps += 1
        feat = call_or_value(feat, "GetNextFeature")
        steps += 1
    return names


def _feature_name_exists(model: Any, name: str, max_nodes: int = MAX_TREE_WALK) -> bool:
    """Early-exit membership probe (P-1, 2026-10-05).

    Semantics identical to ``name in _walk_feature_names(model)`` but
    stops at the first hit instead of collecting the whole tree —
    delete_mate's post-delete recheck previously paid a full O(N×M) walk
    even when the mate was gone (the overwhelmingly common case).
    """
    feat = call_or_value(model, "FirstFeature")
    steps = 0
    while feat is not None and steps < max_nodes:
        feat_name = call_or_value(feat, "Name")
        if not isinstance(feat_name, str):
            break
        if feat_name == name:
            return True
        sub = call_or_value(feat, "GetFirstSubFeature")
        sub_steps = 0
        while sub is not None and sub_steps < max_nodes:
            sub_name = call_or_value(sub, "Name")
            if not isinstance(sub_name, str):
                break
            if sub_name == name:
                return True
            sub = call_or_value(sub, "GetNextSubFeature")
            sub_steps += 1
        feat = call_or_value(feat, "GetNextFeature")
        steps += 1
    return False


def delete_mate(sw_app: SolidWorksApp, mate_name: str) -> dict:
    """Delete one mate from the active assembly (destructive).

    Real machine (N8 probe): mates are selectable via SelectByID2 with
    the "MATE" type only (BODYFEATURE/FEATURE both fail); success is
    judged by the mate disappearing from the tree, not by the EditDelete
    return value.
    """
    try:
        if not mate_name:
            return error_response(
                "mate_name must be non-empty", code="INVALID_PARAMETER"
            )
        model = sw_app.get_active_document()
        if model is None or call_or_value(model, "GetType") != swDocASSEMBLY:
            return error_response("No active assembly document")

        if mate_name not in _walk_feature_names(model):
            return error_response(
                f"Mate not found: {mate_name}", code="MATE_NOT_FOUND"
            )

        model.ClearSelection2(True)
        picked = model.Extension.SelectByID2(
            mate_name, "MATE", 0, 0, 0, False, 0, pythoncom.Nothing, 0
        )
        if not picked:
            return error_response(
                f"SolidWorks refused to select mate '{mate_name}'",
                code="SW_API_ERROR",
            )

        call_or_value(model, "EditDelete")

        # P-1（2026-10-05）：删后复检改早停探针——常见情形（已删掉）在
        # 命中前即返回，不再全树收集；语义与原 `_walk_feature_names`
        # 成员检查一致（含一级子特征，MATE 在 MateGroup 内）。
        if _feature_name_exists(model, mate_name):
            return error_response(
                f"SolidWorks rejected deleting '{mate_name}' "
                f"(still in tree after EditDelete)",
                code="SW_API_ERROR",
            )
        return success_response(
            data={"deleted": mate_name},
            message=f"Deleted mate '{mate_name}'",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to delete mate")
        return error_response(f"Failed to delete mate: {exc}")


def _find_component(model: Any, component_name: str) -> Optional[Any]:
    comps = model.GetComponents(False) or []
    for comp in list(comps)[:MAX_COMPONENTS]:
        if call_or_value(comp, "Name2") == component_name:
            return comp
    return None


def _current_xform16(comp: Any) -> List[float]:
    """Current component transform as 16 floats (identity fallback).

    SetTransformAndSolve3 is absolute, not incremental (N8 probe), so
    deltas must be composed onto GetTotalTransform first. If the read
    fails we fall back to identity — for a never-moved component both
    are equivalent.
    """
    try:
        xform = comp.GetTotalTransform(False)
        data = call_or_value(xform, "ArrayData")
        if isinstance(data, (list, tuple)) and len(data) >= 16:
            return [float(v) for v in data[:16]]
    except Exception:
        logger.debug("GetTotalTransform unavailable; using identity", exc_info=True)
    return list(IDENTITY_XFORM)


def _mat_mul(a: List[float], b: List[float]) -> List[float]:
    """3x3 row-major product a @ b."""
    return [
        sum(a[i * 3 + k] * b[k * 3 + j] for k in range(3))
        for i in range(3)
        for j in range(3)
    ]


def _mat_vec(m: List[float], v: List[float]) -> List[float]:
    return [sum(m[i * 3 + k] * v[k] for k in range(3)) for i in range(3)]


_ROTATIONS = {
    "x": lambda c, s: [1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c],
    "y": lambda c, s: [c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c],
    "z": lambda c, s: [c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0],
}


# N37: the makepy static wrapper has a single home in utils.com;
# the local copy (N5 pattern, with the PyIDispatch guard) moved there.
from solidworks_mcp.utils.com import static_wrap as _wrap_static  # noqa: E402,F401


def _apply_component_xform(
    sw_app: SolidWorksApp, model: Any, comp: Any, data16: List[float]
) -> Optional[str]:
    """Push a 16-element transform to the component; None on success.

    N8 probe: CreateTransform needs the full 16-element array (13 does
    nothing), the typed wrapper is mandatory on this machine (dynamic
    dispatch faults on the VARIANT array), and the interference detector
    reads stale geometry until EditRebuild3 runs.
    """
    variant = win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8, data16
    )
    math_util = call_or_value(sw_app.app, "GetMathUtility")
    if math_util is None:
        return "SolidWorks refused to provide the math utility"
    math_typed = _wrap_static(math_util, "IMathUtility") or math_util
    xform = math_typed.CreateTransform(variant)
    if xform is None:
        return "CreateTransform returned None for the requested transform"
    comp_typed = _wrap_static(comp, "IComponent2")
    solver = (
        comp_typed.SetTransformAndSolve3
        if comp_typed is not None
        else comp.SetTransformAndSolve3
    )
    if not solver(xform, True):
        return "SetTransformAndSolve3 rejected the transform"
    call_or_value(model, "EditRebuild3")
    return None


def move_component(
    sw_app: SolidWorksApp, component_name: str, dx: float, dy: float, dz: float
) -> dict:
    """Translate one component by (dx, dy, dz) millimetres.

    Real machine (N8 probe): TransformComponent2 is gone from SW 2026;
    the working path is CreateTransform(16-element VARIANT) ->
    SetTransformAndSolve3(xform, True) — absolute, so the delta is
    composed onto GetTotalTransform — followed by EditRebuild3.
    """
    try:
        if not component_name:
            return error_response(
                "component_name must be non-empty", code="INVALID_PARAMETER"
            )
        try:
            dx = finite_number("dx", dx)
            dy = finite_number("dy", dy)
            dz = finite_number("dz", dz)
        except ValueError as exc:
            return error_response(str(exc), code="INVALID_PARAMETER")

        model = sw_app.get_active_document()
        if model is None or call_or_value(model, "GetType") != swDocASSEMBLY:
            return error_response("No active assembly document")
        comp = _find_component(model, component_name)
        if comp is None:
            return error_response(
                f"Component not found: {component_name}",
                code="COMPONENT_NOT_FOUND",
            )

        data = _current_xform16(comp)
        data[9] += dx / 1000.0
        data[10] += dy / 1000.0
        data[11] += dz / 1000.0
        failure = _apply_component_xform(sw_app, model, comp, data)
        if failure:
            return error_response(failure, code="SW_API_ERROR")

        return success_response(
            data={"component": component_name, "translation_mm": [dx, dy, dz]},
            message=(
                f"Moved component '{component_name}' by ({dx}, {dy}, {dz}) mm"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to move component")
        return error_response(f"Failed to move component: {exc}")


def rotate_component(
    sw_app: SolidWorksApp, component_name: str, axis: str, angle_deg: float
) -> dict:
    """Rotate one component about an assembly axis (x/y/z) through the origin.

    The rotation multiplies onto the current transform from the left
    (world frame), so orientation and position both rotate about the
    assembly origin (N8 probe composition rule).
    """
    try:
        if not component_name:
            return error_response(
                "component_name must be non-empty", code="INVALID_PARAMETER"
            )
        axis_key = str(axis or "").lower()
        if axis_key not in _ROTATIONS:
            return error_response(
                f"axis must be one of 'x', 'y', 'z' (got {axis!r})",
                code="INVALID_PARAMETER",
            )
        try:
            angle_deg = finite_number("angle_deg", angle_deg)
        except ValueError as exc:
            return error_response(str(exc), code="INVALID_PARAMETER")

        model = sw_app.get_active_document()
        if model is None or call_or_value(model, "GetType") != swDocASSEMBLY:
            return error_response("No active assembly document")
        comp = _find_component(model, component_name)
        if comp is None:
            return error_response(
                f"Component not found: {component_name}",
                code="COMPONENT_NOT_FOUND",
            )

        theta = math.radians(angle_deg)
        rot = _ROTATIONS[axis_key](math.cos(theta), math.sin(theta))
        data = _current_xform16(comp)
        data[0:9] = _mat_mul(rot, data[0:9])
        data[9:12] = _mat_vec(rot, data[9:12])
        failure = _apply_component_xform(sw_app, model, comp, data)
        if failure:
            return error_response(failure, code="SW_API_ERROR")

        return success_response(
            data={
                "component": component_name,
                "axis": axis_key,
                "angle_deg": angle_deg,
            },
            message=(
                f"Rotated component '{component_name}' {angle_deg}° about {axis_key}"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to rotate component")
        return error_response(f"Failed to rotate component: {exc}")


def _component_body_facts(comp: Any) -> tuple:
    """(volume_mm3, mass_g, material) for one component (N8 probe).

    Path: ``comp.GetBody()`` -> ``GetMassProperties(1000)``: [3] volume in
    m³, [5] mass in kg (= volume × density); ``GetMaterialIdName`` is ''
    when the part has no material applied. Missing members yield Nones —
    per-part facts never break the BOM aggregate.
    """
    volume_mm3 = mass_g = material = None
    try:
        body = call_or_value(comp, "GetBody")
        if body is not None:
            props = body.GetMassProperties(1000.0)
            if isinstance(props, (list, tuple)) and len(props) > 5:
                if isinstance(props[3], (int, float)):
                    volume_mm3 = round(props[3] * 1e9, 3)
                mass_kg = props[5]
                if isinstance(mass_kg, (int, float)) and math.isfinite(mass_kg):
                    mass_g = round(mass_kg * 1000.0, 3)
    except Exception:
        logger.debug("component body facts unavailable", exc_info=True)
    try:
        name = call_or_value(comp, "GetMaterialIdName")
        if isinstance(name, str) and name:
            material = name
    except Exception:
        logger.debug("GetMaterialIdName unavailable", exc_info=True)
    return volume_mm3, mass_g, material


def get_bom(sw_app: SolidWorksApp) -> dict:
    """Aggregate a bill of materials from the active assembly's components.

    Instances of the same file+configuration are merged with a count.
    """
    try:
        model = sw_app.get_active_document()
        if model is None or call_or_value(model, "GetType") != swDocASSEMBLY:
            return error_response("No active assembly document")

        comps = model.GetComponents(False) or []
        items: Dict[tuple, Dict[str, Any]] = {}
        total = 0
        for comp in list(comps)[:MAX_COMPONENTS]:
            name2 = call_or_value(comp, "Name2")
            if not isinstance(name2, str):  # degenerate proxy — skip
                continue
            path = call_or_value(comp, "GetPathName")
            if not isinstance(path, str):
                path = ""
            config = call_or_value(comp, "ReferencedConfiguration")
            if not isinstance(config, str):
                config = ""
            total += 1
            key = (path.lower(), config)
            if key not in items:
                volume_mm3, mass_g, material = _component_body_facts(comp)
                items[key] = {
                    "name": os.path.splitext(os.path.basename(path))[0],
                    "path": path,
                    "configuration": config,
                    "count": 0,
                    "volume_mm3": volume_mm3,
                    "mass_g": mass_g,
                    "material": material,
                }
            items[key]["count"] += 1

        return success_response(
            data={
                "items": list(items.values()),
                "total_components": total,
                "unique_parts": len(items),
            },
            message=(
                f"BOM: {len(items)} unique part(s), {total} component instance(s)"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to get BOM")
        return error_response(f"Failed to get BOM: {exc}")


def explode(sw_app: SolidWorksApp) -> dict:
    """Create an automatic exploded view on the active assembly.

    Real-machine contract (N33 probe): typed IAssemblyDoc.AutoExplode is
    zero-arg (it fires via property semantics on dynamic dispatch) and
    builds an automatic exploded view; GetExplodedViewCount/Names read it
    back and ShowExploded(True) switches the display state. Manual
    per-component steps (AddExplodeStep) are a future extension; the
    exploded state as a drawing projection is an observed follow-up."""
    from win32com.client import gencache

    try:
        model = sw_app.get_active_document()
        if model is None or call_or_value(model, "GetType") != swDocASSEMBLY:
            return error_response("No active assembly document")

        mods = gencache.GetModuleForProgID("SldWorks.Application")
        raw = getattr(model, "_oleobj_", None)
        asm_doc = mods.IAssemblyDoc(raw) if mods and raw else model

        done = call_or_value(asm_doc, "AutoExplode")  # property semantics
        if done is not True:
            try:
                done = asm_doc.AutoExplode()
            except Exception as exc:  # noqa: BLE001
                return error_response(f"AutoExplode rejected ({exc})", code="SW_API_ERROR")
        if done is not True:
            return error_response("Explode rejected", code="SW_API_ERROR")

        count = asm_doc.GetExplodedViewCount()
        names = asm_doc.GetExplodedViewNames()
        if isinstance(names, str):
            names = (names,)
        views = list(names or ())
        if not isinstance(count, int) or count < 1 or not views:
            return error_response(
                "AutoExplode returned success but no exploded view exists",
                code="SW_API_ERROR",
            )
        try:
            asm_doc.ShowExploded(True)
        except Exception:  # noqa: BLE001 —— 显示态切换失败不掩盖视图创建
            logger.debug("ShowExploded(True) failed", exc_info=True)

        return success_response(
            data={"explode_views": views, "count": count},
            message=(
                f"Created exploded view(s): {', '.join(views)} "
                "(automatic layout; display switched to exploded)"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to explode assembly")
        return error_response(f"Failed to explode assembly: {exc}")
