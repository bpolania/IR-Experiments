from __future__ import annotations

from pathlib import Path


class CandidateNotFoundError(RuntimeError):
    pass


def discover_candidate_path(exp_root: Path, explicit_candidate: str | None = None) -> Path:
    if explicit_candidate:
        explicit = Path(explicit_candidate).resolve()
        if explicit.is_file() and explicit.suffix == ".ll":
            return explicit
        raise CandidateNotFoundError(f"explicit candidate is not a .ll file: {explicit}")

    raise CandidateNotFoundError(
        "no frozen Phase 1 candidate discovery default is defined; "
        "provide explicit --candidate /path/to/file.ll"
    )


def ensure_run_paths(exp_root: Path, candidate_id: str, run_id: str) -> tuple[Path, Path, Path]:
    run_root = exp_root / "runs" / candidate_id / run_id
    work_dir = run_root / "work"
    result_json_path = exp_root / "runs" / candidate_id / f"{run_id}.json"
    work_dir.mkdir(parents=True, exist_ok=True)
    return run_root, work_dir, result_json_path
