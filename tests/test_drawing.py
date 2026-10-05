"""Drawing tool tests (T12) — fakes follow real-machine shapes:

- NewDocument returns a dynamic dispatch exposing IModelDoc + IDrawingDoc
  members only (SelectByID2 lives on Extension with 9 params, Callout=Nothing)
- zero-arg COM members are properties (GetType/GetTitle/GetFirstView/
  GetNextView/GetDisplayDimensionCount/GetAnnotationCount/EditRebuild3)
- Create1stAngleViews2 always returns False on SW 2026 — the manual route
  (CreateDrawViewFromModelView3 + CreateUnfoldedViewAt3) is the contract
- InsertModelAnnotations2(0, True, 0, True, True, False) is the verified call
  (InsertModelAnnotations3/4 on this machine return None and insert nothing)
"""

from __future__ import annotations

import itertools
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from solidworks_mcp.solidworks_api import drawing


def _fake_bytes(path: str) -> bytes:
    if path.lower().endswith(".pdf"):
        return b"%PDF-1.6\n" + b"0" * 40000
    header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
    header += struct.pack(">II", 1264, 694) + b"\x08\x02\x00\x00\x00"
    return header + b"\x00" * 500


class FakeView:
    def __init__(self, name, dimensions=0, annotations=0):
        self.name = name
        self.dimensions = dimensions
        self.annotations = annotations
        self.next_view = None

    @property
    def Name(self):
        return self.name

    @property
    def GetDisplayDimensionCount(self):
        return self.dimensions

    @property
    def GetAnnotationCount(self):
        return self.annotations

    @property
    def GetNextView(self):
        return self.next_view


class FakeExtension:
    def __init__(self):
        self.calls = []

    def SelectByID2(self, name, type_, x, y, z, append, mark, callout, option):
        self.calls.append((name, type_))
        return True


class FakeDrawingDoc:
    """Sheet view first (GB template title block), model views appended."""

    def __init__(self):
        self.sheet = FakeView("图纸1", annotations=82)
        self.views = [self.sheet]
        self.ext = FakeExtension()
        self.created = []  # (model_path, config)
        self.unfolded = 0
        self.insert_calls = []
        self.save_calls = []
        # N4：尺寸整理/剖视图 fake（探针真实形态见文件头）
        self.sketch_lines = []
        self.section_calls = []
        self.delete_calls = []
        self.sketch_manager = FakeSketchManager(self)
        self.active_sketch = FakeSketch("草图1")
        # N5：公差/粗糙度/注释 fake（探针真实形态见文件头）
        self.text_calls = []
        self.finish_calls = []

    @property
    def GetType(self):
        return 3  # swDocDRAWING

    @property
    def GetTitle(self):
        return "工程图1 - 图纸1"

    @property
    def Extension(self):
        return self.ext

    @property
    def GetFirstView(self):
        return self.views[0] if self.views else None

    @property
    def EditRebuild3(self):
        return True

    @property
    def ViewZoomtofit2(self):
        return True

    def _relink(self):
        for left, right in zip(self.views, self.views[1:]):
            left.next_view = right

    def CreateDrawViewFromModelView3(self, model_name, config, x, y, z):
        self.created.append((model_name, config))
        view = FakeView(f"工程图视图{len(self.views)}")
        self.views.append(view)
        self._relink()
        return view

    def CreateUnfoldedViewAt3(self, x, y, z, not_aligned):
        self.unfolded += 1
        view = FakeView(f"工程图视图{len(self.views)}")
        self.views.append(view)
        self._relink()
        return view

    def InsertModelAnnotations2(self, option, all_types, types, all_views,
                                duplicate, hidden):
        self.insert_calls.append(
            (option, all_types, types, all_views, duplicate, hidden)
        )
        if all_types:  # 实机：AllTypes=True 带入全部显示尺寸
            for view in self.views[1:]:
                view.dimensions += 1
                view.annotations += 1
            return True
        return False

    def SaveAs3(self, path, version, options):
        self.save_calls.append(path)
        Path(path).write_bytes(_fake_bytes(path))
        return 0

    # ---- N4：尺寸删除（SelectByID2 选择名）与剖视图 ----

    def DeleteSelection(self, also_delete_unused):
        """带参方法；删除最后一次 DIMENSION 选择命中的显示尺寸。"""
        self.delete_calls.append(also_delete_unused)
        dim_names = [n for n, t in self.ext.calls if t == "DIMENSION"]
        if not dim_names:
            return False
        target = dim_names[-1]
        for view in self.views:
            for dd in getattr(view, "dims", ()):
                if dd.sel_name == target and not dd.deleted:
                    dd.deleted = True
                    return True
        return False

    @property
    def SketchManager(self):
        return self.sketch_manager

    @property
    def GetActiveSketch2(self):
        return self.active_sketch

    def CreateSectionViewAt4(self, x, y, z, sketch_name, arrow_side, color):
        self.section_calls.append((x, y, z, sketch_name))
        self._section_count = getattr(self, "_section_count", 0) + 1
        view = FakeView(f"剖面视图{chr(ord('A') + self._section_count - 1)}")
        self.views.append(view)
        self._relink()
        return view

    def CreateText2(self, text, x, y, z, width, height):
        self.text_calls.append((text, x, y, z, width, height))
        return FakeNote(text)

    def InsertSurfaceFinishSymbol(self, sym_type, leader_type, x, y, z, lay,
                                  arrow, mach, other, prod, sample, max_rough,
                                  min_rough, spacing):
        self.finish_calls.append((sym_type, leader_type, x, y, z, max_rough))
        return True


class FakePartDoc:
    @property
    def GetType(self):
        return 1  # swDocPART

    @property
    def Extension(self):
        return FakeExtension()


class FakeApp:
    def __init__(self, template_dir: Path, doc=None):
        self.template_dir = template_dir
        self.doc = doc if doc is not None else FakeDrawingDoc()
        self.new_document_calls = []

    def GetUserPreferenceStringValue(self, pref):
        return str(self.template_dir / "gb_a0.drwdot")

    def NewDocument(self, template, paper, width, height):
        self.new_document_calls.append(template)
        return self.doc

    def CloseAllDocuments(self, include_unsaved):
        return True


class DrawingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="swmcp_dwg_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, True))
        # 模板目录：用户默认=A0，同目录存在 A3（应优先选择）
        (self.tmp / "gb_a0.drwdot").touch()
        (self.tmp / "gb_a3.drwdot").touch()
        self.part = str(self.tmp / "probe.SLDPRT")
        Path(self.part).write_bytes(b"part")
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("SOLIDWORKS_MCP_DRAWING_TEMPLATE", None)

    def _sw(self, doc=None):
        app = FakeApp(self.tmp, doc=doc)
        sw = Mock()
        sw.app = app
        sw.get_active_document.return_value = app.doc
        return sw, app

    def _patch_checks(self):
        return (
            patch(
                "solidworks_mcp.solidworks_api.drawing.validate_path",
                side_effect=lambda path, **kwargs: (True, ""),
            ),
            patch(
                "solidworks_mcp.solidworks_api.drawing.validate_output_file",
                side_effect=lambda path, exts, oc=False: (
                    (True, "")
                    if os.path.splitext(path)[1].lower() in exts
                    else (False, f"Unsupported output extension for {exts}: "
                                 f"{os.path.splitext(path)[1]}")
                ),
            ),
            patch(
                "solidworks_mcp.solidworks_api.drawing.ensure_sink_path",
                side_effect=lambda path: (True, "", path),
            ),
        )


class TestCreateDrawing(DrawingTestCase):
    def test_projects_three_views_and_selects_front_by_name(self):
        sw, app = self._sw()
        vp, vo, ve = self._patch_checks()
        with vp, vo, ve:
            result = drawing.create_drawing_from_part(sw, self.part)

        self.assertTrue(result["success"], result)
        self.assertEqual(app.new_document_calls, [str(self.tmp / "gb_a3.drwdot")])
        # 建主视图用绝对路径 + 默认配置名空串
        self.assertEqual(app.doc.created[0][0], os.path.abspath(self.part))
        self.assertEqual(app.doc.created[0][1], "")
        # 主视图按 DRAWINGVIEW 类型选中两次（顶/侧投影各一次）
        self.assertEqual(
            app.doc.ext.calls,
            [("工程图视图1", "DRAWINGVIEW"), ("工程图视图1", "DRAWINGVIEW")],
        )
        self.assertEqual(app.doc.unfolded, 2)
        self.assertEqual(result["data"]["view_count"], 4)
        self.assertEqual(result["data"]["views"][0]["name"], "图纸1")

    def test_env_template_overrides_preference(self):
        env_tpl = self.tmp / "custom.drwdot"
        env_tpl.touch()
        os.environ["SOLIDWORKS_MCP_DRAWING_TEMPLATE"] = str(env_tpl)
        sw, app = self._sw()
        vp, vo, ve = self._patch_checks()
        with vp, vo, ve:
            result = drawing.create_drawing_from_part(sw, self.part)
        self.assertTrue(result["success"])
        self.assertEqual(app.new_document_calls, [str(env_tpl)])

    def test_missing_template_is_reported(self):
        app = FakeApp(self.tmp)
        app.GetUserPreferenceStringValue = lambda pref: ""
        sw = Mock()
        sw.app = app
        vp, vo, ve = self._patch_checks()
        with vp, vo, ve:
            result = drawing.create_drawing_from_part(sw, self.part)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "TEMPLATE_NOT_FOUND")
        self.assertIn("SOLIDWORKS_MCP_DRAWING_TEMPLATE", result["message"])

    def test_invalid_part_path_is_rejected(self):
        sw, _ = self._sw()
        with patch(
            "solidworks_mcp.solidworks_api.drawing.validate_path",
            return_value=(False, "path outside allowed root"),
        ):
            result = drawing.create_drawing_from_part(sw, self.part)
        self.assertFalse(result["success"])
        self.assertIn("path outside allowed root", result["message"])

    def test_new_document_failure_is_structured(self):
        sw = Mock()
        sw.app.GetUserPreferenceStringValue = lambda pref: str(
            self.tmp / "gb_a3.drwdot"
        )
        sw.app.NewDocument = Mock(side_effect=RuntimeError("COM failed"))
        vp, vo, ve = self._patch_checks()
        with vp, vo, ve:
            result = drawing.create_drawing_from_part(sw, self.part)
        self.assertFalse(result["success"])
        self.assertIn("COM failed", result["message"])

    def test_front_view_failure_aborts_with_views_reported(self):
        doc = FakeDrawingDoc()

        def no_front(*args):
            return None

        doc.CreateDrawViewFromModelView3 = no_front
        sw, _ = self._sw(doc=doc)
        vp, vo, ve = self._patch_checks()
        with vp, vo, ve:
            result = drawing.create_drawing_from_part(sw, self.part)
        self.assertFalse(result["success"])
        self.assertIn("front view", result["message"])
        self.assertEqual(doc.unfolded, 0)  # 未继续投影

    def test_select_failure_aborts_projection(self):
        doc = FakeDrawingDoc()
        doc.ext.SelectByID2 = lambda *a: False
        sw, _ = self._sw(doc=doc)
        vp, vo, ve = self._patch_checks()
        with vp, vo, ve:
            result = drawing.create_drawing_from_part(sw, self.part)
        self.assertFalse(result["success"])
        self.assertIn("select the front view", result["message"])

    def test_projection_failure_is_reported(self):
        doc = FakeDrawingDoc()
        doc.CreateUnfoldedViewAt3 = lambda *a: None
        sw, _ = self._sw(doc=doc)
        vp, vo, ve = self._patch_checks()
        with vp, vo, ve:
            result = drawing.create_drawing_from_part(sw, self.part)
        self.assertFalse(result["success"])
        self.assertIn("projected view", result["message"])

    def test_view_count_shortfall_is_reported(self):
        doc = FakeDrawingDoc()
        # 投影调用成功但视图不落链（异常实机形态：返回对象而树未变）
        doc.CreateUnfoldedViewAt3 = lambda *a: FakeView("detached")
        sw, _ = self._sw(doc=doc)
        vp, vo, ve = self._patch_checks()
        with vp, vo, ve:
            result = drawing.create_drawing_from_part(sw, self.part)
        self.assertFalse(result["success"])
        self.assertIn("Only 2 views", result["message"])

    def test_stale_preference_still_resolves_neighbor_template(self):
        # pref 指向不存在的 gb_a0（版本目录失效），同目录 gb_a3 仍可用
        app = FakeApp(self.tmp)
        app.GetUserPreferenceStringValue = lambda pref: str(
            self.tmp / "gb_a0.drwdot"
        )
        (self.tmp / "gb_a0.drwdot").unlink()
        sw = Mock()
        sw.app = app
        vp, vo, ve = self._patch_checks()
        with vp, vo, ve:
            result = drawing.create_drawing_from_part(sw, self.part)
        self.assertTrue(result["success"], result)
        self.assertEqual(app.new_document_calls, [str(self.tmp / "gb_a3.drwdot")])

    def test_preference_com_error_maps_to_template_not_found(self):
        app = FakeApp(self.tmp)
        app.GetUserPreferenceStringValue = Mock(
            side_effect=RuntimeError("COM failed")
        )
        sw = Mock()
        sw.app = app
        vp, vo, ve = self._patch_checks()
        with vp, vo, ve:
            result = drawing.create_drawing_from_part(sw, self.part)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "TEMPLATE_NOT_FOUND")

    def test_views_without_count_members_are_tolerated(self):
        class BareView(FakeView):
            @property
            def GetDisplayDimensionCount(self):
                raise AttributeError("no such member")

        doc = FakeDrawingDoc()
        doc.sheet = BareView("图纸1")
        doc.views = [doc.sheet]
        sw, _ = self._sw(doc=doc)
        vp, vo, ve = self._patch_checks()
        with vp, vo, ve:
            result = drawing.create_drawing_from_part(sw, self.part)
        self.assertTrue(result["success"], result)
        self.assertIsNone(result["data"]["views"][0]["dimensions"])


