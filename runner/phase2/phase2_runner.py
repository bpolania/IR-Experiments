#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.authority_probe import AuthorityRecoveryError, format_probe_summary
from lib.artifacts import load_artifacts
from lib.ids import FrozenIdRuleMissingError, compute_ids_or_require_overrides, resolve_id_authority
from lib.json_emit import write_json
from lib.paths import CandidateNotFoundError, discover_candidate_path, ensure_run_paths
from lib.schema_validate import SchemaValidationError, validate_json_schema_instance


class FrozenLimitsMissingError(RuntimeError):
    pass


class FrozenToolPathMissingError(RuntimeError):
    pass


HARNESS_SEARCH_PATTERNS = [
    "lli",
    "@f",
    "candidate.bc",
    "--entry-function",
    "-entry-function",
    "in_hex",
    "out_cap",
    "expected_out_hex",
    "expected_ret",
    "sum_u32_le",
    "hex_encode",
    "parse_u32_decimal",
]


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_runs_skeleton() -> list[dict[str, Any]]:
    stage_names = [
        "precheck",
        "llvm_as_parse",
        "opt_verify",
        "lli_tests",
        "llc_compile",
        "clang_link",
        "native_tests",
    ]
    return [
        {
            "stage": name,
            "ok": False,
            "exit_code": None,
            "duration_ms": 0,
            "rss_mib": None,
            "crash": None,
        }
        for name in stage_names
    ]


def _load_precheck_limits(artifacts: dict[str, Any], repo_root: Path) -> tuple[int, int]:
    constants_path = artifacts["constants_path"]
    constants = artifacts["constants"]
    limits = constants.get("limits")
    if not isinstance(limits, dict):
        raise FrozenLimitsMissingError(
            "ERR_INTERNAL(-3): missing frozen limits object in "
            f"{constants_path.relative_to(repo_root)}; required keys: max_ll_bytes, max_ll_lines"
        )
    if "max_ll_bytes" not in limits or "max_ll_lines" not in limits:
        raise FrozenLimitsMissingError(
            "ERR_INTERNAL(-3): missing frozen precheck limit key(s) in "
            f"{constants_path.relative_to(repo_root)}; required keys: max_ll_bytes, max_ll_lines"
        )
    max_bytes = limits["max_ll_bytes"]
    max_lines = limits["max_ll_lines"]
    if not isinstance(max_bytes, int) or not isinstance(max_lines, int):
        raise FrozenLimitsMissingError(
            "ERR_INTERNAL(-3): invalid frozen precheck limit types in "
            f"{constants_path.relative_to(repo_root)}; required integer keys: max_ll_bytes, max_ll_lines"
        )
    return max_bytes, max_lines


def _load_stage_exec_limits(artifacts: dict[str, Any], repo_root: Path) -> tuple[int, int]:
    constants_path = artifacts["constants_path"]
    constants = artifacts["constants"]
    limits = constants.get("limits")
    if not isinstance(limits, dict):
        raise FrozenLimitsMissingError(
            "ERR_INTERNAL(-3): missing frozen limits object in "
            f"{constants_path.relative_to(repo_root)}; required keys: timeout_stage_ms, max_rss_mib"
        )
    if "timeout_stage_ms" not in limits or "max_rss_mib" not in limits:
        raise FrozenLimitsMissingError(
            "ERR_INTERNAL(-3): missing frozen stage exec limit key(s) in "
            f"{constants_path.relative_to(repo_root)}; required keys: timeout_stage_ms, max_rss_mib"
        )
    timeout_stage_ms = limits["timeout_stage_ms"]
    max_rss_mib = limits["max_rss_mib"]
    if not isinstance(timeout_stage_ms, int) or not isinstance(max_rss_mib, int):
        raise FrozenLimitsMissingError(
            "ERR_INTERNAL(-3): invalid frozen stage exec limit types in "
            f"{constants_path.relative_to(repo_root)}; required integer keys: timeout_stage_ms, max_rss_mib"
        )
    return timeout_stage_ms, max_rss_mib


def _load_test_exec_limits(artifacts: dict[str, Any], repo_root: Path) -> tuple[int, int]:
    constants_path = artifacts["constants_path"]
    constants = artifacts["constants"]
    limits = constants.get("limits")
    if not isinstance(limits, dict):
        raise FrozenLimitsMissingError(
            "ERR_INTERNAL(-3): missing frozen limits object in "
            f"{constants_path.relative_to(repo_root)}; required keys: timeout_per_test_ms, max_rss_mib"
        )
    if "timeout_per_test_ms" not in limits or "max_rss_mib" not in limits:
        raise FrozenLimitsMissingError(
            "ERR_INTERNAL(-3): missing frozen lli test limit key(s) in "
            f"{constants_path.relative_to(repo_root)}; required keys: timeout_per_test_ms, max_rss_mib"
        )
    timeout_per_test_ms = limits["timeout_per_test_ms"]
    max_rss_mib = limits["max_rss_mib"]
    if not isinstance(timeout_per_test_ms, int) or not isinstance(max_rss_mib, int):
        raise FrozenLimitsMissingError(
            "ERR_INTERNAL(-3): invalid frozen lli test limit types in "
            f"{constants_path.relative_to(repo_root)}; required integer keys: timeout_per_test_ms, max_rss_mib"
        )
    return timeout_per_test_ms, max_rss_mib


