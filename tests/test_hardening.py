"""Wave-2 hardening tests.

Covers: junction-aware path normalization (review P1-7), normalized paths at
COM sinks, overwrite confirmation for derived artifacts (P1-6/action 17),
dynamic LED counts in ring-light output (P1-9), and version-driven template
candidates (action 18).
"""

from __future__ import annotations

import _winapi
import ctypes
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from solidworks_mcp.products import ring_light, ring_light_v3
from solidworks_mcp.solidworks_api.design import _save_active_model
from solidworks_mcp.utils.security import (
    _expand_long_path,
    ensure_sink_path,
    is_path_allowed,
    normalize_path,
)
from solidworks_mcp.utils.templates import _programdata_candidates


class _SketchFeature:
    def __init__(self, name: str = "Sketch"):
        self.Name = name
        self.GetNextFeature = lambda: None

    def Select2(self, append, mark):
        return True


class FakeRingLightModel:
    """COM double satisfying the native ring-light build path."""

    def __init__(self):
        self.Extension = Mock()
        self.Extension.SelectByID2.return_value = True
        self.SketchManager = Mock()
        self.FeatureManager = Mock()
        self.FeatureManager.FeatureCut3.return_value = SimpleNamespace(Name="Cut")
        self.FeatureManager.FeatureExtrusion2.return_value = SimpleNamespace(
            Name="Boss"
        )
        self.sketch = _SketchFeature()

    def ClearSelection2(self, clear_all):
        return None

    def FeatureByName(self, name):
        return SimpleNamespace(Select2=lambda append, mark: True)

    def FirstFeature(self):
        return self.sketch

    def ForceRebuild3(self, force):
        return True

    def SaveAs3(self, path, options, flags):
        return 0


class TestNormalizePathOrdering(unittest.TestCase):
    # GitHub-hosted runners hand tempfile a short-name TMP base
    # (C:\Users\RUNNER~1\...); normalize_path expands it to the long form,
    # so expectations must be built from the canonical base too.
    def _canonical_base(self, base: str) -> str:
        return normalize_path(base)

    def test_existing_prefix_resolves_junction_before_folding(self):
        with tempfile.TemporaryDirectory() as raw_base:
            base = self._canonical_base(raw_base)
            root = os.path.join(base, "root")
            outside = os.path.join(base, "outside")
            os.makedirs(root)
            os.makedirs(outside)
            link = os.path.join(root, "link")
            try:
                # In-process junction creation: spawning `cmd /c mklink` hangs
                # or fails outright under restricted sandboxes and exhausted
                # pagefiles (seen as WinError 1455), leaving orphaned test
                # processes behind. _winapi.CreateJunction needs no subprocess.
                _winapi.CreateJunction(outside, link)
            except OSError:
                self.skipTest("junction creation not permitted on this host")
            victim = os.path.join(root, "link", "..", "escape.sldprt")

            normalized = normalize_path(victim)

            self.assertEqual(normalized, os.path.join(base, "escape.sldprt"))
            self.assertFalse(is_path_allowed(normalized, root))

    def test_nonexistent_tail_resolves_deepest_existing_ancestor(self):
        with tempfile.TemporaryDirectory() as raw_base:
            base = self._canonical_base(raw_base)
            target = os.path.join(base, "a", "b", "new.sldprt")

            normalized = normalize_path(target)

            self.assertEqual(normalized, os.path.normpath(target))
            self.assertTrue(os.path.isabs(normalized))


class TestSinksUseNormalizedPaths(unittest.TestCase):
    def test_save_active_model_passes_normalized_path_to_solidworks(self):
        model = Mock()
        model.SaveAs3.return_value = 0
        result = {}
        with patch(
            "solidworks_mcp.solidworks_api.design.validate_output_file",
            return_value=(True, ""),
        ):
            self.assertIsNone(_save_active_model(model, "part.sldprt", False, result))

        model.SaveAs3.assert_called_once_with(normalize_path("part.sldprt"), 0, 1)
        self.assertEqual(result["saved_to"], "part.sldprt")

    def test_sink_recheck_rejects_junction_escape(self):
        with tempfile.TemporaryDirectory() as base:
            root = os.path.join(base, "root")
            outside = os.path.join(base, "outside")
            os.makedirs(root)
            os.makedirs(outside)
            link = os.path.join(root, "link")
            try:
                _winapi.CreateJunction(outside, link)
            except OSError:
                self.skipTest("junction creation not permitted on this host")

            ok, message, _normalized = ensure_sink_path(
                os.path.join(root, "link", "..", "escape.sldprt"),
                allowed_root=root,
            )

            self.assertFalse(ok)
            self.assertIn("save time", message)

    def test_sink_recheck_passes_normal_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "part.sldprt")

            ok, message, normalized = ensure_sink_path(
                target, allowed_root=tmp
            )

            self.assertTrue(ok)
            self.assertEqual(message, "")
            self.assertEqual(normalized, normalize_path(target))


class TestSessionFilter(unittest.TestCase):
    def test_own_process_matches_current_session(self):
        from solidworks_mcp.solidworks_api.app import _same_session
        import os

        self.assertTrue(_same_session(os.getpid()))

    def test_unqueryable_process_is_treated_as_other_session(self):
        from types import SimpleNamespace

        from solidworks_mcp.solidworks_api.app import _same_session

        fake = SimpleNamespace()
        fake.GetCurrentProcessId = lambda: 4242
        fake.ProcessIdToSessionId = lambda pid, out: False

        self.assertFalse(_same_session(9999, kernel32=fake))


