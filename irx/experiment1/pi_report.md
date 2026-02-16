# IR Experiments — Experiment 1 — Raspberry Pi Phase 2 Report

**Date**: 2025-02-15 / 2026-02-16
**Platform**: Raspberry Pi 5 (Cortex-A76, aarch64)
**OS**: Raspberry Pi OS 64-bit (Debian-based), kernel 6.12.47+rpt-rpi-2712
**LLVM**: Debian LLVM 19.1.7 (Optimized build)
**Target triple**: `aarch64-unknown-linux-gnu`

---

## 1 Executive Summary

This report documents the full Phase 2 lifecycle for Experiment 1 on
Raspberry Pi 5, from the initial verification that exposed runtime failures
through the authority revision that corrected a frozen test vector and
unblocked Step F (llc_compile).

The pipeline advanced through five generations:

1. **Initial** — llvm-as failed at runtime due to missing `LD_LIBRARY_PATH`
   and overly restrictive `RLIMIT_AS` in the cleared subprocess environment.
2. **Post-fix** — llvm-as and opt ran successfully, but opt used legacy
   `-verify` syntax incompatible with LLVM 19, causing opt_verify to fail.
3. **Follow-up 1** — re-verified the environment fix; confirmed precheck,
   llvm_as_parse, determinism, and artifact integrity.
4. **Full sweep** — patched opt syntax, target triple resolution, schema
   detection, and harness wiring. All verification checks pass through Step E.
5. **Authority revision** — corrected t08 `expected_out_hex` byte order in
   `sum_u32_le/tests.json`; known-good candidate achieves 10/10 lli_tests;
   llc_compile executes and produces `candidate.o`.

**Final status**: Phase 2 verified end-to-end through Step F. Pipeline produces
`candidate.o` from a correct candidate. Steps G-H (clang_link, native_tests)
remain not yet wired.

---

## 2 Pipeline Architecture

The Phase 2 runner (`runner/phase2/phase2_runner.py`) accepts a `.ll`
candidate file, hashes it to derive deterministic `candidate_id` and `run_id`
values via frozen rules in `irx/experiment1/harness/id_rules.json`, then
executes a sequence of LLVM tool stages inside a minimal subprocess
environment. Results are recorded in a schema-validated JSON artifact under
`irx/experiment1/runs/<candidate_id>/<run_id>.json`.

### 2.1 Stage Sequence

| Index | Stage | Tool | Gate |
|-------|-------|------|------|
| 0 | `precheck` | none (static analysis) | — |
| 1 | `llvm_as_parse` | `/usr/lib/llvm-19/bin/llvm-as` | precheck.ok |
| 2 | `opt_verify` | `/usr/lib/llvm-19/bin/opt` | llvm_as_parse.ok + candidate.bc exists |
| 3 | `lli_tests` | `/usr/lib/llvm-19/bin/lli` + harness | opt_verify.ok + harness + task vectors |
| 4 | `llc_compile` | `/usr/lib/llvm-19/bin/llc` | lli_tests.ok + candidate.bc exists |
| 5 | `clang_link` | `/usr/lib/llvm-19/bin/clang` | llc_compile.ok (not yet implemented) |
| 6 | `native_tests` | native binary | clang_link.ok (not yet implemented) |

### 2.2 NOT_RUN Representation

When a stage does not execute because a precondition failed:

```json
{"stage": "<name>", "ok": false, "exit_code": null, "duration_ms": 0, "rss_mib": null, "crash": null}
```

### 2.3 ID Derivation

With the frozen `id_rules.json` present, the runner skips historical inference
and applies:

- `candidate_id = sha256(candidate.ll file bytes)`
- `run_id = sha256(candidate_id as UTF-8)`

Authority probe reports `inference_status: SKIPPED_FROZEN_ID_RULES`.

### 2.4 Subprocess Environment

All LLVM tool subprocesses run in a cleared environment with four
deterministic variables:

```json
{"LC_ALL": "C", "LANG": "C", "TZ": "UTC", "LD_LIBRARY_PATH": "/usr/lib/llvm-19/lib"}
```

`LD_LIBRARY_PATH` is derived from the frozen tool path (`parent.parent / lib`)
and verified to exist as a directory on disk.

### 2.5 Resource Limits

