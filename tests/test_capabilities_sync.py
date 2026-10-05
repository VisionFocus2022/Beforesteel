"""N2: capabilities/docstring 与实现同步的防漂移契约。"""
import json
import unittest

from solidworks_mcp import server
from solidworks_mcp.solidworks_api.design import DESIGN_PLAN_OPERATIONS


def _registered():
    return {t.name: t for t in server.mcp._tool_manager.list_tools()}


class TestCapabilitiesSync(unittest.TestCase):
    def test_execute_plan_docstring_lists_all_operations(self):
        desc = _registered()["solidworks_design_execute_plan"].description
        for op in DESIGN_PLAN_OPERATIONS:
            self.assertIn(op, desc)

    def test_capabilities_json_lists_all_operations(self):
        caps_text = json.dumps(server._capabilities(), ensure_ascii=False)
        for op in DESIGN_PLAN_OPERATIONS:
            self.assertIn(op, caps_text)

    def test_example_types_match_operations(self):
        examples = server._capabilities()["design_plan_operations"]
        self.assertEqual({e["type"] for e in examples}, set(DESIGN_PLAN_OPERATIONS))

    def test_limitations_snapshot(self):
        # Positive lock: any limitations edit must consciously update this list.
        caps = server._capabilities()
        self.assertEqual(
            caps["limitations"],
            [
                "Design plans currently support primitive bosses (box/plate/cylinder/cone), round cut holes, ISO threaded holes, and annular patterns.",
                "solidworks_part_create_ring_light generates a validated spherical-dome LED layout (row_counts is free-form, defaulting to the confirmed 9-row product layout); the native SLDPRT uses 24 annular bands when FeatureRevolve2 is unavailable.",
                "Assembly mates use the compatibility AddMate5 API for basic mate types.",
                "Complex surfaces, GD&T feature-control frames, simulation, and PDM are not yet exposed.",
                "Drawing BOM balloons (AutoBalloon family) are blocked by the SolidWorks API on this machine; use drawing_insert_bom_table instead.",
                "Exploded-state drawing projection is an open observation item; project from the saved model configuration.",
                "solidworks_part_circular_pattern drives the PropertyManager pane via UI automation: it needs a visible, maximized SolidWorks window with the standard toolbar layout on a 1920x1040 desktop (N58; pixel-calibrated offsets).",
            ],
        )

    def test_no_stale_negations_for_registered_capabilities(self):
        # Reverse lock keyed by capability keyword (not domain word): if the
        # paired tool is registered, its keyword must not appear in any
        # "not yet exposed" line. Add a pair whenever a tool lands.
        keyword_to_tool = {
            "loft": "solidworks_part_create_loft",
            "sweep": "solidworks_part_create_swept",
            "rib": "solidworks_part_create_rib",
            "dome": "solidworks_part_apply_dome",
            "polygon": "solidworks_part_create_polygon",
            "slot": "solidworks_part_create_slot",
            "ref_plane": "solidworks_part_create_ref_plane",
            "ref_axis": "solidworks_part_create_ref_axis",
            "explode": "solidworks_assembly_explode",
            "sheet metal": "solidworks_sheet_metal_base_flange",
        }
        caps = server._capabilities()
        tools = set(caps["tools"])
        for keyword, tool in keyword_to_tool.items():
            if tool not in tools:
                continue
            for line in caps["limitations"]:
                if "not yet" not in line:
                    continue
                self.assertNotIn(
                    keyword,
                    line.lower(),
                    f"stale limitation: {line!r} negates registered tool {tool}",
                )

    def test_add_mate_states_unit_semantics(self):
        desc = _registered()["solidworks_assembly_add_mate"].description
        self.assertIn("degrees", desc)
        self.assertIn("millimeter", desc.lower())


if __name__ == "__main__":
    unittest.main()
