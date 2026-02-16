# IR Experiments — Experiment 1 — Raspberry Pi Phase 2 Report

**Platform**: Raspberry Pi 5 (Cortex-A76, aarch64)
**OS**: Raspberry Pi OS 64-bit (Debian-based), kernel 6.12.47+rpt-rpi-2712
**LLVM**: Debian LLVM 19.1.7 (Optimized build)
**Target triple**: `aarch64-unknown-linux-gnu`

---

## 1 Executive Summary

This report documents the complete Phase 2 lifecycle for Experiment 1 on
Raspberry Pi 5. The project progressed from a non-functional runner that
could not even load the LLVM shared library, through five incremental
verification rounds, to a fully operational pipeline that compiles a
correct LLVM IR candidate into a native aarch64 object file.

Six generations of work:

1. **Initial** — llvm-as failed at runtime: missing `LD_LIBRARY_PATH` in the
   cleared subprocess environment and an overly restrictive `RLIMIT_AS`
   ceiling that prevented memory-mapping the 123 MB `libLLVM.so.19.1`.
2. **Post-fix** — Environment patch restored llvm-as and opt execution. All
   tools could run, but opt used legacy `-verify` syntax incompatible with
   LLVM 19's new pass manager, causing every opt_verify stage to fail.
3. **Follow-up 1** — Re-verified the environment fix. Confirmed precheck,
   llvm_as_parse, candidate.bc production, and run determinism. The
   opt_verify failure was noted but not yet diagnosed.
4. **Full sweep** — Identified and patched four gaps: opt syntax, target
   triple key mismatch, broken schema per-test detection, and a hardcoded
   lli_tests failure block that prevented the harness from ever being
   invoked. Steps A-E verified PASS.
5. **Authority revision** — A known-good candidate exposed a byte-order error
   in test vector t08. The frozen `expected_out_hex` used MSB-first value
   notation (`"fffffffe"`) instead of the LE-byte encoding (`"feffffff"`)
   used by every other vector. Single-field correction unblocked Step F.
6. **Step F evidence** — With the corrected vector, the known-good candidate
   achieves 10/10 lli_tests, llc_compile executes, and `candidate.o` (1 008
   bytes, aarch64 ELF relocatable) is produced. Evidence bundle and
   reproducible check script committed.

**Final status**: Phase 2 verified end-to-end through Step F (llc_compile).
The pipeline accepts a `.ll` candidate, validates it, runs it against frozen
test vectors under lli, and compiles it to a native object file. Steps G-H
(clang_link, native_tests) remain unwired in the runner.

---

## 2 Pipeline Architecture

### 2.1 Overview

The Phase 2 runner (`runner/phase2/phase2_runner.py`) accepts a `.ll`
candidate file, derives deterministic IDs from it, then executes a fixed
sequence of LLVM tool stages inside a minimal subprocess environment.
Results are recorded in a schema-validated JSON artifact under
`irx/experiment1/runs/<candidate_id>/<run_id>.json`.

### 2.2 Stage Sequence

| Index | Stage | Tool | Precondition |
|-------|-------|------|--------------|
| 0 | `precheck` | static analysis | — |
| 1 | `llvm_as_parse` | `/usr/lib/llvm-19/bin/llvm-as` | precheck.ok |
| 2 | `opt_verify` | `/usr/lib/llvm-19/bin/opt` | llvm_as_parse.ok, candidate.bc exists |
| 3 | `lli_tests` | `/usr/lib/llvm-19/bin/lli` + harness | opt_verify.ok, harness resolved, task vectors loaded |
| 4 | `llc_compile` | `/usr/lib/llvm-19/bin/llc` | lli_tests.ok, candidate.bc exists |
| 5 | `clang_link` | `/usr/lib/llvm-19/bin/clang` | llc_compile.ok (not yet wired) |
| 6 | `native_tests` | native binary | clang_link.ok (not yet wired) |

Each stage either executes and records its result, or is marked NOT_RUN:

```json
{"stage": "<name>", "ok": false, "exit_code": null, "duration_ms": 0, "rss_mib": null, "crash": null}
```

### 2.3 ID Derivation

Frozen rules in `irx/experiment1/harness/id_rules.json`:

- `candidate_id = sha256(candidate.ll file bytes).hexdigest()`
- `run_id = sha256(candidate_id as UTF-8 string).hexdigest()`

The authority probe reports `inference_status: SKIPPED_FROZEN_ID_RULES` when
the rules file is present, bypassing historical run inference entirely.