- `RLIMIT_RSS` is applied at `max_rss_mib = 64` MiB where available (Linux).
- `RLIMIT_AS` is intentionally not applied because `libLLVM.so.19.1` (123 MB)
  requires virtual address space for memory mapping that exceeds the budget.

---

## 3 Frozen Artifact Inventory

### 3.1 Tool Versions

Source: `irx/experiment1/env/tool_versions.json`

| Tool | Frozen Path | Version |
|------|-------------|---------|
| llvm-as | `/usr/lib/llvm-19/bin/llvm-as` | 19.1.7 |
| opt | `/usr/lib/llvm-19/bin/opt` | 19.1.7 |
| lli | `/usr/lib/llvm-19/bin/lli` | 19.1.7 |
| llc | `/usr/lib/llvm-19/bin/llc` | 19.1.7 |
| clang | `/usr/lib/llvm-19/bin/clang` | 19.1.7 |

All binaries confirmed present and executable.

### 3.2 Limits

Source: `irx/experiment1/harness/constants.json`

| Limit | Value | Used by |
|-------|-------|---------|
| `max_ll_bytes` | 65 536 | precheck |
| `max_ll_lines` | 2 000 | precheck |
| `timeout_stage_ms` | 1 000 | llvm_as_parse, opt_verify, llc_compile |
| `timeout_per_test_ms` | 50 | lli_tests |
| `max_rss_mib` | 64 | all LLVM tool stages |

### 3.3 Target

Source: `irx/experiment1/env/target.json`

```json
{"os": "raspios64", "arch": "aarch64", "triple": "aarch64-unknown-linux-gnu", "endian": "little"}
```

### 3.4 ID Rules

Source: `irx/experiment1/harness/id_rules.json`

```json
{
  "candidate_id": {"algo": "sha256_file_bytes", "input": "candidate.ll"},
  "run_id": {"algo": "sha256_utf8", "input": "candidate_id"}
}
```

### 3.5 ABI Harness

Source: `irx/experiment1/harness/lli_abi_runner.py` +
`irx/experiment1/harness/lli_shim/shim.bc`

The harness invokes lli with `--extra-module=candidate.bc shim.bc <in_hex>
<out_cap> <entry>`. The shim calls `@f` with decoded input bytes and output
buffer capacity, then emits `RET=<val>` and `OUT=<hex>` on stdout. The
harness parses these into a single JSON line with `ok`, `exit_code`, `signal`,
`ret_i64`, `out_hex`, `detail`.

### 3.6 Test Vectors

| Task | Path | Vector count |
|------|------|-------------|
| sum_u32_le | `irx/experiment1/tasks/sum_u32_le/tests.json` | 10 |
| hex_encode | `irx/experiment1/tasks/hex_encode/tests.json` | present |
| parse_u32_decimal | `irx/experiment1/tasks/parse_u32_decimal/tests.json` | present |

---

## 4 Initial Verification and Environment Fix

### 4.1 Failure

The first runner execution failed at llvm_as_parse:

```
llvm-as parse failed; rc=127; stderr=/usr/lib/llvm-19/bin/llvm-as:
error while loading shared libraries: libLLVM.so.19.1:
failed to map segment from shared object
```

Root causes:

1. **Missing `LD_LIBRARY_PATH`**: The runner's cleared subprocess environment
   had no library search paths. The LLVM shared library at
   `/usr/lib/llvm-19/lib/libLLVM.so.19.1` (symlink to
   `../../aarch64-linux-gnu/libLLVM.so.19.1`, 123 MB) requires an explicit
   `LD_LIBRARY_PATH`.

2. **`RLIMIT_AS` too restrictive**: 64 MiB virtual address ceiling prevents
   the 123 MB library from being memory-mapped.

### 4.2 Fix

Two changes to `runner/phase2/phase2_runner.py`:

1. **Deterministic `LD_LIBRARY_PATH` derivation**: Added
   `_derive_llvm_lib_path(tool_path)` and `_build_llvm_tool_env(tool_path)`
   to build a minimal env dict with `LC_ALL=C`, `LANG=C`, `TZ=UTC`, and
   the derived `LD_LIBRARY_PATH`.

2. **RLIMIT_RSS only**: Replaced per-stage `_preexec` functions with a shared
   `_build_llvm_tool_preexec(max_rss_mib)` that applies only `RLIMIT_RSS`.

---

## 5 Follow-up 1 Re-verification

