#!/usr/bin/env python3
import json
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    tool_versions_path = root / "env" / "tool_versions.json"

    with tool_versions_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    required = data.get("required_binaries", [])
    detected = {}
    missing_any = False

    for binary in required:
        path = shutil.which(binary)
        if path is None:
            detected[binary] = {
                "ok": False,
                "path": None,
                "version_text": None,
                "error": "not found"
            }
            missing_any = True
            continue

        try:
            proc = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                text=True,
                check=False
            )
            version_text = (proc.stdout + proc.stderr).strip()
            if proc.returncode == 0:
                detected[binary] = {
                    "ok": True,
                    "path": str(Path(path).resolve()),
                    "version_text": version_text,
                    "error": None
                }
            else:
                detected[binary] = {
                    "ok": False,
                    "path": str(Path(path).resolve()),
                    "version_text": version_text if version_text else None,
                    "error": f"--version failed with exit code {proc.returncode}"
                }
        except Exception as exc:
            detected[binary] = {
                "ok": False,
                "path": str(Path(path).resolve()),
                "version_text": None,
                "error": str(exc)
            }

    out = {
        "required_binaries": required,
        "detected": detected
    }

    with tool_versions_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")

    return 1 if missing_any else 0


if __name__ == "__main__":
    sys.exit(main())
