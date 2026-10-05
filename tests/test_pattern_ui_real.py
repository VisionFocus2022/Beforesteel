"""N58 实机验证层（R2, 2026-10-05）。

标记 real_sw：需要真实运行的 SolidWorks 2026（可见、最大化窗口）。
CI 与常规本机测试一律跳过（pyproject 已配 -m "not real_sw" 语义由
调用方约定：CI 跑 `pytest -m "not real_sw"`）。

运行方式（真机）：
    set SOLIDWORKS_MCP_E2E=1
    venv\\Scripts\\python.exe -m pytest tests/test_pattern_ui_real.py -m real_sw

前置：SolidWorks 打开一个含孔特征与基准轴的零件（特征树含
HoleToPattern / AxisToPattern，或经 --pattern-seed/--pattern-axis 覆盖）。
判据沿用 N29 纪律：树 diff 出现新特征即成功。
"""

from __future__ import annotations

import os
import unittest

import pytest

pytestmark = pytest.mark.real_sw

E2E_ENV = "SOLIDWORKS_MCP_E2E"

# 默认特征名（与 tools/e2e 脚本及 test_pattern_ui.py BASE 对齐）
DEFAULT_SEED = os.environ.get("SW_PATTERN_SEED", "HoleToPattern")
DEFAULT_AXIS = os.environ.get("SW_PATTERN_AXIS", "AxisToPattern")


@unittest.skipUnless(
    os.environ.get(E2E_ENV), f"set {E2E_ENV}=1 on a real SolidWorks host"
)
class TestCircularPatternOnRealSW(unittest.TestCase):
    """实机 e2e：COM 预选 + PM 面板驱动 + 树 diff 判据（N58 通道）。"""

    def test_circular_pattern_creates_feature(self):
        from solidworks_mcp.solidworks_api.app import get_solidworks_app
        from solidworks_mcp.solidworks_api.geometry import walk_feature_names
        from solidworks_mcp.solidworks_api.pattern_ui import (
            create_circular_pattern,
        )

        sw = get_solidworks_app()
        result = create_circular_pattern(
            sw,
            seed_feature=DEFAULT_SEED,
            axis_feature=DEFAULT_AXIS,
            instance_count=4,
            equal_spacing=True,
        )
        try:
            self.assertTrue(
                result["success"], f"real-SW pattern failed: {result}"
            )
            model = sw.get_active_document()
            created = result["data"]["feature_name"]
            self.assertIn(created, walk_feature_names(model))
        finally:
            # 清场：删除本用例创建的阵列特征，保持文档可复跑。
            model = sw.get_active_document()
            if model is not None and result.get("success"):
                model.Extension.SelectByID2(
                    created, "BODYFEATURE", 0, 0, 0, False, 0, None, 0
                )
                model.DeleteSelectedFeatures()
