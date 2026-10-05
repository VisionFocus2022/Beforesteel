"""Assembly creation, component, mate, and inspection tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from solidworks_mcp.solidworks_api.app import SolidWorksNotRunningError
from solidworks_mcp.solidworks_api.assembly import (
    _get_or_create_assembly,
    add_component,
    add_mate,
    delete_mate,
    get_components,
    move_component,
    rotate_component,
)


class TestAssemblyCreation(unittest.TestCase):
    def test_reuses_active_assembly(self):
        model = Mock()
        model.GetType.return_value = 2
        sw = Mock()
        sw.get_active_document.return_value = model
        self.assertIs(_get_or_create_assembly(sw), model)

    @patch("solidworks_mcp.solidworks_api.assembly.get_assembly_template", return_value="assembly.asmdot")
    def test_creates_assembly_from_template(self, _template):
        created = Mock()
        sw = Mock()
        sw.get_active_document.return_value = None
        sw.app.NewDocument.return_value = created
        self.assertIs(_get_or_create_assembly(sw), created)

    @patch("solidworks_mcp.solidworks_api.assembly.get_assembly_template", return_value=None)
    def test_missing_template_raises(self, _template):
        sw = Mock()
        sw.get_active_document.return_value = None
        with self.assertRaises(RuntimeError):
            _get_or_create_assembly(sw)

    @patch("solidworks_mcp.solidworks_api.assembly.get_assembly_template", return_value="assembly.asmdot")
    def test_new_document_none_raises(self, _template):
        sw = Mock()
        sw.get_active_document.return_value = None
        sw.app.NewDocument.return_value = None
        with self.assertRaises(RuntimeError):
            _get_or_create_assembly(sw)


class TestComponentOperations(unittest.TestCase):
    @patch("solidworks_mcp.solidworks_api.assembly.validate_path", return_value=(False, "unsafe"))
    def test_rejects_invalid_path(self, _path):
        self.assertEqual(add_component(Mock(), "bad.sldprt")["message"], "unsafe")

    @patch("solidworks_mcp.solidworks_api.assembly.validate_extension", return_value=(False, "wrong type"))
    @patch("solidworks_mcp.solidworks_api.assembly.validate_path", return_value=(True, ""))
    def test_rejects_invalid_extension(self, _path, _extension):
        result = add_component(Mock(), "bad.txt")
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    @patch("solidworks_mcp.solidworks_api.assembly._get_or_create_assembly")
    @patch("solidworks_mcp.solidworks_api.assembly.validate_extension", return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.assembly.validate_path", return_value=(True, ""))
    def test_adds_component_with_meter_coordinates(self, _path, _extension, get_assembly):
        model = Mock()
        model.AddComponent4.return_value = SimpleNamespace(Name2="Part1-1")
        get_assembly.return_value = model
        result = add_component(Mock(), "part.sldprt", 10, 20, 30, "Default")
        self.assertTrue(result["success"])
        model.AddComponent4.assert_called_once_with("part.sldprt", "Default", 0.01, 0.02, 0.03)

    @patch("solidworks_mcp.solidworks_api.assembly._get_or_create_assembly")
    @patch("solidworks_mcp.solidworks_api.assembly.validate_extension", return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.assembly.validate_path", return_value=(True, ""))
    def test_reports_component_insertion_failure(self, _path, _extension, get_assembly):
        get_assembly.return_value.AddComponent4.return_value = None
        self.assertFalse(add_component(Mock(), "part.sldprt")["success"])


class TestMateAndComponents(unittest.TestCase):
    def test_mate_requires_active_assembly_and_supported_type(self):
        sw = Mock()
        sw.get_active_document.return_value = None
        self.assertFalse(add_mate(sw, "coincident", "A", "B")["success"])
        model = Mock()
        model.GetType.return_value = 2
        sw.get_active_document.return_value = model
        self.assertIn("Unsupported", add_mate(sw, "gear", "A", "B")["message"])

    def test_distance_mate_validates_distance(self):
        model = Mock()
        model.GetType.return_value = 2
        sw = Mock()
        sw.get_active_document.return_value = model
        self.assertEqual(add_mate(sw, "distance", "A", "B")["error"]["code"], "INVALID_PARAMETER")
        self.assertEqual(add_mate(sw, "distance", "A", "B", -1)["error"]["code"], "INVALID_PARAMETER")
        self.assertEqual(add_mate(sw, "distance", "A", "B", float("nan"))["error"]["code"], "INVALID_PARAMETER")

    @patch("solidworks_mcp.solidworks_api.assembly.win32com.client.VARIANT")
    def test_selection_and_mate_failures_are_structured(self, variant):
        variant.return_value = SimpleNamespace(value=7)
        model = Mock()
        model.GetType.return_value = 2
        model.GetTitle.return_value = "Assembly1"
        model.Extension.SelectByID2.return_value = False
        sw = Mock()
        sw.get_active_document.return_value = model
        self.assertIn("select", add_mate(sw, "coincident", "A", "B")["message"])
        model.Extension.SelectByID2.return_value = True
        model.AddMate5.return_value = None
        result = add_mate(sw, "coincident", "A", "B", entity1_type="FACE", entity2_type="FACE")
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    def test_get_components_success_empty_and_wrong_document(self):
        sw = Mock()
        sw.get_active_document.return_value = None
        self.assertFalse(get_components(sw)["success"])
        model = Mock()
        model.GetType.return_value = 2
        model.GetComponents.return_value = [SimpleNamespace(Name2="A-1"), SimpleNamespace(Name2="B-1")]
        sw.get_active_document.return_value = model
        self.assertEqual(get_components(sw)["data"]["components"], ["A-1", "B-1"])
        model.GetComponents.return_value = None
        self.assertEqual(get_components(sw)["data"]["count"], 0)

    def test_com_errors_are_structured(self):
        sw = Mock()
        sw.get_active_document.side_effect = RuntimeError("COM")
        self.assertFalse(add_mate(sw, "coincident", "A", "B")["success"])
        self.assertFalse(get_components(sw)["success"])


# --- T11：新建装配 / 组件预开 / mate 扩展与选择顺序 / 干涉 / BOM ---

from solidworks_mcp.solidworks_api.assembly import (  # noqa: E402
    check_interference,
    get_bom,
    new_assembly,
)
from solidworks_mcp.solidworks_api.constants import (  # noqa: E402
    swMateANGLE,
    swMateTANGENT,
    swMateWIDTH,
)


class FakeExtension:
    def __init__(self, accepted_suffix, mates=None):
        self.calls = []
        self.accepted_suffix = accepted_suffix
        # 共享 list 引用：EditDelete 移除即同步（实机语义）
        self.mates = mates if mates is not None else []
        self.reject_mates = False

    def SelectByID2(self, name, type_, x, y, z, append, mark, callout, option):
        self.calls.append((name, type_, append))
        if type_ == "MATE":
            return not self.reject_mates and name in self.mates
        return name.endswith(self.accepted_suffix)


class FakeInterference:
    def __init__(self, volume_m3, comp_names, body=None):
        self._volume_m3 = volume_m3
        self._comp_names = comp_names
        self._body = body

    @property
    def Volume(self):
        return self._volume_m3

    @property
    def Components(self):
        return [SimpleNamespace(Name2=n) for n in self._comp_names]

    def GetInterferenceBody(self):
        return self._body


class FakeInterferenceBody:
    """探针真值形态：干涉体包围盒（米）与质量属性 12 值。"""

    def GetBodyBox(self):
        return [-0.02, -0.02, -0.01, 0.03, 0.02, 0.01]

    def GetMassProperties(self, _density):
        return [0.005, 0.0, 0.0, 4e-05, 8.8e-3, 0.04,
                0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


class FakeBomBody:
    """GetMassProperties(density)：[3]=体积 m³，[5]=体积×density（kg）。"""

    def __init__(self, volume_m3):
        self._volume_m3 = volume_m3

    def GetMassProperties(self, density):
        return [0.005, 0.0, 0.0, self._volume_m3, 8.8e-3,
                self._volume_m3 * density, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


class FakeInterferenceMgr:
    def __init__(self, interferences):
        self._inters = interferences
        self.TreatCoincidenceAsInterference = True

    @property
    def GetInterferences(self):
        return self._inters


class FakeFeature:
    """树特征：顶层 walk + 一层子特征（mate 藏在 MateGroup 里，N8 探针）。"""

    def __init__(self, name, type_name, subs=None, next_feat=None):
        self._name = name
        self._type = type_name
        self._subs = subs or []
        self._next = next_feat
        self._sub_pos = -1

    @property
    def Name(self):
        return self._name

    @property
    def GetTypeName2(self):
        return self._type

    def GetFirstSubFeature(self):
        self._sub_pos = 0
        return self._subs[0] if self._subs else None

    def GetNextSubFeature(self):
        self._sub_pos += 1
        if self._sub_pos < len(self._subs):
            return self._subs[self._sub_pos]
        return None

    def GetNextFeature(self):
        return self._next


class FakeAsmDoc:
    """实机形态：零参成员是属性；GetTitle='装配体1'；干涉经 Mgr。"""

    def __init__(self, comps=None, interferences=None, mates=None):
        self.comps = comps or []
        self.mgr = FakeInterferenceMgr(interferences or [])
        self.mates = list(mates or [])
        self.ext = FakeExtension("@装配体1", mates=self.mates)
        self.add_mate_calls = []
        self.save_calls = []
        self.rebuild_count = 0

    @property
    def GetType(self):
        return 2

    @property
    def GetTitle(self):
        return "装配体1"

    @property
    def InterferenceDetectionManager(self):
        return self.mgr

    @property
    def Extension(self):
        return self.ext

    def GetComponents(self, _toplevel):
        return self.comps

    def ClearSelection2(self, _all):
        return None

    def AddMate5(self, *args):
        self.add_mate_calls.append(args)
        return SimpleNamespace(Name="重合1")

    def SaveAs3(self, path, version, options):
        self.save_calls.append(path)
        return 0

    @property
    def FirstFeature(self):
        subs = [FakeFeature(name, "MateCoincident") for name in self.mates]
        return FakeFeature("配合", "MateGroup", subs=subs)

    def EditDelete(self):
        for name, type_, _append in reversed(self.ext.calls):
            if type_ == "MATE" and name in self.mates:
                self.mates.remove(name)
                return True
        return False

    def EditRebuild3(self):
        self.rebuild_count += 1
        return True


def _asm_sw(doc):
    sw = Mock()
    sw.get_active_document.return_value = doc
    return sw


class TestNewAssembly(unittest.TestCase):
    @patch("solidworks_mcp.solidworks_api.assembly.get_assembly_template",
           return_value="gb.asmdot")
    def test_creates_and_reports(self, _tpl):
        doc = FakeAsmDoc()
        sw = Mock()
        sw.app.NewDocument.return_value = doc
        result = new_assembly(sw)
        self.assertTrue(result["success"], result)
        sw.app.NewDocument.assert_called_once_with("gb.asmdot", 0, 0, 0)
        self.assertEqual(result["data"]["title"], "装配体1")
        self.assertEqual(result["data"]["type"], 2)

    @patch("solidworks_mcp.solidworks_api.assembly.get_assembly_template",
           return_value=None)
    def test_missing_template(self, _tpl):
        result = new_assembly(Mock())
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "TEMPLATE_NOT_FOUND")

    @patch("solidworks_mcp.solidworks_api.assembly.get_assembly_template",
           return_value="gb.asmdot")
    def test_new_document_failure(self, _tpl):
        sw = Mock()
        sw.app.NewDocument.return_value = None
        result = new_assembly(sw)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    @patch("solidworks_mcp.solidworks_api.assembly.ensure_sink_path",
           side_effect=lambda path: (True, "", path))
    @patch("solidworks_mcp.solidworks_api.assembly.validate_output_file",
           return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.assembly.get_assembly_template",
           return_value="gb.asmdot")
    def test_save_path_uses_saveas3(self, _tpl, _vo, _es):
        doc = FakeAsmDoc()
        sw = Mock()
        sw.app.NewDocument.return_value = doc
        result = new_assembly(sw, save_path="asm1.SLDASM")
        self.assertTrue(result["success"], result)
        self.assertEqual(doc.save_calls, ["asm1.SLDASM"])
        self.assertEqual(result["data"]["saved_path"], "asm1.SLDASM")


class TestComponentPreopen(unittest.TestCase):
    @patch("solidworks_mcp.solidworks_api.assembly._get_or_create_assembly")
    @patch("solidworks_mcp.solidworks_api.assembly.validate_extension",
           return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.assembly.validate_path",
           return_value=(True, ""))
    def test_preopens_part_before_add(self, _path, _ext, get_asm):
        # 实机铁律：零件未在会话中打开时 AddComponent4 静默返回 None
        model = Mock()
        model.AddComponent4.return_value = SimpleNamespace(Name2="P-1")
        get_asm.return_value = model
        sw = Mock()
        sw.app.OpenDoc6.return_value = "opened"
        result = add_component(sw, "part.sldprt")
        self.assertTrue(result["success"])
        sw.app.OpenDoc6.assert_called_once()
        self.assertLess(
            sw.app.OpenDoc6.call_count,
            2,
        )

    @patch("solidworks_mcp.solidworks_api.assembly._get_or_create_assembly")
    @patch("solidworks_mcp.solidworks_api.assembly.validate_extension",
           return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.assembly.validate_path",
           return_value=(True, ""))
    def test_closes_preopen_when_add_fails(self, _path, _ext, get_asm):
        # N10：AddComponent4 失败时预开文档无引用持有 → 必须关闭防滞留。
        # 实机证据（probe_n10_asmclose）：一旦插入成功，装配体持有文档，
        # CloseDoc 被静默忽略；只有失败路径的关闭是可行的。
        model = Mock()
        model.AddComponent4.return_value = None
        get_asm.return_value = model
        sw = Mock()
        sw.app.OpenDoc6.return_value = "opened"
        sw.app.GetOpenDocumentByName.return_value = None
        result = add_component(sw, "part.sldprt")
        self.assertFalse(result["success"])
        sw.app.CloseDoc.assert_called_once_with("part.sldprt")

    @patch("solidworks_mcp.solidworks_api.assembly._get_or_create_assembly")
    @patch("solidworks_mcp.solidworks_api.assembly.validate_extension",
           return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.assembly.validate_path",
           return_value=(True, ""))
    def test_keeps_part_open_after_successful_add(self, _path, _ext, get_asm):
        # 成功插入后装配体持有零件文档（SW 装配语义，CloseDoc 静默无效，
        # 实机 count 3→3 证据）→ 不得调用 CloseDoc（调了也无效果且冗余）
        model = Mock()
        model.AddComponent4.return_value = SimpleNamespace(Name2="P-1")
        get_asm.return_value = model
        sw = Mock()
        sw.app.OpenDoc6.return_value = "opened"
        sw.app.GetOpenDocumentByName.return_value = None
        result = add_component(sw, "part.sldprt")
        self.assertTrue(result["success"])
        sw.app.CloseDoc.assert_not_called()

    @patch("solidworks_mcp.solidworks_api.assembly._get_or_create_assembly")
    @patch("solidworks_mcp.solidworks_api.assembly.validate_extension",
           return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.assembly.validate_path",
           return_value=(True, ""))
    def test_keeps_user_opened_part_document(self, _path, _ext, get_asm):
        # 文档是用户先前打开的（非本次预开）→ 即使添加失败也不得关闭
        model = Mock()
        model.AddComponent4.return_value = None
        get_asm.return_value = model
        sw = Mock()
        sw.app.OpenDoc6.return_value = "opened"
        sw.app.GetOpenDocumentByName.return_value = Mock()
        result = add_component(sw, "part.sldprt")
        self.assertFalse(result["success"])
        sw.app.CloseDoc.assert_not_called()


class TestMateExtension(unittest.TestCase):
    def test_constants_match_swconst_values(self):
        self.assertEqual((swMateTANGENT, swMateANGLE, swMateWIDTH), (4, 6, 17))

    def test_title_qualified_name_is_tried_first(self):
        # 实机：裸名选择形态误选导致 AddMate5 None；@装配体标题 全限定先试
        doc = FakeAsmDoc()
        sw = _asm_sw(doc)
        result = add_mate(sw, "coincident", "前视基准面@P1-1", "前视基准面@P2-1",
                          entity1_type="PLANE", entity2_type="PLANE")
        self.assertTrue(result["success"], result)
        first, second = doc.ext.calls[0], doc.ext.calls[1]
        self.assertEqual(first[0], "前视基准面@P1-1@装配体1")
        self.assertEqual(second[0], "前视基准面@P2-1@装配体1")

    def test_second_selection_appends(self):
        doc = FakeAsmDoc()
        sw = _asm_sw(doc)
        add_mate(sw, "coincident", "前视基准面@P1-1", "前视基准面@P2-1",
                 entity1_type="PLANE", entity2_type="PLANE")
        self.assertFalse(doc.ext.calls[0][2])
        self.assertTrue(doc.ext.calls[1][2])

    def test_angle_mate_uses_angle_slot_in_radians(self):
        # 实机：角度必须走 AddMate5 第 10 参 Angle 槽（度→弧度），Distance 槽置 0
        import math

        doc = FakeAsmDoc()
        sw = _asm_sw(doc)
        result = add_mate(sw, "angle", "右视基准面@P1-1", "右视基准面@P2-1",
                          distance=30.0,
                          entity1_type="PLANE", entity2_type="PLANE")
        self.assertTrue(result["success"], result)
        args = doc.add_mate_calls[0]
        self.assertEqual(args[0], swMateANGLE)
        self.assertEqual(args[3], 0.0)  # Distance 槽
        self.assertAlmostEqual(args[8], math.radians(30.0))  # Angle 槽

    def test_tangent_and_width_are_mapped(self):
        doc = FakeAsmDoc()
        sw = _asm_sw(doc)
        add_mate(sw, "tangent", "Face0@P1-1", "Face1@P2-1",
                 entity1_type="FACE", entity2_type="FACE")
        add_mate(sw, "width", "上视基准面@P1-1", "上视基准面@P2-1",
                 entity1_type="PLANE", entity2_type="PLANE")
        self.assertEqual(doc.add_mate_calls[0][0], swMateTANGENT)
        self.assertEqual(doc.add_mate_calls[1][0], swMateWIDTH)


class TestInterference(unittest.TestCase):
    def test_aggregates_volumes_and_components(self):
        doc = FakeAsmDoc(interferences=[
            FakeInterference(4e-05, ["box-1", "box-2"]),
        ])
        result = check_interference(_asm_sw(doc))
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["interference_count"], 1)
        self.assertTrue(result["data"]["has_interference"])
        self.assertEqual(result["data"]["interferences"][0]["volume_mm3"], 40000.0)
        self.assertEqual(result["data"]["interferences"][0]["components"],
                         ["box-1", "box-2"])
        self.assertFalse(doc.mgr.TreatCoincidenceAsInterference)

    def test_no_interference_is_success(self):
        result = check_interference(_asm_sw(FakeAsmDoc()))
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["interference_count"], 0)
        self.assertFalse(result["data"]["has_interference"])

    def test_requires_assembly_document(self):
        sw = Mock()
        sw.get_active_document.return_value = None
        self.assertFalse(check_interference(sw)["success"])


class TestBom(unittest.TestCase):
    def test_aggregates_same_part_instances(self):
        doc = FakeAsmDoc(comps=[
            SimpleNamespace(Name2="box-1", GetPathName=lambda: "e:/a/box.SLDPRT",
                            ReferencedConfiguration=lambda: "默认"),
            SimpleNamespace(Name2="box-2", GetPathName=lambda: "e:/a/box.SLDPRT",
                            ReferencedConfiguration=lambda: "默认"),
            SimpleNamespace(Name2="cyl-1", GetPathName=lambda: "e:/a/cyl.SLDPRT",
                            ReferencedConfiguration=lambda: "默认"),
        ])
        # 零参属性在实机是属性；此处 fake 用可调用形态验证 call_or_value 双兼容
        result = get_bom(_asm_sw(doc))
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["total_components"], 3)
        self.assertEqual(result["data"]["unique_parts"], 2)
        by_name = {i["name"]: i for i in result["data"]["items"]}
        self.assertEqual(by_name["box"]["count"], 2)
        self.assertEqual(by_name["cyl"]["count"], 1)
        self.assertEqual(by_name["box"]["configuration"], "默认")

    def test_requires_assembly_document(self):
        sw = Mock()
        sw.get_active_document.return_value = None
        self.assertFalse(get_bom(sw)["success"])

    def test_com_errors_are_structured(self):
        sw = Mock()
        sw.get_active_document.side_effect = RuntimeError("COM")
        self.assertFalse(check_interference(sw)["success"])
        self.assertFalse(get_bom(sw)["success"])


class TestT11ErrorBranches(unittest.TestCase):
    @patch("solidworks_mcp.solidworks_api.assembly.ensure_sink_path",
           side_effect=lambda path: (True, "", path))
    @patch("solidworks_mcp.solidworks_api.assembly.validate_output_file",
           return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.assembly.get_assembly_template",
           return_value="gb.asmdot")
    def test_new_assembly_save_failure(self, _tpl, _vo, _es):
        doc = FakeAsmDoc()
        doc.SaveAs3 = lambda *a: 2
        sw = Mock()
        sw.app.NewDocument.return_value = doc
        result = new_assembly(sw, save_path="x.SLDASM")
        self.assertFalse(result["success"])
        self.assertIn("code 2", result["message"])

    @patch("solidworks_mcp.solidworks_api.assembly.validate_output_file",
           return_value=(False, "outside root"))
    @patch("solidworks_mcp.solidworks_api.assembly.get_assembly_template",
           return_value="gb.asmdot")
    def test_new_assembly_bad_output_path(self, _tpl, _vo):
        sw = Mock()
        sw.app.NewDocument.return_value = FakeAsmDoc()
        result = new_assembly(sw, save_path="x.SLDASM")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_OUTPUT_PATH")

    @patch("solidworks_mcp.solidworks_api.assembly._get_or_create_assembly")
    @patch("solidworks_mcp.solidworks_api.assembly.validate_extension",
           return_value=(True, ""))
    @patch("solidworks_mcp.solidworks_api.assembly.validate_path",
           return_value=(True, ""))
    def test_add_component_preopen_failure(self, _path, _ext, get_asm):
        sw = Mock()
        sw.app.OpenDoc6.return_value = None
        result = add_component(sw, "locked.sldprt")
        self.assertFalse(result["success"])
        self.assertIn("AddComponent4 requires", result["message"])
        # N32 fix: the assembly is now resolved BEFORE the pre-open (the
        # pre-open switches the active document), so this call is expected.
        get_asm.assert_called_once()

    def test_check_interference_detector_missing(self):
        class NoDetectorAsm(FakeAsmDoc):
            @property
            def InterferenceDetectionManager(self):
                return None

        result = check_interference(_asm_sw(NoDetectorAsm()))
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    def test_mate_unhandled_com_error_is_structured(self):
        sw = Mock()
        sw.get_active_document.return_value = None
        self.assertFalse(
            add_mate(sw, "coincident", "A", "B")["success"]
        )


# --- N8：干涉空间定位 / delete_mate / 组件变换 / BOM 扩列 ---

IDENTITY_XFORM = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]


def _movable_comp(name="box-1"):
    return SimpleNamespace(
        Name2=name,
        GetTotalTransform=Mock(
            return_value=SimpleNamespace(ArrayData=list(IDENTITY_XFORM))
        ),
        SetTransformAndSolve3=Mock(return_value=True),
    )


def _math_sw(doc, comp):
    sw = _asm_sw(doc)
    if comp is not None:
        doc.comps = [comp]
    mu = Mock()
    mu.CreateTransform.return_value = object()
    sw.app.GetMathUtility.return_value = mu
    return sw, mu


class TestInterferenceSpatial(unittest.TestCase):
    def test_row_carries_center_and_bbox_mm(self):
        # 探针真值：60×40×20 盒重叠干涉体的 GetBodyBox/GetMassProperties 形态
        doc = FakeAsmDoc(interferences=[
            FakeInterference(4e-05, ["box-1", "box-2"], body=FakeInterferenceBody()),
        ])
        row = check_interference(_asm_sw(doc))["data"]["interferences"][0]
        self.assertEqual(row["center_mm"], [5.0, 0.0, 0.0])
        self.assertEqual(row["bbox_mm"], [-20.0, -20.0, -10.0, 30.0, 20.0, 10.0])

    def test_row_without_body_reports_nulls(self):
        doc = FakeAsmDoc(interferences=[FakeInterference(4e-05, ["a-1", "a-2"])])
        row = check_interference(_asm_sw(doc))["data"]["interferences"][0]
        self.assertIsNone(row["center_mm"])
        self.assertIsNone(row["bbox_mm"])


class TestDeleteMate(unittest.TestCase):
    def test_deletes_mate_selected_as_mate_type(self):
        # 实机：SelectByID2(name, "MATE") 唯一可用类型；复检树复必含 MateGroup 子树
        doc = FakeAsmDoc(mates=["重合1"])
        result = delete_mate(_asm_sw(doc), "重合1")
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["deleted"], "重合1")
        self.assertEqual(doc.ext.calls[-1][1], "MATE")
        self.assertEqual(doc.mates, [])

    def test_mate_not_found_is_structured(self):
        result = delete_mate(_asm_sw(FakeAsmDoc(mates=["距离1"])), "重合1")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "MATE_NOT_FOUND")

    def test_selection_refusal_is_sw_error(self):
        doc = FakeAsmDoc(mates=["重合1"])
        doc.ext.reject_mates = True
        result = delete_mate(_asm_sw(doc), "重合1")
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    def test_delete_rejected_by_tree_recheck(self):
        doc = FakeAsmDoc(mates=["重合1"])
        doc.EditDelete = lambda: False  # SW 拒删：mate 仍在树
        result = delete_mate(_asm_sw(doc), "重合1")
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    def test_requires_assembly_document(self):
        sw = Mock()
        sw.get_active_document.return_value = None
        self.assertFalse(delete_mate(sw, "重合1")["success"])


class TestComponentTransform(unittest.TestCase):
    @patch("solidworks_mcp.solidworks_api.assembly.win32com.client.VARIANT",
           side_effect=lambda vt, data: data)
    def test_move_translates_and_rebuilds(self, _variant):
        # 探针：16 元素 VARIANT（13 元素不生效）；SetTransformAndSolve3 替换式
        # → 先读当前 GetTotalTransform，平移叠加；EditRebuild3 后干涉才更新
        comp = _movable_comp()
        sw, mu = _math_sw(FakeAsmDoc(), comp)
        result = move_component(sw, "box-1", 10, 20, 30)
        self.assertTrue(result["success"], result)
        data = mu.CreateTransform.call_args[0][0]
        self.assertEqual(len(data), 16)
        self.assertEqual(data[9:12], [0.01, 0.02, 0.03])  # mm→m 叠加在当前平移
        self.assertEqual(data[0:9], [1, 0, 0, 0, 1, 0, 0, 0, 1])
        comp.SetTransformAndSolve3.assert_called_once_with(
            mu.CreateTransform.return_value, True)
        self.assertEqual(sw.get_active_document().rebuild_count, 1)

    @patch("solidworks_mcp.solidworks_api.assembly.win32com.client.VARIANT",
           side_effect=lambda vt, data: data)
    def test_rotate_about_world_z(self, _variant):
        comp = _movable_comp()
        sw, mu = _math_sw(FakeAsmDoc(), comp)
        result = rotate_component(sw, "box-1", "z", 90.0)
        self.assertTrue(result["success"], result)
        data = mu.CreateTransform.call_args[0][0]
        self.assertEqual([round(v, 9) for v in data[0:9]],
                         [0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0])
        self.assertEqual(data[9:12], [0, 0, 0])  # 原点位置保持

    def test_unknown_component_and_bad_params(self):
        sw, _mu = _math_sw(FakeAsmDoc(), None)
        self.assertEqual(move_component(sw, "ghost", 1, 1, 1)["error"]["code"],
                         "COMPONENT_NOT_FOUND")
        comp = _movable_comp()
        sw2, _mu2 = _math_sw(FakeAsmDoc(), comp)
        self.assertEqual(rotate_component(sw2, "box-1", "w", 90)["error"]["code"],
                         "INVALID_PARAMETER")
        self.assertEqual(
            rotate_component(sw2, "box-1", "z", float("nan"))["error"]["code"],
            "INVALID_PARAMETER")
        self.assertEqual(
            move_component(sw2, "box-1", float("nan"), 0, 0)["error"]["code"],
            "INVALID_PARAMETER")

    @patch("solidworks_mcp.solidworks_api.assembly.win32com.client.VARIANT",
           side_effect=lambda vt, data: data)
    def test_transform_refusal_is_sw_error(self, _variant):
        comp = _movable_comp()
        comp.SetTransformAndSolve3.return_value = False
        sw, _mu = _math_sw(FakeAsmDoc(), comp)
        result = move_component(sw, "box-1", 5, 0, 0)
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")


class TestBomExtended(unittest.TestCase):
    def test_rows_carry_volume_mass_material(self):
        # 探针：comp.GetBody→GetMassProperties(1000)：[3] 体积、[5] 质量；
        # GetMaterialIdName 材料名（空串=未设→None）
        body = FakeBomBody(4e-05)
        doc = FakeAsmDoc(comps=[
            SimpleNamespace(Name2="box-1",
                            GetPathName=lambda: "e:/a/box.SLDPRT",
                            ReferencedConfiguration=lambda: "默认",
                            GetBody=lambda: body,
                            GetMaterialIdName=lambda: "普通碳钢"),
        ])
        item = get_bom(_asm_sw(doc))["data"]["items"][0]
        self.assertEqual(item["volume_mm3"], 40000.0)
        self.assertEqual(item["mass_g"], 40.0)
        self.assertEqual(item["material"], "普通碳钢")

    def test_rows_without_body_or_material_stay_structured(self):
        doc = FakeAsmDoc(comps=[
            SimpleNamespace(Name2="box-1",
                            GetPathName=lambda: "e:/a/box.SLDPRT",
                            ReferencedConfiguration=lambda: "默认"),
        ])
        item = get_bom(_asm_sw(doc))["data"]["items"][0]
        self.assertIsNone(item["volume_mm3"])
        self.assertIsNone(item["mass_g"])
        self.assertIsNone(item["material"])


class TestN8ErrorBranches(unittest.TestCase):
    """N8 四组扩展的容错分支：形态不合法/成员抛异常时结构化降级不炸报告。"""

    # --- _interference_spatial：bbox/center 各自独立降级 ---

    def test_spatial_short_box_still_yields_center(self):
        class HalfBody:
            def GetBodyBox(self):
                return [0.1, 0.2]  # <6 值 → bbox 拒收

            def GetMassProperties(self, _d):
                return [0.001, 0.0, 0.0, 1e-05]

        doc = FakeAsmDoc(interferences=[
            FakeInterference(4e-05, ["a-1", "a-2"], body=HalfBody()),
        ])
        row = check_interference(_asm_sw(doc))["data"]["interferences"][0]
        self.assertIsNone(row["bbox_mm"])
        self.assertEqual(row["center_mm"], [1.0, 0.0, 0.0])

    def test_spatial_non_numeric_box_is_rejected(self):
        class OddBoxBody:
            def GetBodyBox(self):
                return ["a"] * 6  # 非数值 → 拒收

            def GetMassProperties(self, _d):
                return [0.001, 0.0, 0.0, 1e-05]

        doc = FakeAsmDoc(interferences=[
            FakeInterference(4e-05, ["a-1", "a-2"], body=OddBoxBody()),
        ])
        row = check_interference(_asm_sw(doc))["data"]["interferences"][0]
        self.assertIsNone(row["bbox_mm"])
        self.assertEqual(row["center_mm"], [1.0, 0.0, 0.0])

    def test_spatial_mass_properties_failure_keeps_bbox(self):
        class ThrowingPropsBody:
            def GetBodyBox(self):
                return [0.0, 0.0, 0.0, 0.01, 0.01, 0.01]

            def GetMassProperties(self, _d):
                raise OSError("com detached")

        doc = FakeAsmDoc(interferences=[
            FakeInterference(4e-05, ["a-1", "a-2"], body=ThrowingPropsBody()),
        ])
        row = check_interference(_asm_sw(doc))["data"]["interferences"][0]
        self.assertIsNone(row["center_mm"])
        self.assertEqual(row["bbox_mm"], [0.0, 0.0, 0.0, 10.0, 10.0, 10.0])

    def test_spatial_short_props_rejected(self):
        class ShortPropsBody:
            def GetBodyBox(self):
                return [0.0] * 6

            def GetMassProperties(self, _d):
                return [0.001]  # len < 3 → center 拒收

        doc = FakeAsmDoc(interferences=[
            FakeInterference(4e-05, ["a-1", "a-2"], body=ShortPropsBody()),
        ])
        row = check_interference(_asm_sw(doc))["data"]["interferences"][0]
        self.assertIsNone(row["center_mm"])
        self.assertEqual(row["bbox_mm"], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    # --- _walk_feature_names：非字符串名断路 ---

    def test_walk_breaks_on_non_string_names(self):
        from solidworks_mcp.solidworks_api.assembly import _walk_feature_names

        class OddNameDoc(FakeAsmDoc):
            @property
            def FirstFeature(self):
                # 子特征名非 str → 子层断路；下一顶层名非 str → 顶层断路
                return FakeFeature("配合", "MateGroup",
                                   subs=[FakeFeature(456, "MateCoincident")],
                                   next_feat=FakeFeature(789, "ICE"))

        self.assertEqual(_walk_feature_names(OddNameDoc()), {"配合"})

    def test_feature_name_exists_matches_full_walk(self):
        """P-1 回归（2026-10-05）：早停探针与全树 walk 成员检查等价
        （含一级子特征），delete_mate 删后复检语义不变。"""
        from solidworks_mcp.solidworks_api.assembly import (
            _feature_name_exists,
            _walk_feature_names,
        )

        doc = FakeAsmDoc(mates=["重合1", "距离1"])
        full = _walk_feature_names(doc)
        for name in ("重合1", "距离1", "不存在"):
            with self.subTest(name=name):
                self.assertEqual(_feature_name_exists(doc, name), name in full)

    # --- delete_mate / move / rotate：SW 未运行与参数闸门 ---

    def test_delete_mate_not_running_is_structured(self):
        sw = Mock()
        sw.get_active_document.side_effect = SolidWorksNotRunningError("not running")
        self.assertFalse(delete_mate(sw, "重合1")["success"])
        sw.get_active_document.side_effect = RuntimeError("COM")
        self.assertFalse(delete_mate(sw, "重合1")["success"])

    def test_move_requires_assembly_document(self):
        sw = Mock()
        sw.get_active_document.return_value = None
        self.assertFalse(move_component(sw, "box-1", 1, 0, 0)["success"])
        self.assertEqual(move_component(sw, "", 1, 0, 0)["error"]["code"],
                         "INVALID_PARAMETER")

    def test_move_not_running_is_structured(self):
        sw = Mock()
        sw.get_active_document.side_effect = SolidWorksNotRunningError("not running")
        self.assertFalse(move_component(sw, "box-1", 1, 0, 0)["success"])
        sw.get_active_document.side_effect = RuntimeError("COM")
        self.assertFalse(move_component(sw, "box-1", 1, 0, 0)["success"])

    def test_rotate_gates_and_not_found(self):
        sw = Mock()
        sw.get_active_document.return_value = None
        self.assertFalse(rotate_component(sw, "box-1", "z", 90)["success"])
        self.assertEqual(rotate_component(sw, "", "z", 90)["error"]["code"],
                         "INVALID_PARAMETER")
        sw2, _mu = _math_sw(FakeAsmDoc(), None)
        self.assertEqual(rotate_component(sw2, "ghost", "z", 90)["error"]["code"],
                         "COMPONENT_NOT_FOUND")

    def test_rotate_not_running_is_structured(self):
        sw = Mock()
        sw.get_active_document.side_effect = SolidWorksNotRunningError("not running")
        self.assertFalse(rotate_component(sw, "box-1", "z", 90)["success"])
        sw.get_active_document.side_effect = RuntimeError("COM")
        self.assertFalse(rotate_component(sw, "box-1", "z", 90)["success"])

    @patch("solidworks_mcp.solidworks_api.assembly.win32com.client.VARIANT",
           side_effect=lambda vt, data: data)
    def test_move_falls_back_to_identity_when_transform_unreadable(self, _v):
        comp = _movable_comp()
        comp.GetTotalTransform.side_effect = OSError("com detached")
        sw, mu = _math_sw(FakeAsmDoc(), comp)
        result = move_component(sw, "box-1", 5, 0, 0)
        self.assertTrue(result["success"], result)
        data = mu.CreateTransform.call_args[0][0]
        self.assertEqual(data[9:12], [0.005, 0.0, 0.0])  # identity + delta
        self.assertEqual(data[0:9], [1, 0, 0, 0, 1, 0, 0, 0, 1])

    @patch("solidworks_mcp.solidworks_api.assembly.win32com.client.VARIANT",
           side_effect=lambda vt, data: data)
    def test_move_without_math_utility_is_sw_error(self, _v):
        comp = _movable_comp()
        doc = FakeAsmDoc(comps=[comp])
        sw = _asm_sw(doc)
        sw.app.GetMathUtility.return_value = None
        result = move_component(sw, "box-1", 1, 0, 0)
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")
        self.assertIn("math utility", result["message"])

    @patch("solidworks_mcp.solidworks_api.assembly.win32com.client.VARIANT",
           side_effect=lambda vt, data: data)
    def test_move_transform_creation_none_is_sw_error(self, _v):
        comp = _movable_comp()
        sw, mu = _math_sw(FakeAsmDoc(), comp)
        mu.CreateTransform.return_value = None
        result = move_component(sw, "box-1", 1, 0, 0)
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")
        self.assertIn("returned None", result["message"])

    @patch("solidworks_mcp.solidworks_api.assembly.win32com.client.VARIANT",
           side_effect=lambda vt, data: data)
    def test_rotate_transform_failure_is_sw_error(self, _v):
        comp = _movable_comp()
        comp.SetTransformAndSolve3.return_value = False
        sw, _mu = _math_sw(FakeAsmDoc(), comp)
        result = rotate_component(sw, "box-1", "z", 90)
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    # --- BOM：退化代理与字段形态防御 ---

    def test_bom_body_fact_edge_shapes(self):
        class ShortPropsBody:
            def GetMassProperties(self, _d):
                return [0.001, 0.0, 0.0]  # len <= 5 → 体积/质量全弃

        class OddVolumeBody:
            def GetMassProperties(self, _d):
                return [0.0, 0.0, 0.0, "bad", 0.0, 0.04, 0, 0, 0, 0, 0, 0]

        class InfMassBody:
            def GetMassProperties(self, _d):
                return [0.0, 0.0, 0.0, 1e-05, 0.0, float("inf"), 0, 0, 0, 0, 0, 0]

        doc = FakeAsmDoc(comps=[
            SimpleNamespace(Name2="a-1", GetPathName=lambda: "e:/a/a.SLDPRT",
                            ReferencedConfiguration=lambda: "c",
                            GetBody=lambda: ShortPropsBody(),
                            GetMaterialIdName=lambda: ""),  # 空串 = 未设 → None
            SimpleNamespace(Name2="b-1", GetPathName=lambda: "e:/a/b.SLDPRT",
                            ReferencedConfiguration=lambda: "c",
                            GetBody=lambda: OddVolumeBody(),
                            GetMaterialIdName=lambda: "钢"),
            SimpleNamespace(Name2="c-1", GetPathName=lambda: "e:/a/c.SLDPRT",
                            ReferencedConfiguration=lambda: "c",
                            GetBody=lambda: InfMassBody()),
        ])
        items = {i["name"]: i for i in get_bom(_asm_sw(doc))["data"]["items"]}
        self.assertIsNone(items["a"]["volume_mm3"])
        self.assertIsNone(items["a"]["mass_g"])
        self.assertIsNone(items["a"]["material"])  # 空串 → None
        self.assertIsNone(items["b"]["volume_mm3"])  # 非数值体积
        self.assertEqual(items["b"]["mass_g"], 40.0)
        self.assertEqual(items["b"]["material"], "钢")
        self.assertEqual(items["c"]["volume_mm3"], 10000.0)
        self.assertIsNone(items["c"]["mass_g"])  # 非有限质量
        self.assertIsNone(items["c"]["material"])  # 缺成员 → None

    def test_bom_skips_degenerate_and_non_string_fields(self):
        doc = FakeAsmDoc(comps=[
            SimpleNamespace(Name2=123),  # 非 str → 跳过不计入 total
            SimpleNamespace(Name2="b-1",
                            GetPathName=lambda: 99,  # 非 str → ""
                            ReferencedConfiguration=lambda: None),  # 非 str → ""
        ])
        data = get_bom(_asm_sw(doc))["data"]
        self.assertEqual(data["total_components"], 1)
        item = data["items"][0]
        self.assertEqual(item["name"], "")  # path "" → basename ""
        self.assertEqual(item["path"], "")
        self.assertEqual(item["configuration"], "")


if __name__ == "__main__":
    unittest.main()
