from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class AuthorityRecoveryError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass
class ExistingRunEvidence:
    json_path: Path
    run_key: str
    candidate_dir: str
    run_stem: str
    json_candidate_id: str
    json_run_id: str
    candidate_bytes: bytes | None


@dataclass
class ProbeSummary:
    total_runs_scanned: int
    usable_runs_with_candidate_bytes: int
    runs_skipped_missing_candidate_bytes: int
    skipped_runs: list[str]
    inference_status: str
    counterexample_detail: str | None


@dataclass
class InferredAuthority:
    candidate_algo: str | None
    run_formula: str | None
    candidate_reason: str
    run_reason: str
    summary: ProbeSummary


def _bounded_entries(entries: list[str], limit: int = 20) -> str:
    shown = entries[:limit]
    if len(entries) <= limit:
        return str(shown)
    omitted = len(entries) - limit
    return str(shown + [f"... ({omitted} more omitted)"])


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha1_hex(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _blake2b256_hex(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def _artifact_material_v1(candidate_id: str, artifact_blobs: list[bytes]) -> str:
    parts = [candidate_id.encode("utf-8")]
    parts.extend(_sha256_hex(blob).encode("utf-8") for blob in artifact_blobs)
    return _sha256_hex(b"\n".join(parts))


def _hash_algorithms() -> dict[str, Callable[[bytes], str]]:
    return {
        "sha256": _sha256_hex,
        "sha1": _sha1_hex,
        "blake2b256": _blake2b256_hex,
    }


def _run_formulas(artifact_blobs: list[bytes]) -> dict[str, Callable[[str, bytes], str]]:
    return {
        "sha256(candidate_id_utf8)": lambda candidate_id, candidate_bytes: _sha256_hex(candidate_id.encode("utf-8")),
        "sha1(candidate_id_utf8)": lambda candidate_id, candidate_bytes: _sha1_hex(candidate_id.encode("utf-8")),
        "blake2b256(candidate_id_utf8)": lambda candidate_id, candidate_bytes: _blake2b256_hex(candidate_id.encode("utf-8")),
        "sha256(candidate_ll_bytes)": lambda candidate_id, candidate_bytes: _sha256_hex(candidate_bytes),
        "artifact_material_v1": lambda candidate_id, candidate_bytes: _artifact_material_v1(candidate_id, artifact_blobs),
    }


def collect_existing_runs(runs_root: Path) -> list[ExistingRunEvidence]:
    records: list[ExistingRunEvidence] = []
    if not runs_root.exists():
        return records

    # Deterministic ordering: candidate dirs sorted, then direct JSON children sorted.
    candidate_dirs = sorted(
        [p for p in runs_root.iterdir() if p.is_dir() and not p.name.startswith(".")],
        key=lambda p: p.name,
    )

    for candidate_path in candidate_dirs:
        run_jsons = sorted(
            [
                p
                for p in candidate_path.iterdir()
                if p.is_file()
                and p.suffix == ".json"
                and not p.name.startswith(".")
            ],
            key=lambda p: p.name,
        )

        for json_path in run_jsons:
            candidate_dir = candidate_path.name
            run_stem = json_path.stem
            run_key = f"{candidate_dir}/{run_stem}"
            obj = json.loads(json_path.read_text(encoding="utf-8"))
            json_candidate_id = obj.get("candidate_id", "")
            json_run_id = obj.get("run_id", "")
            work_candidate = runs_root / candidate_dir / run_stem / "work" / "candidate.ll"

            candidate_bytes = None
            if work_candidate.is_file():
                try:
                    raw = work_candidate.read_bytes()
                    if len(raw) > 0:
                        candidate_bytes = raw
                except OSError:
                    candidate_bytes = None

            records.append(
                ExistingRunEvidence(
                    json_path=json_path,
                    run_key=run_key,
                    candidate_dir=candidate_dir,
                    run_stem=run_stem,
                    json_candidate_id=json_candidate_id,
                    json_run_id=json_run_id,
                    candidate_bytes=candidate_bytes,
                )
            )

    return records


def _raise_no_usable_runs(records: list[ExistingRunEvidence], total: int) -> None:
    scanned = [r.run_key for r in records]
    raise AuthorityRecoveryError(
        4,
        "ERR_AUTHORITY_RECOVERY(-4): cannot infer ID rules; no usable historical runs found under "
        "irx/experiment1/runs/"
        f"; total_runs_scanned={total}; usable_runs_with_candidate_bytes=0; "
        f"scanned_runs={_bounded_entries(scanned)}",
    )


def _first_candidate_counterexample(records: list[ExistingRunEvidence], algo_name: str) -> str | None:
    fn = _hash_algorithms()[algo_name]
    for r in records:
        if r.candidate_bytes is None:
            continue
        expected = fn(r.candidate_bytes)
        actual = r.json_candidate_id
        if not (expected == actual == r.candidate_dir):
            return (
                "ERR_AUTHORITY_RECOVERY(-5): historical run counterexample found\n"
                f"  run: {r.run_key}\n"
                f"  expected candidate_id: {expected}\n"
                f"  actual candidate_id: {actual}\n"
                f"  expected run_id: <unknown>\n"
                f"  actual run_id: {r.json_run_id}"
            )
    return None


def _first_run_counterexample(records: list[ExistingRunEvidence], candidate_algo: str, run_formula: str, artifact_blobs: list[bytes]) -> str | None:
    cand_fn = _hash_algorithms()[candidate_algo]
    run_fn = _run_formulas(artifact_blobs)[run_formula]
    for r in records:
        if r.candidate_bytes is None:
            continue
        expected_candidate = cand_fn(r.candidate_bytes)
        expected_run = run_fn(expected_candidate, r.candidate_bytes)
        if expected_candidate != r.json_candidate_id or expected_candidate != r.candidate_dir or expected_run != r.json_run_id or expected_run != r.run_stem:
            return (
                "ERR_AUTHORITY_RECOVERY(-5): historical run counterexample found\n"
                f"  run: {r.run_key}\n"
                f"  expected candidate_id: {expected_candidate}\n"
                f"  actual candidate_id: {r.json_candidate_id}\n"
                f"  expected run_id: {expected_run}\n"
                f"  actual run_id: {r.json_run_id}"
            )
    return None


def infer_candidate_rule(records: list[ExistingRunEvidence]) -> tuple[str | None, str]:
    usable = [r for r in records if r.candidate_bytes is not None]
    if not usable:
        return None, "no existing runs with work/candidate.ll bytes available"

    matches: list[str] = []
    for algo_name, fn in _hash_algorithms().items():
        all_match = True
        for r in usable:
            expected = fn(r.candidate_bytes or b"")
            if not (expected == r.candidate_dir and expected == r.json_candidate_id and r.candidate_dir == r.json_candidate_id):
                all_match = False
                break
        if all_match:
            matches.append(algo_name)

    if len(matches) == 1:
        return matches[0], (
            f"candidate_id inferred from runs evidence: {matches[0]}(candidate.ll bytes) "
            f"matches candidate dir and JSON candidate_id across {len(usable)} run(s)"
        )
    if len(matches) == 0:
        return None, "no hash candidate matched all run evidences"
    return None, f"ambiguous candidate hash inference: matched {matches}"


def infer_run_rule(records: list[ExistingRunEvidence], artifact_blobs: list[bytes], candidate_algo: str | None) -> tuple[str | None, str]:
    if candidate_algo is None:
        return None, "run_id inference blocked because candidate_id rule is unresolved"

    usable = [r for r in records if r.candidate_bytes is not None]
    if not usable:
        return None, "no existing runs with candidate bytes available for run_id inference"

    cand_fn = _hash_algorithms()[candidate_algo]

    matches: list[str] = []
    for formula_name, fn in _run_formulas(artifact_blobs).items():
        all_match = True
        for r in usable:
            candidate_id = cand_fn(r.candidate_bytes or b"")
            expected_run = fn(candidate_id, r.candidate_bytes or b"")
            if not (expected_run == r.run_stem and expected_run == r.json_run_id and r.run_stem == r.json_run_id):
                all_match = False
                break
        if all_match:
            matches.append(formula_name)

    if len(matches) == 1:
        return matches[0], (
            f"run_id inferred from runs evidence: {matches[0]} matches run file stem and JSON run_id "
            f"across {len(usable)} run(s)"
        )
    if len(matches) == 0:
        return None, "no run_id formula candidate matched all run evidences"
    return None, f"ambiguous run_id inference: matched {matches}"


def probe_authority_or_raise(runs_root: Path, artifact_blobs: list[bytes]) -> InferredAuthority:
    records = collect_existing_runs(runs_root)
    total = len(records)
    if total == 0:
        _raise_no_usable_runs(records, total)

    # Path/JSON identity mismatch is a deterministic historical counterexample.
    for r in records:
        if r.candidate_dir != r.json_candidate_id or r.run_stem != r.json_run_id:
            raise AuthorityRecoveryError(
                5,
                "ERR_AUTHORITY_RECOVERY(-5): historical run counterexample found\n"
                f"  run: {r.run_key}\n"
                f"  expected candidate_id: {r.candidate_dir}\n"
                f"  actual candidate_id: {r.json_candidate_id}\n"
                f"  expected run_id: {r.run_stem}\n"
                f"  actual run_id: {r.json_run_id}",
            )

    usable = [r for r in records if r.candidate_bytes is not None]
    skipped = [r.run_key for r in records if r.candidate_bytes is None]
    if len(usable) == 0:
        _raise_no_usable_runs(records, total)

    candidate_algo, candidate_reason = infer_candidate_rule(records)
    if candidate_algo is None:
        detail = _first_candidate_counterexample(records, "sha256") or (
            "ERR_AUTHORITY_RECOVERY(-5): historical run counterexample found\n"
            "  run: <unknown>\n"
            "  expected candidate_id: <unknown>\n"
            "  actual candidate_id: <unknown>\n"
            "  expected run_id: <unknown>\n"
            "  actual run_id: <unknown>"
        )
        raise AuthorityRecoveryError(5, detail)

    run_formula, run_reason = infer_run_rule(records, artifact_blobs, candidate_algo)
    if run_formula is None:
        detail = _first_run_counterexample(records, candidate_algo, "artifact_material_v1", artifact_blobs) or (
            "ERR_AUTHORITY_RECOVERY(-5): historical run counterexample found\n"
            "  run: <unknown>\n"
            "  expected candidate_id: <unknown>\n"
            "  actual candidate_id: <unknown>\n"
            "  expected run_id: <unknown>\n"
            "  actual run_id: <unknown>"
        )
        raise AuthorityRecoveryError(5, detail)

    detail = _first_run_counterexample(records, candidate_algo, run_formula, artifact_blobs)
    if detail is not None:
        raise AuthorityRecoveryError(5, detail)

    summary = ProbeSummary(
        total_runs_scanned=total,
        usable_runs_with_candidate_bytes=len(usable),
        runs_skipped_missing_candidate_bytes=len(skipped),
        skipped_runs=skipped,
        inference_status="PASS",
        counterexample_detail=None,
    )

    return InferredAuthority(
        candidate_algo=candidate_algo,
        run_formula=run_formula,
        candidate_reason=candidate_reason,
        run_reason=run_reason,
        summary=summary,
    )


def format_probe_summary(summary: ProbeSummary) -> str:
    lines = [
        "Authority probe summary:",
        f"  total_runs_scanned: {summary.total_runs_scanned}",
        f"  usable_runs_with_candidate_bytes: {summary.usable_runs_with_candidate_bytes}",
        f"  runs_skipped_missing_candidate_bytes: {summary.runs_skipped_missing_candidate_bytes}",
        f"  inference_status: {summary.inference_status}",
    ]
    if summary.runs_skipped_missing_candidate_bytes > 0:
        lines.append(f"  skipped_runs: {_bounded_entries(summary.skipped_runs)}")
    if summary.counterexample_detail is not None:
        lines.append(f"  counterexample: {summary.counterexample_detail}")
    return "\n".join(lines)


def compute_candidate_id_by_algo(algo: str, candidate_bytes: bytes) -> str:
    fn = _hash_algorithms().get(algo)
    if fn is None:
        raise ValueError(f"unsupported candidate algo: {algo}")
    return fn(candidate_bytes)


def compute_run_id_by_formula(formula: str, candidate_id: str, candidate_bytes: bytes, artifact_blobs: list[bytes]) -> str:
    fn = _run_formulas(artifact_blobs).get(formula)
    if fn is None:
        raise ValueError(f"unsupported run formula: {formula}")
    return fn(candidate_id, candidate_bytes)
