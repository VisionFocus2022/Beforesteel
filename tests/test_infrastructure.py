"""Infrastructure tests: process detection, COM executor, server wrappers,
template getters, and COM late-binding edge cases."""

from __future__ import annotations

import json
import os
import threading
import unittest
from unittest.mock import patch

from solidworks_mcp import server
from solidworks_mcp.solidworks_api.app import _is_solidworks_process_running
from solidworks_mcp.utils.com import call_or_value
from solidworks_mcp.utils.com_executor import _executor, run_com
from solidworks_mcp.utils.templates import (
    get_assembly_template,
    get_drawing_template,
    get_part_template,
)


class TestProcessDetection(unittest.TestCase):
    def test_probe_returns_plain_boolean(self):
        # Runs the real Toolhelp32 snapshot; SLDWORKS.exe presence varies by
        # host, so only the contract is asserted.
        self.assertIsInstance(_is_solidworks_process_running(), bool)


class TestComExecutor(unittest.TestCase):
    def test_exceptions_propagate_to_caller(self):
        with self.assertRaises(ZeroDivisionError):
            run_com(lambda: 1 / 0)

    def test_reentrant_call_runs_inline_on_same_thread(self):
        def nested():
            outer = threading.get_ident()
            inner = run_com(lambda: threading.get_ident())
            return outer == inner

        self.assertTrue(run_com(nested))

    def test_executor_recovers_after_shutdown(self):
        first = run_com(threading.get_ident)
        _executor.shutdown()
        second = run_com(threading.get_ident)
        self.assertIsInstance(second, int)
        # Identifiers may or may not be reused by the OS; the executor must
        # transparently restart its worker either way.
        self.assertTrue(_executor._thread.is_alive())


class TestCallOrValue(unittest.TestCase):
    def test_cdispatch_objects_are_returned_unwrapped(self):
        class CDispatch:
            pass

        sentinel = CDispatch()
        holder = type("Holder", (), {"Child": sentinel})()

        self.assertIs(call_or_value(holder, "Child"), sentinel)