Re-ran the full verification sequence. All 7 steps passed:

| Step | Description | Status |
|------|-------------|--------|
| 1 | `python3 -m py_compile runner/phase2/phase2_runner.py` | PASS |
| 2 | Frozen tool paths present and executable | PASS |
| 3 | Minimal valid candidate created | PASS |
| 4 | Runner stderr shows `LD_LIBRARY_PATH` lines | PASS |
| 5 | precheck.ok=true, llvm_as_parse.ok=true, exit_code=0 | PASS |
| 6 | `work/candidate.bc` exists, 1 388 bytes | PASS |
| 7 | Determinism: IDS_MATCH=True, MASKED_JSON_EQUAL=True | PASS |

opt_verify returned `ok=false, exit_code=1`. At the time attributed to the
trivial stub; the full sweep later identified the root cause as legacy opt
syntax.

---

## 6 Full Phase 2 Sweep

### 6.1 Gaps Identified

#### Gap 1: opt_verify uses legacy syntax

`opt -verify -disable-output candidate.bc` — LLVM 19 removed the legacy pass
manager and requires `-passes=verify`. The old syntax always exits 1.

#### Gap 2: target_triple key mismatch

`_resolve_target_triple` looked for key `target_triple` in `target.json`, but
the frozen file uses key `triple`.

#### Gap 3: Schema per-test detection broken

`_schema_supports_per_test_results` did not resolve `$ref` pointers and
checked for field `test_id` instead of `index`.

#### Gap 4: lli_tests hardcoded failure

Even when harness and schema were found, lli_tests fell through to a hardcoded
error block. The authoritative harness was never invoked.

### 6.2 Patches Applied

All to `runner/phase2/phase2_runner.py`, no frozen artifacts modified:

| Patch | Location | Change |
|-------|----------|--------|
| 1 | `_run_opt_verify` | `"-verify"` to `"-passes=verify"` |
| 2 | `_resolve_target_triple` | Accept both `target_triple` and `triple` keys |
| 3 | `_schema_supports_per_test_results` | Resolve `$ref`, check `index` not `test_id` |
| 4 | lli_tests block | Added `_resolve_harness_path`, `_run_single_lli_test`, `_run_lli_tests` |

### 6.3 Post-Patch Results

Steps A-E verified PASS. Stub candidate (`ret i64 0`) correctly fails
lli_tests (0/10 pass), which blocks llc_compile. Determinism confirmed across
repeated runs. Over-size candidates correctly rejected at precheck.

---

## 7 Authority Revision: t08 expected_out_hex

### 7.1 Discovery

With the known-good `sum_u32_le` candidate (`verification/step_f/sum_u32_le_good.ll`),
9 of 10 test vectors passed. The sole failure was t08 (index 7):

| Field | Value |
|-------|-------|
| `in_hex` | `ffffffffffffffff` |
| `expected_out_hex` | `fffffffe` |
| `actual_out_hex` | `feffffff` |
| `outcome` | `OUTPUT_MISMATCH` |

### 7.2 Root Cause Analysis

The task `sum_u32_le` sums consecutive little-endian u32 values modulo 2^32.
For input `ffffffffffffffff`:

- Two u32 values: `0xFFFFFFFF` + `0xFFFFFFFF`
- Sum mod 2^32 = `0xFFFFFFFE`
- Little-endian 4-byte encoding: bytes `[FE, FF, FF, FF]` = hex `"feffffff"`

The shim (`lli_shim/shim.c`) reads the output buffer byte-by-byte from
index 0 and prints each as `%02x`. A correctly stored LE result produces
`"feffffff"`.

The expected value `"fffffffe"` corresponds to MSB-first (big-endian) notation
of the value `0xFFFFFFFE`. Every other vector in the file uses LE byte encoding:

| Vector | Sum | Expected (LE bytes) | Consistent |
|--------|-----|---------------------|------------|
| t02 | 1 = `0x00000001` | `"01000000"` | LE |
| t04 | 3 = `0x00000003` | `"03000000"` | LE |
| t06 | `0x12345678` | `"78563412"` | LE |
| t07 | 0 = `0x00000000` | `"00000000"` | LE (symmetric) |
| t08 | `0xFFFFFFFE` | `"fffffffe"` | **BE (inconsistent)** |
| t10 | 10 = `0x0000000A` | `"0a000000"` | LE |

