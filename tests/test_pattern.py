"""Generic annular pattern tests: layout math, COM doubles, registration."""

from __future__ import annotations

import math
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError

from solidworks_mcp.solidworks_api.pattern import (
    AnnularRing,
    build_annular_layout,
    create_annular_pattern,
)
from solidworks_mcp.server import mcp
from solidworks_mcp.registry import part as reg_part


class TestAnnularRingSchema(unittest.TestCase):
    def test_rejects_non_positive_geometry(self):
        with self.assertRaises(ValidationError):
            AnnularRing(radius_mm=0, count=4, diameter_mm=3)
        with self.assertRaises(ValidationError):
            AnnularRing(radius_mm=10, count=0, diameter_mm=3)
        with self.assertRaises(ValidationError):
            AnnularRing(radius_mm=10, count=4, diameter_mm=0)

    def test_rejects_nan_and_out_of_range_phase(self):
        with self.assertRaises(ValidationError):
            AnnularRing(radius_mm=float("nan"), count=4, diameter_mm=3)
        with self.assertRaises(ValidationError):
            AnnularRing(radius_mm=10, count=4, diameter_mm=3, phase_degrees=361)

    def test_rejects_absurd_dimensions(self):
        with self.assertRaises(ValidationError):
            AnnularRing(radius_mm=2e6, count=4, diameter_mm=3)
        with self.assertRaises(ValidationError):
            AnnularRing(radius_mm=10, count=4, diameter_mm=2e6)

    def test_accepts_minimal_ring_with_default_phase(self):
        ring = AnnularRing(radius_mm=10, count=4, diameter_mm=3)
        self.assertIsNone(ring.phase_degrees)


class TestBuildAnnularLayout(unittest.TestCase):
    def test_single_ring_positions_at_cardinals(self):
        layout = build_annular_layout(
            [AnnularRing(radius_mm=10, count=4, diameter_mm=3, phase_degrees=0)]
        )
        positions = layout["rings"][0]["positions_xy_mm"]
        self.assertEqual(len(positions), 4)
        for (x, y), expected in zip(
            positions, [(10.0, 0.0), (0.0, 10.0), (-10.0, 0.0), (0.0, -10.0)]
        ):
            self.assertAlmostEqual(x, expected[0], places=6)
            self.assertAlmostEqual(y, expected[1], places=6)

    def test_explicit_phase_rotates_first_position(self):
        layout = build_annular_layout(
            [AnnularRing(radius_mm=10, count=1, diameter_mm=3, phase_degrees=45)]
        )
        x, y = layout["rings"][0]["positions_xy_mm"][0]
        self.assertAlmostEqual(x, 10 * math.cos(math.radians(45)), places=6)
        self.assertAlmostEqual(y, 10 * math.sin(math.radians(45)), places=6)

    def test_avoid_angles_choose_max_clearance_phase(self):
        layout = build_annular_layout(
            [AnnularRing(radius_mm=10, count=8, diameter_mm=2)],
            avoid_angles_degrees=[0, 90, 180, 270],
        )
        self.assertAlmostEqual(layout["rings"][0]["phase_degrees"], 22.5, places=6)

    def test_single_blocked_angle_optimizes_to_quarter_pitch(self):
        layout = build_annular_layout(
            [AnnularRing(radius_mm=10, count=4, diameter_mm=2)],
            avoid_angles_degrees=[0],
        )
        self.assertAlmostEqual(layout["rings"][0]["phase_degrees"], 45.0, places=6)

    def test_explicit_phase_beats_optimization(self):
        layout = build_annular_layout(
            [AnnularRing(radius_mm=10, count=8, diameter_mm=2, phase_degrees=0)],
            avoid_angles_degrees=[0, 90, 180, 270],
        )
        self.assertAlmostEqual(layout["rings"][0]["phase_degrees"], 0.0, places=6)

    def test_indices_and_totals(self):
        layout = build_annular_layout(
            [
                AnnularRing(radius_mm=20, count=6, diameter_mm=5),
                AnnularRing(radius_mm=30, count=12, diameter_mm=3),
            ]
        )
        self.assertEqual(
            [row["ring_index"] for row in layout["rings"]], [1, 2]
        )
        self.assertEqual(layout["total_feature_count"], 18)

    def test_ring_count_and_total_instance_limits(self):
        rings = [AnnularRing(radius_mm=10 + i, count=1, diameter_mm=1) for i in range(101)]
        with self.assertRaises(ValueError):
            build_annular_layout(rings)
        with self.assertRaises(ValueError):
            build_annular_layout(
                [AnnularRing(radius_mm=10, count=1000, diameter_mm=1)] * 6
            )

    def test_empty_and_nan_inputs_are_invalid(self):
        with self.assertRaises(ValueError):
            build_annular_layout([])
        with self.assertRaises(ValueError):
            build_annular_layout(
                [AnnularRing(radius_mm=10, count=4, diameter_mm=3)],
                avoid_angles_degrees=[float("nan")],
            )

    def test_within_ring_overlap_warning(self):
        layout = build_annular_layout(
            [AnnularRing(radius_mm=10, count=12, diameter_mm=6)]
        )
        self.assertTrue(
            any("overlap" in warning for warning in layout["warnings"])
        )

    def test_cross_ring_overlap_warning(self):
        layout = build_annular_layout(
            [
                AnnularRing(radius_mm=10, count=8, diameter_mm=8),
                AnnularRing(radius_mm=11, count=8, diameter_mm=8),
            ]
        )
        self.assertTrue(
            any("radially" in warning for warning in layout["warnings"])
        )

    def test_clear_layout_has_no_warnings(self):
        layout = build_annular_layout(
            [
                AnnularRing(radius_mm=20, count=6, diameter_mm=3),
                AnnularRing(radius_mm=40, count=12, diameter_mm=3),
            ]
        )
        self.assertEqual(layout["warnings"], [])


