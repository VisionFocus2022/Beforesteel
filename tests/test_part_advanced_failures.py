"""part_advanced 错误分支补桩（R4, 2026-10-05）。

Tessa 测试评估 T5：loft/swept/rib/refgeom 的 API 失败路径未测——
失败时返回结构可能违反 ToolResult 契约。本文件逐函数注入
FeatureManager/选择失败，断言 error_response 结构稳定（success=False +
error.code），沿用 test_part_loft.py 的 patch 缝（_select_plane /
latest_feature_name / prepare_part_save）。
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.part_fakes import BasePartModel, sw_with_model
from solidworks_mcp.solidworks_api import part_advanced
from solidworks_mcp.solidworks_api.part_advanced import (
    create_loft,
    create_polygon,
    create_rib,
    create_slot,
    create_swept,
)

PLANE = "前视基准面"


class FailingSketchManager:
    """记录 sketch 调用；成功形态（绘制不设障碍，失败留给 FM）。"""

    def __init__(self):
        self.calls = []

    def InsertSketch(self, toggle):
        self.calls.append(("InsertSketch", toggle))

    def CreateArc(self, *args):
        self.calls.append(("CreateArc",) + args)

    def CreateLine(self, *args):
        self.calls.append(("CreateLine",) + args)

    def CreateCircleByRadius(self, *args):
        self.calls.append(("CreateCircleByRadius",) + args)

    def CreatePolygon(self, *args):
        self.calls.append(("CreatePolygon",) + args)


class FailingFeatureManager:
    """全部创建调用返回 None —— SW 拒绝特征的最常见形态。"""

    def InsertProtrusionSwept4(self, *args):
        return None

    def InsertProtrusionBlend2(self, *args):
        return None

    def InsertRefPlane(self, *args):
        return None

    def FeatureExtrusion2(self, *args):
        return None


class FailingModel(BasePartModel):
    def __init__(self):
        super().__init__()
        self.sketch = FailingSketchManager()
        self.fm = FailingFeatureManager()

    def InsertProtrusionBlend2(self, *args):
        return self.fm.InsertProtrusionBlend2(*args)


def _names(*names):
    return list(names)


class TestSweptFailureBranches(unittest.TestCase):
    def _run(self, **overrides):
        model = FailingModel()
        sw = sw_with_model(model)
        kwargs = dict(diameter_mm=10.0, path_type="arc", radius_mm=30.0,
                      angle_deg=90.0)
        kwargs.update(overrides)
        with patch.object(part_advanced, "_select_plane", return_value=PLANE), \
             patch.object(part_advanced, "latest_feature_name",
                          side_effect=_names("草图1")), \
             patch.object(part_advanced, "prepare_part_save", return_value=None):
            return create_swept(sw, **kwargs)

    def test_swept_feature_rejected_is_structured_error(self):
        result = self._run()
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")
        self.assertIn("rejected", result["message"])

    def test_swept_arc_without_radius_rejected(self):
        result = self._run(radius_mm=None)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_swept_line_without_length_rejected(self):
        result = self._run(path_type="line", radius_mm=None, length_mm=None)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")


class TestLoftFailureBranches(unittest.TestCase):
    def _run(self, diameters=(20.0, 30.0), spacing=10.0, model=None):
        model = model or FailingModel()
        sw = sw_with_model(model)
        with patch.object(part_advanced, "_select_plane", return_value=PLANE), \
             patch.object(part_advanced, "latest_feature_name",
                          side_effect=_names("草图1", "基准面1", "草图2",
                                             "草图3", "草图4")), \
             patch.object(part_advanced, "prepare_part_save", return_value=None):
            return create_loft(sw, list(diameters), spacing)

    def test_loft_offset_plane_rejected(self):
        """InsertRefPlane 返回 None → 结构化 SW_API_ERROR（code 统一后）。"""
        result = self._run()
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    def test_loft_single_section_rejected(self):
        result = self._run(diameters=(20.0,))
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")


class TestRibFailureBranches(unittest.TestCase):
    def _run(self, base_z_mm=0.0, **overrides):
        model = FailingModel()
        sw = sw_with_model(model)
        kwargs = dict(length_mm=40.0, height_mm=8.0, thickness_mm=5.0,
                      base_z_mm=base_z_mm)
        kwargs.update(overrides)
        # rib 的 offset 分支不走 _select_plane，而是 select_plane（top 候选）
        with patch.object(part_advanced, "prepare_part_save", return_value=None):
            return create_rib(sw, **kwargs)

    def test_rib_negative_base_z_rejected(self):
        result = self._run(base_z_mm=-1.0)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")


class TestPolygonFailureBranches(unittest.TestCase):
    def _run(self, **overrides):
        model = FailingModel()
        sw = sw_with_model(model)
        kwargs = dict(sides=6, circumradius_mm=20.0, height_mm=10.0)
        kwargs.update(overrides)
        with patch.object(part_advanced, "_select_plane", return_value=PLANE), \
             patch.object(part_advanced, "prepare_part_save", return_value=None):
            return create_polygon(sw, **kwargs)

    def test_polygon_sides_out_of_range_rejected(self):
        for bad in (2, 61, True, "six"):
            with self.subTest(sides=bad):
                result = self._run(sides=bad)
                self.assertFalse(result["success"])
                self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")

    def test_polygon_extrusion_rejected_is_structured_error(self):
        result = self._run()
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")


class TestSlotFailureBranches(unittest.TestCase):
    def _run(self, **overrides):
        model = FailingModel()
        sw = sw_with_model(model)
        kwargs = dict(length_mm=30.0, width_mm=10.0, height_mm=5.0)
        kwargs.update(overrides)
        with patch.object(part_advanced, "_select_plane", return_value=PLANE), \
             patch.object(part_advanced, "prepare_part_save", return_value=None), \
             patch.object(part_advanced, "latest_feature_name",
                          side_effect=_names("草图1")):
            return create_slot(sw, **kwargs)

    def test_slot_nonpositive_dimensions_rejected(self):
        for field in ("length_mm", "width_mm", "height_mm"):
            with self.subTest(field=field):
                result = self._run(**{field: 0.0})
                self.assertFalse(result["success"])
                self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")


if __name__ == "__main__":
    unittest.main()