class TestInsertDimensions(DrawingTestCase):
    def test_inserts_via_v2_all_types_and_reports_delta(self):
        sw, app = self._sw()
        doc = app.doc
        doc.CreateDrawViewFromModelView3("p.SLDPRT", "", 0.15, 0.10, 0.0)
        doc.CreateUnfoldedViewAt3(0.15, 0.19, 0.0, False)
        doc.CreateUnfoldedViewAt3(0.27, 0.10, 0.0, False)

        result = drawing.insert_model_dimensions(sw)

        self.assertTrue(result["success"], result)
        self.assertEqual(
            doc.insert_calls,
            [(0, True, 0, True, True, False)],
        )
        self.assertEqual(result["data"]["dimensions_inserted"], 3)
        self.assertEqual(result["data"]["total_dimensions"], 3)

    def test_rejects_non_drawing_document(self):
        sw = Mock()
        sw.get_active_document.return_value = FakePartDoc()
        result = drawing.insert_model_dimensions(sw)
        self.assertFalse(result["success"])
        self.assertIn("not a drawing", result["message"])

    def test_no_effect_is_reported_as_failure(self):
        doc = FakeDrawingDoc()
        doc.InsertModelAnnotations2 = lambda *a: False  # SW 拒绝，无尺寸入图
        sw, _ = self._sw(doc=doc)
        result = drawing.insert_model_dimensions(sw)
        self.assertFalse(result["success"])
        self.assertIn("no dimensions", result["message"])

    def test_com_errors_are_structured(self):
        sw = Mock()
        sw.get_active_document.side_effect = RuntimeError("COM failed")
        self.assertFalse(drawing.insert_model_dimensions(sw)["success"])


class TestExport(DrawingTestCase):
    def test_export_pdf_reports_size(self):
        sw, _ = self._sw()
        out = str(self.tmp / "out.pdf")
        _, vo, ve = self._patch_checks()
        with vo, ve:
            result = drawing.export_drawing_pdf(sw, out)
        self.assertTrue(result["success"], result)
        self.assertGreater(result["data"]["size_bytes"], 10 * 1024)

    def test_export_png_reports_resolution(self):
        sw, _ = self._sw()
        out = str(self.tmp / "out.png")
        _, vo, ve = self._patch_checks()
        with vo, ve:
            result = drawing.export_drawing_png(sw, out)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["resolution"], {"width": 1264, "height": 694})

    def test_export_rejects_wrong_extension(self):
        sw, _ = self._sw()
        _, vo, _ = self._patch_checks()
        with vo, patch(
            "solidworks_mcp.solidworks_api.drawing.ensure_sink_path",
            side_effect=lambda path: (True, "", path),
        ):
            result = drawing.export_drawing_pdf(sw, str(self.tmp / "out.txt"))
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_OUTPUT_PATH")

    def test_export_save_failure_is_reported(self):
        doc = FakeDrawingDoc()
        doc.SaveAs3 = lambda *a: 2  # 非 0 错误码
        sw, _ = self._sw(doc=doc)
        _, vo, ve = self._patch_checks()
        with vo, ve:
            result = drawing.export_drawing_pdf(sw, str(self.tmp / "bad.pdf"))
        self.assertFalse(result["success"])
        self.assertIn("code 2", result["message"])

    def test_export_requires_active_document(self):
        sw = Mock()
        sw.get_active_document.return_value = None
        _, vo, ve = self._patch_checks()
        with vo, ve:
            result = drawing.export_drawing_pdf(sw, str(self.tmp / "x.pdf"))
        self.assertFalse(result["success"])

    def test_export_png_with_bad_header_reports_null_resolution(self):
        doc = FakeDrawingDoc()

        def _save(path, *args):
            Path(path).write_bytes(b"junk-not-png")
            return 0

        doc.SaveAs3 = _save
        sw, _ = self._sw(doc=doc)
        _, vo, ve = self._patch_checks()
        with vo, ve:
            result = drawing.export_drawing_png(sw, str(self.tmp / "bad.png"))
        self.assertTrue(result["success"], result)
        self.assertIsNone(result["data"]["resolution"])

    def test_export_com_error_is_structured(self):
        doc = FakeDrawingDoc()
        doc.SaveAs3 = Mock(side_effect=RuntimeError("COM failed"))
        sw, _ = self._sw(doc=doc)
        _, vo, ve = self._patch_checks()
        with vo, ve:
            result = drawing.export_drawing_pdf(sw, str(self.tmp / "boom.pdf"))
        self.assertFalse(result["success"])
        self.assertIn("COM failed", result["message"])

    def test_export_success_without_file_is_honest(self):
        """T4 残余（2026-10-05）：SaveAs3 返回 0 但盘上无文件——SW 静默
        失败的已知形态，必须如实报错而非假装成功。"""
        doc = FakeDrawingDoc()
        doc.SaveAs3 = lambda *a: 0  # 声称成功但不写盘
        sw, _ = self._sw(doc=doc)
        _, vo, ve = self._patch_checks()
        with vo, ve:
            result = drawing.export_drawing_pdf(
                sw, str(self.tmp / "ghost.pdf")
            )
        self.assertFalse(result["success"])
        self.assertIn("no file was written", result["message"])