def _resolve_llvm_as_path(artifacts: dict[str, Any], repo_root: Path) -> tuple[str | None, str]:
    tool_versions = artifacts["tool_versions"]
    tv_path = artifacts["tool_versions_path"]
    source = str(tv_path.relative_to(repo_root))
    detected = tool_versions.get("detected")
    if not isinstance(detected, dict):
        return None, f"llvm_as_not_executable path=<missing> source={source}"
    llvm_as = detected.get("llvm-as")
    if not isinstance(llvm_as, dict):
        return None, f"llvm_as_not_executable path=<missing> source={source}"
    path = llvm_as.get("path")
    if not isinstance(path, str) or len(path.strip()) == 0:
        return None, f"llvm_as_not_executable path=<missing> source={source}"
    llvm_path = Path(path)
    if not llvm_path.is_file() or not os.access(str(llvm_path), os.X_OK):
        return None, f"llvm_as_not_executable path={path} source={source}"
    return path, f"llvm_as_executable path={path} source={source}"


def _resolve_opt_path(artifacts: dict[str, Any], repo_root: Path) -> tuple[str | None, str]:
    tool_versions = artifacts["tool_versions"]
    tv_path = artifacts["tool_versions_path"]
    source = str(tv_path.relative_to(repo_root))
    detected = tool_versions.get("detected")
    if not isinstance(detected, dict):
        return None, f"opt_not_found_in_tool_versions key=detected.opt.path source={source}"

    key_used = None
    opt_entry = None
    if isinstance(detected.get("opt"), dict):
        key_used = "opt"
        opt_entry = detected["opt"]
    elif isinstance(detected.get("llvm-opt"), dict):
        key_used = "llvm-opt"
        opt_entry = detected["llvm-opt"]

    if not isinstance(opt_entry, dict):
        return None, f"opt_not_found_in_tool_versions key=detected.opt.path source={source}"

    path = opt_entry.get("path")
    if not isinstance(path, str) or len(path.strip()) == 0:
        return None, f"opt_not_found_in_tool_versions key=detected.{key_used}.path source={source}"
    p = Path(path)
    if not p.is_file() or not os.access(str(p), os.X_OK):
        return None, f"opt_not_executable path={path} source={source}"
    return path, f"opt_executable path={path} source={source}"


def _resolve_lli_path(artifacts: dict[str, Any], repo_root: Path) -> tuple[str | None, str]:
    tool_versions = artifacts["tool_versions"]
    tv_path = artifacts["tool_versions_path"]
    source = str(tv_path.relative_to(repo_root))
    detected = tool_versions.get("detected")
    if not isinstance(detected, dict):
        return None, f"lli_not_executable path=<missing> source={source}"

    key_used = None
    lli_entry = None
    if isinstance(detected.get("lli"), dict):
        key_used = "lli"
        lli_entry = detected["lli"]
    elif isinstance(detected.get("llvm-lli"), dict):
        key_used = "llvm-lli"
        lli_entry = detected["llvm-lli"]

    if not isinstance(lli_entry, dict):
        return None, f"lli_not_executable path=<missing> source={source}"

    path = lli_entry.get("path")
    if not isinstance(path, str) or len(path.strip()) == 0:
        return None, f"lli_not_executable path=<missing> source={source};key=detected.{key_used}.path"
    p = Path(path)
    if not p.is_file() or not os.access(str(p), os.X_OK):
        return None, f"lli_not_executable path={path} source={source}"
    return path, f"lli_executable path={path} source={source}"


def _resolve_llc_path(artifacts: dict[str, Any], repo_root: Path) -> tuple[str | None, str]:
    tool_versions = artifacts["tool_versions"]
    tv_path = artifacts["tool_versions_path"]
    source = str(tv_path.relative_to(repo_root))
    detected = tool_versions.get("detected")
    if not isinstance(detected, dict):
        return None, f"llc_not_found_in_tool_versions key=detected.llc.path source={source}"

    key_used = None
    llc_entry = None
    if isinstance(detected.get("llc"), dict):
        key_used = "llc"
        llc_entry = detected["llc"]
    elif isinstance(detected.get("llvm-llc"), dict):
        key_used = "llvm-llc"
        llc_entry = detected["llvm-llc"]

    if not isinstance(llc_entry, dict):
        return None, f"llc_not_found_in_tool_versions key=detected.llc.path source={source}"

    path = llc_entry.get("path")
    if not isinstance(path, str) or len(path.strip()) == 0:
        return None, f"llc_not_found_in_tool_versions key=detected.{key_used}.path source={source}"
    p = Path(path)
    if not p.is_file() or not os.access(str(p), os.X_OK):
        return None, f"llc_not_executable path={path} source={source}"
    return path, f"llc_executable path={path} source={source}"


def _resolve_target_triple(artifacts: dict[str, Any], repo_root: Path) -> tuple[str | None, str]:
    target_obj = artifacts["target"]
    target_path = artifacts["target_path"]
    source = str(target_path.relative_to(repo_root))
    if not isinstance(target_obj, dict):
        return None, f"llc_missing_target_triple source={source}"
    triple = target_obj.get("target_triple")
    if not isinstance(triple, str) or len(triple.strip()) == 0:
        return None, f"llc_missing_target_triple source={source}"
    return triple, f"target_triple={triple}"


def _resolve_task_tests(artifacts: dict[str, Any], task: str) -> tuple[str | None, list[dict[str, Any]]]:
    if task in (None, "", "all_tasks"):
        return None, []
    relative = f"irx/experiment1/tasks/{task}/tests.json"
    obj = artifacts["test_vectors"].get(relative)
    if not isinstance(obj, dict):
        return None, []
    vectors = obj.get("vectors")
    if not isinstance(vectors, list):
        return None, []
    typed: list[dict[str, Any]] = []
    for item in vectors:
        if isinstance(item, dict):
            typed.append(item)
    return relative, typed