### 2.4 Subprocess Environment

All LLVM tool subprocesses run with a cleared environment containing exactly
four variables:

```
LC_ALL=C  LANG=C  TZ=UTC  LD_LIBRARY_PATH=/usr/lib/llvm-19/lib
```

`LD_LIBRARY_PATH` is derived deterministically from the frozen tool path
(`parent.parent / lib`). No host environment variables are consulted.

### 2.5 Resource Limits

`RLIMIT_RSS` is applied at `max_rss_mib = 64` MiB on Linux. `RLIMIT_AS`
(virtual address space) is intentionally not applied because the LLVM shared
library (`libLLVM.so.19.1`, 123 MB on disk) requires virtual memory well
beyond 64 MiB for its memory-mapped segments.

---

## 3 Frozen Artifact Inventory

### 3.1 Tool Versions (`env/tool_versions.json`)

| Tool | Frozen Path | Version |
|------|-------------|---------|
| llvm-as | `/usr/lib/llvm-19/bin/llvm-as` | 19.1.7 |
| opt | `/usr/lib/llvm-19/bin/opt` | 19.1.7 |
| lli | `/usr/lib/llvm-19/bin/lli` | 19.1.7 |
| llc | `/usr/lib/llvm-19/bin/llc` | 19.1.7 |
| clang | `/usr/lib/llvm-19/bin/clang` | 19.1.7 |

All confirmed present, executable, owned by root.

### 3.2 Limits (`harness/constants.json`)

| Limit | Value | Enforced at |
|-------|-------|-------------|
| `max_ll_bytes` | 65 536 | precheck |
| `max_ll_lines` | 2 000 | precheck |
| `max_basic_blocks` | 200 | reserved |
| `max_instructions` | 20 000 | reserved |
| `max_alloca_bytes_total` | 4 096 | reserved |
| `timeout_stage_ms` | 1 000 | llvm_as, opt, llc |
| `timeout_per_test_ms` | 50 | lli_tests |
| `max_rss_mib` | 64 | all tool stages |

### 3.3 Target (`env/target.json`)

```json
{"os": "raspios64", "arch": "aarch64", "triple": "aarch64-unknown-linux-gnu", "endian": "little"}
```

Note: the key is `triple`, not `target_triple`. The runner accepts both (Patch 2, section 6.2).

### 3.4 ID Rules (`harness/id_rules.json`)

```json
{
  "candidate_id": {"algo": "sha256_file_bytes", "input": "candidate.ll"},
  "run_id": {"algo": "sha256_utf8", "input": "candidate_id"}
}
```

### 3.5 Result Schema (`harness/result_schema.json`)

Required top-level keys: `experiment`, `task`, `candidate_id`, `run_id`,
`timestamps`, `gates`, `runs`, `metrics`, `verdict`. Optional `test_results`
array of `$defs.testResult` objects with per-test fields: `index`, `in_hex`,
`out_cap`, `expected_ret`, `expected_out_hex`, `actual_ret`, `actual_out_hex`,
`outcome`, `exit_code`, `signal`, `detail`.

### 3.6 ABI Harness

- Entrypoint: `harness/lli_abi_runner.py`
- Shim: `harness/lli_shim/shim.bc`
- Candidate ABI: `int64_t f(uint8_t* in_ptr, int32_t in_len, uint8_t* out_ptr, int32_t out_cap)`
- LLVM IR: `i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap)`

The harness runs `lli --extra-module=candidate.bc shim.bc <in_hex> <out_cap> f`
in a clean environment (`LC_ALL=C LANG=C TZ=UTC`), parses the shim's
`RET=`/`OUT=` stdout lines, and emits a single JSON object with keys `ok`,
`exit_code`, `signal`, `ret_i64`, `out_hex`, `detail`.

### 3.7 Test Vectors

| Task | File | Vectors |
|------|------|---------|
| sum_u32_le | `tasks/sum_u32_le/tests.json` | 10 |
| hex_encode | `tasks/hex_encode/tests.json` | present |
| parse_u32_decimal | `tasks/parse_u32_decimal/tests.json` | present |

---

## 4 Generation 1: Initial Verification and Environment Fix

### 4.1 Failure

The first runner execution on the Pi failed immediately at llvm_as_parse:

```
rc=127; stderr: error while loading shared libraries: libLLVM.so.19.1:
failed to map segment from shared object
```

Two root causes:

1. **Missing `LD_LIBRARY_PATH`**: The runner's `clear_env=true` created a
   subprocess with no library search paths. The LLVM shared library at
   `/usr/lib/llvm-19/lib/libLLVM.so.19.1` (symlink chain to
   `/usr/lib/aarch64-linux-gnu/libLLVM.so.19.1`, 123 MB) was not discoverable.

2. **`RLIMIT_AS` = 64 MiB**: The runner applied `max_rss_mib` to `RLIMIT_AS`
   (virtual address space). The 123 MB library requires virtual address space
   for memory mapping that far exceeds 64 MiB.

### 4.2 Fix

Two changes to `runner/phase2/phase2_runner.py`:

1. Added `_derive_llvm_lib_path(tool_path)` and `_build_llvm_tool_env(tool_path)`
   — derives `LD_LIBRARY_PATH` deterministically from the frozen tool path
   (`parent.parent / lib`), verified to exist on disk.

2. Replaced per-stage `_preexec` functions with `_build_llvm_tool_preexec(max_rss_mib)`
   — applies only `RLIMIT_RSS`, not `RLIMIT_AS`.

Constraints satisfied: no `clear_env` disable, no `os.environ` passthrough,
no arbitrary host `LD_LIBRARY_PATH`, deterministic derivation, no gate or
schema changes.

---

## 5 Generation 2: Follow-up 1 Re-verification

All 7 verification steps passed:

| Step | Check | Status |
|------|-------|--------|
| 1 | `py_compile runner/phase2/phase2_runner.py` | PASS |
| 2 | Frozen tool paths present and executable | PASS |
| 3 | Minimal candidate created (91 bytes, 4 lines) | PASS |
| 4 | Stderr shows `[llvm-as] LD_LIBRARY_PATH=...` | PASS |
| 5 | precheck.ok=true, llvm_as_parse.ok=true, exit=0 | PASS |
| 6 | `work/candidate.bc` exists, 1 388 bytes | PASS |
| 7 | Determinism: IDS_MATCH=True, MASKED_JSON_EQUAL=True | PASS |

opt_verify returned `ok=false, exit_code=1`. Attributed at the time to the
trivial `ret i64 0` stub. The actual cause (legacy opt syntax) was identified
in the full sweep.

---

## 6 Generation 3: Full Phase 2 Sweep

### 6.1 Gaps Identified

**Gap 1 — opt_verify uses legacy syntax**: `opt -verify -disable-output` is
not supported by LLVM 19's new pass manager. Every invocation exits 1 with
"The `opt -passname` syntax for the new pass manager is not supported."

**Gap 2 — target_triple key mismatch**: `_resolve_target_triple` looked for
`target_triple` but the frozen `target.json` uses `triple`.

**Gap 3 — Schema per-test detection broken**: `_schema_supports_per_test_results`
did not resolve `$ref` pointers in the JSON schema and checked for field
`test_id` instead of `index`. False-negative detection blocked lli_tests.

**Gap 4 — lli_tests hardcoded failure**: Even when the harness existed and the
schema supported per-test results, lli_tests fell through to a hardcoded
error: "frozen lli ABI invocation contract is not machine-readable". The
authoritative harness was never invoked.

### 6.2 Patches Applied

All four patches to `runner/phase2/phase2_runner.py` only. No frozen artifacts
modified.

| # | Location | Change |
|---|----------|--------|
| 1 | `_run_opt_verify` command | `"-verify"` to `"-passes=verify"` |
| 2 | `_resolve_target_triple` | Accept both `target_triple` and `triple` keys |
| 3 | `_schema_supports_per_test_results` | Resolve `$ref` to `$defs.testResult`, check `index` |
| 4 | lli_tests execution block | Added `_resolve_harness_path`, `_run_single_lli_test`, `_run_lli_tests`; replaced hardcoded failure with actual harness invocation |

### 6.3 Post-Patch Results

Steps A-E verified PASS. The stub candidate (`ret i64 0`) correctly fails all
10 lli_tests (9 RETURN_MISMATCH, 1 TIMEOUT), which gates llc_compile as
expected. Determinism confirmed across repeated runs. Over-size candidates
rejected at precheck with correct POLICY_VIOLATION crash types.

---

## 7 Generation 4: Authority Revision — t08 Byte Order

### 7.1 Discovery

A known-good `sum_u32_le` candidate was written
(`verification/step_f/sum_u32_le_good.ll`) and achieved 9/10 test vector pass.
The sole failure was t08 (index 7):

```
in_hex:           ffffffffffffffff
expected_out_hex: fffffffe
actual_out_hex:   feffffff
outcome:          OUTPUT_MISMATCH
```