class TestNotRunningPaths(unittest.TestCase):
    def test_all_tools_report_not_running(self):
        from solidworks_mcp.solidworks_api.app import SolidWorksNotRunningError

        sw = Mock()
        sw.get_active_document.side_effect = SolidWorksNotRunningError("not running")
        self.assertFalse(drawing.insert_model_dimensions(sw)["success"])
        self.assertFalse(drawing.export_drawing_pdf(sw, "x.pdf")["success"])
        self.assertFalse(drawing.export_drawing_png(sw, "x.png")["success"])
        self.assertFalse(drawing.organize_dimensions(sw)["success"])
        self.assertFalse(drawing.insert_section_view(sw, "v", 0.0)["success"])
        self.assertFalse(drawing.set_tolerance(sw, "D1", 0.1, -0.05)["success"])
        self.assertFalse(
            drawing.insert_surface_finish(sw, 1.6, 100.0, 50.0)["success"]
        )
        self.assertFalse(drawing.insert_note(sw, "x", 10.0, 10.0)["success"])

    def test_bare_mock_view_walk_breaks_on_sentinel(self):
        # 视图走查遇退化代理必须立即停（Name 非 str），空结果报 SW_NO_EFFECT
        sw = Mock()
        sw.get_active_document.return_value.GetType.return_value = 3
        result = drawing.insert_model_dimensions(sw)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_NO_EFFECT")


# ---------------------------------------------------------------------------
# N4：尺寸整理 + 剖视图（探针 tools/probe_drawing/probe_dim_organize_section.py）
# 实机契约：GetNameForSelection/GetAnnotation/GetDisplayDimensions 均为零参属性；
# 删除链 = SelectByID2(选择名, "DIMENSION") → DeleteSelection(True)（带参）；
# 剖视图链 = SketchManager.CreateLine → GetActiveSketch2().Name →
# CreateSectionViewAt4(x, y, 0, 草图名, 0, 0)


class FakeAnnotation:
    def __init__(self, x, y, z):
        self._position = (x, y, z)
        self.set_calls = []

    def GetPosition(self):
        return self._position

    def SetPosition(self, x, y, z):
        self.set_calls.append((x, y, z))
        self._position = (x, y, z)
        return True


class FakeDimension:
    def __init__(self, full_name):
        self.full_name = full_name

    @property
    def FullName(self):
        return self.full_name


_dd_sequence = itertools.count(1)  # 模拟 SW 实例号（GetNameForSelection 带 -n 后缀）


class FakeNote:
    def __init__(self, text):
        self.text = text


class FakeStaticDimension:
    """模拟 makepy 静态包装后的 IDimension（动态 dispatch 下 SetTolerance* 不可调）。"""

    def __init__(self):
        self.calls = []
        self._type = 0
        self._values = None

    def SetToleranceType(self, value):
        self.calls.append(("SetToleranceType", value))
        self._type = value
        return True

    def SetToleranceValues(self, tol_min, tol_max):
        self.calls.append(("SetToleranceValues", tol_min, tol_max))
        self._values = (tol_min, tol_max)
        return True

    def GetToleranceType(self):
        return self._type

    def GetToleranceValues(self):
        return self._values


class FakeDisplayDimension:
    def __init__(self, full_name, view_name, x=0.33, y=0.19, z=-0.10):
        self.dim = FakeDimension(full_name)
        self.sel_name = f"{full_name}-{next(_dd_sequence)}@{view_name}"
        self.ann = FakeAnnotation(x, y, z)
        self.deleted = False

    def GetDimension2(self, index):
        return self.dim

    @property
    def GetNameForSelection(self):
        return self.sel_name

    @property
    def GetAnnotation(self):
        return self.ann


class DimensionedView(FakeView):
    def __init__(self, name, dims=(), x=0.15, y=0.10, z=0.0):
        super().__init__(name)
        self.dims = list(dims)
        self.position = (x, y, z)

    @property
    def GetDisplayDimensions(self):
        return tuple(d for d in self.dims if not d.deleted)

    @property
    def GetDisplayDimensionCount(self):
        return len([d for d in self.dims if not d.deleted])

    @property
    def Position(self):
        return self.position


class FakeSketchManager:
    def __init__(self, doc):
        self.doc = doc

    def CreateLine(self, x1, y1, z1, x2, y2, z2):
        self.doc.sketch_lines.append((x1, y1, z1, x2, y2, z2))
        return object()


class FakeSketch:
    def __init__(self, name):
        self.name = name

    @property
    def Name(self):
        return self.name


