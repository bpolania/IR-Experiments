# IR Experiments - Experiment 1 - Phase 0

This directory contains only the deterministic Phase 0 scaffold for Experiment 1.
Execution logic is intentionally not implemented yet.

## Layout

- `env/`: frozen target metadata and tool version placeholder files.
- `tasks/`: task specifications and fixed test vectors.
  - `tasks/sum_u32_le/`: `spec.json`, `tests.json`
  - `tasks/hex_encode/`: `spec.json`, `tests.json`
  - `tasks/parse_u32_decimal/`: `spec.json`, `tests.json`
- `harness/`: frozen shared constants and result schema.
- `candidates/`: empty directory reserved for submitted candidates.
- `runs/`: empty directory reserved for run artifacts.

## Frozen Assets

- ABI and limits: `harness/constants.json`
- Task specs and vectors: `tasks/*/spec.json`, `tasks/*/tests.json`
- Result shape contract: `harness/result_schema.json`

## ID Derivation (Frozen)

Authoritative ID rules are frozen in `harness/id_rules.json`:
- `candidate_id = sha256(candidate.ll bytes).hexdigest()`
- `run_id = sha256(candidate_id UTF-8).hexdigest()`

## Phase 1: Toolchain Discovery and Environment Capture

Phase 1 adds deterministic local toolchain discovery and canonical run-configuration capture.
This phase verifies binary availability, records paths and versions, and generates frozen run defaults.

Files added/updated in Phase 1:
- Added: `harness/discover_toolchain.py`
- Added: `harness/generate_run_config.py`
- Added: `phase1_check.sh`
- Added: `env/run_config.default.json` (generated)
- Updated: `env/tool_versions.json` (`detected` populated by discovery)

Phase 1 does not implement candidate execution, LLVM gates, `lli` runs, `llc` builds, or policy checking.

## Raspberry Pi Quick Start (Phase 1)

This project's authoritative target environment is Raspberry Pi OS 64-bit (aarch64 Linux). Run Phase 1 on the Pi to capture the real toolchain state before starting Phase 2.

1) Pull the repo on the Pi
- Ensure you are on Raspberry Pi OS 64-bit (aarch64).

2) Confirm required binaries exist

Phase 1 requires these binaries to be present on the Pi:
- llvm-as
- opt
- lli
- llc
- clang

3) Run Phase 1 check

From the repository root:

```bash
bash irx/experiment1/phase1_check.sh
echo $?
```

4) Expected result
- Exit code 0 means all required binaries were found.
- Exit code non-zero means one or more required binaries are missing (Phase 1 still writes partial detection output).

5) Inspect captured environment artifacts

After the script runs, review:
- `irx/experiment1/env/tool_versions.json`
- All required binaries should have `"ok": true`
- Paths should be Linux paths (for example `/usr/bin/llvm-as`)
- Version text should reference LLVM/clang for Linux (not Apple clang)
- `irx/experiment1/env/run_config.default.json`
- Must contain:
- `"experiment": "1"`
- `"target_triple": "aarch64-unknown-linux-gnu"`
- limits copied from `harness/constants.json`

6) Do not proceed to Phase 2 until Phase 1 passes on the Pi

Phase 2 depends on a valid ARM64/Linux LLVM toolchain and a captured tool snapshot.

## ABI Harness Contract

Authoritative `lli` harness entrypoint:
- `irx/experiment1/harness/lli_abi_runner.py`

Frozen candidate ABI:
- `i64 @f(i8* %in_ptr, i32 %in_len, i8* %out_ptr, i32 %out_cap)`

Frozen shim source and contract docs:
- `irx/experiment1/harness/lli_shim/shim.c`
- `irx/experiment1/harness/lli_shim/README.md`

The harness executes `lli` with an absolute `--lli` path, links `candidate.bc` with the frozen shim, and prints exactly one JSON object to stdout.

## Per-test Results Schema

`harness/result_schema.json` includes an optional top-level field:
- `test_results`: array of per-test records for `lli_tests`

Each item records expected vs actual return/output plus deterministic outcome classification without changing existing required top-level fields.

