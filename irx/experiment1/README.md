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
