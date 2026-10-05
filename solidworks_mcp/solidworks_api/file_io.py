"""File import/export operations for SolidWorks."""

from __future__ import annotations

import logging
import os
from typing import Optional

from solidworks_mcp.solidworks_api.app import SolidWorksApp, SolidWorksNotRunningError
from solidworks_mcp.solidworks_api.constants import (
    swDocASSEMBLY,
    swDocDRAWING,
    swDocPART,
    swFileSaveErrorNone,
    swOpenDocOptions_Silent,
    swSaveAsOptions_Silent,
)
from solidworks_mcp.utils.common import error_response, success_response
from solidworks_mcp.utils.com import call_or_value, make_error_variants
from solidworks_mcp.utils.security import (
    ensure_sink_path,
    normalize_path,
    validate_output_file,
    validate_path,
)

logger = logging.getLogger(__name__)

# Common SolidWorks file load error codes
FILE_LOAD_ERROR_NON_SW = 2097152
SUPPORTED_OPEN_EXTENSIONS = {
    ".sldprt",
    ".prt",
    ".sldasm",
    ".asm",
    ".slddrw",
    ".drw",
    ".step",
    ".stp",
    ".iges",
    ".igs",
    ".x_t",
    ".x_b",
    ".sat",
    ".stl",
}


