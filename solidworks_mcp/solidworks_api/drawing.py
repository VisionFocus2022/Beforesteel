"""Engineering drawing tools: create from part / project views / insert
model dimensions / export PDF + PNG.

Real-machine contract (probe ``tools/probe_drawing.py``, SW 2026 Chinese,
2026-08-29):

- Template discovery: ``GetUserPreferenceStringValue(10)`` returns the user's
  default ``.drwdot``; the GB template directory beside it holds ``gb_a0`` …
  ``gb_a4p``. A3 is preferred; ``SOLIDWORKS_MCP_DRAWING_TEMPLATE`` overrides.
- ``app.NewDocument(template, 0, 0.0, 0.0)`` — paper arguments are ignored
  when a template path is given. Returns a dynamic dispatch whose member
  surface is IModelDoc + IDrawingDoc: **``SelectByID2`` is NOT resolvable on
  it** (that lives on ModelDoc2) — view selection must go through
  ``model.Extension.SelectByID2`` (9 params, Callout=``pythoncom.Nothing``).
- ``Create1stAngleViews2`` always returns False on this machine (two
  templates, after ActivateDoc3). The manual route works deterministically:
  ``CreateDrawViewFromModelView3(path, "", x, y, 0)`` for the front view,
  select it as ``DRAWINGVIEW``, then ``CreateUnfoldedViewAt3`` for the
  projected views. Sheet coordinates are metres.
- Dimensions: ``drawing.InsertModelAnnotations2(0, True, 0, True, True,
  False)`` inserts every display dimension. InsertModelAnnotations3/4 return
  None and insert nothing here; the plan's ``Extension.InsertModelAnnotations3``
  host is wrong (it is a DrawingDoc member, and the Extension object rejects
  the name outright).
- View/dimension judgment: zero-arg properties ``GetFirstView`` /
  ``GetNextView`` / ``GetDisplayDimensionCount`` / ``GetAnnotationCount``
  (sheet view '图纸1' carries ~82 template annotations — the GB title block).
- Export: ``SaveAs3(path, 0, swSaveAsOptions_Silent)`` returns 0 on success;
  PDF ≈ 45 KB, PNG is a valid raster (line art compresses well — judge by
  the IHDR resolution, not file size).
- A drawing holds its referenced part open (file lock); cleanup needs
  ``app.CloseAllDocuments(True)``.
"""

from __future__ import annotations

import logging
import os
import struct
from typing import Any, Dict, List, Optional, Tuple

import pythoncom

from solidworks_mcp.config import get_config
from solidworks_mcp.solidworks_api.app import SolidWorksApp, SolidWorksNotRunningError
from solidworks_mcp.solidworks_api.constants import (
    swDocDRAWING,
    swSaveAsOptions_Silent,
)
from solidworks_mcp.utils.common import error_response, success_response
from solidworks_mcp.utils.com import call_or_value
from solidworks_mcp.utils.security import (
    ensure_sink_path,
    validate_output_file,
    validate_path,
)
from solidworks_mcp.solidworks_api.geometry import mm_to_m
from solidworks_mcp.utils.validation import finite_number

logger = logging.getLogger(__name__)

# A3 first-angle-ish layout in sheet metres (probe-verified on gb_a3.drwdot)
FRONT_XY = (0.15, 0.10)
TOP_XY = (0.15, 0.19)
SIDE_XY = (0.27, 0.10)

# Preference order when falling back from the user default (usually gb_a0)
PREFERRED_TEMPLATES = ("gb_a3.drwdot", "gb_a4.drwdot", "gb_a0.drwdot")

PAPER_SIZE_DEFAULT = 0  # ignored when a template path is supplied
MAX_VIEW_WALK = 50

SUPPORTED_PART_EXTENSIONS = (".sldprt", ".prt")
DRAWING_VIEW_TYPE = "DRAWINGVIEW"


def _resolve_template(app: Any) -> Optional[str]:
    """Pick a drawing template: env override → A3/A4 beside the user default."""
    env_template = get_config().drawing_template
    if env_template and os.path.isfile(env_template):
        return env_template

    try:
        preferred = app.GetUserPreferenceStringValue(10)  # swDefaultTemplateDrawing
    except Exception:
        return None
    if not isinstance(preferred, str) or not preferred:
        return None
    # The preference can go stale (uninstalled version dir); the GB set
    # beside it is still usable.
    template_dir = os.path.dirname(preferred)
    for name in PREFERRED_TEMPLATES:
        candidate = os.path.join(template_dir, name)
        if os.path.isfile(candidate):
            return candidate
    return preferred if os.path.isfile(preferred) else None


def _view_reports(model: Any) -> List[Dict[str, Any]]:
    views: List[Dict[str, Any]] = []
    view = call_or_value(model, "GetFirstView")
    for _ in range(MAX_VIEW_WALK):
        if view is None:
            break
        name = call_or_value(view, "Name")
        if not isinstance(name, str):  # degenerate proxy — stop immediately
            break
        try:
            dims = call_or_value(view, "GetDisplayDimensionCount")
        except Exception:
            dims = None
        try:
            anns = call_or_value(view, "GetAnnotationCount")
        except Exception:
            anns = None
        views.append(
            {
                "name": name,
                "dimensions": dims if isinstance(dims, int) else None,
                "annotations": anns if isinstance(anns, int) else None,
            }
        )
        view = call_or_value(view, "GetNextView")
    return views


