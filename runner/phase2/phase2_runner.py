#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.authority_probe import AuthorityRecoveryError, format_probe_summary
from lib.artifacts import load_artifacts
from lib.ids import FrozenIdRuleMissingError, compute_ids_or_require_overrides, resolve_id_authority
from lib.json_emit import write_json
from lib.paths import CandidateNotFoundError, discover_candidate_path, ensure_run_paths
from lib.schema_validate import SchemaValidationError, validate_json_schema_instance


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
                "ok": False,
                "detail": loaded_artifacts_detail,
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
        "runs": _build_runs_skeleton(),
        "metrics": {
            "tests_total": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "ret_mismatches": 0,
            "output_mismatches": 0,
            "timeouts": 0,
            "crashes": 0,
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
