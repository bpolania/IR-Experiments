from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def load_artifacts(repo_root: Path) -> dict[str, Any]:
    exp_root = repo_root / "irx" / "experiment1"
    runs_root = exp_root / "runs"

    tool_versions_path = exp_root / "env" / "tool_versions.json"
    result_schema_path = exp_root / "harness" / "result_schema.json"
    constants_path = exp_root / "harness" / "constants.json"
    target_path = exp_root / "env" / "target.json"

    test_vector_paths = [
        exp_root / "tasks" / "sum_u32_le" / "tests.json",
        exp_root / "tasks" / "hex_encode" / "tests.json",
        exp_root / "tasks" / "parse_u32_decimal" / "tests.json",
    ]
    id_rule_search_paths = [
        exp_root / "harness" / "generate_run_config.py",
        exp_root / "harness" / "discover_toolchain.py",
        exp_root / "phase1_check.sh",
        exp_root / "README.md",
        exp_root / "harness" / "constants.json",
        exp_root / "harness" / "result_schema.json",
        exp_root / "env" / "tool_versions.json",
        exp_root / "env" / "target.json",
    ]

    tool_versions = _read_json(tool_versions_path)
    result_schema = _read_json(result_schema_path)
    constants = _read_json(constants_path)
    target = _read_json(target_path)
    test_vectors = {str(p.relative_to(repo_root)): _read_json(p) for p in test_vector_paths}

    detected_tools = tool_versions.get("detected", {})
    tool_paths = {
        name: entry.get("path")
        for name, entry in detected_tools.items()
        if isinstance(entry, dict)
    }

    return {
        "exp_root": exp_root,
        "tool_versions_path": tool_versions_path,
        "result_schema_path": result_schema_path,
        "constants_path": constants_path,
        "target_path": target_path,
        "test_vector_paths": test_vector_paths,
        "id_rule_search_paths": id_rule_search_paths,
        "runs_root": runs_root,
        "tool_versions": tool_versions,
        "result_schema": result_schema,
        "constants": constants,
        "target": target,
        "test_vectors": test_vectors,
        "tool_paths": tool_paths,
        "raw": {
            "tool_versions": _read_bytes(tool_versions_path),
            "result_schema": _read_bytes(result_schema_path),
            "constants": _read_bytes(constants_path),
            "target": _read_bytes(target_path),
            "test_vectors": [_read_bytes(p) for p in test_vector_paths],
        },
    }
