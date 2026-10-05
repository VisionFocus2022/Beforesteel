"""Concave ring-light v3 geometry tests."""

from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from solidworks_mcp.products import ring_light_v3
from solidworks_mcp.products.ring_light_v3 import (
    build_concave_dish_bands,
    build_ring_light_v3_layout,
    _band_crosses_mount_zone,
    create_ring_light_v3,
)


class TestRingLightV3Layout(unittest.TestCase):
    def test_defaults_follow_step_and_confirmed_led_requirements(self):
        layout = build_ring_light_v3_layout()

        self.assertEqual(layout["surface_profile"], "spherical_concave_dish")
        self.assertEqual(layout["outer_diameter_mm"], 80.0)
        self.assertEqual(layout["center_hole_diameter_mm"], 40.0)
        self.assertAlmostEqual(layout["reference_total_depth_mm"], 18.0025, places=4)
        self.assertEqual(layout["row_counts"], list(range(21, 30)))
        self.assertEqual(layout["total_led_count"], 225)
        self.assertEqual(layout["led_diameter_mm"], 2.6)
        self.assertEqual(layout["native_approximation"]["inner_row_marker_style"], "raised_boss")
        self.assertEqual(layout["native_approximation"]["inner_row_marker_height_mm"], 0.3)
        self.assertEqual(layout["rows"][0]["angle_degrees"], 30.0)
        self.assertEqual(layout["rows"][-1]["angle_degrees"], 60.0)

    def test_row_counts_are_free_between_one_and_sixty_four(self):
        layout = build_ring_light_v3_layout(row_counts=[10, 12])
        self.assertEqual(len(layout["rows"]), 2)
        self.assertEqual(layout["total_led_count"], 22)
        with self.assertRaises(ValueError):
            build_ring_light_v3_layout(row_counts=[])
        with self.assertRaises(ValueError):
            build_ring_light_v3_layout(row_counts=[5] * 65)

    def test_rows_form_one_concave_sphere_and_point_inward(self):
        layout = build_ring_light_v3_layout()
        sphere_radius = layout["dish"]["sphere_radius_mm"]
        outer_z = layout["dish"]["outer_row_z_mm"]

        self.assertAlmostEqual(sphere_radius, 44.0, places=6)
        heights = [row["z_mm"] for row in layout["rows"]]
        self.assertEqual(heights, sorted(heights))
        self.assertLess(heights[0], heights[-1])
        self.assertAlmostEqual(heights[-1], outer_z, places=6)
        for row in layout["rows"]:
            theta = math.radians(row["angle_degrees"])
            self.assertAlmostEqual(row["radius_mm"], sphere_radius * math.sin(theta), places=5)
            self.assertAlmostEqual(
                row["z_mm"], outer_z + sphere_radius * (math.cos(math.radians(60.0)) - math.cos(theta)), places=5
            )
            axis = row["sample_led_axis"]
            self.assertLess(axis[0], 0.0)
            self.assertAlmostEqual(axis[2], math.cos(theta), places=6)

    def test_inner_edge_stays_inside_step_body(self):
        layout = build_ring_light_v3_layout()

        self.assertAlmostEqual(layout["dish"]["inner_edge_z_mm"], -15.691836, places=5)
        self.assertAlmostEqual(layout["dish"]["minimum_back_thickness_mm"], 0.308164, places=5)
        self.assertGreater(layout["dish"]["minimum_back_thickness_mm"], 0.3)

    def test_48_blind_cut_bands_deepen_toward_center(self):
        layout = build_ring_light_v3_layout()
        bands = build_concave_dish_bands(layout, step_count=48)

        self.assertEqual(len(bands), 48)
        self.assertAlmostEqual(bands[0]["outer_radius_mm"], layout["rows"][-1]["radius_mm"], places=6)
        self.assertAlmostEqual(bands[-1]["inner_radius_mm"], 21.13, places=6)
        depths = [band["cut_depth_mm"] for band in bands]
        self.assertEqual(depths, sorted(depths))
        self.assertGreater(depths[-1], 16.8)
        self.assertLess(depths[-1], 17.2)

    def test_all_dish_bands_keep_cardinal_ribs_continuous(self):
        layout = build_ring_light_v3_layout()
        for band in build_concave_dish_bands(layout, step_count=48):
            self.assertTrue(
                _band_crosses_mount_zone(band["inner_radius_mm"], band["outer_radius_mm"])
            )

    def test_all_led_centers_clear_step_mounting_holes_and_ribs(self):
        layout = build_ring_light_v3_layout()
        led_radius = layout["led_diameter_mm"] / 2.0
        holes = layout["mounting"]["holes"]

        for row in layout["rows"]:
            self.assertEqual(len(row["led_angles_degrees"]), row["count"])
            radius = row["radius_mm"]
            for angle_degrees in row["led_angles_degrees"]:
                phi = math.radians(angle_degrees)
                x = radius * math.cos(phi)
                y = radius * math.sin(phi)
                for hole in holes:
                    clearance = math.hypot(x - hole["x_mm"], y - hole["y_mm"])
                    self.assertGreaterEqual(clearance, led_radius + hole["radius_mm"] + 1.5)
                nearest_axis = min(
                    abs((angle_degrees - cardinal + 180.0) % 360.0 - 180.0)
                    for cardinal in (0.0, 90.0, 180.0, 270.0)
                )
                self.assertGreaterEqual(nearest_axis, 8.0)