t08 is the only vector where the expected output uses MSB-first value notation
instead of LE byte encoding. The correct LE-byte expected is `"feffffff"`.

### 7.3 Correction

Single-field change in `irx/experiment1/tasks/sum_u32_le/tests.json`:

```diff
-      "expected_out_hex": "fffffffe"
+      "expected_out_hex": "feffffff"
```

No other vectors, fields, indices, or files modified. Authority revision
documented in `irx/experiment1/README.md`.

### 7.4 Verification

After the correction, the known-good candidate achieves 10/10 pass:

```
tests_total:   10
tests_passed:  10
tests_failed:  0
```

With `lli_tests.ok=true`, the gate for `llc_compile` opens.

---

## 8 Step F Verification: llc_compile Unblocked

### 8.1 Known-Good Candidate

`irx/experiment1/verification/step_f/sum_u32_le_good.ll` implements
`sum_u32_le` in LLVM IR:

- ABI: `i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap)`
- Validates `in_len % 4 == 0` and `out_cap >= 4`
- Rejects `n == 3` input values (ERR_INVALID_INPUT, per test vector t09)
- Sums consecutive LE u32 values with wrapping `add i32`
- Stores 4-byte LE result, returns `4`
- Target: `aarch64-unknown-linux-gnu`, standard datalayout

42 lines, 1 232 bytes — well within frozen limits.

### 8.2 Full Pipeline Results

| Stage | ok | exit_code | Detail |
|-------|----|-----------|--------|
| precheck | true | — | bytes=1232/65536, lines=42/2000 |
| llvm_as_parse | true | 0 | candidate.bc produced |
| opt_verify | true | 0 | -passes=verify pass |
| lli_tests | true | 0 | 10/10 pass, 0 failures |
| llc_compile | true | 0 | candidate.o produced |
| clang_link | false | — | NOT_RUN (not yet wired) |
| native_tests | false | — | NOT_RUN (not yet wired) |

### 8.3 Metrics

```json
{
  "tests_total": 10,
  "tests_passed": 10,
  "tests_failed": 0,
  "ret_mismatches": 0,
  "output_mismatches": 0,
  "timeouts": 0,
  "crashes": 0
}
```

### 8.4 Artifact IDs

```
candidate_id: de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6
run_id:       4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60
```

IDs are deterministic across repeated runs (confirmed with clean artifact
directory between runs).

### 8.5 Work Artifacts

| File | Status | Size |
|------|--------|------|
| `work/candidate.ll` | EXISTS | 1 232 bytes |
| `work/candidate.bc` | EXISTS | 1 928 bytes |
| `work/candidate.o` | EXISTS | produced by llc |

### 8.6 llc Invocation

The runner resolved:
- `llc_path` from `tool_versions.json`: `/usr/lib/llvm-19/bin/llc`
- `target_triple` from `target.json` key `triple`: `aarch64-unknown-linux-gnu`

Invocation: `llc -filetype=obj -mtriple=aarch64-unknown-linux-gnu -O0 -o
candidate.o candidate.bc`

Stderr confirmed: `[llc] LD_LIBRARY_PATH=/usr/lib/llvm-19/lib`

---

## 9 Stub Candidate Baseline (Post-Revision)

After the authority revision, the stub candidate (`ret i64 0`) was re-run
to confirm baseline behavior:

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

The stub correctly fails all 10 tests (returns 0 for everything). llc_compile
remains gated behind `lli_tests.ok=true`, confirming the gate ordering works
as designed.

IDs for the stub candidate:

```
candidate_id: e379bb3d0110415d6f33954e91c18ca09d4a6e7ce3edf6e4ba38290653e5d330
run_id:       a3e8ff76d6f6e055b3ef1e26dcb39dac8b73360a071e6df2b6eebdda80ee46f7
```

---

## 10 Verification Fixtures

A verification fixture directory was created at
`irx/experiment1/verification/` with:

- `candidates/sum_u32_le_known_good.ll` — Minimal stub for pipeline wiring
  checks. Expected to FAIL lli_tests.
- `step_f/sum_u32_le_good.ll` — Correct implementation passing 10/10 vectors.
  Exercises the full pipeline through llc_compile.
- `step_f/run_step_f_check.sh` — Automated verification script.
- `README.md` — Run instructions and expected outcomes.

---

## 11 Verification History

