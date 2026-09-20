"""N58 circular-pattern tool: FakeModel contract tests.

The production channel drives the real PM pane via pywinauto (N58/U9
定谳: pure-COM creation paths cannot build patterns — see
tools/INDEX.md); tests replace the pane driver at the module seam and
exercise the COM-side contract: validation, pre-selection marks
(seed BODYFEATURE mark 4, axis AXIS mark 1 — recorded contract), and
the tree-diff verdict (N29 discipline)."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from solidworks_mcp.solidworks_api import pattern_ui
from solidworks_mcp.utils.common import success_response


class FakeFeature:
    def __init__(self, name, next_feature=None):
        self.Name = name
        self._next = next_feature
        self.renamed_to = None

    def GetNextFeature(self):
        return self._next

    def GetTypeName2(self):
        return "ProfileFeature"


class FakeModel:
    """Mutable feature list + recording extension; walk reflects mutation."""

    def __init__(self, names):
        self.features = [FakeFeature(n) for n in names]
        for cur, nxt in zip(self.features, self.features[1:]):
            cur._next = nxt
        self.selects = []
        self.cleared = []

    def FirstFeature(self):
        return self.features[0] if self.features else None

    def ClearSelection2(self, all):
        self.cleared.append(all)

    @property
    def Extension(self):
        return self

    def SelectByID2(self, name, sel_type, x, y, z, append, mark, callout, opts):
        self.selects.append((name, sel_type, append, mark))
        return True

    def GetTypeName2(self):
        return 1  # swDocPART via call_or_value


class _FakeSwApp:
    def __init__(self, model):
        self._model = model

    def get_active_document(self):
        return self._model


BASE = ["草图1", "凸台-拉伸1", "草图2", "HoleToPattern", "AxisToPattern"]


def _make(seed="HoleToPattern", axis="AxisToPattern"):
    model = FakeModel(list(BASE))
    sw = _FakeSwApp(model)
    return model, sw


class TestValidation(unittest.TestCase):
    def test_rejects_instance_count_below_two(self):
        model, sw = _make()
        with patch.object(pattern_ui, "drive_pattern_pane") as drive:
            result = pattern_ui.create_circular_pattern(
                sw, "HoleToPattern", "AxisToPattern", 1
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_PARAMETER")
        drive.assert_not_called()

    def test_rejects_angle_out_of_range(self):
        model, sw = _make()
        result = pattern_ui.create_circular_pattern(
            sw, "HoleToPattern", "AxisToPattern", 4, angle_deg=0.0
        )
        self.assertFalse(result["success"])

    def test_rejects_missing_seed(self):
        model, sw = _make()
        with patch.object(pattern_ui, "drive_pattern_pane") as drive:
            result = pattern_ui.create_circular_pattern(
                sw, "Nope", "AxisToPattern", 4
            )
        self.assertFalse(result["success"])
        self.assertIn("seed", result["message"])
        drive.assert_not_called()

    def test_rejects_missing_axis(self):
        model, sw = _make()
        with patch.object(pattern_ui, "drive_pattern_pane") as drive:
            result = pattern_ui.create_circular_pattern(sw, "HoleToPattern", "Nope", 4)
        self.assertFalse(result["success"])
        self.assertIn("axis", result["message"])
        drive.assert_not_called()

    def test_rejects_no_active_document(self):
        sw = _FakeSwApp(None)
        result = pattern_ui.create_circular_pattern(
            sw, "HoleToPattern", "AxisToPattern", 4
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "NO_DOCUMENT")


class TestSuccessPath(unittest.TestCase):
    def test_preselection_marks_follow_recorded_contract(self):
        model, sw = _make()
        with patch.object(pattern_ui, "drive_pattern_pane") as drive:

            def grow(*args):
                model.features.append(FakeFeature("阵列(圆周)1"))
                model.features[-2]._next = model.features[-1]

            drive.side_effect = grow
            result = pattern_ui.create_circular_pattern(
                sw, "HoleToPattern", "AxisToPattern", 4
            )
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["feature_name"], "阵列(圆周)1")
        self.assertEqual(result["data"]["instance_count"], 4)
        # 录制契约：种子 BODYFEATURE mark4 append=False → 轴 AXIS mark1 append=True
        self.assertEqual(
            model.selects,
            [
                ("HoleToPattern", "BODYFEATURE", False, 4),
                ("AxisToPattern", "AXIS", True, 1),
            ],
        )
        drive.assert_called_once_with("SOLIDWORKS.*", "HoleToPattern", "AxisToPattern", 4, True)

    def test_rename_on_success(self):
        model, sw = _make()
        with patch.object(pattern_ui, "drive_pattern_pane") as drive:

            def grow(*args):
                model.features.append(FakeFeature("阵列(圆周)1"))
                model.features[-2]._next = model.features[-1]

            drive.side_effect = grow
            result = pattern_ui.create_circular_pattern(
                sw, "HoleToPattern", "AxisToPattern", 4, pattern_name="MyPattern"
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["feature_name"], "MyPattern")
        self.assertIn("MyPattern", [f.Name for f in model.features])


class TestFailurePaths(unittest.TestCase):
    def test_drive_failure_cancels_pane_and_reports(self):
        model, sw = _make()
        with patch.object(pattern_ui, "drive_pattern_pane") as drive, patch.object(
            pattern_ui, "esc_cancel_pane"
        ) as cancel:
            drive.side_effect = RuntimeError("pane not found")
            result = pattern_ui.create_circular_pattern(
                sw, "HoleToPattern", "AxisToPattern", 4
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_UI_ERROR")
        self.assertIn("pane not found", result["message"])
        cancel.assert_called_once()

    def test_tree_diff_empty_reports_boundary_error(self):
        model, sw = _make()
        with patch.object(pattern_ui, "drive_pattern_pane"):
            result = pattern_ui.create_circular_pattern(
                sw, "HoleToPattern", "AxisToPattern", 4
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")
        self.assertIn("tree diff empty", result["message"])


class TestRegistryWiring(unittest.TestCase):
    def test_tool_registered(self):
        from solidworks_mcp.registry import part

        self.assertTrue(hasattr(part, "solidworks_part_circular_pattern"))
        self.assertTrue(callable(part.solidworks_part_circular_pattern))


if __name__ == "__main__":
    unittest.main()
