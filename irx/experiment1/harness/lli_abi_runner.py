#!/usr/bin/env python3
"""
Authoritative LLI ABI Harness Contract (Experiment 1)

Frozen function ABI:
  i64 @f(i8* %in_ptr, i32 %in_len, i8* %out_ptr, i32 %out_cap)

Execution contract:
- This harness executes a frozen shim module under lli and links candidate.bc as an extra module.
- The shim calls symbol @f with decoded input bytes and out buffer capacity.
- The shim emits parseable stdout records; this harness converts them to a single JSON line.

Determinism:
- No randomness.
- No clock usage in logic.
- Subprocess env is cleared except LC_ALL=C, LANG=C, TZ=UTC.
- Output JSON key order is fixed.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any


def _clip_detail(detail: str | None) -> str | None:
    if detail is None:
        return None
    text = " ".join(detail.split())
    return text[:200]


def _emit(*, ok: bool, exit_code: int | None, sig_name: str | None, ret_i64: int | None, out_hex: str | None, detail: str | None) -> int:
    obj = {
        "ok": ok,
        "exit_code": exit_code,
        "signal": sig_name,
        "ret_i64": ret_i64,
        "out_hex": out_hex,
        "detail": _clip_detail(detail),
    }
    print(json.dumps(obj, separators=(",", ":"), ensure_ascii=True))
    return 0 if ok else 1


def _signal_name_from_rc(rc: int) -> str | None:
    if rc >= 0:
        return None
    sig = -rc
    mapping = {
        signal.SIGSEGV: "SIGSEGV",
        signal.SIGILL: "SIGILL",
        signal.SIGABRT: "SIGABRT",
        signal.SIGFPE: "SIGFPE",
    }
    return mapping.get(sig)


def _parse_shim_stdout(stdout_text: str) -> tuple[int | None, str | None, str | None]:
    ret_val: int | None = None
    out_hex: str | None = None
    for line in stdout_text.splitlines():
        if line.startswith("RET="):
            try:
                ret_val = int(line[4:].strip(), 10)
            except ValueError:
                return None, None, "invalid_ret_format"
        elif line.startswith("OUT="):
            out_hex = line[4:].strip().lower()
    if ret_val is None:
        return None, None, "missing_ret"
    if out_hex is None:
        out_hex = ""
    return ret_val, out_hex, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Experiment 1 authoritative lli ABI runner")
    parser.add_argument("--lli", required=True, help="absolute path to lli")
    parser.add_argument("--bc", required=True, help="path to candidate.bc")
    parser.add_argument("--in_hex", required=True, help="input bytes as lowercase hex")
    parser.add_argument("--out_cap", required=True, type=int, help="output capacity in bytes")
    parser.add_argument("--timeout_ms", required=True, type=int, help="timeout in milliseconds")
    parser.add_argument("--entry", default="f", help="symbol name, default f")
    parser.add_argument("--workdir", default=None, help="optional working directory for deterministic temp files")
    args = parser.parse_args()

    lli_path = Path(args.lli)
    bc_path = Path(args.bc)
    shim_bc = Path(__file__).resolve().parent / "lli_shim" / "shim.bc"

    if not lli_path.is_absolute():
        return _emit(ok=False, exit_code=None, sig_name=None, ret_i64=None, out_hex=None, detail="lli_path_must_be_absolute")
    if not lli_path.is_file() or not os.access(str(lli_path), os.X_OK):
        return _emit(ok=False, exit_code=None, sig_name=None, ret_i64=None, out_hex=None, detail=f"lli_not_executable path={lli_path}")
    if not bc_path.is_file():
        return _emit(ok=False, exit_code=None, sig_name=None, ret_i64=None, out_hex=None, detail=f"candidate_bc_missing path={bc_path}")
    if args.out_cap < 0:
        return _emit(ok=False, exit_code=None, sig_name=None, ret_i64=None, out_hex=None, detail="out_cap_must_be_nonnegative")
    if args.timeout_ms <= 0:
        return _emit(ok=False, exit_code=None, sig_name=None, ret_i64=None, out_hex=None, detail="timeout_ms_must_be_positive")
    if args.entry != "f":
        return _emit(ok=False, exit_code=None, sig_name=None, ret_i64=None, out_hex=None, detail=f"unsupported_entry entry={args.entry} expected=f")
    if not shim_bc.is_file():
        return _emit(ok=False, exit_code=None, sig_name=None, ret_i64=None, out_hex=None, detail=f"shim_bc_missing path={shim_bc}")

    cwd = Path(args.workdir) if args.workdir else bc_path.parent
    if not cwd.exists() or not cwd.is_dir():
        return _emit(ok=False, exit_code=None, sig_name=None, ret_i64=None, out_hex=None, detail=f"invalid_workdir path={cwd}")

    env = {"LC_ALL": "C", "LANG": "C", "TZ": "UTC"}
    cmd = [
        str(lli_path),
        f"--extra-module={bc_path}",
        str(shim_bc),
        args.in_hex,
        str(args.out_cap),
        args.entry,
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout_text, stderr_text = proc.communicate(timeout=args.timeout_ms / 1000.0)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout_text, stderr_text = proc.communicate()

        if timed_out:
            return _emit(ok=False, exit_code=None, sig_name=None, ret_i64=None, out_hex=None, detail=f"timeout_ms={args.timeout_ms}")

        rc = proc.returncode if proc.returncode is not None else -1
        if rc != 0:
            sig_name = _signal_name_from_rc(rc)
            return _emit(
                ok=False,
                exit_code=(rc if rc >= 0 else None),
                sig_name=sig_name,
                ret_i64=None,
                out_hex=None,
                detail=f"lli_failed rc={rc} stderr={' '.join((stderr_text or '').split())[:120]}",
            )

        ret_i64, out_hex, parse_err = _parse_shim_stdout(stdout_text or "")
        if parse_err is not None:
            return _emit(ok=False, exit_code=0, sig_name=None, ret_i64=None, out_hex=None, detail=f"shim_output_parse_failed {parse_err}")

        return _emit(ok=True, exit_code=0, sig_name=None, ret_i64=ret_i64, out_hex=out_hex, detail=None)

    except Exception as exc:
        # Internal harness failure: deterministic short detail.
        return _emit(ok=False, exit_code=None, sig_name=None, ret_i64=None, out_hex=None, detail=f"harness_internal_error {type(exc).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