def _total_dimensions(views: List[Dict[str, Any]]) -> int:
    return sum(v["dimensions"] or 0 for v in views)


def _select_view(model: Any, view_name: str) -> bool:
    """Select a drawing view by name (9-param Extension form, ModelDoc2's
    SelectByID2 is not resolvable on the NewDocument dispatch)."""
    extension = call_or_value(model, "Extension")
    try:
        return bool(
            extension.SelectByID2(
                view_name, DRAWING_VIEW_TYPE, 0, 0, 0, False, 0,
                pythoncom.Nothing, 0,
            )
        )
    except Exception:
        logger.exception("Failed to select drawing view %s", view_name)
        return False


def create_drawing_from_part(sw_app: SolidWorksApp, part_path: str) -> dict:
    """Create a new drawing from a saved part and project three views."""
    try:
        valid, msg = validate_path(part_path, must_exist=True)
        if not valid:
            return error_response(msg, code="INVALID_PARAMETER")

        ext = os.path.splitext(part_path)[1].lower()
        if ext not in SUPPORTED_PART_EXTENSIONS:
            return error_response(
                f"Expected a part file (.sldprt), got: {ext or '<none>'}",
                code="INVALID_PARAMETER",
            )

        template = _resolve_template(sw_app.app)
        if template is None:
            return error_response(
                "No drawing template found; set SOLIDWORKS_MCP_DRAWING_TEMPLATE "
                "to a .drwdot file",
                code="TEMPLATE_NOT_FOUND",
            )

        drawing = sw_app.app.NewDocument(
            template, PAPER_SIZE_DEFAULT, 0.0, 0.0
        )
        if drawing is None:
            return error_response(
                "SolidWorks rejected creating the drawing document",
                code="SW_API_ERROR",
            )

        abs_part = os.path.abspath(part_path)
        front = drawing.CreateDrawViewFromModelView3(
            abs_part, "", FRONT_XY[0], FRONT_XY[1], 0.0
        )
        if front is None:
            return error_response(
                "SolidWorks refused to create the front view "
                f"(part must be a valid saved model: {abs_part})",
                code="SW_API_ERROR",
            )
        front_name = call_or_value(front, "Name")

        for target_xy in (TOP_XY, SIDE_XY):
            if not _select_view(drawing, front_name):
                return error_response(
                    f"Failed to select the front view {front_name!r} before "
                    "projecting",
                    code="SW_API_ERROR",
                )
            projected = drawing.CreateUnfoldedViewAt3(
                target_xy[0], target_xy[1], 0.0, False
            )
            if projected is None:
                return error_response(
                    f"SolidWorks refused to create the projected view at "
                    f"({target_xy[0]}, {target_xy[1]})",
                    code="SW_API_ERROR",
                )

        views = _view_reports(drawing)
        if len(views) < 4:  # sheet + front + two projections
            return error_response(
                f"Only {len(views)} views present after projection "
                "(expected 4: sheet + three views)",
                code="SW_API_ERROR",
            )

        return success_response(
            data={
                "title": call_or_value(drawing, "GetTitle"),
                "template": template,
                "part": part_path,
                "view_count": len(views),
                "views": views,
            },
            message="Created drawing with three projected views "
            "(drawing stays open; the referenced part is opened by SolidWorks)",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to create drawing")
        return error_response(f"Failed to create drawing: {exc}")


def insert_model_dimensions(sw_app: SolidWorksApp) -> dict:
    """Insert all model dimensions of the drawing's views.

    ``InsertModelAnnotations2(0, True, 0, True, True, False)`` is the only
    call verified to insert anything on this machine (SW 2026).
    """
    try:
        model = sw_app.get_active_document()
        if model is None:
            return error_response("No active document")
        doc_type = call_or_value(model, "GetType")
        if doc_type != swDocDRAWING:
            return error_response(
                f"Active document is not a drawing (type={doc_type})"
            )

        before = _total_dimensions(_view_reports(model))
        inserted = model.InsertModelAnnotations2(
            0, True, 0, True, True, False
        )
        call_or_value(model, "EditRebuild3")
        views = _view_reports(model)
        after = _total_dimensions(views)

        if after <= before:
            return error_response(
                "SolidWorks inserted no dimensions "
                f"(call returned {inserted!r}; the part may expose no display "
                "dimensions — create sketch/extrude features with dimensions)",
                code="SW_NO_EFFECT",
            )

        return success_response(
            data={
                "dimensions_inserted": after - before,
                "total_dimensions": after,
                "views": views,
            },
            message=f"Inserted {after - before} model dimensions into the drawing",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to insert model dimensions")
        return error_response(f"Failed to insert model dimensions: {exc}")


# ---------------------------------------------------------------------------
# N4: dimension organize + section view (probe: tools/probe_drawing/
# probe_dim_organize_section.py, 8 probe rounds, SW 2026):
#
# - ``view.GetDisplayDimensions`` / ``dd.GetNameForSelection`` /
#   ``dd.GetAnnotation`` are zero-argument PROPERTIES on the dynamic dispatch;
#   GetText returns empty strings (unusable as a dedupe key — use FullName).
# - Delete route: ``Extension.SelectByID2(selname, "DIMENSION", ...)`` where
#   selname is GetNameForSelection (FullName is REJECTED — returns False),
#   then ``drawing.DeleteSelection(True)`` — DeleteSelection takes a boolean
#   argument; calling it bare raises DISP_E_PARAMNOTFOUND.
# - Stagger route: ``ann.GetPosition()`` / ``ann.SetPosition(x, y, z)`` return
#   sheet metres. ``ann.Select3`` raises a type-mismatch com_error — never
#   needed, selection goes through SelectByID2.
# - Section view: the cut line MUST live in a SHEET-level sketch. Lines
#   drawn on top of a model view are absorbed into that view's sketch and
#   CreateSectionViewAt4 then returns None (probes 9-11). Drawing the line
#   just OUTSIDE the view (vertical → below, horizontal → left of the view
#   anchor, which IView.Position reports) reliably yields a real section
#   view: ``SketchManager.CreateLine`` → ``GetActiveSketch2().Name`` →
#   ``CreateSectionViewAt4(x, y, 0.0, sketchName, 0, 0)``. At5/
#   ICreateSectionViewAt4 reject every argument shape tried; At/At2/At3/
#   CreateSectionView likewise; At5 is not on the runtime dispatch.

DIMENSION_SELECT_TYPE = "DIMENSION"
ORGANIZE_MODES = ("dedupe", "shift", "dedupe_shift")
DEFAULT_SHIFT_STEP_MM = 8.0
MAX_SHIFT_STEP_MM = 100.0
# Annotation centres closer than 2 sheet millimetres read as one pile.
OVERLAP_GAP_M = 0.002
MAX_DDS_PER_VIEW = 200

SECTION_DIRECTIONS = ("vertical", "horizontal")
MAX_CUT_OFFSET_MM = 500.0
SECTION_LINE_HALF_M = 0.02  # probe-verified cut-line half length
SECTION_LINE_CLEAR_M = 0.06  # cut-line centre sits this far outside the view
SECTION_VIEW_OFFSET_M = 0.12  # default placement: 120 mm right of the source
MAX_SHEET_COORD_M = 1.5
# N5：公差/粗糙度/注释（探针 probe_tolerance_finish_dxf.py 5 轮收敛）
TOLERANCE_PLUS_MINUS = 5  # swToleranceType_e；type=7 (Fit) 时 values 归零佐证序列
MAX_TOLERANCE_MM = 100.0
SURFACE_SYMBOL_TYPES = {
    "basic": 0,
    "remove_material": 1,
    "no_remove_material": 2,
}
MIN_ROUGHNESS_UM = 0.008
MAX_ROUGHNESS_UM = 100.0
NOTE_TEXT_SIZE_M = 0.003  # CreateText2 width/height（探针实测可用值）


class _DrawingError(Exception):
    """Domain error carrying a structured code."""

    def __init__(self, message: str, code: str = "SW_API_ERROR"):
        super().__init__(message)
        self.code = code


def _active_drawing(sw_app: SolidWorksApp) -> Any:
    """Return the active document, asserting it is a drawing (type 3)."""
    model = sw_app.get_active_document()
    if model is None:
        raise _DrawingError("No active document")
    doc_type = call_or_value(model, "GetType")
    if doc_type != swDocDRAWING:
        raise _DrawingError(
            f"Active document is not a drawing (type={doc_type})"
        )
    return model


def _model_views(model: Any) -> List[Tuple[str, Any]]:
    """Walk the view chain, filtering out degenerate proxies."""
    views: List[Tuple[str, Any]] = []
    view = call_or_value(model, "GetFirstView")
    for _ in range(MAX_VIEW_WALK):
        if view is None:
            break
        name = call_or_value(view, "Name")
        if not isinstance(name, str):
            break
        views.append((name, view))
        view = call_or_value(view, "GetNextView")
    return views


def _collect_dimension_records(
    model: Any, view_name: Optional[str]
) -> List[Dict[str, Any]]:
    """Per-view display dimensions with FullName / selection name / position.

    Records whose COM members fail to resolve are skipped (their objects
    stay untouched)."""
    records: List[Dict[str, Any]] = []
    for name, view in _model_views(model):
        if view_name is not None and name != view_name:
            continue
        try:
            count = call_or_value(view, "GetDisplayDimensionCount")
        except Exception:
            count = None
        if not count:
            continue
        dds = call_or_value(view, "GetDisplayDimensions") or ()
        for dd in list(dds)[:MAX_DDS_PER_VIEW]:
            try:
                full = call_or_value(dd.GetDimension2(0), "FullName")
                selname = call_or_value(dd, "GetNameForSelection")
                ann = call_or_value(dd, "GetAnnotation")
                pos = ann.GetPosition()
            except Exception as exc:
                logger.debug("dimension member failed on %s: %r", name, exc)
                continue
            if not isinstance(full, str) or not isinstance(selname, str):
                continue
            records.append(
                {"view": name, "dd": dd, "ann": ann, "full": full,
                 "selname": selname, "pos": pos}
            )
    return records


def _delete_dimension(model: Any, ext: Any, record: Dict[str, Any]) -> bool:
    """SelectByID2(GetNameForSelection, "DIMENSION") + DeleteSelection(True)."""
    selected = ext.SelectByID2(
        record["selname"], DIMENSION_SELECT_TYPE, 0, 0, 0, False, 0,
        pythoncom.Nothing, 0,
    )
    if not selected:
        return False
    return bool(model.DeleteSelection(True))


def organize_dimensions(
    sw_app: SolidWorksApp,
    view_name: Optional[str] = None,
    mode: str = "dedupe_shift",
    shift_step_mm: float = DEFAULT_SHIFT_STEP_MM,
) -> dict:
    """De-duplicate and stagger dimensions in the active drawing.

    ``dedupe`` removes same-FullName duplicates within one view (the first
    occurrence is kept); ``shift`` staggers annotations that pile up closer
    than 2 sheet millimetres by ``shift_step_mm`` along +Y.
    """
    try:
        if mode not in ORGANIZE_MODES:
            return error_response(
                f"mode must be one of {', '.join(ORGANIZE_MODES)}, got {mode!r}",
                code="INVALID_PARAMETER",
            )
        if not 0.0 < shift_step_mm <= MAX_SHIFT_STEP_MM:
            return error_response(
                f"shift_step_mm must be in (0, {MAX_SHIFT_STEP_MM:g}], got "
                f"{shift_step_mm}",
                code="INVALID_PARAMETER",
            )

        model = _active_drawing(sw_app)

        known = [name for name, _ in _model_views(model)]
        if view_name is not None and view_name not in known:
            return error_response(
                f"View {view_name!r} not found in the drawing; known views: "
                f"{', '.join(known) or '<none>'}",
                code="INVALID_PARAMETER",
            )

        extension = call_or_value(model, "Extension")
        failures: List[Dict[str, str]] = []
        deleted = 0

        if "dedupe" in mode:
            records = _collect_dimension_records(model, view_name)
            seen = set()
            for record in records:
                key = (record["view"], record["full"])
                if key not in seen:
                    seen.add(key)
                    continue
                try:
                    if _delete_dimension(model, extension, record):
                        deleted += 1
                    else:
                        failures.append(
                            {"selname": record["selname"],
                             "error": "select or delete refused"}
                        )
                except Exception as exc:
                    failures.append(
                        {"selname": record["selname"],
                         "error": repr(exc)[:180]}
                    )
            call_or_value(model, "EditRebuild3")

        moved = 0
        if "shift" in mode:
            step_m = shift_step_mm / 1000.0
            by_view: Dict[str, List[Dict[str, Any]]] = {}
            for record in _collect_dimension_records(model, view_name):
                by_view.setdefault(record["view"], []).append(record)
            for group in by_view.values():
                group.sort(key=lambda r: (r["pos"][1], r["pos"][0]))
                prev = None
                index = 0
                for record in group:
                    y = record["pos"][1]
                    if prev is not None and abs(y - prev) < OVERLAP_GAP_M:
                        index += 1
                        try:
                            x, _, z = record["pos"]
                            if record["ann"].SetPosition(
                                x, y + index * step_m, z
                            ):
                                moved += 1
                            else:
                                failures.append(
                                    {"selname": record["selname"],
                                     "error": "SetPosition returned False"}
                                )
                        except Exception as exc:
                            failures.append(
                                {"selname": record["selname"],
                                 "error": repr(exc)[:180]}
                            )
                    else:
                        index = 0
                    prev = y
            call_or_value(model, "EditRebuild3")

        views = _view_reports(model)
        return success_response(
            data={
                "mode": mode,
                "view_name": view_name,
                "deleted": deleted,
                "moved": moved,
                "total_dimensions": _total_dimensions(views),
                "views": views,
                "failures": failures,
            },
            message=(
                f"Organized drawing dimensions: deleted {deleted} duplicates, "
                f"staggered {moved} overlapping annotations"
            ),
        )
    except _DrawingError as exc:
        return error_response(str(exc), code=exc.code)
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to organize dimensions")
        return error_response(f"Failed to organize dimensions: {exc}")


def insert_section_view(
    sw_app: SolidWorksApp,
    source_view_name: str,
    cut_position_mm: float = 0.0,
    direction: str = "vertical",
    position_xy_mm: Optional[List[float]] = None,
) -> dict:
    """Create a section view by cutting ``source_view_name`` with a line.

    ``vertical`` draws a vertical cut line at anchor_x + cut offset, placed
    in the blank strip BELOW the view; ``horizontal`` a horizontal line at
    anchor_y + cut offset, LEFT of the view (sheet mm; the view anchor is
    IView.Position, the view's lower-left). Lines drawn on top of a view are
    absorbed into that view's sketch and never produce a section view — the
    blank-strip placement is the probe-verified contract. The section view
    lands 120 mm right of the view unless ``position_xy_mm`` (sheet mm) is
    given; SolidWorks assigns the A/B/C label automatically.
    """
    try:
        if direction not in SECTION_DIRECTIONS:
            return error_response(
                f"direction must be one of {', '.join(SECTION_DIRECTIONS)}, "
                f"got {direction!r}",
                code="INVALID_PARAMETER",
            )
        if not -MAX_CUT_OFFSET_MM <= cut_position_mm <= MAX_CUT_OFFSET_MM:
            return error_response(
                f"cut_position_mm must be within ±{MAX_CUT_OFFSET_MM:g}, got "
                f"{cut_position_mm}",
                code="INVALID_PARAMETER",
            )
        placement_m: Optional[Tuple[float, float]] = None
        if position_xy_mm is not None:
            if (
                len(position_xy_mm) != 2
                or not all(isinstance(v, (int, float)) for v in position_xy_mm)
                or not all(abs(float(v)) / 1000.0 <= MAX_SHEET_COORD_M
                           for v in position_xy_mm)
            ):
                return error_response(
                    "position_xy_mm must be two numeric sheet coordinates "
                    f"(mm, within ±{int(MAX_SHEET_COORD_M * 1000)} mm)",
                    code="INVALID_PARAMETER",
                )
            placement_m = (
                float(position_xy_mm[0]) / 1000.0,
                float(position_xy_mm[1]) / 1000.0,
            )

        model = _active_drawing(sw_app)

        views_now = _model_views(model)
        source = next(
            (v for n, v in views_now if n == source_view_name), None
        )
        if source is None:
            known = [n for n, _ in views_now]
            return error_response(
                f"Source view {source_view_name!r} not found; known views: "
                f"{', '.join(known) or '<none>'}",
                code="INVALID_PARAMETER",
            )

        pos = call_or_value(source, "Position")
        x0, y0 = float(pos[0]), float(pos[1])
        cut_m = float(cut_position_mm) / 1000.0
        if direction == "vertical":
            # 竖直剖切线（x 固定）：画在视图下方空白区（y < 锚点必在视图外）
            line = (x0 + cut_m,
                    y0 - SECTION_LINE_CLEAR_M - SECTION_LINE_HALF_M, 0.0,
                    x0 + cut_m,
                    y0 - SECTION_LINE_CLEAR_M + SECTION_LINE_HALF_M, 0.0)
        else:
            # 水平剖切线（y 固定）：画在视图左侧空白区（x < 锚点必在视图外）
            line = (x0 - SECTION_LINE_CLEAR_M - SECTION_LINE_HALF_M,
                    y0 + cut_m, 0.0,
                    x0 - SECTION_LINE_CLEAR_M + SECTION_LINE_HALF_M,
                    y0 + cut_m, 0.0)

        sketch_manager = call_or_value(model, "SketchManager")
        sketch_manager.CreateLine(*line)
        sketch = call_or_value(model, "GetActiveSketch2")
        sketch_name = call_or_value(sketch, "Name")
        if not isinstance(sketch_name, str) or not sketch_name:
            return error_response(
                "Drawing did not activate a sketch after drawing the cut line",
                code="SW_API_ERROR",
            )

        place = placement_m or (x0 + SECTION_VIEW_OFFSET_M, y0)
        section = model.CreateSectionViewAt4(
            place[0], place[1], 0.0, sketch_name, 0, 0
        )
        if section is None:
            return error_response(
                "SolidWorks refused to create the section view "
                f"(sketch {sketch_name!r}, placement {place})",
                code="SW_API_ERROR",
            )
        call_or_value(model, "EditRebuild3")

        section_name = call_or_value(section, "Name")
        views = _view_reports(model)
        return success_response(
            data={
                "source_view": source_view_name,
                "direction": direction,
                "cut_line_m": [round(v, 6) for v in line[:2] + line[3:5]],
                "sketch": sketch_name,
                "placement_m": [round(place[0], 6), round(place[1], 6)],
                "section_view": section_name,
                "view_count": len(views),
                "views": views,
            },
            message=(
                f"Created section view {section_name!r} from "
                f"{source_view_name!r} ({direction} cut, offset "
                f"{cut_position_mm:g} mm)"
            ),
        )
    except _DrawingError as exc:
        return error_response(str(exc), code=exc.code)
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to insert section view")
        return error_response(f"Failed to insert section view: {exc}")


def _wrap_dimension_static(dim):
    """Wrap a dynamic IDimension in its makepy static class.

    Tolerance setters are unreachable through dynamic dispatch (probe round 4:
    ``SetToleranceType`` reads back as an int property, bracket calls raise
    TypeError); the generated ``IDimension`` class accepts the raw
    ``PyIDispatch`` and restores the typed signatures.
    """
    try:
        from win32com.client import gencache

        mods = gencache.GetModuleForProgID("SldWorks.Application")
        if mods is None:
            return None
        return mods.IDimension(dim._oleobj_)
    except Exception:
        logger.debug("IDimension static wrap failed", exc_info=True)
        return None


def set_tolerance(
    sw_app: SolidWorksApp,
    dimension_name: str,
    upper_mm: float,
    lower_mm: float,
) -> dict:
    """Set +/- tolerances on a display dimension (PlusMinus type).

    ``dimension_name`` matches the dimension FullName exactly or without its
    trailing part segment (e.g. 'D1@凸台-拉伸1' hits 'D1@凸台-拉伸1@probe.Part').
    Both bounds are sheet millimetres and keep their sign (lower_mm=-0.05
    renders as -0.05). Values are verified by reading them back.
    """
    try:
        name = str(dimension_name or "").strip()
        if not name:
            return error_response(
                "dimension_name must not be empty", code="INVALID_PARAMETER"
            )
        try:
            upper_m = float(upper_mm) / 1000.0
            lower_m = float(lower_mm) / 1000.0
        except (TypeError, ValueError):
            return error_response(
                "upper_mm and lower_mm must be numbers", code="INVALID_PARAMETER"
            )
        if abs(float(upper_mm)) > MAX_TOLERANCE_MM or abs(float(lower_mm)) > MAX_TOLERANCE_MM:
            return error_response(
                f"tolerance bounds must stay within +/-{MAX_TOLERANCE_MM:g} mm",
                code="INVALID_PARAMETER",
            )
        model = sw_app.get_active_document()
        if model is None:
            return error_response("No active document")
        if call_or_value(model, "GetType") != swDocDRAWING:
            return error_response("Active document is not a drawing")

        found = None
        for _view_name, view in _model_views(model):
            try:
                dds = call_or_value(view, "GetDisplayDimensions") or ()
            except Exception:
                continue
            # C-8（2026-10-05）：与 _collect_dimension_records 的截断纪律
            # 对齐——GB 模板单视图注释可上百，无上限的逐 COM 往返在
            # 大图纸上代价失控。
            for dd in list(dds)[:MAX_DDS_PER_VIEW]:
                try:
                    dim = dd.GetDimension2(0)
                    full = call_or_value(dim, "FullName")
                except Exception:
                    continue
                if not isinstance(full, str):
                    continue
                if name in (full, full.rsplit("@", 1)[0]):
                    found = (dim, full)
                    break
            if found:
                break
        if not found:
            return error_response(
                f"No display dimension matches {name!r}",
                code="INVALID_PARAMETER",
            )
        dim, full = found

        wrapper = _wrap_dimension_static(dim)
        if wrapper is None:
            return error_response(
                "IDimension static wrapper unavailable (SldWorks typelib "
                "cache missing); tolerance setters need the makepy class",
                code="SW_API_ERROR",
            )
        wrapper.SetToleranceType(TOLERANCE_PLUS_MINUS)
        wrapper.SetToleranceValues(lower_m, upper_m)
        back_type = wrapper.GetToleranceType()
        back_values = wrapper.GetToleranceValues()
        call_or_value(model, "EditRebuild3")
        return success_response(
            data={
                "dimension": full,
                "tolerance_type": back_type,
                "tolerance_values": back_values,
                "upper_mm": float(upper_mm),
                "lower_mm": float(lower_mm),
            },
            message=f"Set +{float(upper_mm):g}/-{abs(float(lower_mm)):g} mm tolerance on {full}",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to set tolerance")
        return error_response(f"Failed to set tolerance: {exc}")


def insert_surface_finish(
    sw_app: SolidWorksApp,
    value_um: float,
    x_mm: float,
    y_mm: float,
    symbol: str = "remove_material",
) -> dict:
    """Insert a surface-finish symbol (default: remove-material + Ra value).

    ``symbol`` picks the GB shape: basic / remove_material / no_remove_material.
    Coordinates are sheet millimetres; the Ra text comes from ``value_um``
    (0.008-100 um).
    """
    try:
        sym_type = SURFACE_SYMBOL_TYPES.get(str(symbol or "").strip())
        if sym_type is None:
            return error_response(
                f"symbol must be one of {sorted(SURFACE_SYMBOL_TYPES)}",
                code="INVALID_PARAMETER",
            )
        try:
            value = float(value_um)
            x_m = float(x_mm) / 1000.0
            y_m = float(y_mm) / 1000.0
        except (TypeError, ValueError):
            return error_response(
                "value_um, x_mm and y_mm must be numbers", code="INVALID_PARAMETER"
            )
        if not (MIN_ROUGHNESS_UM <= value <= MAX_ROUGHNESS_UM):
            return error_response(
                f"value_um must be within [{MIN_ROUGHNESS_UM:g}, "
                f"{MAX_ROUGHNESS_UM:g}]",
                code="INVALID_PARAMETER",
            )
        if abs(x_m) > MAX_SHEET_COORD_M or abs(y_m) > MAX_SHEET_COORD_M:
            return error_response(
                "x_mm/y_mm exceed the printable sheet area",
                code="INVALID_PARAMETER",
            )
        model = sw_app.get_active_document()
        if model is None:
            return error_response("No active document")
        if call_or_value(model, "GetType") != swDocDRAWING:
            return error_response("Active document is not a drawing")

        ok = model.InsertSurfaceFinishSymbol(
            sym_type, 0, x_m, y_m, 0.0, 0, 0, 0.0, 0.0, "", "",
            f"{value:g}", "", "",
        )
        if not ok:
            return error_response(
                "SolidWorks rejected the surface-finish symbol",
                code="SW_API_ERROR",
            )
        call_or_value(model, "EditRebuild3")
        return success_response(
            data={
                "symbol": symbol,
                "symbol_type": sym_type,
                "value_um": value,
                "x_mm": float(x_mm),
                "y_mm": float(y_mm),
            },
            message=(
                f"Inserted surface-finish symbol ({symbol}, Ra {value:g} um) "
                f"at ({float(x_mm):g}, {float(y_mm):g}) mm"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to insert surface finish symbol")
        return error_response(f"Failed to insert surface finish symbol: {exc}")


def insert_note(sw_app: SolidWorksApp, text: str, x_mm: float, y_mm: float) -> dict:
    """Insert a plain text note (e.g. technical requirements) in sheet mm."""
    try:
        body = str(text or "")
        if not body.strip():
            return error_response("text must not be empty", code="INVALID_PARAMETER")
        try:
            x_m = float(x_mm) / 1000.0
            y_m = float(y_mm) / 1000.0
        except (TypeError, ValueError):
            return error_response(
                "x_mm and y_mm must be numbers", code="INVALID_PARAMETER"
            )
        if abs(x_m) > MAX_SHEET_COORD_M or abs(y_m) > MAX_SHEET_COORD_M:
            return error_response(
                "x_mm/y_mm exceed the printable sheet area",
                code="INVALID_PARAMETER",
            )
        model = sw_app.get_active_document()
        if model is None:
            return error_response("No active document")
        if call_or_value(model, "GetType") != swDocDRAWING:
            return error_response("Active document is not a drawing")

        note = model.CreateText2(body, x_m, y_m, 0.0, NOTE_TEXT_SIZE_M, NOTE_TEXT_SIZE_M)
        if note is None:
            return error_response(
                "SolidWorks rejected the note text", code="SW_API_ERROR"
            )
        call_or_value(model, "EditRebuild3")
        return success_response(
            data={"note": "created", "x_mm": float(x_mm), "y_mm": float(y_mm)},
            message=f"Inserted note at ({float(x_mm):g}, {float(y_mm):g}) mm",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to insert note")
        return error_response(f"Failed to insert note: {exc}")


def _png_resolution(path: str) -> Optional[Dict[str, int]]:
    """Read the IHDR chunk (no imaging dependency needed for line art)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(24)
        if len(head) < 24 or head[12:16] != b"IHDR":
            return None
        return {
            "width": struct.unpack(">I", head[16:20])[0],
            "height": struct.unpack(">I", head[20:24])[0],
        }
    except OSError:
        return None


def _export_drawing(
    sw_app: SolidWorksApp,
    file_path: str,
    extensions: Tuple[str, ...],
    overwrite_confirm: bool,
    label: str,
) -> dict:
    try:
        valid, msg = validate_output_file(file_path, set(extensions), overwrite_confirm)
        if not valid:
            return error_response(msg, code="INVALID_OUTPUT_PATH")

        model = sw_app.get_active_document()
        if model is None:
            return error_response("No active document to export")

        ok, message, sink_path = ensure_sink_path(file_path)
        if not ok:
            return error_response(message, code="INVALID_OUTPUT_PATH")

        call_or_value(model, "ViewZoomtofit2")
        result = model.SaveAs3(sink_path, 0, swSaveAsOptions_Silent)
        if result != 0:
            return error_response(f"{label} export failed with code {result}")

        try:
            size = os.path.getsize(sink_path)
        except OSError:
            return error_response(f"{label} export reported success but no "
                                  f"file was written: {sink_path}")
        data: Dict[str, Any] = {"path": file_path, "size_bytes": size}
        if sink_path.lower().endswith(".png"):
            data["resolution"] = _png_resolution(sink_path)
        return success_response(
            data=data,
            message=f"Exported {label} to: {file_path}",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to export %s", label)
        return error_response(f"Failed to export {label}: {exc}")


def export_drawing_pdf(
    sw_app: SolidWorksApp,
    file_path: str,
    overwrite_confirm: bool = False,
) -> dict:
    """Export the active drawing to PDF."""
    return _export_drawing(
        sw_app, file_path, (".pdf",), overwrite_confirm, "PDF"
    )


def export_drawing_png(
    sw_app: SolidWorksApp,
    file_path: str,
    overwrite_confirm: bool = False,
) -> dict:
    """Export the active drawing to PNG (raster of the sheet)."""
    return _export_drawing(
        sw_app, file_path, (".png",), overwrite_confirm, "PNG"
    )


def insert_bom_table(
    sw_app: SolidWorksApp,
    view_name: str,
    x_mm: float = 240.0,
    y_mm: float = 20.0,
    bom_type: str = "parts_only",
) -> dict:
    """Insert a BOM table on a named drawing view of an assembly drawing.

    Real-machine contract (N32 probe): IView.InsertBomTable5 with
    UseAnchorPoint=False, TopLeft anchor, no table template; parts-only
    or top-level rows. The AutoBalloon family (bubbles) is BLOCKED on
    this machine (probe evidence) — this tool lands the table only."""
    try:
        if not view_name:
            return error_response("view_name must be non-empty", code="INVALID_PARAMETER")
        bom_types = {"parts_only": 1, "top_level": 2}  # swBomType_e
        if bom_type not in bom_types:
            return error_response(
                "bom_type must be 'parts_only' or 'top_level'",
                code="INVALID_PARAMETER",
            )
        x_mm = finite_number("x_mm", x_mm)
        y_mm = finite_number("y_mm", y_mm)

        model = sw_app.get_active_document()
        if model is None or call_or_value(model, "GetType") != swDocDRAWING:
            return error_response("No active drawing document")

        if not _select_view(model, view_name):
            return error_response(
                f"Could not select drawing view {view_name!r}",
                code="SW_API_ERROR",
            )
        view = model.SelectionManager.GetSelectedObject6(1, -1)
        if view is None:
            return error_response(
                "Selected object is not a drawing view", code="SW_API_ERROR"
            )

        table = view.InsertBomTable5(
            False, mm_to_m(x_mm), mm_to_m(y_mm),
            1, bom_types[bom_type], "", "",
            False, 0, False, False,
        )
        if table is None:
            return error_response(
                "BOM table creation rejected", code="SW_API_ERROR"
            )
        return success_response(
            data={"view": view_name, "bom_type": bom_type},
            message=(
                f"Inserted {bom_type} BOM table on view {view_name!r} "
                "(balloons unavailable — AutoBalloon BLOCKED, ADR-0011)"
            ),
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to insert BOM table")
        return error_response(f"Failed to insert BOM table: {exc}")


# N52：GD&T 形位公差框格。契约（typelib 2026-09-10 取证）：
# 宿主 = IDrawingDoc.NewGtol()（零参工厂）；IGtol.SetFrameSymbols2 九参全标量
# （FrameNumber, GCS, TolDia1, TolMC1, TolDia2, TolMC2, DatumMC1-3）、
# SetFrameValues2 六参字符串（FrameNumber, Tol1, Tol2, Datum1-3）、
# SetPosition 米制；判据 = GetFrameCount 零参属性（成功必为 1）。
# GCS/MC 枚举值经 PowerShell 反射 swconst.dll（makepy 不生成枚举值）。
GTOL_CHARACTERISTICS: Dict[str, int] = {
    "symmetry": 13,
    "straightness": 14,
    "flatness": 15,
    "circularity": 16,
    "cylindricity": 17,
    "profile_line": 18,
    "profile_surface": 19,
    "angularity": 20,
    "perpendicularity": 21,
    "parallelism": 22,
    "position": 23,
    "concentricity": 24,
    "circular_runout": 25,
    "total_runout": 26,
}
GTOL_MATERIAL_CONDITIONS: Dict[str, int] = {"none": 0, "mmc": 1, "rfs": 2, "lmc": 3}
MAX_GTOL_TOLERANCE_MM = 100.0


def insert_gtol(
    sw_app: SolidWorksApp,
    characteristic: str,
    tolerance_mm: float,
    x_mm: float,
    y_mm: float,
    diameter: bool = False,
    material_condition: str = "none",
    datum_a: Optional[str] = None,
    datum_b: Optional[str] = None,
    datum_c: Optional[str] = None,
) -> dict:
    """Insert a GD&T feature-control frame on the active drawing.

    ``characteristic`` is one of the GTOL_CHARACTERISTICS keys (flatness,
    position, perpendicularity, ...); ``tolerance_mm`` is the tolerance zone
    width in millimetres; ``diameter`` prefixes the Ø modifier and
    ``material_condition`` picks none/mmc/rfs/lmc; ``datum_a/b/c`` are the
    reference letters. Coordinates are sheet millimetres.
    """
    key = str(characteristic or "").strip().lower()
    gcs = GTOL_CHARACTERISTICS.get(key)
    if gcs is None:
        return error_response(
            "characteristic must be one of "
            f"{sorted(GTOL_CHARACTERISTICS)}",
            code="INVALID_PARAMETER",
        )
    mc_key = str(material_condition or "none").strip().lower()
    mc = GTOL_MATERIAL_CONDITIONS.get(mc_key)
    if mc is None:
        return error_response(
            f"material_condition must be one of {sorted(GTOL_MATERIAL_CONDITIONS)}",
            code="INVALID_PARAMETER",
        )
    try:
        tol = float(tolerance_mm)
        x_m = float(x_mm) / 1000.0
        y_m = float(y_mm) / 1000.0
    except (TypeError, ValueError):
        return error_response(
            "tolerance_mm, x_mm and y_mm must be numbers",
            code="INVALID_PARAMETER",
        )
    if not (0 < tol <= MAX_GTOL_TOLERANCE_MM):
        return error_response(
            f"tolerance_mm must be within (0, {MAX_GTOL_TOLERANCE_MM:g}]",
            code="INVALID_PARAMETER",
        )
    if abs(x_m) > MAX_SHEET_COORD_M or abs(y_m) > MAX_SHEET_COORD_M:
        return error_response(
            "x_mm/y_mm exceed the printable sheet area",
            code="INVALID_PARAMETER",
        )
    datums = [
        (str(d).strip() if d else "")[:4]
        for d in (datum_a, datum_b, datum_c)
    ]

    try:
        model = sw_app.get_active_document()
        if model is None:
            return error_response("No active document")
        if call_or_value(model, "GetType") != swDocDRAWING:
            return error_response("Active document is not a drawing")

        try:
            gtol = model.NewGtol()
        except Exception:  # noqa: BLE001 —— N57 批次 A 实证：NewDocument 返回的
            # dynamic dispatch 上 NewGtol 报 DISP_E_MEMBERNOTFOUND（成员面受限，
            # quirks#26③ 同族）——必须转 typed IDrawingDoc（gencache 缓存模块）。
            from win32com.client import gencache

            typed_doc = gencache.GetModuleForProgID(
                "SldWorks.Application"
            ).IDrawingDoc(model._oleobj_)
            gtol = typed_doc.NewGtol()
        if gtol is None:
            return error_response(
                "SolidWorks rejected the feature-control frame (NewGtol "
                "returned nothing) — no frame was inserted",
                code="SW_API_ERROR",
            )
        gtol.SetFrameSymbols2(1, gcs, bool(diameter), mc, False, 0, 0, 0, 0)
        gtol.SetFrameValues2(
            1, f"{tol:g}", "", datums[0], datums[1], datums[2]
        )
        gtol.SetPosition(x_m, y_m, 0.0)
        frames = call_or_value(gtol, "GetFrameCount")
        if frames != 1:
            return error_response(
                f"frame was not committed (frame count = {frames})",
                code="SW_NO_EFFECT",
            )
        call_or_value(model, "EditRebuild3")
        return success_response(
            {
                "characteristic": key,
                "tolerance_mm": tol,
                "diameter": bool(diameter),
                "material_condition": mc_key,
                "datums": [d for d in datums if d],
                "x_mm": float(x_mm),
                "y_mm": float(y_mm),
                "frames": int(frames),
            }
        )
    except ValueError as exc:
        return error_response(str(exc), code="INVALID_PARAMETER")
    except Exception as exc:
        logger.exception("Failed to insert GD&T frame")
        return error_response(f"Failed to insert GD&T frame: {exc}")
