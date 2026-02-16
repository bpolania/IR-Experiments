"""Unit tests for compute_verdict logic.

Hermetic — no Pi toolchain, LLVM, or compiled binary required.
"""

from __future__ import annotations

import unittest
import sys
import os

# Ensure runner/phase2 is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from phase2_runner import compute_verdict, _build_runs_skeleton


def _make_runs_all_pass():
    """Build a runs list where all 7 stages executed and passed."""
    stages = [
        "precheck", "llvm_as_parse", "opt_verify", "lli_tests",
        "llc_compile", "clang_link", "native_tests",
    ]
    return [
        {
            "stage": name,
            "ok": True,
            "exit_code": 0,
            "duration_ms": 10,
            "rss_mib": 1.0,
            "crash": None,
        }
        for name in stages
    ]


def _make_metrics_all_pass():
    """Metrics with 10/10 lli and 10/10 native, zero failures."""
    return {
        "tests_total": 10,
        "tests_passed": 10,
        "tests_failed": 0,
        "ret_mismatches": 0,
        "output_mismatches": 0,
        "timeouts": 0,
        "crashes": 0,
        "native_tests_total": 10,
        "native_tests_passed": 10,
        "native_tests_failed": 0,
        "native_ret_mismatches": 0,
        "native_output_mismatches": 0,
        "native_timeouts": 0,
        "native_crashes": 0,
    }


def _make_gates_stub():
    """Minimal gates object for compute_verdict."""
    return {
        "parse": {"ok": True, "detail": ""},
        "verify": {"ok": True, "detail": ""},
        "policy": {"ok": False, "detail": ""},
        "tests": {"ok": True, "detail": ""},
    }


class TestComputeVerdictPass(unittest.TestCase):
    """PASS: all stages ok, zero test failures."""

    def test_all_pass(self):
        runs = _make_runs_all_pass()
        metrics = _make_metrics_all_pass()
        gates = _make_gates_stub()
        verdict, detail = compute_verdict(runs, metrics, gates)
        self.assertEqual(verdict, "PASS")
        self.assertEqual(detail, "ALL_STAGES_PASS")

    def test_pass_without_native(self):
        """PASS when native metrics are absent (pre-Step-H artifact)."""
        runs = _make_runs_all_pass()
        # Mark native_tests as NOT_RUN.
        runs[6] = {
            "stage": "native_tests",
            "ok": True,
            "exit_code": 0,
            "duration_ms": 0,
            "rss_mib": None,
            "crash": None,
        }
        # But keep all ok=True (skeleton default overridden).
        metrics = _make_metrics_all_pass()
        del metrics["native_tests_failed"]
        del metrics["native_tests_total"]
        del metrics["native_tests_passed"]
        del metrics["native_ret_mismatches"]
        del metrics["native_output_mismatches"]
        del metrics["native_timeouts"]
        del metrics["native_crashes"]
        gates = _make_gates_stub()
        verdict, detail = compute_verdict(runs, metrics, gates)
        self.assertEqual(verdict, "PASS")


class TestComputeVerdictFailStage(unittest.TestCase):
    """FAIL: one executed stage has ok=False."""

    def test_stage_failed(self):
        runs = _make_runs_all_pass()
        runs[2]["ok"] = False  # opt_verify fails
        metrics = _make_metrics_all_pass()
        gates = _make_gates_stub()
        verdict, detail = compute_verdict(runs, metrics, gates)
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(detail, "STAGE_FAILED:opt_verify")

    def test_first_stage_failed(self):
        runs = _make_runs_all_pass()
        runs[0]["ok"] = False  # precheck fails
        metrics = _make_metrics_all_pass()
        gates = _make_gates_stub()
        verdict, detail = compute_verdict(runs, metrics, gates)
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(detail, "STAGE_FAILED:precheck")


class TestComputeVerdictFailLliTests(unittest.TestCase):
    """FAIL: lli tests_failed > 0."""

    def test_lli_tests_failed(self):
        runs = _make_runs_all_pass()
        metrics = _make_metrics_all_pass()
        metrics["tests_failed"] = 3
        gates = _make_gates_stub()
        verdict, detail = compute_verdict(runs, metrics, gates)
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(detail, "LLI_TESTS_FAILED")


class TestComputeVerdictFailNativeTests(unittest.TestCase):
    """FAIL: native_tests_failed > 0."""

    def test_native_tests_failed(self):
        runs = _make_runs_all_pass()
        metrics = _make_metrics_all_pass()
        metrics["native_tests_failed"] = 1
        gates = _make_gates_stub()
        verdict, detail = compute_verdict(runs, metrics, gates)
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(detail, "NATIVE_TESTS_FAILED")


class TestComputeVerdictError(unittest.TestCase):
    """ERROR: no stages executed."""

    def test_no_stages_executed(self):
        # Fresh skeleton: all stages NOT_RUN.
        runs = _build_runs_skeleton()
        metrics = {
            "tests_total": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "ret_mismatches": 0,
            "output_mismatches": 0,
            "timeouts": 0,
            "crashes": 0,
        }
        gates = _make_gates_stub()
        verdict, detail = compute_verdict(runs, metrics, gates)
        self.assertEqual(verdict, "ERROR")
        self.assertEqual(detail, "NO_STAGES_EXECUTED")


class TestComputeVerdictNotRunDownstream(unittest.TestCase):
    """FAIL: upstream passes but downstream NOT_RUN due to gating."""

    def test_partial_execution_with_failure(self):
        """lli_tests fails, downstream stages NOT_RUN -> FAIL."""
        runs = _make_runs_all_pass()
        # lli_tests failed
        runs[3]["ok"] = False
        # Downstream stages NOT_RUN
        for i in [4, 5, 6]:
            runs[i] = {
                "stage": runs[i]["stage"],
                "ok": False,
                "exit_code": None,
                "duration_ms": 0,
                "rss_mib": None,
                "crash": None,
            }
        metrics = _make_metrics_all_pass()
        metrics["tests_failed"] = 10
        metrics["tests_passed"] = 0
        gates = _make_gates_stub()
        verdict, detail = compute_verdict(runs, metrics, gates)
        self.assertEqual(verdict, "FAIL")
        self.assertIn("STAGE_FAILED", detail)


if __name__ == "__main__":
    unittest.main()
