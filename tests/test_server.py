"""MCP registration and COM execution contract tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from solidworks_mcp import __version__
from solidworks_mcp.config import get_config
from solidworks_mcp.solidworks_api.app import SolidWorksApp
from solidworks_mcp.server import _capabilities, mcp
from solidworks_mcp.utils.com_executor import run_com


class TestServerRegistration(unittest.TestCase):
    def test_facade_reexports_every_registry_tool(self):
        # server.py's compatibility re-export promise ("the imports below
        # re-export the tool functions") must cover every registry tool def
        # as new tools land (sweep gap found by expert-sweep-20260906 AR-2).
        import importlib
        import inspect
        import pkgutil

        import solidworks_mcp.registry as registry_pkg
        import solidworks_mcp.server as server_mod

        tool_defs = set()
        for mod_info in pkgutil.iter_modules(registry_pkg.__path__):
            if mod_info.name in {"__init__", "base", "prompts"}:
                continue
            mod = importlib.import_module(
                f"solidworks_mcp.registry.{mod_info.name}"
            )
            for name, obj in vars(mod).items():
                if name.startswith("solidworks_") and inspect.isfunction(obj):
                    tool_defs.add(name)

        missing = sorted(
            name for name in tool_defs if not hasattr(server_mod, name)
        )
        self.assertEqual(
            missing,
            [],
            f"server.py facade misses re-export of {len(missing)} tool(s); "
            f"add them to the per-domain import blocks: {missing}",
        )

    def test_standard_surfaces_are_registered(self):
        tools = mcp._tool_manager.list_tools()
        resources = mcp._resource_manager.list_resources()
        prompts = mcp._prompt_manager.list_prompts()
        self.assertEqual(len(tools), 81)
        self.assertEqual(len(resources), 3)
        self.assertEqual(len(prompts), 5)

    def test_advertised_tool_list_matches_registration(self):
        registered = [tool.name for tool in mcp._tool_manager.list_tools()]
        self.assertEqual(registered, _capabilities()["tools"])

    def test_cone_and_threaded_hole_tools_are_registered(self):
        cone = mcp._tool_manager.get_tool("solidworks_part_create_cone")
        self.assertIsNotNone(cone)
        self.assertIn("bottom_diameter", cone.parameters["properties"])
        threaded = mcp._tool_manager.get_tool("solidworks_part_cut_threaded_hole")
        self.assertIsNotNone(threaded)
        self.assertIn("spec", threaded.parameters["properties"])

    def test_threaded_hole_spec_is_literal_enum(self):
        """N19: spec exposes the THREAD_SPECS enum so LLMs pick valid taps."""
        from typing import get_args

        from solidworks_mcp.registry.part import ThreadSpec
        from solidworks_mcp.solidworks_api.constants import THREAD_SPECS

        self.assertEqual(set(get_args(ThreadSpec)), set(THREAD_SPECS))
        threaded = mcp._tool_manager.get_tool("solidworks_part_cut_threaded_hole")
        enum = threaded.parameters["properties"]["spec"].get("enum")
        self.assertIsNotNone(enum, "spec must be a Literal so the schema carries an enum")
        self.assertEqual(set(enum), set(THREAD_SPECS))

    def test_n9_unlocked_tools_are_registered(self):
        mirror = mcp._tool_manager.get_tool("solidworks_features_mirror")
        draft = mcp._tool_manager.get_tool("solidworks_features_apply_draft")
        thread = mcp._tool_manager.get_tool("solidworks_part_cut_real_thread")
        holes = mcp._tool_manager.get_tool("solidworks_part_create_linear_holes")
        for tool in (mirror, draft, thread, holes):
            self.assertIsNotNone(tool)
        self.assertIn("neutral_face", draft.parameters["properties"])
        self.assertIn("profile_dia", thread.parameters["properties"])
        self.assertIn("count", holes.parameters["properties"])

    def test_handshake_version_matches_package(self):
        self.assertEqual(mcp._mcp_server.version, __version__)

    def test_every_tool_has_annotations_and_output_schema(self):
        for tool in mcp._tool_manager.list_tools():
            with self.subTest(tool=tool.name):
                self.assertIsNotNone(tool.annotations)
                self.assertIsNotNone(tool.output_schema)
                self.assertTrue(
                    {"success", "data", "message", "warning", "error"}
                    <= set(tool.output_schema["properties"])
                )

    def test_positive_dimensions_are_expressed_in_input_schema(self):
        tool = mcp._tool_manager.get_tool("solidworks_part_create_plate")
        self.assertEqual(tool.parameters["properties"]["width"]["exclusiveMinimum"], 0)

    def test_n8_assembly_repair_tools_are_registered(self):
        delete = mcp._tool_manager.get_tool("solidworks_assembly_delete_mate")
        self.assertIsNotNone(delete)
        self.assertTrue(delete.annotations.destructiveHint)
        move = mcp._tool_manager.get_tool("solidworks_assembly_move_component")
        self.assertIsNotNone(move)
        self.assertEqual(move.parameters["properties"]["dx"]["type"], "number")
        rotate = mcp._tool_manager.get_tool("solidworks_assembly_rotate_component")
        self.assertIsNotNone(rotate)
        self.assertEqual(
            rotate.parameters["properties"]["axis"]["enum"], ["x", "y", "z"]
        )

    def test_mate_type_is_an_enum(self):
        tool = mcp._tool_manager.get_tool("solidworks_assembly_add_mate")
        self.assertEqual(
            tool.parameters["properties"]["mate_type"]["enum"],
            ["coincident", "concentric", "distance", "tangent", "angle", "width"],
        )

    def test_n5_drawing_tools_forward_to_connected_call(self):
        from solidworks_mcp import server
        from solidworks_mcp.registry import drawing, file_io

        with patch.object(
            drawing, "_call_connected", return_value={"success": True}
        ) as draw_call, patch.object(
            file_io, "_call_connected", return_value={"success": True}
        ) as file_call:
            self.assertTrue(
                server.solidworks_drawing_set_tolerance("D1@f", 0.1, -0.05)["success"]
            )
            self.assertTrue(
                server.solidworks_drawing_insert_surface_finish(
                    1.6, 100.0, 50.0
                )["success"]
            )
            self.assertTrue(
                server.solidworks_drawing_insert_note("x", 10.0, 10.0)["success"]
            )
            self.assertTrue(server.solidworks_file_export_dxf("d.dxf")["success"])
        self.assertEqual(draw_call.call_count, 3)
        self.assertEqual(file_call.call_count, 1)


class TestProductToolGate(unittest.TestCase):
    """N14: ring-light product tools register only under their env gate."""

    def _registered_tools_in_subprocess(self, extra_env):
        code = (
            "import json; from solidworks_mcp.server import mcp; "
            "print(json.dumps([t.name for t in mcp._tool_manager.list_tools()]))"
        )
        env = {
            **os.environ,
            **extra_env,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        }
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_product_tools_are_hidden_by_default(self):
        tools = {tool.name for tool in mcp._tool_manager.list_tools()}
        self.assertNotIn("solidworks_part_create_ring_light", tools)
        self.assertNotIn("solidworks_part_create_ring_light_v3", tools)

    def test_default_subprocess_registers_79_tools(self):
        tools = self._registered_tools_in_subprocess({})
        self.assertEqual(len(tools), 81)
        self.assertNotIn("solidworks_part_create_ring_light", tools)

    def test_product_tools_register_under_env_gate(self):
        tools = self._registered_tools_in_subprocess(
            {"SOLIDWORKS_MCP_PRODUCT_TOOLS": "ring_light"}
        )
        self.assertEqual(len(tools), 83)
        self.assertIn("solidworks_part_create_ring_light", tools)
        self.assertIn("solidworks_part_create_ring_light_v3", tools)


class TestSolidWorksConnection(unittest.TestCase):
    def test_cached_connection_uses_method_or_property_revision(self):
        class FakeApp:
            def RevisionNumber(self):
                return "34.2.1"

        sw = SolidWorksApp()
        sw._app = FakeApp()
        result = sw.connect(launch_if_needed=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["version"], "34.2.1")
        self.assertEqual(result["message"], "Already connected to SolidWorks")

    @patch("solidworks_mcp.registry.base.run_com", side_effect=RuntimeError("worker failed"))
    def test_connect_returns_structured_error_when_com_executor_fails(self, _run_com):
        from solidworks_mcp.server import solidworks_connect

        result = solidworks_connect(launch_if_needed=False)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")
        self.assertNotIn("worker failed", result["message"])


class TestComExecutor(unittest.TestCase):
    def test_calls_share_one_com_thread(self):
        first = run_com(threading.get_ident)
        second = run_com(threading.get_ident)
        self.assertEqual(first, second)
        self.assertNotEqual(first, threading.get_ident())


class TestConfig(unittest.TestCase):
    def test_auto_start_environment_is_read_at_call_time(self):
        with patch.dict(os.environ, {"SOLIDWORKS_MCP_AUTO_START": "true"}):
            self.assertTrue(get_config().auto_start)


if __name__ == "__main__":
    unittest.main()