class TestOrganizeDimensions(DrawingTestCase):
    def _doc(self, *dimensioned_views):
        doc = FakeDrawingDoc()
        doc.views.extend(dimensioned_views)
        doc._relink()
        return doc

    def test_dedupes_duplicate_fullname_within_view(self):
        first = FakeDisplayDimension("D1@凸台-拉伸1@p.Part", "工程图视图1")
        dup = FakeDisplayDimension("D1@凸台-拉伸1@p.Part", "工程图视图1")
        other = FakeDisplayDimension("D2@草图1@p.Part", "工程图视图1")
        doc = self._doc(DimensionedView("工程图视图1", [first, dup, other]))
        sw, _ = self._sw(doc=doc)

        result = drawing.organize_dimensions(sw, mode="dedupe")

        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["deleted"], 1)
        self.assertEqual(result["data"]["total_dimensions"], 2)
        self.assertFalse(first.deleted)
        self.assertTrue(dup.deleted)
        # 删除链：SelectByID2(选择名, "DIMENSION") + DeleteSelection(True)
        self.assertIn((dup.sel_name, "DIMENSION"), doc.ext.calls)
        self.assertIn(True, doc.delete_calls)

    def test_same_fullname_across_views_is_kept(self):
        d1 = FakeDisplayDimension("D1@凸台-拉伸1@p.Part", "工程图视图1")
        d2 = FakeDisplayDimension("D1@凸台-拉伸1@p.Part", "工程图视图2")
        doc = self._doc(
            DimensionedView("工程图视图1", [d1]),
            DimensionedView("工程图视图2", [d2]),
        )
        sw, _ = self._sw(doc=doc)

        result = drawing.organize_dimensions(sw, mode="dedupe")

        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["deleted"], 0)
        self.assertFalse(d1.deleted or d2.deleted)

    def test_shift_staggers_overlapping_annotations(self):
        low = FakeDisplayDimension("D1@凸台-拉伸1@p.Part", "工程图视图1",
                                   x=0.33, y=0.190)
        near = FakeDisplayDimension("D2@草图1@p.Part", "工程图视图1",
                                    x=0.33, y=0.1905)
        doc = self._doc(DimensionedView("工程图视图1", [low, near]))
        sw, _ = self._sw(doc=doc)

        result = drawing.organize_dimensions(sw, mode="shift", shift_step_mm=8.0)

        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["moved"], 1)
        self.assertEqual(len(near.ann.set_calls), 1)
        new_x, new_y, new_z = near.ann.set_calls[0]
        self.assertAlmostEqual(new_x, 0.33)
        self.assertAlmostEqual(new_y, 0.1905 + 0.008, places=6)
        self.assertAlmostEqual(new_z, -0.10)
        self.assertEqual(low.ann.set_calls, [])

    def test_distant_annotations_are_not_shifted(self):
        a = FakeDisplayDimension("D1@f@p.Part", "工程图视图1", y=0.19)
        b = FakeDisplayDimension("D2@f@p.Part", "工程图视图1", y=0.25)
        doc = self._doc(DimensionedView("工程图视图1", [a, b]))
        sw, _ = self._sw(doc=doc)

        result = drawing.organize_dimensions(sw, mode="shift")

        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["moved"], 0)
        self.assertEqual(a.ann.set_calls + b.ann.set_calls, [])

    def test_dedupe_only_does_not_move(self):
        first = FakeDisplayDimension("D1@f@p.Part", "工程图视图1")
        dup = FakeDisplayDimension("D1@f@p.Part", "工程图视图1")
        doc = self._doc(DimensionedView("工程图视图1", [first, dup]))
        sw, _ = self._sw(doc=doc)

        result = drawing.organize_dimensions(sw, mode="dedupe")

        self.assertTrue(result["success"], result)
        self.assertEqual(first.ann.set_calls + dup.ann.set_calls, [])

    def test_view_name_scopes_operation(self):
        dup = FakeDisplayDimension("D1@f@p.Part", "工程图视图1")
        elsewhere = FakeDisplayDimension("D1@f@p.Part", "工程图视图2")
        doc = self._doc(
            DimensionedView(
                "工程图视图1",
                [FakeDisplayDimension("D1@f@p.Part", "工程图视图1"), dup],
            ),
            DimensionedView("工程图视图2", [elsewhere]),
        )
        sw, _ = self._sw(doc=doc)

        result = drawing.organize_dimensions(
            sw, view_name="工程图视图1", mode="dedupe"
        )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["deleted"], 1)
        self.assertTrue(dup.deleted)
        self.assertFalse(elsewhere.deleted)

    def test_invalid_mode_is_rejected(self):
        sw, _ = self._sw()
        result = drawing.organize_dimensions(sw, mode="bogus")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_invalid_step_is_rejected(self):
        sw, _ = self._sw()
        for step in (0.0, -5.0, 1000.0):
            result = drawing.organize_dimensions(sw, shift_step_mm=step)
            self.assertFalse(result["success"])
            self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_unknown_view_name_is_reported(self):
        sw, _ = self._sw()
        result = drawing.organize_dimensions(sw, view_name="不存在")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_rejects_non_drawing_document(self):
        sw = Mock()
        sw.get_active_document.return_value = FakePartDoc()
        result = drawing.organize_dimensions(sw)
        self.assertFalse(result["success"])
        self.assertIn("not a drawing", result["message"])