class TestServerToolWrappers(unittest.TestCase):
    SENTINEL = {
        "success": True,
        "data": None,
        "message": "ok",
        "warning": None,
        "error": None,
    }

    def test_every_tool_returns_structured_response(self):
        calls = [
            (server.solidworks_get_active_document, {}),
            (server.solidworks_part_new, {}),
            (
                server.solidworks_part_create_plate,
                {"width": 1, "depth": 1, "thickness": 1},
            ),
            (
                server.solidworks_part_create_box,
                {"width": 1, "depth": 1, "height": 1},
            ),
            (
                server.solidworks_part_create_cylinder,
                {"diameter": 1, "height": 1},
            ),
            (server.solidworks_part_cut_round_hole, {"diameter": 1}),
            (
                server.solidworks_part_create_annular_pattern,
                {"rings": [{"radius_mm": 10, "count": 4, "diameter_mm": 3}]},
            ),
            (
                server.solidworks_part_create_ring_light,
                {"save_path": "ring.sldprt"},
            ),
            (
                server.solidworks_part_create_ring_light_v3,
                {"source_path": "src.step", "save_path": "ring.sldprt"},
            ),
            (
                server.solidworks_design_execute_plan,
                {"operations": [{"type": "new_part"}]},
            ),
            (server.solidworks_part_get_mass_properties, {}),
            (server.solidworks_file_open, {"file_path": "part.sldprt"}),
            (server.solidworks_file_close, {}),
            (server.solidworks_file_import_step, {"file_path": "part.step"}),
            (server.solidworks_file_export_step, {"file_path": "part.step"}),
            (server.solidworks_file_export_stl, {"file_path": "part.stl"}),
            (server.solidworks_features_list, {}),
            (
                server.solidworks_feature_rename,
                {"old_name": "A", "new_name": "B"},
            ),
            (
                server.solidworks_feature_set_suppression,
                {"feature_name": "A", "suppressed": True},
            ),
            (
                server.solidworks_assembly_add_component,
                {"file_path": "part.sldprt"},
            ),
            (server.solidworks_assembly_list_components, {}),
            (
                server.solidworks_assembly_add_mate,
                {"mate_type": "coincident", "entity1": "A", "entity2": "B"},
            ),
        ]
        # N14: tools live in per-domain registry modules now, so the shared
        # _call_connected stub must be patched in every domain's namespace.
        from contextlib import ExitStack

        from solidworks_mcp.registry import (
            assembly,
            features,
            file_io,
            misc,
            part,
            products,
        )

        with ExitStack() as stack:
            for domain in (misc, part, features, file_io, assembly, products):
                stack.enter_context(
                    patch.object(
                        domain, "_call_connected", return_value=dict(self.SENTINEL)
                    )
                )
            for fn, kwargs in calls:
                with self.subTest(tool=fn.__name__):
                    self.assertEqual(fn(**kwargs), self.SENTINEL)

    def test_connect_maps_executor_failure_to_structured_error(self):
        from solidworks_mcp.registry import base

        with patch.object(base, "run_com", side_effect=RuntimeError("boom")):
            result = server.solidworks_connect(launch_if_needed=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_API_ERROR")

    def test_design_capabilities_responds_directly(self):
        result = server.solidworks_design_capabilities()

        self.assertTrue(result["success"])
        self.assertEqual(len(result["data"]["tools"]), 81)

    def test_resources_return_json_payloads(self):
        status = json.loads(server.solidworks_status_resource())
        self.assertIn("connected", status)

        with patch.object(
            server, "_call_connected", return_value=dict(self.SENTINEL)
        ):
            active = json.loads(server.solidworks_active_document_resource())
        self.assertTrue(active["success"])

        capabilities = json.loads(server.solidworks_capabilities_resource())
        self.assertEqual(len(capabilities["tools"]), 81)


class TestComTimeout(unittest.TestCase):
    def test_timeout_poisons_executor_and_fails_fast(self):
        from solidworks_mcp.utils.com_executor import (
            ComCallTimeoutError,
            ComExecutor,
            ComExecutorPoisonedError,
        )

        release = threading.Event()
        executor = ComExecutor()
        try:
            with self.assertRaises(ComCallTimeoutError):
                executor.call(release.wait, timeout=0.1)
            with self.assertRaises(ComExecutorPoisonedError):
                executor.call(lambda: "unreachable")
        finally:
            release.set()
            executor.shutdown()

    def test_com_timeout_env_is_parsed_and_enabled_by_default(self):
        self.assertEqual(server._com_timeout(), 120.0)
        with patch.dict(
            os.environ, {"SOLIDWORKS_MCP_COM_TIMEOUT_SECONDS": "12.5"}
        ):
            self.assertEqual(server._com_timeout(), 12.5)
        with patch.dict(os.environ, {"SOLIDWORKS_MCP_COM_TIMEOUT_SECONDS": "0"}):
            self.assertEqual(server._com_timeout(), 120.0)
        with patch.dict(
            os.environ, {"SOLIDWORKS_MCP_COM_TIMEOUT_SECONDS": "junk"}
        ):
            self.assertEqual(server._com_timeout(), 120.0)

    def test_connect_maps_timeout_to_dedicated_error_code(self):
        from solidworks_mcp.utils.com_executor import ComCallTimeoutError

        from solidworks_mcp.registry import base

        with patch.object(
            base, "run_com", side_effect=ComCallTimeoutError("too slow")
        ):
            result = server.solidworks_connect(launch_if_needed=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_TIMEOUT")


class TestTemplateGetters(unittest.TestCase):
    @patch("solidworks_mcp.utils.templates.os.path.isfile", return_value=True)
    def test_getters_return_first_existing_candidate(self, _isfile):
        self.assertIn("gb_part.prtdot", get_part_template())
        self.assertIn("gb_assembly.asmdot", get_assembly_template())
        self.assertIn("gb_a4p.drwdot", get_drawing_template())

    @patch("solidworks_mcp.utils.templates.os.path.isfile", return_value=False)
    def test_getters_return_none_when_nothing_exists(self, _isfile):
        self.assertIsNone(get_part_template())
        self.assertIsNone(get_assembly_template())
        self.assertIsNone(get_drawing_template())

    @patch("solidworks_mcp.utils.templates.os.path.isfile", return_value=True)
    def test_programdata_version_follows_environment(self, _isfile):
        with patch.dict(
            os.environ, {"SOLIDWORKS_MCP_SOLIDWORKS_VERSION": "2027"}
        ):
            self.assertIn("SolidWorks 2027", get_part_template())


if __name__ == "__main__":
    unittest.main()
