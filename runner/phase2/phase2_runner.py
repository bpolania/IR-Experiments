#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
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

    env = {
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
    }

    def _preexec() -> None:
        try:
            import resource

            rss_bytes = max_rss_mib * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (rss_bytes, rss_bytes))
            if hasattr(resource, "RLIMIT_RSS"):
                resource.setrlimit(resource.RLIMIT_RSS, (rss_bytes, rss_bytes))
        except Exception:
            # Best effort per requirement.
            pass

    proc = subprocess.Popen(
        [llvm_as_path, "-o", out_name, in_name],
        cwd=str(work_dir),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        preexec_fn=_preexec,
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
                "ok": False,
                "detail": loaded_artifacts_detail,
            },
            "policy": {
                "ok": False,
                "detail": loaded_artifacts_detail,
            },
            "tests": {
                "ok": False,
                "detail": loaded_artifacts_detail,
            },
        },
        "runs": runs_skeleton,
        "metrics": {
            "tests_total": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "ret_mismatches": 0,
            "output_mismatches": 0,
            "timeouts": 0,
            "crashes": 0 if (precheck_ok and llvm_as_ok) else 1,
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
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
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
