"""File import and export behavior tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from solidworks_mcp.solidworks_api.file_io import (
    FILE_LOAD_ERROR_NON_SW,
    _format_load_error,
    _guess_document_type,
    close_document,
    export_dxf,
    export_step,
    export_stl,
    import_step,
    open_document,
)


def _typed_wrapper_open_doc6(model, error_code=0, warning_code=0):
    """Simulate makepy wrappers rejecting byref-VARIANT OpenDoc6 arguments.

    On the plain-int retry the wrapper bundles the byref out-params into the
    return value, so callers receive ``(retval, errors, warnings)``.
    """

    def open_doc6(*args):
        if not all(isinstance(arg, int) for arg in args[4:6]):
            raise TypeError(
                "int() argument must be a string, a bytes-like object "
                "or a real number, not 'VARIANT'"
            )
        return (model, error_code, warning_code)

    return open_doc6


class TestOpenDocument(unittest.TestCase):
    @patch(
        "solidworks_mcp.solidworks_api.file_io.validate_path",
        return_value=(True, ""),
    )
    def test_rejects_unknown_extension_before_calling_solidworks(self, _validate_path):
        sw_app = Mock()

        result = open_document(sw_app, r"C:\models\notes.txt")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")
        sw_app.app.OpenDoc6.assert_not_called()

    def test_document_type_detection_and_load_error_formatting(self):
        self.assertEqual(_guess_document_type("part.SLDPRT"), 1)
        self.assertEqual(_guess_document_type("assembly.sldasm"), 2)
        self.assertEqual(_guess_document_type("drawing.slddrw"), 3)
        self.assertEqual(_guess_document_type("model.step"), 1)
        self.assertIn("3DInterconnect", _format_load_error(FILE_LOAD_ERROR_NON_SW))
        self.assertEqual(_format_load_error(7), "load error code 7")

    @patch("solidworks_mcp.solidworks_api.file_io.validate_path", return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.file_io._make_error_variants")
    def test_opens_supported_document(self, variants, _validate):
        variants.return_value = (SimpleNamespace(value=0), SimpleNamespace(value=2))
        model = SimpleNamespace(GetTitle=lambda: "Part1")
        sw = Mock()
        sw.app.OpenDoc6.return_value = model
        result = open_document(sw, r"C:\models\part.sldprt")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["title"], "Part1")
        self.assertEqual(result["data"]["warnings"], 2)

    @patch("solidworks_mcp.solidworks_api.file_io.validate_path", return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.file_io._make_error_variants")
    def test_open_reports_solidworks_load_failure(self, variants, _validate):
        variants.return_value = (
            SimpleNamespace(value=FILE_LOAD_ERROR_NON_SW),
            SimpleNamespace(value=0),
        )
        sw = Mock()
        sw.app.OpenDoc6.return_value = None
        result = open_document(sw, r"C:\models\part.step")
        self.assertFalse(result["success"])
        self.assertIn("3DInterconnect", result["message"])

    @patch("solidworks_mcp.solidworks_api.file_io.validate_path", return_value=(False, "unsafe"))
    def test_open_rejects_invalid_path(self, _validate):
        self.assertEqual(open_document(Mock(), "bad.sldprt")["message"], "unsafe")

    @patch("solidworks_mcp.solidworks_api.file_io.validate_path", return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.file_io._make_error_variants")
    def test_open_retries_with_plain_ints_when_typed_wrapper_rejects_variants(
        self, variants, _validate
    ):
        # Real-machine evidence (T1, 2026-08-29): makepy-generated wrappers
        # coerce VT_BYREF|VT_I4 params with int(), which raises TypeError on
        # the pre-built VARIANTs used for dynamic dispatch.
        variants.return_value = (SimpleNamespace(value=0), SimpleNamespace(value=0))
        model = SimpleNamespace(GetTitle=lambda: "Part1")
        sw = Mock()
        sw.app.OpenDoc6.side_effect = _typed_wrapper_open_doc6(model)

        result = open_document(sw, r"C:\models\part.sldprt")

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["title"], "Part1")
        self.assertEqual(sw.app.OpenDoc6.call_count, 2)
        self.assertEqual(sw.app.OpenDoc6.call_args_list[-1].args[4:6], (0, 0))

    @patch("solidworks_mcp.solidworks_api.file_io.validate_path", return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.file_io._make_error_variants")
    def test_open_reports_load_error_from_typed_wrapper_tuple(self, variants, _validate):
        variants.return_value = (SimpleNamespace(value=0), SimpleNamespace(value=0))
        sw = Mock()
        sw.app.OpenDoc6.side_effect = _typed_wrapper_open_doc6(
            None, error_code=FILE_LOAD_ERROR_NON_SW
        )

        result = open_document(sw, r"C:\models\part.step")

        self.assertFalse(result["success"])
        self.assertIn("3DInterconnect", result["message"])

    @patch("solidworks_mcp.solidworks_api.file_io.validate_path", return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.file_io._make_error_variants")
    def test_open_failure_without_error_code_is_honest(self, variants, _validate):
        """C-3 回归（2026-10-05）：动态派发返回非 tuple（拿不到错误码）
        时不得伪装 "load error code 0"——如实说明并给出排查方向。"""

        def dynamic_dispatch_open_doc6(*args):
            # 首 VARIANT 调用抛 TypeError（makepy 形态）；重试路径返回
            # 裸 None（dynamic dispatch 不打包 byref out-params）。
            if not all(isinstance(arg, int) for arg in args[4:6]):
                raise TypeError("int() argument must be a real number, not 'VARIANT'")
            return None

        variants.return_value = (SimpleNamespace(value=0), SimpleNamespace(value=0))
        sw = Mock()
        sw.app.OpenDoc6.side_effect = dynamic_dispatch_open_doc6

        result = open_document(sw, r"C:\models\part.sldprt")

        self.assertFalse(result["success"])
        self.assertIn("no document and no error code", result["message"])
        self.assertNotIn("load error code 0", result["message"])


class TestCloseDocument(unittest.TestCase):
    def test_close_without_save_skips_save_and_reports_title(self):
        model = SimpleNamespace(GetTitle=lambda: "Part1")
        sw = Mock()
        sw.get_active_document.return_value = model
        sw.app.CloseDoc.return_value = True

        result = close_document(sw)

        self.assertTrue(result["success"])
        self.assertEqual(result["data"], {"title": "Part1", "saved": False})
        sw.app.CloseDoc.assert_called_once_with("Part1")

    def test_close_with_save_reports_saved_and_save_rejection(self):
        model = SimpleNamespace(GetTitle=lambda: "Part1", Save3=lambda *a: True)
        sw = Mock()
        sw.get_active_document.return_value = model
        sw.app.CloseDoc.return_value = True
        self.assertTrue(close_document(sw, save_changes=True)["data"]["saved"])

        model.Save3 = lambda *a: False
        result = close_document(sw, save_changes=True)
        self.assertEqual(result["error"]["code"], "SW_SAVE_FAILED")
        sw.app.CloseDoc.assert_called_once()  # only from the first call

    def test_close_handles_missing_document_and_close_rejection(self):
        sw = Mock()
        sw.get_active_document.return_value = None
        self.assertFalse(close_document(sw)["success"])

        model = SimpleNamespace(GetTitle=lambda: "P", Save3=lambda *a: True)
        sw.get_active_document.return_value = model
        sw.app.CloseDoc.side_effect = OSError("rejected")
        self.assertEqual(close_document(sw)["error"]["code"], "SW_API_ERROR")


class TestImportExport(unittest.TestCase):
    @patch("solidworks_mcp.solidworks_api.file_io.validate_path", return_value=(True, ""))
    def test_import_step_validates_extension(self, _validate):
        result = import_step(Mock(), "part.iges")
        self.assertFalse(result["success"])
        self.assertIn("Expected .step", result["message"])

    @patch("solidworks_mcp.solidworks_api.file_io.validate_path", return_value=(True, ""))
    def test_import_step_success_and_failure(self, _validate):
        sw = Mock()
        sw.app.GetImportFileData.return_value = object()
        sw.app.LoadFile4.return_value = (
            SimpleNamespace(GetTitle=lambda: "Imported"),
            0,
        )
        self.assertTrue(import_step(sw, "part.step")["success"])
        sw.app.LoadFile4.return_value = (None, 1)
        self.assertFalse(import_step(sw, "part.stp")["success"])

    @patch("solidworks_mcp.solidworks_api.file_io.validate_path", return_value=(True, ""))
    def test_import_step_uses_foreign_file_loader_with_absolute_path(self, _validate):
        sw = Mock()
        sw.app.GetImportFileData.return_value = object()
        sw.app.LoadFile4.return_value = (
            SimpleNamespace(GetTitle=lambda: "Imported"),
            0,
        )

        result = import_step(sw, "part.step")

        self.assertTrue(result["success"])
        load_args = sw.app.LoadFile4.call_args.args
        self.assertTrue(os.path.isabs(load_args[0]))
        self.assertEqual(load_args[2], sw.app.GetImportFileData.return_value)
        sw.app.OpenDoc6.assert_not_called()

    def test_export_validates_output_and_active_document(self):
        with patch(
            "solidworks_mcp.solidworks_api.file_io.validate_output_file",
            return_value=(False, "bad"),
        ):
            result = export_step(Mock(), "part.stl")
        self.assertEqual(result["error"]["code"], "INVALID_OUTPUT_PATH")
        sw = Mock()
        sw.get_active_document.return_value = None
        with patch(
            "solidworks_mcp.solidworks_api.file_io.validate_output_file",
            return_value=(True, ""),
        ):
            self.assertFalse(export_stl(sw, "part.stl")["success"])

    def test_export_step_and_stl_success_and_save_error(self):
        model = Mock()
        sw = Mock()
        sw.get_active_document.return_value = model
        with patch(
            "solidworks_mcp.solidworks_api.file_io.validate_output_file",
            return_value=(True, ""),
        ):
            model.SaveAs3.return_value = 0
            self.assertTrue(export_step(sw, "part.step")["success"])
            self.assertTrue(export_stl(sw, "part.stl")["success"])
            model.SaveAs3.return_value = 9
            self.assertFalse(export_step(sw, "part.step")["success"])
            self.assertFalse(export_stl(sw, "part.stl")["success"])

    def test_com_exceptions_are_structured(self):
        with patch(
            "solidworks_mcp.solidworks_api.file_io.validate_path",
            side_effect=RuntimeError("COM"),
        ):
            self.assertFalse(open_document(Mock(), "part.sldprt")["success"])
            self.assertFalse(import_step(Mock(), "part.step")["success"])
        with patch(
            "solidworks_mcp.solidworks_api.file_io.validate_output_file",
            side_effect=RuntimeError("COM"),
        ):
            self.assertFalse(export_step(Mock(), "part.step")["success"])
            self.assertFalse(export_stl(Mock(), "part.stl")["success"])
            self.assertFalse(export_dxf(Mock(), "drawing.dxf")["success"])


class TestExportDXF(unittest.TestCase):
    """N5：DXF 导出——SaveAs3 恒返警告 1，判据=文件存在+头含 SECTION（探针）。"""

    def _patches(self, path):
        return (
            patch(
                "solidworks_mcp.solidworks_api.file_io.validate_output_file",
                return_value=(True, ""),
            ),
            patch(
                "solidworks_mcp.solidworks_api.file_io.ensure_sink_path",
                side_effect=lambda p: (True, "", p),
            ),
        )

    def test_accepts_warning_code_with_valid_header(self):
        model = Mock()
        sw = Mock()
        sw.get_active_document.return_value = model
        with tempfile.TemporaryDirectory() as tmp:
            dxf = os.path.join(tmp, "drawing.dxf")
            Path(dxf).write_bytes(b"  0\r\nSECTION\r\n  2\r\nHEADER\r\n" + b"0" * 300)
            vp, sp = self._patches(dxf)
            with vp, sp:
                model.SaveAs3.return_value = 1  # DXF 恒返警告 1（探针）
                ok = export_dxf(sw, dxf)
                self.assertTrue(ok["success"], ok)
                self.assertEqual(ok["data"]["path"], dxf)
                model.SaveAs3.return_value = 0  # 0 同样接受
                self.assertTrue(export_dxf(sw, dxf)["success"])
                model.SaveAs3.return_value = 9  # 其他错误码拒
                self.assertFalse(export_dxf(sw, dxf)["success"])

    def test_rejects_bad_header_or_missing_file(self):
        model = Mock()
        sw = Mock()
        sw.get_active_document.return_value = model
        model.SaveAs3.return_value = 1
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.dxf")
            Path(bad).write_bytes(b"junk bytes without dxf marker")
            missing = os.path.join(tmp, "missing.dxf")
            vp, sp = self._patches(bad)
            with vp, sp:
                self.assertFalse(export_dxf(sw, bad)["success"])
                self.assertFalse(export_dxf(sw, missing)["success"])

    def test_rejects_wrong_extension_without_patches(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt = os.path.join(tmp, "out.txt")
            Path(txt).touch()
            result = export_dxf(Mock(), txt)
            self.assertFalse(result["success"])
            self.assertEqual(result["error"]["code"], "INVALID_OUTPUT_PATH")

    def test_requires_active_document(self):
        sw = Mock()
        sw.get_active_document.return_value = None
        result = export_dxf(sw, "drawing.dxf")
        self.assertFalse(result["success"])
        self.assertIn("No active document", result["message"])


if __name__ == "__main__":
    unittest.main()