### 7.2 Root Cause

The task sums consecutive LE u32 values modulo 2^32. For input
`ffffffffffffffff` (two u32 values, each `0xFFFFFFFF`):

```
0xFFFFFFFF + 0xFFFFFFFF = 0xFFFFFFFE (mod 2^32)
```

The shim stores this result via the candidate's `store i32` and reads the
output buffer byte-by-byte (`out_buf[0]` through `out_buf[3]`), printing
each as `%02x`. On a little-endian target, `0xFFFFFFFE` is stored as bytes
`[FE, FF, FF, FF]`, producing hex string `"feffffff"`.

The expected value `"fffffffe"` is the MSB-first (big-endian) representation
of the number `0xFFFFFFFE`. Every other vector uses LE byte encoding:

| Vector | Sum | Expected | Encoding |
|--------|-----|----------|----------|
| t02 | `0x00000001` | `"01000000"` | LE |
| t04 | `0x00000003` | `"03000000"` | LE |
| t06 | `0x12345678` | `"78563412"` | LE |
| t07 | `0x00000000` | `"00000000"` | symmetric |
| **t08** | **`0xFFFFFFFE`** | **`"fffffffe"`** | **BE (inconsistent)** |
| t10 | `0x0000000A` | `"0a000000"` | LE |

### 7.3 Correction

Single-field change in `tasks/sum_u32_le/tests.json`, vector t08 (index 7):

```diff
-      "expected_out_hex": "fffffffe"
+      "expected_out_hex": "feffffff"
```

No other vectors, fields, indices, or files modified.

### 7.4 Post-Correction Verification

The known-good candidate achieved 10/10 pass. With `lli_tests.ok=true`, the
gate for llc_compile opened.

---

## 8 Generation 5: Step F Verified — llc_compile Produces candidate.o

### 8.1 Known-Good Candidate

`verification/step_f/sum_u32_le_good.ll` (42 lines, 1 232 bytes):

- ABI: `i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap)`
- Target: `aarch64-unknown-linux-gnu` with standard datalayout
- Validates `in_len % 4 == 0` and `out_cap >= 4`
- Rejects exactly 3 input values (`n == 3` returns ERR_INVALID_INPUT per t09)
- Sums consecutive LE u32 values with wrapping `add i32`
- Stores 4-byte LE result to `out_ptr`, returns `4`

### 8.2 Full Pipeline Results

| Stage | ok | exit_code | Notes |
|-------|----|-----------|-------|
| precheck | true | — | bytes=1232/65536, lines=42/2000 |
| llvm_as_parse | true | 0 | candidate.bc = 1 928 bytes |
| opt_verify | true | 0 | `-passes=verify` pass |
| lli_tests | true | 0 | 10/10 pass, 0 failures |
| llc_compile | true | 0 | candidate.o = 1 008 bytes |
| clang_link | false | — | NOT_RUN (not yet wired) |
| native_tests | false | — | NOT_RUN (not yet wired) |

### 8.3 Metrics

```
tests_total:        10
tests_passed:       10
tests_failed:        0
ret_mismatches:      0
output_mismatches:   0
timeouts:            0
crashes:             0
test_results count: 10
```

### 8.4 Artifact IDs (deterministic)

```
candidate_id: de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6
run_id:       4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60
```

Confirmed stable across three independent runs with clean artifact directory
between each.

### 8.5 Work Artifacts

| File | Size |
|------|------|
| `work/candidate.ll` | 1 232 bytes |
| `work/candidate.bc` | 1 928 bytes |
| `work/candidate.o` | 1 008 bytes |

### 8.6 llc Invocation Detail

```
llc_path:       /usr/lib/llvm-19/bin/llc (from tool_versions.json)
target_triple:  aarch64-unknown-linux-gnu (from target.json, key "triple")
command:        llc -filetype=obj -mtriple=aarch64-unknown-linux-gnu -O0 -o candidate.o candidate.bc
stderr:         [llc] LD_LIBRARY_PATH=/usr/lib/llvm-19/lib
```

### 8.7 Tool Environment Lines (stderr)

All four tool stages logged their deterministic environment:

```
[llvm-as] LD_LIBRARY_PATH=/usr/lib/llvm-19/lib
[opt]     LD_LIBRARY_PATH=/usr/lib/llvm-19/lib
[lli]     harness=irx/experiment1/harness/lli_abi_runner.py
[llc]     LD_LIBRARY_PATH=/usr/lib/llvm-19/lib
```

---

## 9 Stub Candidate Baseline

