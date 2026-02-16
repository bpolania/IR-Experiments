from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from lib.authority_probe import (
    ProbeSummary,
    collect_existing_runs,
    compute_candidate_id_by_algo,
    compute_run_id_by_formula,
    probe_authority_or_raise,
)


class FrozenIdRuleMissingError(RuntimeError):
    pass


def _load_frozen_id_rules_if_present(artifacts: dict[str, Any], repo_root: Path) -> dict[str, Any] | None:
    path = artifacts["exp_root"] / "harness" / "id_rules.json"
    rel = str(path.relative_to(repo_root))
    if not path.exists():
        return None

    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FrozenIdRuleMissingError(
            f"ERR_INTERNAL(-3): malformed {rel}: invalid JSON ({type(exc).__name__})"
        )

    expected = {
        "candidate_id": {"algo": "sha256_file_bytes", "input": "candidate.ll"},
        "run_id": {"algo": "sha256_utf8", "input": "candidate_id"},
    }
    if not isinstance(obj, dict):
        raise FrozenIdRuleMissingError(f"ERR_INTERNAL(-3): malformed {rel}: top-level object required")
    if set(obj.keys()) != set(expected.keys()):
        raise FrozenIdRuleMissingError(
            f"ERR_INTERNAL(-3): malformed {rel}: expected keys candidate_id,run_id only"
        )
    for top_key in ("candidate_id", "run_id"):
        val = obj.get(top_key)
        if not isinstance(val, dict):
            raise FrozenIdRuleMissingError(
                f"ERR_INTERNAL(-3): malformed {rel}: {top_key} must be object"
            )
        if set(val.keys()) != {"algo", "input"}:
            raise FrozenIdRuleMissingError(
                f"ERR_INTERNAL(-3): malformed {rel}: {top_key} must contain only algo,input"
            )
        if val != expected[top_key]:
            raise FrozenIdRuleMissingError(
                f"ERR_INTERNAL(-3): malformed {rel}: unexpected value for {top_key}"
            )

    return {"path": path, "rules": obj}


def _extract_explicit_rule_markers(text: str) -> tuple[str | None, str | None]:
    candidate_rule = None
    run_rule = None

    for line in text.splitlines():
        if candidate_rule is None and re.search(r"\bcandidate_id\b", line) and re.search(
            r"\b(hash|sha|digest|derive|format)\b", line, flags=re.IGNORECASE
        ):
            candidate_rule = line.strip()
        if run_rule is None and re.search(r"\brun_id\b", line) and re.search(
            r"\b(hash|sha|digest|derive|format)\b", line, flags=re.IGNORECASE
        ):
            run_rule = line.strip()
    return candidate_rule, run_rule


def _find_explicit_rules(artifacts: dict[str, Any], repo_root: Path) -> tuple[str | None, str | None, list[str]]:
    candidate_rule = None
    run_rule = None
    searched: list[str] = []

    for path in artifacts["id_rule_search_paths"]:
        searched.append(str(path.relative_to(repo_root)))
        text = path.read_text(encoding="utf-8")
        c_rule, r_rule = _extract_explicit_rule_markers(text)
        if candidate_rule is None and c_rule is not None:
            candidate_rule = c_rule
        if run_rule is None and r_rule is not None:
            run_rule = r_rule

    return candidate_rule, run_rule, searched