class TestDerivedFileConfirmation(unittest.TestCase):
    @patch(
        "solidworks_mcp.products.ring_light.check_overwrite_confirm",
        return_value=(False, "File already exists"),
    )
    @patch(
        "solidworks_mcp.products.ring_light.validate_output_file",
        return_value=(True, ""),
    )
    def test_ring_light_rejects_existing_derived_artifacts(self, _validate, _confirm):
        result = ring_light.create_ring_light(Mock(), save_path="out.sldprt")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_OUTPUT_PATH")

    @patch(
        "solidworks_mcp.products.ring_light_v3.check_overwrite_confirm",
        return_value=(False, "File already exists"),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.validate_output_file",
        return_value=(True, ""),
    )
    @patch(
        "solidworks_mcp.products.ring_light_v3.validate_path",
        return_value=(True, ""),
    )
    def test_v3_rejects_existing_layout_json(self, _path, _output, _confirm):
        result = ring_light_v3.create_ring_light_v3(Mock(), "src.step", "out.sldprt")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INVALID_OUTPUT_PATH")


class TestRingLightDynamicCounts(unittest.TestCase):
    def _run_native_fallback(self, row_counts):
        layout = ring_light.build_ring_light_layout(row_counts=row_counts)
        model = FakeRingLightModel()
        sw = Mock()
        sw.get_active_document.return_value = model
        with patch.object(
            ring_light, "create_new_part", return_value={"success": True}
        ), patch.object(
            ring_light, "create_cylinder", return_value={"success": True}
        ):
            return ring_light._save_native_fallback(sw, layout, "out.sldprt")

    def test_message_and_feature_name_follow_custom_row_counts(self):
        result = self._run_native_fallback([1] * 9)

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["total_led_count"], 9)
        self.assertIn("LED_MARKERS_9_DOME_HEIGHT", result["data"]["features"])
        self.assertIn("9 LED markers", result["message"])
        self.assertNotIn("225", result["message"])

    def test_default_layout_reports_225(self):
        result = self._run_native_fallback(None)

        self.assertTrue(result["success"])
        self.assertIn("LED_MARKERS_225_DOME_HEIGHT", result["data"]["features"])
        self.assertIn("225 LED markers", result["message"])


class TestVersionDrivenTemplates(unittest.TestCase):
    def test_programdata_candidates_follow_configured_version(self):
        with patch.dict(
            os.environ, {"SOLIDWORKS_MCP_SOLIDWORKS_VERSION": "2027"}
        ):
            candidates = _programdata_candidates(["Part.prtdot"])

        self.assertEqual(
            candidates,
            [r"C:\ProgramData\SolidWorks\SolidWorks 2027\templates\Part.prtdot"],
        )


class TestNormalizeExpands8_3ShortNames(unittest.TestCase):
    """GitHub-hosted runners resolve realpath to 8.3 short names (RUNNER~1)
    for the temp profile; the CI first run (33582839316) failed on exactly
    that. normalize_path must expand existing components back to long
    names, so allowed-root containment cannot be bypassed by short-name
    drift (N24 fix batch)."""

    def test_existing_whole_path_short_name_is_expanded(self):
        # Simulate the runner: realpath yields the 8.3 form of an existing
        # path (PROGRA~1 really exists here, so the expansion is real).
        with patch(
            "os.path.realpath", return_value=r"C:\PROGRA~1"
        ):
            normalized = normalize_path(r"C:\Program Files")
        self.assertEqual(normalized, r"C:\Program Files")
        self.assertNotIn("~", normalized)

    def test_component_short_name_is_expanded_for_nonexistent_tail(self):
        target = r"C:\Program Files\deeply\nested\new.sldprt"
        realpath_calls = []

        def fake_realpath(p):
            realpath_calls.append(p)
            # First existing component canonicalizes to its short form
            if p == r"C:\Program Files":
                return r"C:\PROGRA~1"
            return p

        with patch("os.path.realpath", side_effect=fake_realpath):
            normalized = normalize_path(target)
        self.assertEqual(normalized, target)
        self.assertNotIn("~", normalized)
        self.assertTrue(realpath_calls)

    def test_undersized_buffer_falls_back_to_input(self):
        # GetLongPathNameW returns the *required size* (larger than the
        # buffer) when the buffer is too small, not the copied length;
        # that return value must be treated as failure so an undefined
        # buffer content is never trusted (code-review LOW hardening).
        tiny = ctypes.create_unicode_buffer(4)
        with patch("ctypes.create_unicode_buffer", return_value=tiny):
            expanded = _expand_long_path(r"C:\PROGRA~1")
        self.assertEqual(expanded, r"C:\PROGRA~1")


if __name__ == "__main__":
    unittest.main()



class TestLongPathRetry(unittest.TestCase):
    """N40/L-5: an undersized first buffer retries once with the required
    size and succeeds; a buffer that never fits still falls back."""

    def test_retry_with_required_size_succeeds(self):
        path = r"C:\PROGRA~1"
        long_name = r"C:\Program Files"  # 16 chars + null = 17 required

        class FakeBuffer:
            def __init__(self, size):
                self._chars = ["\0"] * size
                self.value = ""

            def __len__(self):
                return len(self._chars)

        tiny = FakeBuffer(4)
        big = FakeBuffer(17)
        big.value = long_name

        calls = {"n": 0}

        def fake_api(p, buf, size):
            calls["n"] += 1
            if calls["n"] == 1:
                return 17  # required size signal
            return len(long_name)  # copied length

        with patch(
            "ctypes.create_unicode_buffer", side_effect=lambda n: tiny if calls["n"] == 0 else big
        ), patch.object(
            ctypes.windll.kernel32, "GetLongPathNameW", side_effect=fake_api
        ):
            expanded = _expand_long_path(path)
        self.assertEqual(expanded, long_name)
        self.assertEqual(calls["n"], 2)
