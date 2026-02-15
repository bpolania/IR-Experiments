#!/usr/bin/env python3
import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    constants_path = root / "harness" / "constants.json"
    target_path = root / "env" / "target.json"
    out_path = root / "env" / "run_config.default.json"

    with constants_path.open("r", encoding="utf-8") as f:
        constants = json.load(f)

    with target_path.open("r", encoding="utf-8") as f:
        target = json.load(f)

    run_config = {
        "experiment": "1",
        "target_triple": target["triple"],
        "limits": constants["limits"],
        "modes": {
            "lli_enabled": True,
            "native_enabled": True,
            "sanitizer_enabled": False,
            "fuzz_enabled": False
        },
        "determinism": {
            "clear_env": True,
            "cwd_mode": "run_dir",
            "seed_source": "candidate_id"
        },
        "logging": {
            "capture_stdout": True,
            "capture_stderr": True
        }
    }

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(run_config, f, indent=2)
        f.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