class TestInsertSectionView(DrawingTestCase):
    def _doc(self):
        doc = FakeDrawingDoc()
        doc.views.append(DimensionedView("工程图视图1", [], x=0.15, y=0.10))
        doc._relink()
        return doc

    def test_vertical_cut_creates_section_view(self):
        doc = self._doc()
        sw, _ = self._sw(doc=doc)

        result = drawing.insert_section_view(sw, "工程图视图1", 0.0, "vertical")

        self.assertTrue(result["success"], result)
        # 剖切线竖直：x1==x2==锚点 x，画在视图下方空白区 y∈[锚-0.08, 锚-0.04]
        (x1, y1, _z1, x2, y2, _z2) = doc.sketch_lines[0]
        self.assertAlmostEqual(x1, 0.15)
        self.assertAlmostEqual(x1, x2)
        self.assertAlmostEqual(y1, 0.10 - 0.08)
        self.assertAlmostEqual(y2, 0.10 - 0.04)
        # 剖视图默认放源视图右侧 120mm，用活动草图名
        self.assertEqual(doc.section_calls, [(0.15 + 0.12, 0.10, 0.0, "草图1")])
        self.assertEqual(result["data"]["view_count"], 3)
        self.assertIn("剖面视图", result["data"]["section_view"])

    def test_horizontal_cut_draws_horizontal_line(self):
        doc = self._doc()
        sw, _ = self._sw(doc=doc)

        result = drawing.insert_section_view(sw, "工程图视图1", 10.0, "horizontal")

        self.assertTrue(result["success"], result)
        (x1, y1, _z1, x2, y2, _z2) = doc.sketch_lines[0]
        self.assertAlmostEqual(y1, 0.10 + 0.010)
        self.assertAlmostEqual(y1, y2)
        self.assertAlmostEqual(x1, 0.15 - 0.08)
        self.assertAlmostEqual(x2, 0.15 - 0.04)

    def test_custom_placement_is_used(self):
        doc = self._doc()
        sw, _ = self._sw(doc=doc)

        result = drawing.insert_section_view(
            sw, "工程图视图1", 0.0, "vertical", position_xy_mm=[300.0, 200.0]
        )

        self.assertTrue(result["success"], result)
        self.assertEqual(doc.section_calls[0][:2], (0.30, 0.20))

    def test_unknown_source_view_is_rejected(self):
        sw, _ = self._sw(doc=self._doc())
        result = drawing.insert_section_view(sw, "无此视图", 0.0, "vertical")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_bad_direction_is_rejected(self):
        sw, _ = self._sw(doc=self._doc())
        result = drawing.insert_section_view(sw, "工程图视图1", 0.0, "diagonal")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_out_of_bounds_cut_position_is_rejected(self):
        sw, _ = self._sw(doc=self._doc())
        for cut in (600.0, -600.0):
            result = drawing.insert_section_view(sw, "工程图视图1", cut, "vertical")
            self.assertFalse(result["success"])
            self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_rejects_non_drawing_document(self):
        sw = Mock()
        sw.get_active_document.return_value = FakePartDoc()
        result = drawing.insert_section_view(sw, "v", 0.0, "vertical")
        self.assertFalse(result["success"])
        self.assertIn("not a drawing", result["message"])

    def test_section_view_failure_is_reported(self):
        doc = self._doc()
        doc.CreateSectionViewAt4 = lambda *a: None
        sw, _ = self._sw(doc=doc)
        result = drawing.insert_section_view(sw, "工程图视图1", 0.0, "vertical")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")


class TestSetTolerance(DrawingTestCase):
    FULL = "D1@凸台-拉伸1@probe.Part"

    def _doc(self):
        doc = FakeDrawingDoc()
        doc.views.append(DimensionedView(
            "工程图视图1",
            [FakeDisplayDimension(self.FULL, "工程图视图1")],
        ))
        doc._relink()
        return doc

    def test_sets_plus_minus_with_metre_conversion(self):
        sw, _ = self._sw(doc=self._doc())
        wrap = FakeStaticDimension()
        with patch.object(drawing, "_wrap_dimension_static", return_value=wrap):
            result = drawing.set_tolerance(sw, self.FULL, 0.10, -0.05)

        self.assertTrue(result["success"], result)
        self.assertEqual(
            wrap.calls,
            [("SetToleranceType", 5), ("SetToleranceValues", -5e-05, 1e-04)],
        )
        self.assertEqual(result["data"]["tolerance_type"], 5)
        self.assertEqual(result["data"]["tolerance_values"], (-5e-05, 1e-04))

    def test_short_dimension_name_suffix_matches(self):
        # 'D1@凸台-拉伸1'（不含零件名）也应命中 FullName
        sw, _ = self._sw(doc=self._doc())
        with patch.object(drawing, "_wrap_dimension_static",
                          return_value=FakeStaticDimension()):
            result = drawing.set_tolerance(sw, "D1@凸台-拉伸1", 0.0, 0.0)
        self.assertTrue(result["success"], result)

    def test_unknown_dimension_name_is_rejected(self):
        sw, _ = self._sw(doc=self._doc())
        result = drawing.set_tolerance(sw, "D9@无此特征", 0.1, 0.0)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_wrap_failure_is_structured_error(self):
        sw, _ = self._sw(doc=self._doc())
        with patch.object(drawing, "_wrap_dimension_static", return_value=None):
            result = drawing.set_tolerance(sw, self.FULL, 0.1, 0.0)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    def test_tolerance_bounds_are_enforced(self):
        sw, _ = self._sw()
        for upper, lower in ((500.0, 0.0), (-500.0, 0.0), (0.0, 500.0)):
            result = drawing.set_tolerance(sw, self.FULL, upper, lower)
            self.assertFalse(result["success"])
            self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_rejects_non_drawing_document(self):
        sw = Mock()
        sw.get_active_document.return_value = FakePartDoc()
        result = drawing.set_tolerance(sw, self.FULL, 0.1, 0.0)
        self.assertFalse(result["success"])
        self.assertIn("not a drawing", result["message"])

    def test_invalid_names_and_numbers_are_rejected_early(self):
        sw, _ = self._sw()
        self.assertEqual(
            drawing.set_tolerance(sw, "  ", 0.1, 0.0)["error"]["code"],
            "INVALID_PARAMETER",
        )
        self.assertEqual(
            drawing.set_tolerance(sw, "D1", "x", 0.0)["error"]["code"],
            "INVALID_PARAMETER",
        )

    def test_no_active_document_is_reported(self):
        sw = Mock()
        sw.get_active_document.return_value = None
        self.assertFalse(drawing.set_tolerance(sw, "D1", 0.1, 0.0)["success"])


