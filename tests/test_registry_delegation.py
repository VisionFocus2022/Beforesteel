"""Registry delegation sweep (R1, 2026-10-05) — 一次清零委托层盲区。

Tessa 测试评估（engineering-assurance/code-review-solidworks-mcp-2026-10-05）定谳：
此前哨兵表只抽查 ~23 个工具，其余 ~60 个工具的委托 lambda 从未真实执行，
参数名抄错/顺序颠倒/结构化契约破裂这类接线 bug 只能等实机暴露。

本文件对 server 门面暴露的全部 solidworks_* 工具做三层断言：
  1. 转发断言——patch _call_connected 为记录器，逐工具用"合法最小参数"
     调用，断言确实走了 _call_connected（纯计算工具除外，见豁免表）；
  2. 回传断言——_call_connected 的返回值原样穿透（不吞不改）；
  3. 计数断言——sweep 覆盖数 == 注册表计数钉（tests/_counts.py，防
     新工具漏入 sweep 的静默漂移）。

豁免（纯计算/本地工具，不经过 _call_connected，已有专属测试）：
  solidworks_design_capabilities / solidworks_measure_distance /
  solidworks_pattern_annular_layout（validation 已由 test_pattern 与
  test_infrastructure 覆盖）。

参数策略：按参数名后缀/名字生成合法最小值，绕开 pydantic Field 约束
（gt=0 / min_length=1 / Literal 枚举等）；必须随真实签名维护的字面量表
只有两处——SAMPLE_VALUES（按名字）与 LITERAL_PARAMS（按枚举）。
"""

from __future__ import annotations

import inspect
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from tests import _counts

from solidworks_mcp import server
from solidworks_mcp.registry import (
    assembly,
    drawing,
    features,
    file_io,
    misc,
    part,
    products,
    properties,
)

SENTINEL = {
    "success": True,
    "data": None,
    "message": "ok",
    "warning": None,
    "error": None,
}

# 不经过 _call_connected 的纯计算/本地工具（各已有专属测试）。
PURE_TOOLS = frozenset(
    {
        "solidworks_design_capabilities",
        "solidworks_measure_distance",
        "solidworks_pattern_annular_layout",
    }
)

# Literal / 枚举型参数必须取真实枚举值，逐个列出（新增枚举参数时同步）。
LITERAL_PARAMS = {
    "mate_type": "concentric",
    "axis": "x",
    "path_type": "arc",
    "plane": "top",  # "front"/"top" 均合法，统一用 "top"
    "feature_kind": "cut",
    "spec": "M6",
    "characteristic": "flatness",
    "material_condition": "none",
    "bom_type": "parts_only",
    "suppressed": True,  # bool 必填位（非枚举，但需要非默认合法值语义）
}

# 按参数名（含后缀语义）生成合法最小值；命中顺序：LITERAL → 精确名 → 后缀。
SAMPLE_VALUES = {
    "instance_count": 4,
    "index": 0,
    "sides": 6,
    "count": 4,
    "row_counts": [3, 5],
    "rings": [{"radius_mm": 30, "count": 6, "diameter_mm": 6}],
    "operations": [{"type": "new_part"}],
    "plan": {"version": 1, "operations": []},
    "point1": [0.0, 0.0, 0.0],
    "point2": [10.0, 0.0, 0.0],
    "face_names": ["面1"],
    "profile_diameters_mm": [20.0, 30.0],
    "equation": '"x" = 50',
    "new_text": '"x" = 60',
    "value_mm": 10.0,
    "value_deg": 45.0,
    "angle_deg": 90.0,
    "start_angle_degrees": 30.0,
    "end_angle_degrees": 60.0,
    "tolerance_mm": 0.05,
    "upper_mm": 0.02,
    "lower_mm": 0.0,
    "x": 10.0,
    "y": 10.0,
    "x_mm": 240.0,
    "y_mm": 20.0,
    "dx": 1.0,
    "dy": 1.0,
    "dz": 1.0,
    "pitch": 1.0,
}