class TestRingLightV3ServerRegistration(unittest.TestCase):
    """N14: the tool registers only when SOLIDWORKS_MCP_PRODUCT_TOOLS lists it."""

    def test_v3_tool_registers_under_env_gate(self):
        code = (
            "from solidworks_mcp.server import mcp; "
            "assert mcp._tool_manager.get_tool("
            "'solidworks_part_create_ring_light_v3') is not None"
        )
        env = {
            **os.environ,
            "SOLIDWORKS_MCP_PRODUCT_TOOLS": "ring_light",
            "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        }
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


class _V3Sketch:
    def __init__(self):
        self.Name = "Sketch"
        self.GetNextFeature = lambda: None


class FakeV3Model:
    """COM double satisfying the STEP-based v3 build path."""

    def __init__(self):
        self.Extension = Mock()
        self.Extension.SelectByRay.return_value = True
        self.SketchManager = Mock()
        self.FeatureManager = Mock()
        self.FeatureManager.FeatureCut3.return_value = SimpleNamespace(Name="Cut")
        self.FeatureManager.FeatureExtrusion2.return_value = SimpleNamespace(
            Name="Boss"
        )
        self.sketch = _V3Sketch()

    def ClearSelection2(self, clear_all):
        return None

    def FeatureByPositionReverse(self, index):
        return SimpleNamespace(Select2=lambda append, mark: True)

    def FirstFeature(self):
        return self.sketch

    def GetTitle(self):
        return "RingLightV3"

    def SaveAs3(self, path, options, flags):
        return 0

    def Save3(self, options, errors, warnings):
        return True

    def ForceRebuild3(self, force):
        return True


class TestCreateRingLightV3EndToEnd(unittest.TestCase):
    @patch(
        "solidworks_mcp.products.ring_light_v3.check_overwrite_confirm",
        return_value=(True, ""),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.ensure_sink_path",
        side_effect=lambda path, allowed_root=None: (True, "", path),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.validate_output_file",
        return_value=(True, ""),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.validate_path",
        return_value=(True, ""),
    )
    def test_full_build_reports_quadrant_bands_and_layout(
        self, _path, _output, _sink, _confirm
    ):
        model = FakeV3Model()
        sw = Mock()
        sw.app.OpenDoc6.return_value = model

        with tempfile.TemporaryDirectory() as tmp:
            save_path = os.path.join(tmp, "v3.sldprt")
            result = create_ring_light_v3(sw, "source.sldprt", save_path)

            self.assertTrue(result["success"])
            # 48 bands, each split into four quadrants to keep cardinal ribs.
            self.assertEqual(len(result["data"]["dish_features"]), 192)
            self.assertIn("204 shallow", result["warning"])
            self.assertIn("21 raised", result["warning"])
            self.assertTrue(os.path.isfile(os.path.join(tmp, "v3.layout.json")))

    @patch(
        "solidworks_mcp.products.ring_light_v3.check_overwrite_confirm",
        return_value=(True, ""),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.ensure_sink_path",
        side_effect=lambda path, allowed_root=None: (True, "", path),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.validate_output_file",
        return_value=(True, ""),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.validate_path",
        return_value=(True, ""),
    )
    def test_unselectable_front_face_fails_gracefully(
        self, _path, _output, _sink, _confirm
    ):
        model = FakeV3Model()
        model.Extension.SelectByRay.return_value = False
        sw = Mock()
        sw.app.OpenDoc6.return_value = model

        result = create_ring_light_v3(sw, "source.sldprt", "out.sldprt")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    @patch(
        "solidworks_mcp.products.ring_light_v3.check_overwrite_confirm",
        return_value=(True, ""),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.ensure_sink_path",
        side_effect=lambda path, allowed_root=None: (True, "", path),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.validate_output_file",
        return_value=(True, ""),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.validate_path",
        return_value=(True, ""),
    )
    def test_unopenable_source_reports_import_failure(
        self, _path, _output, _sink, _confirm
    ):
        sw = Mock()
        sw.app.OpenDoc6.return_value = None
        sw.app.ActiveDoc = None

        result = create_ring_light_v3(sw, "source.step", "out.sldprt")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_IMPORT_FAILED")

    @patch(
        "solidworks_mcp.products.ring_light_v3.check_overwrite_confirm",
        return_value=(True, ""),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.ensure_sink_path",
        side_effect=lambda path, allowed_root=None: (True, "", path),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.validate_output_file",
        return_value=(True, ""),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.validate_path",
        return_value=(True, ""),
    )
    def test_step_source_falls_back_to_loadfile4(self, _path, _output, _sink, _confirm):
        model = FakeV3Model()
        sw = Mock()
        sw.app.OpenDoc6.return_value = None
        sw.app.LoadFile4.return_value = model
        sw.app.ActiveDoc = model

        with tempfile.TemporaryDirectory() as tmp:
            result = create_ring_light_v3(
                sw, "source.step", os.path.join(tmp, "v3.sldprt")
            )

            self.assertTrue(result["success"])
            sw.app.LoadFile4.assert_called_once()


if __name__ == "__main__":
    unittest.main()