## Raspberry Pi (ARM64) runbook (Experiment 1)

### 1) Toolchain snapshot (must match)

This experiment uses frozen absolute tool paths from:

- `env/tool_versions.json`

The Phase 2 runner will not use PATH lookup. It will use the snapshot paths and will record `POLICY_VIOLATION` if a frozen tool path is missing/non-executable.

Verify on Pi:

```bash
cat env/tool_versions.json | sed -n '1,200p'
ls -l /usr/lib/llvm-19/bin/llvm-as /usr/lib/llvm-19/bin/opt /usr/lib/llvm-19/bin/lli || true
```

### 2) Frozen ABI for @f (authoritative)

Candidate function signature (LLVM):
- `i64 @f(i8* %in_ptr, i32 %in_len, i8* %out_ptr, i32 %out_cap)`

C equivalent:
- `int64_t f(uint8_t* in_ptr, int32_t in_len, uint8_t* out_ptr, int32_t out_cap);`

Do not introduce wrappers or alternate signatures without an authority revision.

### 3) Build the lli shim bitcode (required for Step E)

The ABI harness uses a shim module compiled to bitcode:
- `harness/lli_shim/shim.c -> harness/lli_shim/shim.bc`

Build on Pi (use frozen LLVM tools):

```bash
cd irx/experiment1/harness/lli_shim
/usr/lib/llvm-19/bin/clang -O0 -S -emit-llvm shim.c -o shim.ll
/usr/lib/llvm-19/bin/llvm-as shim.ll -o shim.bc
ls -l shim.bc
```

### 4) Harness contract (`harness/lli_abi_runner.py`)

The harness is the authoritative way to run a single test case under lli without inventing ABI semantics.

CLI:
- `--lli <absolute_path>` (required)
- `--bc <path/to/candidate.bc>` (required)
- `--in_hex <hex>` (required)
- `--out_cap <int>` (required)
- `--timeout_ms <int>` (required)
- `--entry <symbol>` (optional, default `f`)
- `--workdir <dir>` (optional)

Stdout: exactly one JSON line with fixed keys:
- `ok`, `exit_code`, `signal`, `ret_i64`, `out_hex`, `detail`

Preflight (no tool execution required):

```bash
python3 -m py_compile harness/lli_abi_runner.py
python3 harness/lli_abi_runner.py --lli /does/not/matter --bc /tmp/missing.bc --in_hex 00 --out_cap 4 --timeout_ms 10
```

### 5) Phase 2 runner (current gates)

Run:

```bash
python3 runner/phase2/phase2_runner.py --candidate /path/to/candidate.ll
```

Artifacts:
- `runs/<candidate_id>/<run_id>.json`
- `runs/<candidate_id>/<run_id>/work/`

Notes:
- Step B enforces `limits.max_ll_bytes` and `limits.max_ll_lines` from `harness/constants.json`.
- Step C uses `llvm-as` to produce `work/candidate.bc`.
- Step D runs `opt -verify -disable-output candidate.bc`.
- Step E is unblocked by the `test_results` schema container and the `lli_abi_runner.py` harness + shim.

## Step F End-to-End Verification Fixture

A known-good `sum_u32_le` candidate is provided in `verification/step_f/` for pipeline verification:

- `verification/step_f/sum_u32_le_good.ll` - Correct implementation passing 9/10 frozen vectors
- `verification/step_f/run_step_f_check.sh` - Automated verification script

Run:

```bash
bash irx/experiment1/verification/step_f/run_step_f_check.sh
```

The candidate passes all pipeline stages through `lli_tests` (10/10 vectors).

## Authority Revision: t08 expected_out_hex correction

`tasks/sum_u32_le/tests.json` vector t08 (index 7) `expected_out_hex` was corrected
from `"fffffffe"` (MSB-first value notation) to `"feffffff"` (little-endian byte order).
This aligns t08 with the LE-byte encoding convention used by the ABI harness and all
other vectors in the file. No other fields, vectors, or files were changed.

## Verification Fixtures

Pipeline wiring fixtures and run instructions are in `verification/README.md`.