# 名字精确命中优先于后缀规则。
EXACT_NAMES = {
    "text": "note",
    "name": "Default",
    "value": "val",
    "index_or_text": 0,
    "dimension_full_name": "D1@草图1",
    "dimension_name": "D1@草图1",
    "feature_name": "凸台-拉伸1",
    "old_name": "凸台-拉伸1",
    "new_name": "重命名1",
    "seed_feature": "HoleToPattern",
    "axis_feature": "AxisToPattern",
    "mate_name": "重合1",
    "component_name": "part-1",
    "material_name": "合金钢",
    "view_name": "工程图视图1",
    "source_view_name": "工程图视图1",
    "part_path": "ring.SLDPRT",
    "file_path": "out.step",
    "source_path": "housing.step",
    "save_path": None,  # Optional：显式 None 最小合法
}


def _sample_for(param: inspect.Parameter):
    """Pick a legal minimal value for one parameter by name heuristics."""
    name = param.name
    if name in LITERAL_PARAMS:
        return LITERAL_PARAMS[name]
    if name in EXACT_NAMES:
        return EXACT_NAMES[name]
    if name in SAMPLE_VALUES:
        return SAMPLE_VALUES[name]
    low = name.lower()
    if low.endswith(("_mm", "_deg", "_degrees")) or low in (
        "width", "depth", "height", "thickness", "diameter", "offset_mm",
        "radius_mm", "height_mm", "length_mm", "width_mm", "thickness_mm",
        "thread_length", "bottom_diameter", "outer_diameter",
        "center_hole_diameter", "carrier_thickness", "led_diameter",
        "circumradius_mm", "section_spacing_mm", "diameter_mm",
    ):
        return 10.0 if not low.startswith("led") else 2.6
    if low.startswith(("face_", "entity")) or low in ("plane_name",):
        return "面1"
    if low.endswith("_path") or low in ("path",):
        return "file.step"
    if param.default is not inspect.Parameter.empty:
        return param.default  # 有默认值不会被用到（只填必填位）
    # 兜底：字符串参数给非空串（NonEmptyString 最常见）。
    return "x"


def _min_kwargs(fn) -> dict:
    """Build the minimal legal kwargs (required params only)."""
    sig = inspect.signature(fn)
    return {
        p.name: _sample_for(p)
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
    }


class TestEveryToolDelegates(unittest.TestCase):
    """全 83 工具委托 sweep：转发 + 回传 + 计数三断言。"""

    def test_all_tools_forward_and_return_structured(self):
        domains = (misc, part, features, file_io, assembly, drawing, properties, products)
        checked = []
        with ExitStack() as stack:
            for domain in domains:
                stack.enter_context(
                    patch.object(
                        domain,
                        "call_connected",
                        return_value=dict(SENTINEL),
                    )
                )
            for name, fn in sorted(vars(server).items()):
                if not name.startswith("solidworks_"):
                    continue
                if name.endswith(("_prompt", "_resource")):
                    continue  # prompts（5）与 resources（3）不是 tools
                if not inspect.isfunction(fn):
                    continue  # 资源函数不带 solidworks_ 前缀，双保险跳过
                if name in PURE_TOOLS:
                    continue
                kwargs = _min_kwargs(fn)
                with self.subTest(tool=name):
                    result = fn(**kwargs)
                    self.assertEqual(
                        result,
                        SENTINEL,
                        f"{name} must forward through _call_connected "
                        "and return its payload unchanged",
                    )
                checked.append(name)
        # 计数钉：默认 81 + 产品门 2 − 纯计算豁免 3 —— sweep 一个不漏。
        self.assertEqual(
            len(checked),
            _counts.PRODUCT_TOOLS - len(PURE_TOOLS),
            f"sweep covered {len(checked)} tools; expected "
            f"{_counts.PRODUCT_TOOLS - len(PURE_TOOLS)} "
            f"({_counts.PRODUCT_TOOLS} tools - {len(PURE_TOOLS)} pure) — "
            "new tool missing from sweep or misclassified in PURE_TOOLS",
        )

    def test_pure_tools_are_covered_elsewhere(self):
        """豁免表不可静默膨胀：每个豁免名必须真实存在于门面。"""
        facade_names = {
            n for n, f in vars(server).items()
            if n.startswith("solidworks_") and inspect.isfunction(f)
        }
        unknown = PURE_TOOLS - facade_names
        self.assertEqual(
            unknown,
            set(),
            f"PURE_TOOLS lists non-existent tools (renamed/removed): {unknown}",
        )
        # 豁免数钉死：3。新增豁免 = 手工确认有专属测试后再 +1。
        self.assertEqual(len(PURE_TOOLS), 3)


if __name__ == "__main__":
    unittest.main()