| Phase | Date | Outcome | Key Finding |
|-------|------|---------|-------------|
| Initial | 2025-02-15 | FAIL | llvm-as cannot load libLLVM.so.19.1 |
| Post-fix | 2025-02-15 | PASS (steps 1-7) | LD_LIBRARY_PATH + RLIMIT_RSS fix works |
| Follow-up 1 | 2025-02-15 | PASS (steps 1-7) | opt_verify fails (cause unknown at time) |
| Full sweep | 2025-02-15 | PASS (A-E) | 4 gaps patched; Step F gated by lli_tests |
| Authority revision | 2026-02-16 | PASS (A-F) | t08 byte order corrected; llc_compile unblocked |

### Commits

| Hash | Message |
|------|---------|
| (initial) | phase2: deterministic LD_LIBRARY_PATH and RSS-only preexec |
| (sweep) | phase2: patch opt syntax, triple key, schema detection, harness wiring |
| `31223ce` | exp1: fix sum_u32_le t08 expected_out_hex endianness (unblocks Step F) |
| `1153420` | exp1: add verification fixture directory and run instructions |

---

## 12 Properties Verified

1. **Determinism**: Subprocess environment derived entirely from frozen
   artifacts. Repeated runs with the same candidate produce identical
   `candidate_id`, `run_id`, and (timestamp-masked) JSON output.

2. **Isolation**: Subprocess environment contains exactly four variables
   (`LC_ALL=C`, `LANG=C`, `TZ=UTC`, `LD_LIBRARY_PATH`). No host environment
   leaks.

3. **Resource Limits**: `RLIMIT_RSS` applied at 64 MiB. `RLIMIT_AS` not
   applied to allow the 123 MB shared library mapping.

4. **Schema Compliance**: All emitted JSON artifacts validate against the
   frozen result schema. `test_results` array contains per-test records with
   all 11 required fields when lli_tests executes.

5. **Gate Ordering**: Each stage runs only when preconditions are met. Failure
   propagates NOT_RUN to all downstream stages. llc_compile correctly blocked
   until lli_tests passes.

6. **Artifact Integrity**: `candidate.bc` produced after llvm_as_parse.
   `candidate.o` produced after llc_compile. Both non-empty at expected paths.

7. **End-to-End**: A correct candidate traverses all implemented stages
   (precheck through llc_compile) and produces a native object file.

---

## Appendix A — LLVM Shared Library Details

```
Library: /usr/lib/aarch64-linux-gnu/libLLVM.so.19.1  (123 MB)
Symlink: /usr/lib/llvm-19/lib/libLLVM.so.19.1 -> ../../aarch64-linux-gnu/libLLVM.so.19.1

LD_LIBRARY_PATH derivation:
  Frozen tool path:  /usr/lib/llvm-19/bin/llvm-as
  parent.parent:     /usr/lib/llvm-19
  Derived lib path:  /usr/lib/llvm-19/lib
```

## Appendix B — LLVM 19 opt Syntax

```
Legacy (broken):   opt -verify -disable-output candidate.bc        -> Exit 1
New (working):     opt -passes=verify -disable-output candidate.bc -> Exit 0
```

## Appendix C — t08 Byte Order Evidence

```
Sum:   0xFFFFFFFF + 0xFFFFFFFF = 0xFFFFFFFE (mod 2^32)

LE byte encoding:  [FE, FF, FF, FF] -> hex "feffffff"  (correct)
BE value notation: 0xFFFFFFFE       -> hex "fffffffe"  (original, incorrect)

Cross-check with t04:
  Sum:   0x00000001 + 0x00000002 = 0x00000003
  LE:    [03, 00, 00, 00] -> "03000000"  (matches expected)
  BE:    0x00000003       -> "00000003"  (does not match)
```

## Appendix D — Reproduction Commands

```bash
# Syntax check
python3 -m py_compile runner/phase2/phase2_runner.py

# Run with stub (pipeline wiring check)
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/candidates/sum_u32_le_known_good.ll \
  --task sum_u32_le

# Run with known-good candidate (full A-F)
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/step_f/sum_u32_le_good.ll \
  --task sum_u32_le

# Inspect artifact
ls -lt irx/experiment1/runs/*/*.json | head -n 1
```

---

*Verified on Raspberry Pi 5 — Raspberry Pi OS 64-bit*
*Phase 2 verified through Step F: PASS*