def _guess_document_type(file_path: str) -> int:
    """Guess SolidWorks document type from extension."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".sldprt", ".prt"):
        return swDocPART
    if ext in (".sldasm", ".asm"):
        return swDocASSEMBLY
    if ext in (".slddrw", ".drw"):
        return swDocDRAWING
    # Treat generic CAD formats as parts by default.
    return swDocPART


_make_error_variants = make_error_variants


def _format_load_error(error_code: int) -> str:
    """Provide a human-readable hint for common load error codes."""
    if error_code == FILE_LOAD_ERROR_NON_SW:
        return (
            "SolidWorks could not open the file as a native document. "
            "For STEP/IGES files, ensure 3DInterconnect is enabled: "
            "Tools > Options > System Options > Import > Enable 3D Interconnect"
        )
    return f"load error code {error_code}"


def _model_title(model) -> str:
    return call_or_value(model, "GetTitle")


def _open_doc6(app, file_path: str, doc_type: int) -> tuple:
    """Open a document, tolerating typed wrappers that reject byref VARIANTs.

    Makepy-generated wrappers coerce ``VT_BYREF|VT_I4`` parameters with
    ``int()``, which raises TypeError on the pre-built VARIANTs used for
    dynamic dispatch. The plain-int retry works there, and the wrapper then
    bundles the byref out-params into the return value as a tuple.

    Returns ``(model, error_code, warning_code)``.
    """
    errs, warns = _make_error_variants()
    args = (normalize_path(file_path), doc_type, swOpenDocOptions_Silent, "")
    try:
        model = app.OpenDoc6(*args, errs, warns)
        return model, errs.value, warns.value
    except TypeError:
        result = app.OpenDoc6(*args, 0, 0)
        if not isinstance(result, tuple):
            return result, 0, 0
        model = result[0] if result else None
        error_code = result[1] if len(result) > 1 and isinstance(result[1], int) else 0
        warning_code = result[2] if len(result) > 2 and isinstance(result[2], int) else 0
        return model, error_code, warning_code


def open_document(
    sw_app: SolidWorksApp,
    file_path: str,
    doc_type: Optional[int] = None,
) -> dict:
    """Open an existing SolidWorks document."""
    try:
        valid, msg = validate_path(file_path, must_exist=True)
        if not valid:
            return error_response(msg)

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in SUPPORTED_OPEN_EXTENSIONS:
            return error_response(
                f"Unsupported document extension: {ext or '<none>'}",
                code="INVALID_PARAMETER",
            )

        target_type = doc_type if doc_type is not None else _guess_document_type(file_path)
        model, error_code, warning_code = _open_doc6(sw_app.app, file_path, target_type)
        if model is None:
            # C-3（2026-10-05）：动态派发路径拿不到真实错误码（返回非
            # tuple 时 _open_doc6 记 0）——如实说明，不要伪装成 "code 0"。
            if error_code:
                detail = _format_load_error(error_code)
            else:
                detail = (
                    "SolidWorks returned no document and no error code "
                    "(dynamic dispatch) — check the file format, import "
                    "settings, and that the file is not corrupt"
                )
            return error_response(f"Failed to open document: {file_path}. {detail}")

        return success_response(
            data={
                "path": file_path,
                "type": target_type,
                "title": _model_title(model),
                "errors": error_code,
                "warnings": warning_code,
            },
            message=f"Opened document: {os.path.basename(file_path)}",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to open document")
        return error_response(f"Failed to open document: {exc}")


def close_document(sw_app: SolidWorksApp, save_changes: bool = False) -> dict:
    """Close the active document, optionally saving it first.

    Closing without ``save_changes`` discards unsaved edits.
    """
    try:
        model = sw_app.get_active_document()
        if model is None:
            return error_response("No active document")

        title = _model_title(model)
        if save_changes:
            errors, warnings = _make_error_variants()
            saved = bool(model.Save3(swSaveAsOptions_Silent, errors, warnings))
            if not saved:
                return error_response(
                    "SolidWorks rejected saving the document before closing",
                    code="SW_SAVE_FAILED",
                )

        # CloseDoc is a void COM method: dynamic dispatch returns None on
        # success, so failure must be detected from a raised COM error,
        # never from the (always falsy) return value.
        try:
            sw_app.app.CloseDoc(title)
        except Exception:
            return error_response(
                f"SolidWorks rejected closing document: {title}",
                code="SW_API_ERROR",
            )

        return success_response(
            data={"title": title, "saved": save_changes},
            message=f"Closed document: {title}",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to close document")
        return error_response(f"Failed to close document: {exc}")


def import_step(
    sw_app: SolidWorksApp,
    file_path: str,
) -> dict:
    """Import a STEP (.step/.stp) file into SolidWorks.

    Foreign formats go through the dedicated ``LoadFile4`` loader with
    ``GetImportFileData``: real-machine evidence (T1, 2026-08-29) shows
    ``OpenDoc6`` rejects STEP files with a native-document load error even
    when 3D Interconnect is enabled. ``LoadFile4`` also requires an
    absolute path. Typed wrappers bundle the byref error out-param into
    the return value as ``(model, error_code)``.
    """
    try:
        valid, msg = validate_path(file_path, must_exist=True)
        if not valid:
            return error_response(msg)

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in (".step", ".stp"):
            return error_response(f"Expected .step or .stp file, got: {ext}")

        path = normalize_path(file_path)
        import_data = sw_app.app.GetImportFileData(path)
        result = sw_app.app.LoadFile4(path, "", import_data, 0)
        if isinstance(result, tuple):
            model = result[0] if result else None
            error_code = result[1] if len(result) > 1 and isinstance(result[1], int) else 0
        else:
            model, error_code = result, 0
        if model is None:
            return error_response(
                f"Failed to import STEP: {file_path}. load error code {error_code}"
            )

        return success_response(
            data={
                "path": file_path,
                "title": _model_title(model),
                "errors": error_code,
            },
            message=f"Imported STEP: {os.path.basename(file_path)}",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to import STEP")
        return error_response(f"Failed to import STEP: {exc}")


def export_step(
    sw_app: SolidWorksApp,
    file_path: str,
    overwrite_confirm: bool = False,
) -> dict:
    """Export the active document to STEP format."""
    try:
        valid, msg = validate_output_file(
            file_path, {".step", ".stp"}, overwrite_confirm
        )
        if not valid:
            return error_response(msg, code="INVALID_OUTPUT_PATH")

        model = sw_app.get_active_document()
        if model is None:
            return error_response("No active document to export")

        ok, message, sink_path = ensure_sink_path(file_path)
        if not ok:
            return error_response(message, code="INVALID_OUTPUT_PATH")
        result = model.SaveAs3(sink_path, 0, swSaveAsOptions_Silent)
        if result != swFileSaveErrorNone:
            return error_response(f"Export failed with code {result}")

        return success_response(
            data={"path": file_path},
            message=f"Exported STEP to: {file_path}",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to export STEP")
        return error_response(f"Failed to export STEP: {exc}")


def export_stl(
    sw_app: SolidWorksApp,
    file_path: str,
    overwrite_confirm: bool = False,
) -> dict:
    """Export the active part to STL format."""
    try:
        valid, msg = validate_output_file(file_path, {".stl"}, overwrite_confirm)
        if not valid:
            return error_response(msg, code="INVALID_OUTPUT_PATH")

        model = sw_app.get_active_document()
        if model is None:
            return error_response("No active document to export")

        ok, message, sink_path = ensure_sink_path(file_path)
        if not ok:
            return error_response(message, code="INVALID_OUTPUT_PATH")
        result = model.SaveAs3(sink_path, 0, swSaveAsOptions_Silent)
        if result != swFileSaveErrorNone:
            return error_response(f"STL export failed with code {result}")

        return success_response(
            data={"path": file_path},
            message=f"Exported STL to: {file_path}",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to export STL")
        return error_response(f"Failed to export STL: {exc}")


def export_dxf(
    sw_app: SolidWorksApp,
    file_path: str,
    overwrite_confirm: bool = False,
) -> dict:
    """Export the active drawing to ASCII DXF (AC1015).

    SolidWorks returns warning code 1 for every DXF SaveAs3 (probe-verified),
    so success is judged by the file existing with a valid 'SECTION' header
    instead of the return code.
    """
    try:
        valid, msg = validate_output_file(file_path, {".dxf"}, overwrite_confirm)
        if not valid:
            return error_response(msg, code="INVALID_OUTPUT_PATH")

        model = sw_app.get_active_document()
        if model is None:
            return error_response("No active document to export")

        ok, message, sink_path = ensure_sink_path(file_path)
        if not ok:
            return error_response(message, code="INVALID_OUTPUT_PATH")
        result = model.SaveAs3(sink_path, 0, swSaveAsOptions_Silent)
        if result not in (0, 1):  # DXF exports return warning code 1 by default
            return error_response(f"DXF export failed with code {result}")

        try:
            with open(sink_path, "rb") as handle:
                head = handle.read(64)
        except OSError:
            return error_response(
                f"DXF export reported success but no file was written: {sink_path}"
            )
        if b"SECTION" not in head:
            return error_response(
                "Exported file does not look like an ASCII DXF "
                "(missing SECTION header)",
                code="SW_API_ERROR",
            )
        return success_response(
            data={"path": file_path, "size_bytes": os.path.getsize(sink_path)},
            message=f"Exported DXF to: {file_path}",
        )
    except SolidWorksNotRunningError as exc:
        return error_response(str(exc))
    except Exception as exc:
        logger.exception("Failed to export DXF")
        return error_response(f"Failed to export DXF: {exc}")
