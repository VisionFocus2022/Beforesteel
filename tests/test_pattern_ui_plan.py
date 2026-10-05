"""N58 PM 面板驱动计划契约测试（R2, 2026-10-05）。

背景（engineering-assurance/code-review-solidworks-mcp-2026-10-05 T1）：
drive_pattern_pane 的六步点击序列原为 130 行过程代码内联（写死像素坐标 +
中文菜单 + sleep），单元层被 patch 掉、实机层又不在 pytest 体系——
SW 界面语言/分辨率/版本一变即静默失败，是全仓最大单点盲区。

R2 方案：序列抽成 PANE_CLICK_PLAN 数据结构，本文件锁其**完整性与顺序**；
实机验证另走 tests/test_pattern_ui_real.py（real_sw marker，CI 跳过）。
分辨率/布局变化时只改 pattern_ui.PM_OFFSETS 一处数据。
"""

from __future__ import annotations

import unittest

from solidworks_mcp.solidworks_api.pattern_ui import (
    PM_OFFSETS,
    PANE_CLICK_PLAN,
)

EXPECTED_PURPOSES_EQUAL_SPACING = [
    "focus_axis_box",
    "open_feature_tree",
    "pick_axis",
    "focus_features_box",
    "pick_seed",
    "toggle_equal_spacing",
    "set_instance_count",
    "commit_ok",
]

EXPECTED_PURPOSES_NO_EQUAL_SPACING = [
    p for p in EXPECTED_PURPOSES_EQUAL_SPACING if p != "toggle_equal_spacing"
]


class TestPaneClickPlanContract(unittest.TestCase):
    """计划结构契约：步骤号、顺序、动作类型、字段完备性。"""

    def test_steps_are_sequential_from_one(self):
        steps = [item["step"] for item in PANE_CLICK_PLAN]
        self.assertEqual(steps, list(range(1, len(PANE_CLICK_PLAN) + 1)))

    def test_purposes_in_expected_order(self):
        self.assertEqual(
            [item["purpose"] for item in PANE_CLICK_PLAN],
            EXPECTED_PURPOSES_EQUAL_SPACING,
        )

    def test_only_one_conditional_step(self):
        conditional = [i for i in PANE_CLICK_PLAN if "when" in i]
        self.assertEqual(len(conditional), 1)
        self.assertEqual(conditional[0]["when"], "equal_spacing")
        self.assertEqual(conditional[0]["purpose"], "toggle_equal_spacing")

    def test_tree_select_targets_are_axis_then_seed(self):
        tree_steps = [
            (i["purpose"], i["target"])
            for i in PANE_CLICK_PLAN
            if i["action"] == "tree_select"
        ]
        self.assertEqual(
            tree_steps,
            [("pick_axis", "axis_feature"), ("pick_seed", "seed_feature")],
        )

    def test_plan_starts_with_axis_box_and_ends_with_ok(self):
        self.assertEqual(PANE_CLICK_PLAN[0]["purpose"], "focus_axis_box")
        self.assertEqual(PANE_CLICK_PLAN[-1]["purpose"], "commit_ok")

    def test_every_action_is_known_type(self):
        known = {"click", "tree_select", "type_instances"}
        for item in PANE_CLICK_PLAN:
            with self.subTest(step=item["step"]):
                self.assertIn(item["action"], known)
                self.assertTrue(item["purpose"])

    def test_click_steps_reference_live_offsets(self):
        """计划里的每个坐标必须来自 PM_OFFSETS（防数据两处漂移）。"""
        live_offsets = {tuple(v) for v in PM_OFFSETS.values()}
        for item in PANE_CLICK_PLAN:
            if "offset" in item:
                with self.subTest(step=item["step"], purpose=item["purpose"]):
                    self.assertIn(tuple(item["offset"]), live_offsets)

    def test_no_equal_spacing_plan_skips_only_toggle(self):
        """equal_spacing=False 的执行序列 = 完整计划剔除条件步。"""
        filtered = [
            i["purpose"] for i in PANE_CLICK_PLAN
            if i.get("when") != "equal_spacing"
        ]
        self.assertEqual(filtered, EXPECTED_PURPOSES_NO_EQUAL_SPACING)


class TestPmOffsetsContract(unittest.TestCase):
    """标定数据契约：四键完备、坐标为窗口内正偏移、互不冲突。"""

    def test_required_keys_present(self):
        for key in (
            "ok", "cancel", "equal_spacing", "instance_count",
            "axis_box", "feature_tree_icon", "features_faces_box",
        ):
            self.assertIn(key, PM_OFFSETS)

    def test_offsets_are_positive_xy_pairs(self):
        for key, (dx, dy) in PM_OFFSETS.items():
            with self.subTest(key=key):
                self.assertIsInstance(dx, int)
                self.assertIsInstance(dy, int)
                self.assertGreater(dx, 0)
                self.assertGreater(dy, 0)

    def test_ok_and_cancel_are_distinct(self):
        self.assertNotEqual(PM_OFFSETS["ok"], PM_OFFSETS["cancel"])


if __name__ == "__main__":
    unittest.main()