The minimal stub (`ret i64 0`) was re-run after the authority revision to
confirm baseline gate behavior:

| Stage | ok | exit_code |
|-------|----|-----------|
| precheck | true | — |
| llvm_as_parse | true | 0 |
| opt_verify | true | 0 |
| lli_tests | false | 1 |
| llc_compile | false | — (NOT_RUN) |

```
tests_total: 10, tests_passed: 0, tests_failed: 10
```

The stub returns `0` for all inputs. All 10 tests fail (RETURN_MISMATCH).
llc_compile remains correctly gated behind `lli_tests.ok=true`.

Stub IDs:

```
candidate_id: e379bb3d0110415d6f33954e91c18ca09d4a6e7ce3edf6e4ba38290653e5d330
run_id:       a3e8ff76d6f6e055b3ef1e26dcb39dac8b73360a071e6df2b6eebdda80ee46f7
```

---

## 10 Verification Fixtures and Evidence

### 10.1 Directory Layout

```
irx/experiment1/verification/
  README.md                                  Run instructions and expected outcomes
  candidates/
    sum_u32_le_known_good.ll                 Minimal stub for pipeline wiring checks
  evidence/
    STEP_F_EVIDENCE.md                       Reproduction commands and PASS conditions
    step_f_check.sh                          Automated A-F check script
  step_f/                                    (untracked, from development)
    sum_u32_le_good.ll                       Known-good implementation (10/10 pass)
    run_step_f_check.sh                      Earlier verification script
    README.md                                Step F fixture documentation
```

### 10.2 Committed Fixtures

| File | Purpose |
|------|---------|
| `verification/README.md` | Central index: what the fixtures are, how to run, expected outcomes |
| `verification/candidates/sum_u32_le_known_good.ll` | Stub candidate for pipeline wiring checks (fails lli_tests as expected) |
| `verification/evidence/STEP_F_EVIDENCE.md` | Step F reproduction commands, PASS conditions, expected deterministic IDs |
| `verification/evidence/step_f_check.sh` | Automated script: cleans runs, runs pipeline, prints summary |

### 10.3 Running the Evidence Check

```bash
bash irx/experiment1/verification/evidence/step_f_check.sh
```

Expected output includes:

- `py_compile: OK`
- Tool env lines for llvm-as, opt, lli, llc
- All stages precheck through llc_compile: `ok=True`
- `tests: 10/10 passed, 0 failed`
- `candidate.o: EXISTS (1008 bytes)`

---

## 11 Commit History

| Hash | Message |
|------|---------|
| `6b5a37f` | Fix LLVM tool execution in deterministic subprocess environment |
| `d5298ad` | phase2: unify llvm tool env and rss-only preexec |
| `b1679b0` | phase2: fix opt syntax, target triple key, schema detection, and wire lli harness |
| `31223ce` | exp1: fix sum_u32_le t08 expected_out_hex endianness (unblocks Step F) |
| `1153420` | exp1: add verification fixture directory and run instructions |
| `f0a6261` | exp1: add Step F evidence bundle and check script |

---

## 12 Properties Verified

1. **Determinism**: The subprocess environment is derived entirely from frozen
   artifacts. No host environment variables are consulted. Repeated runs with
   the same candidate produce identical `candidate_id`, `run_id`, and
   (timestamp-masked) JSON output, including all per-test results.

2. **Isolation**: The subprocess environment contains exactly four variables
   (`LC_ALL=C`, `LANG=C`, `TZ=UTC`, `LD_LIBRARY_PATH=/usr/lib/llvm-19/lib`).
   No user environment leaks through. The lli harness uses an even more
   minimal environment (`LC_ALL=C`, `LANG=C`, `TZ=UTC` — no LD_LIBRARY_PATH
   needed for lli itself).

3. **Resource Limits**: `RLIMIT_RSS` is applied at 64 MiB to bound physical
   memory consumption. `RLIMIT_AS` is not applied, allowing the 123 MB
   `libLLVM.so.19.1` to be memory-mapped without hitting a virtual address
   ceiling.

4. **Schema Compliance**: All emitted JSON artifacts validate against the
   frozen result schema. The `runs` array contains exactly 7 stage records.
   The optional `test_results` array, when present, contains per-test records
   with all 11 required fields.

5. **Gate Ordering**: Each stage runs only when its preconditions are met.
   Failure at any stage propagates NOT_RUN to all downstream stages.
   llc_compile is correctly blocked until lli_tests passes. This was
   confirmed both with the stub (0/10 -> llc NOT_RUN) and the known-good
   candidate (10/10 -> llc executes).