class _PatternSketch:
    def __init__(self):
        self.Name = "Sketch"
        self.GetNextFeature = lambda: None


class FakePatternModel:
    """COM double satisfying the annular pattern build path."""

    def __init__(self):
        self.Extension = Mock()
        self.Extension.SelectByID2.return_value = True
        self.SketchManager = Mock()
        self.FeatureManager = Mock()
        self.FeatureManager.FeatureCut3.return_value = SimpleNamespace(Name="Cut")
        self.FeatureManager.FeatureExtrusion2.return_value = SimpleNamespace(
            Name="Boss"
        )
        self.sketch = _PatternSketch()
        self.feature_by_name_calls = 0

    def GetType(self):
        return 1

    def ClearSelection2(self, clear_all):
        return None

    def FeatureByName(self, name):
        self.feature_by_name_calls += 1
        return SimpleNamespace(Select2=lambda append, mark: True)

    def FirstFeature(self):
        return self.sketch

    def SaveAs3(self, path, options, flags):
        return 0


def _fake_sw(model):
    sw = Mock()
    sw.get_active_document.return_value = model
    return sw


class TestCreateAnnularPattern(unittest.TestCase):
    RINGS = [
        AnnularRing(radius_mm=20, count=6, diameter_mm=5, phase_degrees=0),
        AnnularRing(radius_mm=30, count=12, diameter_mm=3, phase_degrees=15),
    ]

    def test_cut_through_all_creates_named_feature_per_ring(self):
        model = FakePatternModel()
        result = create_annular_pattern(_fake_sw(model), self.RINGS)

        self.assertTrue(result["success"])
        self.assertEqual(
            result["data"]["features"],
            ["ANNULAR_CUT_RING_01_R20.00_N6", "ANNULAR_CUT_RING_02_R30.00_N12"],
        )
        self.assertEqual(result["data"]["total_feature_count"], 18)
        cut_call = model.FeatureManager.FeatureCut3.call_args
        self.assertEqual(cut_call.args[3], 1)  # end condition: through all
        self.assertTrue(cut_call.args[2])

    def test_plane_is_reselected_before_every_ring_sketch(self):
        model = FakePatternModel()
        result = create_annular_pattern(_fake_sw(model), self.RINGS)

        self.assertTrue(result["success"])
        # Two rings: open+close sketch per ring, and one plane selection
        # per ring (the previous ring's feature creation consumed the
        # selection — regression lock for the multi-ring HIGH finding).
        self.assertEqual(model.SketchManager.InsertSketch.call_count, 4)
        self.assertEqual(model.feature_by_name_calls, 2)

    def test_avoid_angle_cap_and_deduplication(self):
        layout = build_annular_layout(
            [AnnularRing(radius_mm=10, count=8, diameter_mm=2)],
            avoid_angles_degrees=[0, 360, 720, 90, 90.0],
        )
        self.assertEqual(layout["avoid_angles_degrees"], [0.0, 90.0])
        with self.assertRaises(ValueError):
            build_annular_layout(
                [AnnularRing(radius_mm=10, count=8, diameter_mm=2)],
                avoid_angles_degrees=[float(i) for i in range(73)],
            )

    def test_phase_optimization_survives_large_inputs_quickly(self):
        # Worst legal case: max per-ring count and max deduplicated angles.
        blocked = [i * 5.0 for i in range(72)]
        layout = build_annular_layout(
            [AnnularRing(radius_mm=10, count=1000, diameter_mm=1)],
            avoid_angles_degrees=blocked,
        )
        self.assertEqual(layout["total_feature_count"], 1000)
        self.assertTrue(0.0 <= layout["rings"][0]["phase_degrees"] < 360.0)

    def test_non_positive_depth_is_invalid_parameter(self):
        sw = _fake_sw(FakePatternModel())
        self.assertEqual(
            create_annular_pattern(
                sw, self.RINGS[:1], through_all=False, depth=-5.0
            )["error"]["code"],
            "INVALID_PARAMETER",
        )
        self.assertEqual(
            create_annular_pattern(
                sw, self.RINGS[:1], feature_kind="boss", depth=0.0
            )["error"]["code"],
            "INVALID_PARAMETER",
        )

    def test_save_path_is_validated_before_any_geometry(self):
        model = FakePatternModel()
        with patch(
            "solidworks_mcp.solidworks_api.pattern.validate_output_file",
            return_value=(False, "bad path"),
        ):
            result = create_annular_pattern(
                _fake_sw(model), self.RINGS, save_path="out.sldprt"
            )

        self.assertEqual(result["error"]["code"], "INVALID_OUTPUT_PATH")
        model.SketchManager.InsertSketch.assert_not_called()

    def test_blind_cut_passes_depth_in_meters(self):
        model = FakePatternModel()
        result = create_annular_pattern(
            _fake_sw(model),
            self.RINGS[:1],
            through_all=False,
            depth=4.0,
        )

        self.assertTrue(result["success"])
        cut_call = model.FeatureManager.FeatureCut3.call_args
        self.assertEqual(cut_call.args[3], 0)  # end condition: blind
        self.assertAlmostEqual(cut_call.args[5], 0.004, places=9)

    def test_boss_uses_extrusion_with_depth(self):
        model = FakePatternModel()
        result = create_annular_pattern(
            _fake_sw(model),
            [self.RINGS[0]],
            feature_kind="boss",
            depth=3.0,
        )

        self.assertTrue(result["success"])
        self.assertIn("ANNULAR_BOSS_RING_01", result["data"]["features"][0])
        extrude_call = model.FeatureManager.FeatureExtrusion2.call_args
        self.assertAlmostEqual(extrude_call.args[5], 0.003, places=9)

    def test_parameter_validation_errors(self):
        sw = _fake_sw(FakePatternModel())
        cases = [
            dict(rings=self.RINGS, feature_kind="rib"),
            dict(rings=self.RINGS, through_all=False),
            dict(rings=self.RINGS, feature_kind="boss"),
            dict(rings=self.RINGS, plane=" "),
        ]
        for kwargs in cases:
            with self.subTest(**{k: str(v)[:24] for k, v in kwargs.items()}):
                result = create_annular_pattern(sw, **kwargs)
                self.assertEqual(
                    result["error"]["code"], "INVALID_PARAMETER"
                )

    def test_unselectable_plane_reports_error(self):
        model = FakePatternModel()
        model.FeatureByName = lambda name: None
        model.Extension.SelectByID2.return_value = False

        result = create_annular_pattern(_fake_sw(model), self.RINGS)

        self.assertFalse(result["success"])
        self.assertIn("select plane", result["message"])

    def test_feature_creation_failure_is_structured(self):
        model = FakePatternModel()
        model.FeatureManager.FeatureCut3.return_value = None

        result = create_annular_pattern(_fake_sw(model), self.RINGS)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    def test_com_errors_are_structured(self):
        sw = Mock()
        sw.get_active_document.side_effect = RuntimeError("COM")

        result = create_annular_pattern(sw, self.RINGS)

        self.assertFalse(result["success"])

    def test_save_path_surfaces_save_helper_result(self):
        model = FakePatternModel()
        with patch(
            "solidworks_mcp.solidworks_api.pattern._save_active_model",
            return_value={
                "success": False,
                "data": None,
                "message": "bad path",
                "warning": None,
                "error": {"code": "INVALID_OUTPUT_PATH", "details": None},
            },
        ) as save_mock:
            result = create_annular_pattern(
                _fake_sw(model), self.RINGS, save_path="out.sldprt"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_OUTPUT_PATH")
        save_mock.assert_called_once()


class TestPatternRegistration(unittest.TestCase):
    def test_pattern_tools_are_registered_with_item_schema(self):
        tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}

        self.assertIn("solidworks_pattern_annular_layout", tools)
        create = tools["solidworks_part_create_annular_pattern"]
        rings_schema = create.parameters["properties"]["rings"]
        self.assertEqual(rings_schema["type"], "array")
        ref_name = rings_schema["items"]["$ref"].rsplit("/", 1)[-1]
        ring_model = create.parameters["$defs"][ref_name]
        self.assertEqual(
            ring_model["properties"]["radius_mm"]["exclusiveMinimum"], 0
        )
        self.assertEqual(
            ring_model["properties"]["count"]["exclusiveMinimum"], 0
        )
        self.assertEqual(
            create.parameters["properties"]["feature_kind"]["enum"],
            ["cut", "boss"],
        )

    def test_layout_tool_computes_without_solidworks(self):
        result = reg_part.solidworks_pattern_annular_layout(
            rings=[AnnularRing(radius_mm=10, count=4, diameter_mm=3)]
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["total_feature_count"], 4)
        self.assertEqual(len(result["data"]["rings"][0]["positions_xy_mm"]), 4)


if __name__ == "__main__":
    unittest.main()