def resolve_id_authority(artifacts: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    frozen = _load_frozen_id_rules_if_present(artifacts, repo_root)
    if frozen is not None:
        rules_path = frozen["path"]
        summary = ProbeSummary(
            total_runs_scanned=0,
            usable_runs_with_candidate_bytes=0,
            runs_skipped_missing_candidate_bytes=0,
            skipped_runs=[],
            inference_status="SKIPPED_FROZEN_ID_RULES",
            counterexample_detail=None,
        )
        return {
            "explicit_candidate_rule": "candidate_id=sha256(candidate.ll bytes) from harness/id_rules.json",
            "explicit_run_rule": "run_id=sha256(candidate_id utf8) from harness/id_rules.json",
            "searched_paths": [str(rules_path.relative_to(repo_root))],
            "records_count": 0,
            "candidate_algo": "sha256",
            "run_formula": "sha256(candidate_id_utf8)",
            "candidate_reason": (
                "candidate_id frozen by harness/id_rules.json: sha256(candidate.ll bytes)"
            ),
            "run_reason": (
                "run_id frozen by harness/id_rules.json: sha256(candidate_id utf8)"
            ),
            "probe_summary": summary,
        }

    explicit_candidate_rule, explicit_run_rule, searched = _find_explicit_rules(artifacts, repo_root)
    artifact_blobs = [
        artifacts["raw"]["tool_versions"],
        artifacts["raw"]["result_schema"],
        artifacts["raw"]["constants"],
        artifacts["raw"]["target"],
        *artifacts["raw"]["test_vectors"],
    ]
    records = collect_existing_runs(artifacts["runs_root"])
    inferred = probe_authority_or_raise(artifacts["runs_root"], artifact_blobs)

    return {
        "explicit_candidate_rule": explicit_candidate_rule,
        "explicit_run_rule": explicit_run_rule,
        "searched_paths": searched,
        "records_count": len(records),
        "candidate_algo": inferred.candidate_algo,
        "run_formula": inferred.run_formula,
        "candidate_reason": inferred.candidate_reason,
        "run_reason": inferred.run_reason,
        "probe_summary": inferred.summary,
    }


def compute_ids_or_require_overrides(
    *,
    authority: dict[str, Any],
    candidate_bytes: bytes,
    artifacts: dict[str, Any],
    provided_candidate_id: str | None,
    provided_run_id: str | None,
) -> tuple[str, str, list[str]]:
    notes: list[str] = []

    candidate_id: str | None = None
    run_id: str | None = None

    candidate_algo = authority.get("candidate_algo")
    run_formula = authority.get("run_formula")

    if candidate_algo is not None:
        candidate_id = compute_candidate_id_by_algo(candidate_algo, candidate_bytes)
        notes.append(f"candidate_id rule from runs evidence: {candidate_algo}(candidate.ll bytes)")
        if provided_candidate_id is not None and provided_candidate_id != candidate_id:
            raise FrozenIdRuleMissingError(
                "ERR_INTERNAL(-3): provided --candidate-id does not match authoritative computed candidate_id"
            )
    else:
        if provided_candidate_id is None:
            raise FrozenIdRuleMissingError(
                "ERR_INTERNAL(-3): missing authoritative candidate_id derivation rule; "
                "provide --candidate-id explicitly. "
                f"inference_reason={authority.get('candidate_reason')}"
            )
        candidate_id = provided_candidate_id
        notes.append("candidate_id provided via --candidate-id (authoritative fallback)")

    artifact_blobs = [
        artifacts["raw"]["tool_versions"],
        artifacts["raw"]["result_schema"],
        artifacts["raw"]["constants"],
        artifacts["raw"]["target"],
        *artifacts["raw"]["test_vectors"],
    ]

    if run_formula is not None:
        run_id = compute_run_id_by_formula(run_formula, candidate_id, candidate_bytes, artifact_blobs)
        notes.append(f"run_id rule from runs evidence: {run_formula}")
        if provided_run_id is not None and provided_run_id != run_id:
            raise FrozenIdRuleMissingError(
                "ERR_INTERNAL(-3): provided --run-id does not match authoritative computed run_id"
            )
    else:
        if provided_run_id is None:
            raise FrozenIdRuleMissingError(
                "ERR_INTERNAL(-3): missing authoritative run_id derivation rule; "
                "provide --run-id explicitly. "
                f"inference_reason={authority.get('run_reason')}"
            )
        run_id = provided_run_id
        notes.append("run_id provided via --run-id (authoritative fallback)")

    return candidate_id, run_id, notes