class TestWrapDimensionStatic(unittest.TestCase):
    def test_returns_none_for_objects_without_oleobj(self):
        # 动态对象无 _oleobj_ 时 except 路径返回 None（不抛）
        self.assertIsNone(drawing._wrap_dimension_static(object()))


class TestInsertSurfaceFinish(DrawingTestCase):
    def _doc(self):
        doc = FakeDrawingDoc()
        doc.views.append(DimensionedView("工程图视图1", []))
        doc._relink()
        return doc

    def test_creates_remove_material_symbol(self):
        doc = self._doc()
        sw, _ = self._sw(doc=doc)

        result = drawing.insert_surface_finish(sw, 1.6, 400.0, 50.0)

        self.assertTrue(result["success"], result)
        self.assertEqual(doc.finish_calls, [(1, 0, 0.40, 0.05, 0.0, "1.6")])
        self.assertEqual(result["data"]["symbol_type"], 1)
        self.assertEqual(result["data"]["value_um"], 1.6)

    def test_symbol_type_mapping_and_unknown(self):
        sw, _ = self._sw(doc=self._doc())
        ok = drawing.insert_surface_finish(sw, 3.2, 400.0, 50.0, symbol="basic")
        self.assertTrue(ok["success"], ok)
        self.assertEqual(ok["data"]["symbol_type"], 0)
        bad = drawing.insert_surface_finish(sw, 3.2, 400.0, 50.0, symbol="bogus")
        self.assertFalse(bad["success"])
        self.assertEqual(bad["error"]["code"], "INVALID_PARAMETER")

    def test_value_and_coordinate_bounds_are_enforced(self):
        sw, _ = self._sw()
        for value in (0.0, -1.6, 400.0):
            result = drawing.insert_surface_finish(sw, value, 100.0, 50.0)
            self.assertFalse(result["success"])
            self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")
        for x, y in ((2000.0, 50.0), (100.0, -2000.0)):
            result = drawing.insert_surface_finish(sw, 1.6, x, y)
            self.assertFalse(result["success"])
            self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_sw_false_result_is_reported(self):
        doc = self._doc()
        doc.InsertSurfaceFinishSymbol = lambda *a: False
        sw, _ = self._sw(doc=doc)
        result = drawing.insert_surface_finish(sw, 1.6, 400.0, 50.0)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    def test_rejects_non_drawing_document(self):
        sw = Mock()
        sw.get_active_document.return_value = FakePartDoc()
        result = drawing.insert_surface_finish(sw, 1.6, 100.0, 50.0)
        self.assertFalse(result["success"])
        self.assertIn("not a drawing", result["message"])

    def test_non_numeric_and_no_document_paths(self):
        sw, _ = self._sw()
        self.assertEqual(
            drawing.insert_surface_finish(sw, "x", 1.0, 1.0)["error"]["code"],
            "INVALID_PARAMETER",
        )
        idle = Mock()
        idle.get_active_document.return_value = None
        self.assertFalse(drawing.insert_surface_finish(idle, 1.6, 100.0, 50.0)["success"])


class TestInsertNote(DrawingTestCase):
    TEXT = "技术要求：未注公差按 GB/T 1804-m。"

    def _doc(self):
        doc = FakeDrawingDoc()
        doc.views.append(DimensionedView("工程图视图1", []))
        doc._relink()
        return doc

    def test_creates_note_with_sheet_mm(self):
        doc = self._doc()
        sw, _ = self._sw(doc=doc)

        result = drawing.insert_note(sw, self.TEXT, 50.0, 30.0)

        self.assertTrue(result["success"], result)
        self.assertEqual(
            doc.text_calls, [(self.TEXT, 0.05, 0.03, 0.0, 0.003, 0.003)]
        )
        self.assertIn("note", result["data"])

    def test_empty_text_is_rejected(self):
        sw, _ = self._sw()
        result = drawing.insert_note(sw, "  ", 50.0, 30.0)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_coordinate_bounds_are_enforced(self):
        sw, _ = self._sw()
        for x, y in ((2000.0, 30.0), (50.0, -2000.0)):
            result = drawing.insert_note(sw, self.TEXT, x, y)
            self.assertFalse(result["success"])
            self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_sw_none_result_is_reported(self):
        doc = self._doc()
        doc.CreateText2 = lambda *a: None
        sw, _ = self._sw(doc=doc)
        result = drawing.insert_note(sw, self.TEXT, 50.0, 30.0)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    def test_rejects_non_drawing_document(self):
        sw = Mock()
        sw.get_active_document.return_value = FakePartDoc()
        result = drawing.insert_note(sw, "x", 50.0, 30.0)
        self.assertFalse(result["success"])
        self.assertIn("not a drawing", result["message"])

    def test_non_numeric_and_no_document_paths(self):
        sw, _ = self._sw()
        self.assertEqual(
            drawing.insert_note(sw, "text", "a", 1.0)["error"]["code"],
            "INVALID_PARAMETER",
        )
        idle = Mock()
        idle.get_active_document.return_value = None
        self.assertFalse(drawing.insert_note(idle, "x", 10.0, 10.0)["success"])


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# N52：形位公差框格（GD&T）——契约（typelib 取证 2026-09-10）：
# IDrawingDoc.NewGtol() 零参工厂 → IGtol；SetFrameSymbols2（9 参标量）+
# SetFrameValues2（6 参字符串）+ SetPosition（米）；判据 = GetFrameCount
# 零参属性；NewGtol 静默 None = AutoBalloon 同族风险，fakes 覆盖诚实失败。


class FakeGtol:
    def __init__(self):
        self.symbol_calls = []
        self.value_calls = []
        self.position = None

    def SetFrameSymbols2(self, *args):
        self.symbol_calls.append(args)
        return True

    def SetFrameValues2(self, *args):
        self.value_calls.append(args)
        return True

    def SetPosition(self, x, y, z):
        self.position = (x, y, z)
        return True

    @property
    def GetFrameCount(self):
        return 1


