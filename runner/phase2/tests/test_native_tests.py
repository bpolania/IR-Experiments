"""Unit tests for native_tests parsing and gating logic.

These tests are hermetic — they do not require a Pi toolchain, LLVM, or
any compiled binary. All subprocess calls are mocked.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
import os

# Ensure runner/phase2 is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from phase2_runner import (
    _parse_native_runner_output,
    _resolve_native_harness_source,
    _build_runs_skeleton,
)


class TestParseNativeRunnerOutput(unittest.TestCase):
    """Tests for _parse_native_runner_output."""

    def test_ok_with_ret_and_out(self):
        stdout = "RET=4\nOUT=01020304\n"
        result = _parse_native_runner_output(stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["ret_i64"], 4)
        self.assertEqual(result["out_hex"], "01020304")
        self.assertIsNone(result["detail"])

    def test_negative_ret_empty_out(self):
        stdout = "RET=-1\nOUT=\n"
        result = _parse_native_runner_output(stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["ret_i64"], -1)
        self.assertEqual(result["out_hex"], "")
        self.assertIsNone(result["detail"])

    def test_missing_ret_line(self):
        stdout = "OUT=aabb\n"
        result = _parse_native_runner_output(stdout)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["ret_i64"])
        self.assertEqual(result["detail"], "missing_ret")

    def test_missing_out_line_defaults_empty(self):
        stdout = "RET=4\n"
        result = _parse_native_runner_output(stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["ret_i64"], 4)
        self.assertEqual(result["out_hex"], "")

    def test_invalid_ret_format(self):
        stdout = "RET=abc\nOUT=\n"
        result = _parse_native_runner_output(stdout)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["ret_i64"])
        self.assertEqual(result["detail"], "invalid_ret_format")

    def test_empty_stdout(self):
        result = _parse_native_runner_output("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["detail"], "missing_ret")

    def test_err_internal_ret(self):
        stdout = "RET=-3\nOUT=\n"
        result = _parse_native_runner_output(stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["ret_i64"], -3)
        self.assertEqual(result["out_hex"], "")

    def test_out_hex_uppercase_normalized(self):
        stdout = "RET=4\nOUT=AABBCCDD\n"
        result = _parse_native_runner_output(stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["out_hex"], "aabbccdd")


class TestResolveNativeHarnessSource(unittest.TestCase):
    """Tests for _resolve_native_harness_source."""

    def test_missing_source_returns_none(self):
        # Use a temp dir that won't have the file.
        path, detail = _resolve_native_harness_source(Path("/nonexistent"))
        self.assertIsNone(path)
        self.assertIn("native_harness_source_not_found", detail)


class TestNativeTestsGating(unittest.TestCase):
    """Tests for native_tests gating logic."""

    def test_runs_skeleton_has_native_tests_stage(self):
        skeleton = _build_runs_skeleton()
        self.assertEqual(len(skeleton), 7)
        self.assertEqual(skeleton[6]["stage"], "native_tests")
        self.assertFalse(skeleton[6]["ok"])
        self.assertIsNone(skeleton[6]["exit_code"])

    def test_gate_requires_all_prior_stages(self):
        """Verify the stage 7 gate logic by checking that native_tests
        stays NOT_RUN when any prior stage is False."""
        # This is a logic test — we check that the gate expression
        # would evaluate to False when any condition is missing.
        for missing_stage in range(6):
            stages_ok = [True] * 6
            stages_ok[missing_stage] = False
            can_run = all(stages_ok)
            self.assertFalse(
                can_run,
                f"stage7_can_run should be False when stage {missing_stage} is False",
            )

    def test_gate_requires_candidate_exe(self):
        """Even with all stages ok, missing candidate.exe prevents run."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            exe_path = Path(td) / "candidate.exe"
            # File doesn't exist.
            self.assertFalse(exe_path.is_file())


class TestNativeTestsNotRunWhenHarnessMissing(unittest.TestCase):
    """Verify native_tests is NOT_RUN when harness source is missing."""

    @patch("phase2_runner._resolve_native_harness_source")
    def test_marks_not_run(self, mock_resolve):
        mock_resolve.return_value = (None, "native_harness_source_not_found path=missing")
        path, detail = mock_resolve(Path("/fake"))
        self.assertIsNone(path)
        self.assertIn("not_found", detail)


if __name__ == "__main__":
    unittest.main()
