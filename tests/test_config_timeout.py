"""COM timeout env parsing is locked behavior (ADR-0007 follow-up, N3).

Default changed from disabled (0) to 120s defense-in-depth (2026-08-30):
a stuck SolidWorks COM call now fails fast out of the box. Explicit
positive values still override; garbage/non-positive falls back to 120.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from solidworks_mcp import server
from solidworks_mcp.registry import misc as reg_misc
from solidworks_mcp.config import get_config
from solidworks_mcp.registry import base
from solidworks_mcp.utils.com_executor import ComExecutorPoisonedError


class TestComTimeoutConfig(unittest.TestCase):
    def test_unset_defaults_to_120_seconds(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOLIDWORKS_MCP_COM_TIMEOUT_SECONDS", None)
            self.assertEqual(get_config().com_timeout_seconds, 120.0)

    def test_valid_value_is_parsed(self):
        with patch.dict(os.environ, {"SOLIDWORKS_MCP_COM_TIMEOUT_SECONDS": "150"}):
            self.assertEqual(get_config().com_timeout_seconds, 150.0)

    def test_garbage_and_nonpositive_fall_back_to_120(self):
        for bad in ("abc", "-5", "0"):
            with patch.dict(os.environ, {"SOLIDWORKS_MCP_COM_TIMEOUT_SECONDS": bad}):
                self.assertEqual(get_config().com_timeout_seconds, 120.0)


class TestPoisonedRecovery(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"SOLIDWORKS_MCP_POISONED_EXIT": "0"})
        env.start()
        self.addCleanup(env.stop)

    def test_poisoned_call_returns_structured_result_with_recovery(self):
        with patch.object(
            base, "run_com", side_effect=ComExecutorPoisonedError("stuck")
        ):
            result = base.call_connected(lambda sw: {})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_EXECUTOR_POISONED")
        self.assertEqual(result["data"]["recovery"], "restart-mcp-session")
        self.assertIn("重启", result["message"])

    def test_poisoned_connect_tool_returns_same_structured_result(self):
        with patch.object(
            base, "run_com", side_effect=ComExecutorPoisonedError("stuck")
        ):
            result = reg_misc.solidworks_connect(launch_if_needed=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "SW_EXECUTOR_POISONED")
        self.assertEqual(result["data"]["recovery"], "restart-mcp-session")

    def test_poisoned_exit_switch_terminates_process(self):
        with patch.dict(os.environ, {"SOLIDWORKS_MCP_POISONED_EXIT": "1"}):
            with patch.object(
                base, "run_com", side_effect=ComExecutorPoisonedError("stuck")
            ):
                with self.assertRaises(SystemExit):
                    base.call_connected(lambda sw: {})


if __name__ == "__main__":
    unittest.main()
