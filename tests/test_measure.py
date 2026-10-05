"""Measurement tool tests (distance + bounding box)."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from solidworks_mcp.solidworks_api.measure import get_bounding_box, measure_distance


class Body:
    def __init__(self, box_m):
        self._box = box_m

    def GetBodyBox(self):
        return self._box


class Model:
    def __init__(self, bodies):
        self._bodies = bodies

    def GetBodies2(self, body_type, visible_only):
        self.body_args = (body_type, visible_only)
        return self._bodies


class TestMeasureDistance(unittest.TestCase):
    """N14: measure_distance is pure computation — no SolidWorks involved."""

    def test_distance_between_two_points(self):
        result = measure_distance([0, 0, 0], [30, 40, 0])
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["distance_mm"], 50.0)
        self.assertEqual(result["data"]["delta_mm"], [30.0, 40.0, 0.0])

    def test_rejects_malformed_points(self):
        bad = measure_distance([0, 0], [1, 2, 3])
        self.assertEqual(bad["error"]["code"], "INVALID_PARAMETER")

    def test_works_without_any_solidworks_connection(self):
        result = measure_distance([0, 0, 0], [1, 1, 1])
        self.assertTrue(result["success"])
        self.assertAlmostEqual(result["data"]["distance_mm"], 3.0 ** 0.5, places=5)


class TestBoundingBox(unittest.TestCase):
    def test_box_merged_across_bodies(self):
        body1 = Body((0.0, -0.01, 0.0, 0.06, 0.01, 0.02))
        body2 = Body((0.02, 0.0, 0.005, 0.08, 0.03, 0.025))
        model = Model((body1, body2))
        sw = Mock()
        sw.get_active_document.return_value = model
        result = get_bounding_box(sw)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual(model.body_args, (0, False))
        self.assertEqual(data["min_mm"], [0.0, -10.0, 0.0])
        self.assertEqual(data["max_mm"], [80.0, 30.0, 25.0])
        self.assertEqual(data["size_mm"], [80.0, 40.0, 25.0])
        self.assertEqual(data["center_mm"], [40.0, 10.0, 12.5])
        self.assertEqual(data["body_count"], 2)

    def test_no_bodies_is_error(self):
        sw = Mock()
        sw.get_active_document.return_value = Model(())
        self.assertFalse(get_bounding_box(sw)["success"])

    def test_degenerate_body_is_skipped_not_fatal(self):
        """C-7 回归（2026-10-05）：GetBodyBox 返回 None 的退化体跳过，
        不再让整包测量报错；全部退化时如实报 SW_API_ERROR。"""
        good = Body((0.0, 0.0, 0.0, 0.06, 0.01, 0.02))
        bad = Body(None)
        model = Model((good, bad))
        sw = Mock()
        sw.get_active_document.return_value = model
        result = get_bounding_box(sw)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["body_count"], 1)

        sw2 = Mock()
        sw2.get_active_document.return_value = Model((Body(None),))
        all_bad = get_bounding_box(sw2)
        self.assertFalse(all_bad["success"])
        self.assertEqual(all_bad["error"]["code"], "SW_API_ERROR")

    def test_com_error_is_tool_error(self):
        sw = Mock()
        sw.get_active_document.side_effect = RuntimeError("COM failed")
        self.assertFalse(get_bounding_box(sw)["success"])


if __name__ == "__main__":
    unittest.main()