class TestInsertGtol(DrawingTestCase):
    def _doc(self, gtol):
        doc = FakeDrawingDoc()
        doc.NewGtol = Mock(return_value=gtol)
        return doc

    def test_flatness_gtol_success(self):
        doc = self._doc(FakeGtol())
        sw, _ = self._sw(doc=doc)
        result = drawing.insert_gtol(sw, "flatness", 0.05, 120.0, 60.0)
        self.assertTrue(result["success"], result)
        gtol = doc.NewGtol.return_value
        self.assertEqual(gtol.symbol_calls[0][1], 15)  # swGcsFLAT
        self.assertEqual(gtol.value_calls[0][1], "0.05")  # Tol1 槽
        self.assertAlmostEqual(gtol.position[0], 0.12)
        self.assertEqual(result["data"]["frames"], 1)

    def test_position_gtol_with_datums_and_modifiers(self):
        doc = self._doc(FakeGtol())
        sw, _ = self._sw(doc=doc)
        result = drawing.insert_gtol(
            sw, "position", 0.1, 100.0, 50.0,
            diameter=True, material_condition="mmc",
            datum_a="A", datum_b="B",
        )
        self.assertTrue(result["success"], result)
        gtol = doc.NewGtol.return_value
        self.assertEqual(gtol.symbol_calls[0][1], 23)  # swGcsPOSITION
        self.assertIs(gtol.symbol_calls[0][2], True)   # TolDia1（直径修饰）
        self.assertEqual(gtol.symbol_calls[0][3], 1)   # swMcMMC
        self.assertEqual(gtol.value_calls[0][3], "A")  # Datum1 槽
        self.assertEqual(gtol.value_calls[0][4], "B")  # Datum2 槽

    def test_invalid_characteristic_rejected(self):
        sw, _ = self._sw(doc=self._doc(FakeGtol()))
        result = drawing.insert_gtol(sw, "bogus", 0.05, 0.0, 0.0)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_invalid_material_condition_rejected(self):
        sw, _ = self._sw(doc=self._doc(FakeGtol()))
        result = drawing.insert_gtol(
            sw, "flatness", 0.05, 0.0, 0.0, material_condition="bogus"
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_nonpositive_tolerance_rejected(self):
        sw, _ = self._sw(doc=self._doc(FakeGtol()))
        self.assertFalse(drawing.insert_gtol(sw, "flatness", 0.0, 0, 0)["success"])
        self.assertFalse(drawing.insert_gtol(sw, "flatness", -1.0, 0, 0)["success"])

    def test_new_gtol_none_is_honest_failure(self):
        sw, _ = self._sw(doc=self._doc(gtol=None))
        result = drawing.insert_gtol(sw, "flatness", 0.05, 0.0, 0.0)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    def test_zero_frame_count_is_no_effect(self):
        class EmptyGtol(FakeGtol):
            @property
            def GetFrameCount(self):
                return 0

        sw, _ = self._sw(doc=self._doc(EmptyGtol()))
        result = drawing.insert_gtol(sw, "flatness", 0.05, 0.0, 0.0)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_NO_EFFECT")

    def test_not_a_drawing_document(self):
        part_doc = Mock()
        part_doc.GetType = 1  # swDocPART
        sw = Mock()
        sw.get_active_document.return_value = part_doc
        result = drawing.insert_gtol(sw, "flatness", 0.05, 0.0, 0.0)
        self.assertFalse(result["success"])

    def test_new_gtol_dynamic_failure_falls_back_to_typed(self):
        """N57 批次 A 实机契约：dynamic dispatch 上 NewGtol 报
        DISP_E_MEMBERNOTFOUND（成员面受限）——生产工具必须走 typed
        IDrawingDoc 兜底，fakes 用 monkeypatch gencache 钉住该路径。"""
        import pywintypes

        class FakeTypedDrawing:
            def NewGtol(self):
                return FakeGtol()

        class FakeGenModule:
            @staticmethod
            def IDrawingDoc(oleobj):
                return FakeTypedDrawing()

        doc = FakeDrawingDoc()
        doc.NewGtol = Mock(side_effect=pywintypes.com_error(
            (-2147352573, "找不到成员。", None, None)
        ))
        doc._oleobj_ = object()
        sw, _ = self._sw(doc=doc)
        with patch(
            "win32com.client.gencache.GetModuleForProgID",
            return_value=FakeGenModule,
        ):
            result = drawing.insert_gtol(sw, "flatness", 0.05, 0.0, 0.0)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["frames"], 1)

    def test_gtol_non_numeric_inputs_rejected(self):
        """R4（2026-10-05）：tolerance/x/y 非数值 → INVALID_PARAMETER。"""
        sw, _ = self._sw(doc=self._doc(FakeGtol()))
        result = drawing.insert_gtol(sw, "flatness", "thick", 0.0, 0.0)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_gtol_sheet_coord_overflow_rejected(self):
        """R4：x/y 超出可打印幅面 → INVALID_PARAMETER（防误置框外）。"""
        sw, _ = self._sw(doc=self._doc(FakeGtol()))
        result = drawing.insert_gtol(sw, "flatness", 0.05, 1e9, 0.0)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_gtol_no_active_document(self):
        """R4：无活动文档 → 结构化错误（不裸崩）。"""
        idle = Mock()
        idle.get_active_document.return_value = None
        result = drawing.insert_gtol(idle, "flatness", 0.05, 0.0, 0.0)
        self.assertFalse(result["success"])

    def test_gtol_unexpected_exception_is_structured(self):
        """R4：NewGtol 抛非 COM 异常 → 兜底 except 结构化返回。"""
        doc = FakeDrawingDoc()
        doc.NewGtol = Mock(side_effect=RuntimeError("ui exploded"))
        sw, _ = self._sw(doc=doc)
        with patch(
            "win32com.client.gencache.GetModuleForProgID",
            side_effect=RuntimeError("gencache unavailable"),
        ):
            result = drawing.insert_gtol(sw, "flatness", 0.05, 0.0, 0.0)
        self.assertFalse(result["success"])
        self.assertIn("Failed to insert GD&T frame", result["message"])
