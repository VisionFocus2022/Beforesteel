"""Unit tests for utility modules using the built-in unittest framework."""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

# Ensure the project package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from solidworks_mcp.utils.common import error_response, success_response
from solidworks_mcp.utils.security import (
    check_overwrite_confirm,
    is_path_allowed,
    normalize_path,
    validate_extension,
    validate_output_file,
    validate_path,
)
from solidworks_mcp.utils.templates import find_template
from solidworks_mcp.utils.com import call_or_value
from solidworks_mcp.utils.validation import finite_number, parse_bool, positive_number


class TestCommonResponse(unittest.TestCase):
    def test_success_response(self):
        result = success_response(data={"x": 1}, message="Done")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"], {"x": 1})
        self.assertEqual(result["message"], "Done")
        self.assertIsNone(result["warning"])

    def test_error_response(self):
        result = error_response(message="Failed")
        self.assertFalse(result["success"])
        self.assertIsNone(result["data"])
        self.assertEqual(result["message"], "Failed")
        self.assertEqual(result["error"]["code"], "OPERATION_FAILED")


class TestSecurity(unittest.TestCase):
    def test_normalize_path_resolves_relative(self):
        self.assertTrue(os.path.isabs(normalize_path("some/relative/path")))

    def test_default_allowed_root_reads_env_at_call_time(self):
        """P-2 回归（2026-10-05）：allowed_root 惰性求值——import 后设置
        SOLIDWORKS_MCP_ALLOWED_ROOT 必须生效（此前 import 期冻结被静默忽略）。"""
        from solidworks_mcp.utils.security import default_allowed_root

        fake_root = os.path.abspath(os.sep + "swmcp" + os.sep + "lazy-root")
        with patch.dict(
            os.environ, {"SOLIDWORKS_MCP_ALLOWED_ROOT": fake_root}
        ):
            self.assertEqual(default_allowed_root(), os.path.normpath(fake_root))

    def test_is_path_allowed_within_root(self):
        self.assertTrue(
            is_path_allowed(
                r"E:\SolidWorks 2026\test.step",
                r"E:\SolidWorks 2026",
            )
        )

    def test_is_path_allowed_outside_root(self):
        self.assertFalse(
            is_path_allowed(
                r"C:\Windows\test.step",
                r"E:\SolidWorks 2026",
            )
        )

    def test_is_path_allowed_traversal_blocked(self):
        self.assertFalse(
            is_path_allowed(
                r"E:\SolidWorks 2026\..\Windows\test.step",
                r"E:\SolidWorks 2026",
            )
        )

    def test_validate_path_rejects_empty(self):
        valid, msg = validate_path("")
        self.assertFalse(valid)
        self.assertIn("non-empty", msg)

    def test_validate_path_must_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nonexistent.file")
            valid, msg = validate_path(missing, allowed_root=tmp, must_exist=True)
            self.assertFalse(valid)
            self.assertIn("does not exist", msg)

    def test_validate_path_rejects_existing_when_must_not_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = os.path.join(tmp, "existing.txt")
            with open(existing, "w") as f:
                f.write("hello")
            valid, msg = validate_path(existing, allowed_root=tmp, must_not_exist=True)
            self.assertFalse(valid)
            self.assertIn("already exists", msg)

    def test_validate_path_requires_existing_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "missing", "part.sldprt")
            valid, msg = validate_path(
                target,
                allowed_root=tmp,
                parent_must_exist=True,
            )
            self.assertFalse(valid)
            self.assertIn("Parent directory", msg)

    def test_validate_extension_is_case_insensitive(self):
        valid, _ = validate_extension("part.STEP", {".step", ".stp"})
        self.assertTrue(valid)

    def test_validate_extension_rejects_wrong_format(self):
        valid, msg = validate_extension("part.stl", {".step", ".stp"})
        self.assertFalse(valid)
        self.assertIn(".step", msg)

    def test_validate_output_file_checks_extension_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "part.stl")
            valid, msg = validate_output_file(
                target,
                {".sldprt"},
                allowed_root=tmp,
            )
            self.assertFalse(valid)
            self.assertIn("extension", msg)

    def test_check_overwrite_confirm_blocks_without_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = os.path.join(tmp, "existing.txt")
            with open(existing, "w") as f:
                f.write("hello")
            allowed, msg = check_overwrite_confirm(existing, overwrite_confirm=False)
            self.assertFalse(allowed)
            self.assertIn("overwrite_confirm", msg)

    def test_check_overwrite_confirm_allows_with_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = os.path.join(tmp, "existing.txt")
            with open(existing, "w") as f:
                f.write("hello")
            allowed, msg = check_overwrite_confirm(existing, overwrite_confirm=True)
            self.assertTrue(allowed)


class TestTemplates(unittest.TestCase):
    def test_find_template_returns_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_template = os.path.join(tmp, "Part.prtdot")
            with open(fake_template, "w") as f:
                f.write("fake")
            result = find_template([fake_template, os.path.join(tmp, "missing.prtdot")])
            self.assertEqual(result, fake_template)

    def test_find_template_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = find_template([os.path.join(tmp, "missing.prtdot")])
            self.assertIsNone(result)


class TestComHelpers(unittest.TestCase):
    def test_call_or_value_calls_method(self):
        class MethodObject:
            def GetTitle(self):
                return "Part1"

        self.assertEqual(call_or_value(MethodObject(), "GetTitle"), "Part1")

    def test_call_or_value_returns_property(self):
        class PropertyObject:
            GetTitle = "Part2"

        self.assertEqual(call_or_value(PropertyObject(), "GetTitle"), "Part2")


class TestValidation(unittest.TestCase):
    def test_parse_bool_handles_false_string(self):
        self.assertFalse(parse_bool("through_all", "false"))

    def test_parse_bool_rejects_ambiguous_value(self):
        with self.assertRaises(ValueError):
            parse_bool("through_all", "sometimes")

    def test_positive_number_rejects_nan(self):
        with self.assertRaises(ValueError):
            positive_number("diameter", float("nan"))

    def test_finite_number_accepts_zero(self):
        self.assertEqual(finite_number("x", 0), 0.0)


if __name__ == "__main__":
    unittest.main()