def _is_hidden_path(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def _discover_lli_abi_mechanism(repo_root: Path) -> dict[str, Any]:
    exp_root = repo_root / "irx" / "experiment1"
    harness_root = exp_root / "harness"
    search_roots = [harness_root, exp_root]

    inspected_files: list[str] = []
    candidate_mechanisms: list[dict[str, Any]] = []
    seen: set[Path] = set()

    for root in search_roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if p in seen:
                continue
            seen.add(p)
            if not p.is_file():
                continue
            rel = p.relative_to(repo_root)
            if _is_hidden_path(rel):
                continue
            if "runs" in rel.parts:
                continue
            inspected_files.append(str(rel))
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if len(text) == 0:
                continue

            lower = text.lower()
            matched = [pat for pat in HARNESS_SEARCH_PATTERNS if pat.lower() in lower]
            has_lli = "lli" in lower
            has_candidate_bc = "candidate.bc" in lower
            has_f_symbol = "@f" in text
            has_io_contract = (
                ("in_hex" in lower and "out_cap" in lower)
                or ("in_ptr" in lower and "out_ptr" in lower)
            )
            has_expected_actual = (
                "expected_ret" in lower
                or "expected_out_hex" in lower
                or "actual_ret" in lower
                or "actual_out_hex" in lower
            )
            has_exec = (
                "subprocess" in lower
                or "popen(" in lower
                or "os.system(" in lower
                or " lli " in lower
            )

            if has_lli and has_candidate_bc and has_f_symbol and has_io_contract and has_expected_actual and has_exec:
                candidate_mechanisms.append({
                    "path": str(rel),
                    "matched_patterns": matched,
                })

    candidate_mechanisms.sort(key=lambda x: x["path"])
    inspected_files_sorted = sorted(inspected_files)
    report: dict[str, Any] = {
        "searched_dirs": [str(harness_root.relative_to(repo_root)), str(exp_root.relative_to(repo_root))],
        "searched_patterns": HARNESS_SEARCH_PATTERNS,
        "inspected_files_count": len(inspected_files_sorted),
        "inspected_files_sample": inspected_files_sorted[:30],
    }

    if candidate_mechanisms:
        chosen = candidate_mechanisms[0]
        report["status"] = "found"
        report["chosen_harness"] = chosen["path"]
        report["chosen_harness_contract"] = "existing_repo_mechanism_detected_by_pattern_bundle"
        report["chosen_harness_evidence_patterns"] = chosen["matched_patterns"]
    else:
        report["status"] = "not_found"
        report["chosen_harness"] = None
        report["chosen_harness_contract"] = None
        report["chosen_harness_evidence_patterns"] = []

    return report


def _format_harness_not_found_detail(report: dict[str, Any]) -> str:
    sample = report.get("inspected_files_sample", [])
    listed = ",".join(sample) if isinstance(sample, list) else ""
    omitted = max(int(report.get("inspected_files_count", 0)) - (len(sample) if isinstance(sample, list) else 0), 0)
    if omitted > 0:
        listed = f"{listed},... ({omitted} more omitted)" if listed else f"... ({omitted} more omitted)"
    return (
        "lli_abi_mechanism_not_found;"
        f"searched_dirs={','.join(report.get('searched_dirs', []))};"
        f"searched_patterns={','.join(report.get('searched_patterns', []))};"
        f"inspected_files={listed}"
    )


def _schema_supports_per_test_results(schema: dict[str, Any]) -> tuple[bool, str]:
    inspected_paths = [
        "$.properties",
        "$.properties.runs",
        "$.properties.metrics",
        "$.properties.gates",
        "$.$defs",
    ]
    props = schema.get("properties")
    if not isinstance(props, dict):
        return False, "ERR_INTERNAL(-3): schema missing $.properties"

    for _, val in props.items():
        if not isinstance(val, dict):
            continue
        if val.get("type") != "array":
            continue
        item = val.get("items")
        if not isinstance(item, dict):
            continue
        if "$ref" in item and item.get("$ref") == "#/$defs/runRecord":
            continue
        item_props = item.get("properties")
        if not isinstance(item_props, dict):
            continue
        required = {"test_id", "expected_ret", "expected_out_hex", "actual_ret", "actual_out_hex"}
        if required.issubset(set(item_props.keys())):
            return True, "schema has explicit per-test array"

    return False, (
        "ERR_INTERNAL(-3): schema has no explicit per-test result container; "
        f"inspected={','.join(inspected_paths)}"
    )


def _count_lines(candidate_bytes: bytes) -> int:
    if len(candidate_bytes) == 0:
        return 0
    return candidate_bytes.count(b"\n") + (0 if candidate_bytes.endswith(b"\n") else 1)


def _apply_precheck(
    runs: list[dict[str, Any]],
    candidate_bytes: bytes,
    max_bytes: int,
    max_lines: int,
) -> tuple[bool, str]:
    precheck = runs[0]
    byte_count = len(candidate_bytes)
    line_count = _count_lines(candidate_bytes)

    byte_fail = byte_count > max_bytes
    line_fail = line_count > max_lines

    if byte_fail or line_fail:
        reasons: list[str] = []
        if byte_fail:
            reasons.append(f"bytes_exceeded actual={byte_count} limit={max_bytes}")
        if line_fail:
            reasons.append(f"lines_exceeded actual={line_count} limit={max_lines}")
        reason = "; ".join(reasons)
        precheck["ok"] = False
        precheck["exit_code"] = None
        precheck["duration_ms"] = 0
        precheck["rss_mib"] = None
        precheck["crash"] = {
            "type": "POLICY_VIOLATION",
            "signal": None,
            "detail": f"precheck_failed:{reason}",
        }
        return False, f"PRECHECK_FAIL:{reason}"

    precheck["ok"] = True
    precheck["exit_code"] = None
    precheck["duration_ms"] = 0
    precheck["rss_mib"] = None
    precheck["crash"] = None
    return True, f"PRECHECK_PASS:bytes={byte_count}/{max_bytes};lines={line_count}/{max_lines}"


def _derive_llvm_lib_path(tool_path: str) -> str | None:
    """Derive LLVM lib directory from frozen tool path.

    Given a frozen tool path like /usr/lib/llvm-19/bin/llvm-as,
    derive the lib directory as /usr/lib/llvm-19/lib.

    Returns the lib path if it exists as a directory, otherwise None.
    """
    tool_p = Path(tool_path)
    # tool_path = /usr/lib/llvm-19/bin/llvm-as
    # parent = /usr/lib/llvm-19/bin
    # llvm_root = /usr/lib/llvm-19
    llvm_root = tool_p.parent.parent
    llvm_lib = llvm_root / "lib"
    if llvm_lib.is_dir():
        return str(llvm_lib)
    return None


def _build_llvm_tool_env(tool_path: str) -> tuple[dict[str, str], str | None]:
    """Build deterministic subprocess environment for LLVM tool invocation.

    Returns (env_dict, ld_library_path_used).
    ld_library_path_used is the derived path if set, otherwise None.
    """
    env = {
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
    }
    llvm_lib = _derive_llvm_lib_path(tool_path)
    if llvm_lib is not None:
        env["LD_LIBRARY_PATH"] = llvm_lib
    return env, llvm_lib


def _build_llvm_tool_preexec(max_rss_mib: int):
    """Build preexec function for LLVM tools with RSS-only limits.

    RLIMIT_AS is intentionally not set for LLVM tools. Only RLIMIT_RSS is
    applied when available.
    """

    def _preexec() -> None:
        try:
            import resource

            rss_bytes = max_rss_mib * 1024 * 1024
            if hasattr(resource, "RLIMIT_RSS"):
                resource.setrlimit(resource.RLIMIT_RSS, (rss_bytes, rss_bytes))
        except Exception:
            # Best effort per requirement.
            pass

    return _preexec


def _prepare_llvm_tool_runtime(tool_name: str, tool_path: str, max_rss_mib: int):
    """Shared deterministic runtime setup for LLVM tool subprocesses."""
    env, ld_library_path = _build_llvm_tool_env(tool_path)
    print(f"[{tool_name}] LD_LIBRARY_PATH={ld_library_path}", file=sys.stderr)
    return env, _build_llvm_tool_preexec(max_rss_mib), ld_library_path


def _prepare_lli_runtime(lli_path: str, max_rss_mib: int):
    return _prepare_llvm_tool_runtime("lli", lli_path, max_rss_mib)


def _prepare_llc_runtime(llc_path: str, max_rss_mib: int):
    return _prepare_llvm_tool_runtime("llc", llc_path, max_rss_mib)


def _prepare_clang_runtime(clang_path: str, max_rss_mib: int):
    return _prepare_llvm_tool_runtime("clang", clang_path, max_rss_mib)


def _map_signal_to_crash_type(sig_num: int) -> str | None:
    mapping = {
        signal.SIGSEGV: "SIGSEGV",
        signal.SIGILL: "SIGILL",
        signal.SIGABRT: "SIGABRT",
        signal.SIGFPE: "SIGFPE",
    }
    return mapping.get(sig_num)


def _run_llvm_as_parse(
    *,
    llvm_as_path: str,
    work_dir: Path,
    timeout_stage_ms: int,
    max_rss_mib: int,
    stage_record: dict[str, Any],
) -> tuple[bool, str]:
    in_name = "candidate.ll"
    out_name = "candidate.bc"
    out_path = work_dir / out_name
    if out_path.exists():
        out_path.unlink()

    env, preexec_fn, _ = _prepare_llvm_tool_runtime("llvm-as", llvm_as_path, max_rss_mib)

    proc = subprocess.Popen(
        [llvm_as_path, "-o", out_name, in_name],
        cwd=str(work_dir),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        preexec_fn=preexec_fn,
    )

    timed_out = False
    try:
        _, stderr = proc.communicate(timeout=timeout_stage_ms / 1000.0)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _, stderr = proc.communicate()

    rc = proc.returncode if proc.returncode is not None else -1
    stderr_text = (stderr or "").strip()
    stderr_compact = " ".join(stderr_text.split())[:240]

    stage_record["duration_ms"] = 0
    stage_record["rss_mib"] = None

    if timed_out:
        stage_record["ok"] = False
        stage_record["exit_code"] = None
        stage_record["crash"] = {
            "type": "TIMEOUT",
            "signal": None,
            "detail": f"llvm-as timeout after {timeout_stage_ms}ms",
        }
        return False, "LLVM_AS_PARSE_FAIL:timeout"

    if rc == 0:
        if not out_path.exists() or out_path.stat().st_size == 0:
            stage_record["ok"] = False
            stage_record["exit_code"] = 0
            stage_record["crash"] = {
                "type": "PARSE_FAIL",
                "signal": None,
                "detail": "llvm-as reported success but candidate.bc missing or empty",
            }
            return False, "LLVM_AS_PARSE_FAIL:missing_or_empty_bc"
        stage_record["ok"] = True
        stage_record["exit_code"] = 0
        stage_record["crash"] = None
        return True, "LLVM_AS_PARSE_PASS"

    # Non-zero return handling
    if rc < 0:
        sig_num = -rc
        mapped = _map_signal_to_crash_type(sig_num)
        if mapped is not None:
            stage_record["ok"] = False
            stage_record["exit_code"] = None
            stage_record["crash"] = {
                "type": mapped,
                "signal": sig_num,
                "detail": f"llvm-as terminated by signal {sig_num}",
            }
            return False, f"LLVM_AS_PARSE_FAIL:signal_{sig_num}"

    lower_err = stderr_text.lower()
    if "out of memory" in lower_err or "cannot allocate memory" in lower_err:
        stage_record["ok"] = False
        stage_record["exit_code"] = rc if rc >= 0 else None
        stage_record["crash"] = {
            "type": "OOM",
            "signal": None if rc >= 0 else -rc,
            "detail": "llvm-as reported memory exhaustion",
        }
        return False, "LLVM_AS_PARSE_FAIL:oom"

    stage_record["ok"] = False
    stage_record["exit_code"] = rc if rc >= 0 else None
    stage_record["crash"] = {
        "type": "PARSE_FAIL",
        "signal": None if rc >= 0 else -rc,
        "detail": f"llvm-as parse failed; rc={rc}; stderr={stderr_compact}",
    }
    return False, "LLVM_AS_PARSE_FAIL:parse_fail"


def _run_opt_verify(
    *,
    opt_path: str,
    work_dir: Path,
    timeout_stage_ms: int,
    max_rss_mib: int,
    stage_record: dict[str, Any],
) -> tuple[bool, str]:
    env, preexec_fn, _ = _prepare_llvm_tool_runtime("opt", opt_path, max_rss_mib)

    proc = subprocess.Popen(
        [opt_path, "-verify", "-disable-output", "candidate.bc"],
        cwd=str(work_dir),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        preexec_fn=preexec_fn,
    )

    timed_out = False
    try:
        _, stderr = proc.communicate(timeout=timeout_stage_ms / 1000.0)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _, stderr = proc.communicate()

    rc = proc.returncode if proc.returncode is not None else -1
    stderr_text = (stderr or "").strip()

    stage_record["duration_ms"] = 0
    stage_record["rss_mib"] = None

    if timed_out:
        stage_record["ok"] = False
        stage_record["exit_code"] = None
        stage_record["crash"] = {
            "type": "TIMEOUT",
            "signal": None,
            "detail": f"opt_timeout ms={timeout_stage_ms}",
        }
        return False, "OPT_VERIFY_FAIL:timeout"

    if rc == 0:
        stage_record["ok"] = True
        stage_record["exit_code"] = 0
        stage_record["crash"] = None
        return True, "OPT_VERIFY_PASS"

    if rc < 0:
        sig_num = -rc
        mapped = _map_signal_to_crash_type(sig_num)
        if mapped is not None:
            stage_record["ok"] = False
            stage_record["exit_code"] = None
            stage_record["crash"] = {
                "type": mapped,
                "signal": sig_num,
                "detail": f"opt terminated by signal {sig_num}",
            }
            return False, f"OPT_VERIFY_FAIL:signal_{sig_num}"

    lower_err = stderr_text.lower()
    if "out of memory" in lower_err or "cannot allocate memory" in lower_err:
        stage_record["ok"] = False
        stage_record["exit_code"] = rc if rc >= 0 else None
        stage_record["crash"] = {
            "type": "OOM",
            "signal": None if rc >= 0 else -rc,
            "detail": "opt reported memory exhaustion",
        }
        return False, "OPT_VERIFY_FAIL:oom"

    stage_record["ok"] = False
    stage_record["exit_code"] = rc if rc >= 0 else None
    stage_record["crash"] = {
        "type": "VERIFY_FAIL",
        "signal": None if rc >= 0 else -rc,
        "detail": f"opt_verify_failed exit_code={rc}",
    }
    return False, "OPT_VERIFY_FAIL:verify_fail"


def _run_llc_compile(
    *,
    llc_path: str,
    target_triple: str,
    work_dir: Path,
    timeout_stage_ms: int,
    max_rss_mib: int,
    stage_record: dict[str, Any],
) -> tuple[bool, str]:
    out_name = "candidate.o"
    out_path = work_dir / out_name
    if out_path.exists():
        out_path.unlink()

    env, preexec_fn, _ = _prepare_llc_runtime(llc_path, max_rss_mib)
    proc = subprocess.Popen(
        [llc_path, "-filetype=obj", f"-mtriple={target_triple}", "-O0", "-o", out_name, "candidate.bc"],
        cwd=str(work_dir),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        preexec_fn=preexec_fn,
    )

    timed_out = False
    try:
        _, stderr = proc.communicate(timeout=timeout_stage_ms / 1000.0)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _, stderr = proc.communicate()

    rc = proc.returncode if proc.returncode is not None else -1
    stderr_text = (stderr or "").strip()
    stage_record["duration_ms"] = 0
    stage_record["rss_mib"] = None

    if timed_out:
        stage_record["ok"] = False
        stage_record["exit_code"] = None
        stage_record["crash"] = {
            "type": "TIMEOUT",
            "signal": None,
            "detail": f"llc_timeout ms={timeout_stage_ms}",
        }
        return False, "LLC_COMPILE_FAIL:timeout"

    if rc == 0:
        if not out_path.exists() or out_path.stat().st_size == 0:
            stage_record["ok"] = False
            stage_record["exit_code"] = 0
            stage_record["crash"] = {
                "type": "POLICY_VIOLATION",
                "signal": None,
                "detail": "llc_output_missing_or_empty path=candidate.o",
            }
            return False, "LLC_COMPILE_FAIL:missing_or_empty_output"
        stage_record["ok"] = True
        stage_record["exit_code"] = 0
        stage_record["crash"] = None
        return True, "LLC_COMPILE_PASS"

    if rc < 0:
        sig_num = -rc
        mapped = _map_signal_to_crash_type(sig_num)
        if mapped is not None:
            stage_record["ok"] = False
            stage_record["exit_code"] = None
            stage_record["crash"] = {
                "type": mapped,
                "signal": sig_num,
                "detail": f"llc terminated by signal {sig_num}",
            }
            return False, f"LLC_COMPILE_FAIL:signal_{sig_num}"

    lower_err = stderr_text.lower()
    if "out of memory" in lower_err or "cannot allocate memory" in lower_err:
        stage_record["ok"] = False
        stage_record["exit_code"] = rc if rc >= 0 else None
        stage_record["crash"] = {
            "type": "OOM",
            "signal": None if rc >= 0 else -rc,
            "detail": "llc reported memory exhaustion",
        }
        return False, "LLC_COMPILE_FAIL:oom"

    stage_record["ok"] = False
    stage_record["exit_code"] = rc if rc >= 0 else None
    stage_record["crash"] = {
        "type": "POLICY_VIOLATION",
        "signal": None if rc >= 0 else -rc,
        "detail": f"llc_failed exit_code={rc}",
    }
    return False, "LLC_COMPILE_FAIL:policy_violation"


def run_step_a(
    repo_root: Path,
    task: str,
    candidate: str | None = None,
    provided_candidate_id: str | None = None,
    provided_run_id: str | None = None,
) -> dict[str, Any]:
    artifacts = load_artifacts(repo_root)
    exp_root = artifacts["exp_root"]

    candidate_path = discover_candidate_path(exp_root=exp_root, explicit_candidate=candidate)
    candidate_bytes = candidate_path.read_bytes()
    max_candidate_bytes, max_candidate_lines = _load_precheck_limits(artifacts, repo_root)
    timeout_stage_ms, max_rss_mib = _load_stage_exec_limits(artifacts, repo_root)
    timeout_per_test_ms, max_rss_mib_tests = _load_test_exec_limits(artifacts, repo_root)

    authority = resolve_id_authority(artifacts=artifacts, repo_root=repo_root)
    print(format_probe_summary(authority["probe_summary"]))
    candidate_id, run_id, id_notes = compute_ids_or_require_overrides(
        authority=authority,
        candidate_bytes=candidate_bytes,
        artifacts=artifacts,
        provided_candidate_id=provided_candidate_id,
        provided_run_id=provided_run_id,
    )

    _, work_dir, result_json_path = ensure_run_paths(exp_root=exp_root, candidate_id=candidate_id, run_id=run_id)

    work_candidate_path = work_dir / "candidate.ll"
    work_candidate_path.write_bytes(candidate_bytes)

    started = _iso_utc_now()
    finished = _iso_utc_now()
    loaded_artifacts_detail = (
        "LOADED_STEP_A:"
        f"tool_versions={artifacts['tool_versions_path'].relative_to(repo_root)};"
        f"result_schema={artifacts['result_schema_path'].relative_to(repo_root)};"
        f"constants={artifacts['constants_path'].relative_to(repo_root)};"
        f"target={artifacts['target_path'].relative_to(repo_root)};"
        "test_vectors=irx/experiment1/tasks/sum_u32_le/tests.json,"
        "irx/experiment1/tasks/hex_encode/tests.json,"
        "irx/experiment1/tasks/parse_u32_decimal/tests.json;"
        f"id_authority_candidate={authority.get('candidate_reason')};"
        f"id_authority_run={authority.get('run_reason')};"
        f"id_notes={','.join(id_notes)}"
    )
    runs_skeleton = _build_runs_skeleton()
    precheck_ok, precheck_detail = _apply_precheck(
        runs=runs_skeleton,
        candidate_bytes=candidate_bytes,
        max_bytes=max_candidate_bytes,
        max_lines=max_candidate_lines,
    )
    llvm_as_ok = False
    llvm_as_detail = "LLVM_AS_PARSE_NOT_RUN:precheck_failed"
    if precheck_ok:
        llvm_as_path, llvm_as_path_detail = _resolve_llvm_as_path(artifacts, repo_root)
        if llvm_as_path is None:
            runs_skeleton[1]["ok"] = False
            runs_skeleton[1]["exit_code"] = None
            runs_skeleton[1]["duration_ms"] = 0
            runs_skeleton[1]["rss_mib"] = None
            runs_skeleton[1]["crash"] = {
                "type": "POLICY_VIOLATION",
                "signal": None,
                "detail": llvm_as_path_detail,
            }
            llvm_as_ok = False
            llvm_as_detail = f"LLVM_AS_PARSE_FAIL:{llvm_as_path_detail}"
        else:
            llvm_as_ok, llvm_as_detail = _run_llvm_as_parse(
                llvm_as_path=llvm_as_path,
                work_dir=work_dir,
                timeout_stage_ms=timeout_stage_ms,
                max_rss_mib=max_rss_mib,
                stage_record=runs_skeleton[1],
            )

    opt_ok = False
    candidate_bc_path = work_dir / "candidate.bc"
    stage3_can_run = (
        precheck_ok
        and llvm_as_ok
        and candidate_bc_path.is_file()
        and candidate_bc_path.stat().st_size > 0
    )
    if not stage3_can_run:
        opt_detail = "OPT_VERIFY_NOT_RUN:preconditions_failed"
    else:
        opt_path, opt_path_detail = _resolve_opt_path(artifacts, repo_root)
        if opt_path is None:
            runs_skeleton[2]["ok"] = False
            runs_skeleton[2]["exit_code"] = None
            runs_skeleton[2]["duration_ms"] = 0
            runs_skeleton[2]["rss_mib"] = None
            runs_skeleton[2]["crash"] = {
                "type": "POLICY_VIOLATION",
                "signal": None,
                "detail": opt_path_detail,
            }
            opt_ok = False
            opt_detail = f"OPT_VERIFY_FAIL:{opt_path_detail}"
        else:
            opt_ok, opt_detail = _run_opt_verify(
                opt_path=opt_path,
                work_dir=work_dir,
                timeout_stage_ms=timeout_stage_ms,
                max_rss_mib=max_rss_mib,
                stage_record=runs_skeleton[2],
            )

    lli_ok = False
    tests_total = 0
    tests_passed = 0
    tests_failed = 0
    ret_mismatches = 0
    output_mismatches = 0
    timeouts = 0
    crashes = 0 if (precheck_ok and llvm_as_ok and opt_ok) else 1

    stage4_can_run = (
        precheck_ok
        and llvm_as_ok
        and opt_ok
        and candidate_bc_path.is_file()
        and candidate_bc_path.stat().st_size > 0
    )
    harness_probe: dict[str, Any] | None = None
    if not stage4_can_run:
        lli_detail = "LLI_TESTS_NOT_RUN:preconditions_failed"
    else:
        lli_path, lli_path_detail = _resolve_lli_path(artifacts, repo_root)
        if lli_path is None:
            runs_skeleton[3]["ok"] = False
            runs_skeleton[3]["exit_code"] = None
            runs_skeleton[3]["duration_ms"] = 0
            runs_skeleton[3]["rss_mib"] = None
            runs_skeleton[3]["crash"] = {
                "type": "POLICY_VIOLATION",
                "signal": None,
                "detail": lli_path_detail,
            }
            lli_ok = False
            lli_detail = f"LLI_TESTS_FAIL:{lli_path_detail}"
            crashes = 1
        else:
            harness_probe = _discover_lli_abi_mechanism(repo_root)
            task_tests_path, task_vectors = _resolve_task_tests(artifacts, task)
            tests_total = len(task_vectors)
            if task_tests_path is None:
                runs_skeleton[3]["ok"] = False
                runs_skeleton[3]["exit_code"] = None
                runs_skeleton[3]["duration_ms"] = 0
                runs_skeleton[3]["rss_mib"] = None
                runs_skeleton[3]["crash"] = {
                    "type": "POLICY_VIOLATION",
                    "signal": None,
                    "detail": f"lli_tests_task_not_found task={task}",
                }
                lli_ok = False
                lli_detail = f"LLI_TESTS_FAIL:task_not_found task={task}"
                tests_failed = tests_total
                crashes = 1
            else:
                if harness_probe.get("status") != "found":
                    detail = _format_harness_not_found_detail(harness_probe)
                    runs_skeleton[3]["ok"] = False
                    runs_skeleton[3]["exit_code"] = None
                    runs_skeleton[3]["duration_ms"] = 0
                    runs_skeleton[3]["rss_mib"] = None
                    runs_skeleton[3]["crash"] = {
                        "type": "POLICY_VIOLATION",
                        "signal": None,
                        "detail": detail,
                    }
                    lli_ok = False
                    lli_detail = f"LLI_TESTS_FAIL:{detail}"
                    tests_failed = tests_total
                    crashes = 1
                else:
                    schema_has_per_test, schema_detail = _schema_supports_per_test_results(artifacts["result_schema"])
                    if not schema_has_per_test:
                        runs_skeleton[3]["ok"] = False
                        runs_skeleton[3]["exit_code"] = None
                        runs_skeleton[3]["duration_ms"] = 0
                        runs_skeleton[3]["rss_mib"] = None
                        runs_skeleton[3]["crash"] = {
                            "type": "POLICY_VIOLATION",
                            "signal": None,
                            "detail": schema_detail,
                        }
                        lli_ok = False
                        lli_detail = f"LLI_TESTS_FAIL:{schema_detail}"
                        tests_failed = tests_total
                        crashes = 1
                    else:
                        mechanism = str(harness_probe.get("chosen_harness"))
                        detail = (
                            "ERR_INTERNAL(-3): frozen lli ABI invocation contract is not machine-readable; "
                            f"chosen_harness={mechanism};required_contract=explicit_cli_or_io_spec"
                        )
                        runs_skeleton[3]["ok"] = False
                        runs_skeleton[3]["exit_code"] = None
                        runs_skeleton[3]["duration_ms"] = 0
                        runs_skeleton[3]["rss_mib"] = None
                        runs_skeleton[3]["crash"] = {
                            "type": "POLICY_VIOLATION",
                            "signal": None,
                            "detail": detail,
                        }
                        lli_ok = False
                        lli_detail = (
                            f"LLI_TESTS_FAIL:{detail};timeout_per_test_ms={timeout_per_test_ms};"
                            f"max_rss_mib={max_rss_mib_tests}"
                        )
                        tests_failed = tests_total
                        crashes = 1

    probe_detail = ""
    if harness_probe is not None:
        probe_detail = (
            ";LLI_HARNESS_PROBE:"
            f"status={harness_probe.get('status')};"
            f"chosen={harness_probe.get('chosen_harness')};"
            f"inspected_files_count={harness_probe.get('inspected_files_count')}"
        )

    llc_ok = False
    stage5_can_run = (
        precheck_ok
        and llvm_as_ok
        and opt_ok
        and lli_ok
        and candidate_bc_path.is_file()
        and candidate_bc_path.stat().st_size > 0
    )
    if not stage5_can_run:
        llc_detail = "LLC_COMPILE_NOT_RUN:preconditions_failed"
    else:
        llc_path, llc_path_detail = _resolve_llc_path(artifacts, repo_root)
        if llc_path is None:
            runs_skeleton[4]["ok"] = False
            runs_skeleton[4]["exit_code"] = None
            runs_skeleton[4]["duration_ms"] = 0
            runs_skeleton[4]["rss_mib"] = None
            runs_skeleton[4]["crash"] = {
                "type": "POLICY_VIOLATION",
                "signal": None,
                "detail": llc_path_detail,
            }
            llc_ok = False
            llc_detail = f"LLC_COMPILE_FAIL:{llc_path_detail}"
            crashes = 1
        else:
            target_triple, target_detail = _resolve_target_triple(artifacts, repo_root)
            if target_triple is None:
                runs_skeleton[4]["ok"] = False
                runs_skeleton[4]["exit_code"] = None
                runs_skeleton[4]["duration_ms"] = 0
                runs_skeleton[4]["rss_mib"] = None
                runs_skeleton[4]["crash"] = {
                    "type": "POLICY_VIOLATION",
                    "signal": None,
                    "detail": "llc_missing_target_triple source=irx/experiment1/env/target.json",
                }
                llc_ok = False
                llc_detail = (
                    "LLC_COMPILE_FAIL:ERR_INTERNAL(-3): missing/invalid frozen "
                    "target_triple in irx/experiment1/env/target.json"
                )
                crashes = 1
            else:
                llc_ok, llc_detail = _run_llc_compile(
                    llc_path=llc_path,
                    target_triple=target_triple,
                    work_dir=work_dir,
                    timeout_stage_ms=timeout_stage_ms,
                    max_rss_mib=max_rss_mib,
                    stage_record=runs_skeleton[4],
                )
                if not llc_ok:
                    crashes = 1

    result_obj: dict[str, Any] = {
        "experiment": str(artifacts["constants"].get("experiment", "1")),
        "task": task,
        "candidate_id": candidate_id,
        "run_id": run_id,
        "timestamps": {
            "started_at": started,
            "finished_at": finished,
        },
        "gates": {
            "parse": {
                "ok": llvm_as_ok,
                "detail": loaded_artifacts_detail + ";" + precheck_detail + ";" + llvm_as_detail,
            },
            "verify": {
                "ok": opt_ok,
                "detail": loaded_artifacts_detail + ";" + opt_detail,
            },
            "policy": {
                "ok": False,
                "detail": loaded_artifacts_detail + ";" + llc_detail,
            },
            "tests": {
                "ok": lli_ok,
                "detail": loaded_artifacts_detail + ";" + lli_detail + probe_detail,
            },
        },
        "runs": runs_skeleton,
        "metrics": {
            "tests_total": tests_total,
            "tests_passed": tests_passed,
            "tests_failed": tests_failed,
            "ret_mismatches": ret_mismatches,
            "output_mismatches": output_mismatches,
            "timeouts": timeouts,
            "crashes": crashes,
        },
        "verdict": "ERROR",
    }

    validate_json_schema_instance(result_obj, artifacts["result_schema"])
    write_json(result_json_path, result_obj, artifacts["result_schema"])

    return {
        "candidate_id": candidate_id,
        "run_id": run_id,
        "result_json": result_json_path,
        "work_candidate": work_candidate_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Experiment 1 Phase 2 Step A runner skeleton")
    parser.add_argument("--task", default="all_tasks", help="task label for result.json")
    parser.add_argument(
        "--candidate",
        default=None,
        help="explicit path to candidate .ll (required until Phase 0/1 freezes a default candidate discovery rule)",
    )
    parser.add_argument("--candidate-id", default=None, help="authoritative fallback candidate_id if inference is unavailable")
    parser.add_argument("--run-id", default=None, help="authoritative fallback run_id if inference is unavailable")
    parser.add_argument(
        "--probe-harness",
        action="store_true",
        help="print deterministic lli harness discovery report and exit",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    if args.probe_harness:
        print(json.dumps(_discover_lli_abi_mechanism(repo_root), indent=2))
        return 0

    try:
        out = run_step_a(
            repo_root=repo_root,
            task=args.task,
            candidate=args.candidate,
            provided_candidate_id=args.candidate_id,
            provided_run_id=args.run_id,
        )
    except CandidateNotFoundError as exc:
        print(str(exc))
        return 2
    except FrozenIdRuleMissingError as exc:
        print(str(exc))
        return 3
    except AuthorityRecoveryError as exc:
        print(str(exc))
        return exc.code
    except FrozenLimitsMissingError as exc:
        print(str(exc))
        return 3
    except SchemaValidationError as exc:
        print(f"ERR_INTERNAL(-3): schema validation failed: {exc}")
        return 3

    print(json.dumps({
        "candidate_id": out["candidate_id"],
        "run_id": out["run_id"],
        "result_json": str(out["result_json"]),
        "work_candidate": str(out["work_candidate"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