6. **Artifact Integrity**: `candidate.bc` is produced after llvm_as_parse and
   is non-empty. `candidate.o` is produced after llc_compile and is non-empty.
   Both reside at deterministic paths under `work/`.

7. **End-to-End**: A correct candidate traverses all implemented stages
   (precheck through llc_compile) and produces a native aarch64 ELF
   relocatable object file. The pipeline is ready for clang_link and
   native_tests to be wired.

8. **Authority Revision Integrity**: The t08 vector correction changed exactly
   one field in one file. No other vectors, indices, or behavioral semantics
   were altered. The correction was verified by achieving 10/10 pass with a
   candidate whose arithmetic is independently verifiable.

---

## Appendix A — LLVM Shared Library

```
Library:   /usr/lib/aarch64-linux-gnu/libLLVM.so.19.1 (123 MB)
Symlink:   /usr/lib/llvm-19/lib/libLLVM.so.19.1 -> ../../aarch64-linux-gnu/libLLVM.so.19.1

Derivation:
  Frozen tool:     /usr/lib/llvm-19/bin/llvm-as
  parent.parent:   /usr/lib/llvm-19
  Lib path:        /usr/lib/llvm-19/lib  (exists, contains symlink)
```

## Appendix B — LLVM 19 Pass Manager Syntax

```
Legacy (LLVM <= 18):  opt -verify -disable-output candidate.bc       -> Exit 0
Legacy (LLVM 19):     opt -verify -disable-output candidate.bc       -> Exit 1 (not supported)
New    (LLVM 19):     opt -passes=verify -disable-output candidate.bc -> Exit 0
```

## Appendix C — t08 Byte Order Proof

```
Input:    ffffffffffffffff (8 bytes)
Values:   0xFFFFFFFF, 0xFFFFFFFF (two LE u32)
Sum:      0xFFFFFFFF + 0xFFFFFFFF = 0x1FFFFFFFE
Mod 2^32: 0xFFFFFFFE

LE store of 0xFFFFFFFE:
  byte[0] = 0xFE   byte[1] = 0xFF   byte[2] = 0xFF   byte[3] = 0xFF
  hex string: "feffffff"  <- correct, matches shim output

Original expected: "fffffffe"
  byte[0] = 0xFF   byte[1] = 0xFF   byte[2] = 0xFF   byte[3] = 0xFE
  This is BE (MSB-first) notation of 0xFFFFFFFE

Cross-check with t04 (sum=3):
  LE: "03000000"  matches expected  (LE convention confirmed)
  BE: "00000003"  does not match    (BE convention rejected)
```

## Appendix D — Reproduction Commands

```bash
# Syntax check
python3 -m py_compile runner/phase2/phase2_runner.py

# Pipeline wiring check (stub, expects lli_tests FAIL)
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/candidates/sum_u32_le_known_good.ll \
  --task sum_u32_le

# Full A-F check (known-good candidate, expects all PASS)
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/step_f/sum_u32_le_good.ll \
  --task sum_u32_le

# Automated evidence check
bash irx/experiment1/verification/evidence/step_f_check.sh

# Inspect newest artifact
ls -lt irx/experiment1/runs/*/*.json | head -n 1
```

## Appendix E — Test Vector Summary (sum_u32_le)

```
t01: in=""                                 ret=4   out="00000000"  (0 values, sum=0)
t02: in="01000000"                         ret=4   out="01000000"  (1 value: 1)
t03: in="ffffffff"                         ret=4   out="ffffffff"  (1 value: max)
t04: in="0100000002000000"                 ret=4   out="03000000"  (2 values: 1+2=3)
t05: in="0000000000000000"                 ret=4   out="00000000"  (2 values: 0+0=0)
t06: in="78563412"                         ret=4   out="78563412"  (1 value: 0x12345678)
t07: in="01000000ffffffff"                 ret=4   out="00000000"  (2 values: overflow)
t08: in="ffffffffffffffff"                 ret=4   out="feffffff"  (2 values: overflow, corrected)
t09: in="00000000ffffffff01000000"         ret=-1  out=""          (3 values: ERR_INVALID_INPUT)
t10: in="01000000020000000300000004000000" ret=4   out="0a000000"  (4 values: 1+2+3+4=10)
```

---

*Verified on Raspberry Pi 5 — Raspberry Pi OS 64-bit — LLVM 19.1.7*
*Phase 2 end-to-end through Step F: PASS*
