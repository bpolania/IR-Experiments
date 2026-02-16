# Experiment 1 — Raspberry Pi 5 Report

## Platform

- **Board**: Raspberry Pi 5 (Broadcom BCM2712, Cortex-A76 quad-core)
- **Architecture**: aarch64 (ARMv8.2-A), little-endian
- **OS**: Raspberry Pi OS 64-bit (Debian-based)
- **Kernel**: 6.12.47+rpt-rpi-2712 (SMP PREEMPT)
- **Target triple**: `aarch64-unknown-linux-gnu`
- **LLVM**: Debian LLVM 19.1.7, optimized build
- **Clang**: Debian clang 19.1.7 (3+b1)

All five LLVM binaries are sourced from a single frozen installation under
`/usr/lib/llvm-19/bin/`: llvm-as, opt, lli, llc, clang. Paths and version
strings are recorded in `irx/experiment1/env/tool_versions.json`. The target
triple is frozen in `irx/experiment1/env/target.json`.

---

## Pipeline Overview

The Phase 2 runner (`runner/phase2/phase2_runner.py`, 1972 lines) implements
a seven-stage gated pipeline that takes a candidate LLVM IR file and evaluates
it against a set of frozen test vectors. Each stage must succeed before the
next is permitted to execute.

```
candidate.ll
  |
  v
[A] precheck        size/line limits
  |
  v
[B] llvm_as_parse   llvm-as -> candidate.bc
  |
  v
[C] opt_verify      opt -passes=verify
  |
  v
[D] lli_tests       lli interpreter + harness -> test results
  |
  v
[E] llc_compile     llc -> candidate.o (ELF relocatable)
  |
  v
[F] clang_link      clang + lld -> candidate.exe (ELF executable)
  |
  v
[G] native_tests    native_runner loads ELF, calls f() -> test results
```

Stage gating is strict: if lli_tests reports any failure, llc_compile is
skipped and all downstream stages record `ok=False` with `exit_code=null`.
This prevents wasted compilation on known-bad candidates and ensures the
native pipeline only runs against candidates that first pass interpretation.

### Subprocess environment

Every tool invocation runs in a deterministic subprocess environment. The
environment is cleared entirely, then rebuilt with only four variables:
`LC_ALL=C`, `LANG=C`, `TZ=UTC`, and `LD_LIBRARY_PATH=/usr/lib/llvm-19/lib`.
This eliminates locale-dependent behavior, timezone drift, and stray
environment variable contamination across runs. Resource limits use
`RLIMIT_RSS` only (not `RLIMIT_AS`) because `libLLVM.so.19.1` maps
approximately 123 MB on load, which would immediately trip an AS limit.

### Deterministic identity

Every run produces two SHA-256 identifiers:

- **candidate_id**: `sha256(candidate.ll bytes)` — identifies the source
- **run_id**: `sha256(candidate_id as UTF-8)` — deterministically derived

These rules are frozen in `irx/experiment1/harness/id_rules.json`. Given
the same candidate file, every run on every machine produces the same IDs.
The run directory structure uses these IDs as path components:
`runs/<candidate_id>/<run_id>.json`.

---

## Tasks

Three tasks are defined under `irx/experiment1/tasks/`, each with a
`spec.json` describing the function contract and a `tests.json` containing
10 frozen test vectors.

### sum_u32_le

Sums an array of little-endian uint32 values. The candidate receives a byte
buffer and its length, writes a 4-byte little-endian result, and returns the
number of bytes written (4) or -1 on error. Special case: if the input
contains exactly three uint32 values, the function returns -1 (tests overflow
boundary behavior).

Test vectors cover: empty input (zero sum), single element, max uint32
(0xFFFFFFFF), two-element addition, duplicate zeros, byte-order verification
(0x12345678), overflow wrapping (1 + 0xFFFFFFFF = 0), double-max wrapping,
the three-element error case, and four-element addition.

### hex_encode

Converts raw bytes to lowercase hexadecimal ASCII. Each input byte becomes
two output bytes (the ASCII hex digits). Returns the number of output bytes
written, or -2 if the output buffer is too small.

Test vectors cover: empty input, single zero byte, values 0x01 and 0x0F,
insufficient output capacity, 0xFF, multi-byte sequences ("deadbeef"),
three-byte input, ten sequential bytes, and ASCII string encoding.

### parse_u32_decimal

Parses a decimal ASCII string into a little-endian uint32. The input is
a byte buffer containing ASCII digit characters. Returns 4 (bytes written)
on success, -1 on error (empty input, non-digit characters, overflow beyond
2^32 - 1).

Test vectors cover: single zero, single non-zero digit, two-digit number,
leading zeros, maximum uint32 (4294967295), overflow (4294967296), empty
input, negative sign prefix, large number (1234567890), and embedded
non-digit character.

---

## Known-Good Candidate: sum_u32_le

A known-good candidate exists at
`irx/experiment1/verification/step_f/sum_u32_le_good.ll`. This is a 42-line
LLVM IR file implementing the sum_u32_le contract using a simple loop with
phi nodes for accumulation.

The candidate targets `aarch64-unknown-linux-gnu` with the standard data
layout. It defines a single function `@f(ptr, i32, ptr, i32) -> i64` that:

1. Validates input length is divisible by 4
2. Validates output capacity is at least 4
3. Rejects exactly 3 elements (returns -1)
4. Loops over uint32 elements with wrapping addition
5. Stores the result as a little-endian uint32 and returns 4

Deterministic IDs for this candidate:

```
candidate_id: de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6
run_id:       4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60
```

No known-good candidates exist yet for hex_encode or parse_u32_decimal.

---

## Native Execution Harness

Step G links the candidate into a freestanding ELF executable using:

```
clang -target aarch64-unknown-linux-gnu \
      -nostdlib -fuse-ld=lld \
      -Wl,--no-dynamic-linker -Wl,-e,f \
      -o candidate.exe candidate.o
```

This produces a minimal static ELF with `f` as the entry point, no C runtime,
no dynamic linker, and no library dependencies. The resulting binary is
typically 2304 bytes.

Step H executes test vectors against this binary using `native_runner`
(`irx/experiment1/harness/native/native_runner.c`, 421 lines). This is a
custom ELF64 loader written in pure C with no external dependencies beyond
libc. It:

1. Memory-maps the candidate ELF file
2. Parses ELF64 headers and locates LOAD segments
3. Maps segments at their specified virtual addresses with correct permissions
   (read/write/execute as indicated by `p_flags`)
4. Searches the `.symtab` section for the symbol `f` (not `.dynsym`, since
   the freestanding binary has no dynamic symbol table)
5. Flushes the instruction cache using `__builtin___clear_cache` (required on
   aarch64 where instruction and data caches are not coherent)
6. Calls the function pointer with the same `(ptr, i32, ptr, i32) -> i64`
   ABI used by the lli harness
7. Prints `RET=<decimal>` and `OUT=<hex>` in the same wire format the Python
   harness expects

The native_runner includes a `--selftest` mode that validates its hex
encode/decode routines before any candidate execution. The Phase 2 runner
calls selftest on first use and caches the result for subsequent invocations
within the same run.

---

## Verdict Computation

The runner computes a final verdict from stage outcomes and test metrics
using the `compute_verdict()` function. The logic:

1. Identify stages that actually executed (exit_code not null, duration > 0,
   or crash present)
2. If any executed stage has `ok=False`, verdict is **FAIL** with detail
   naming the first failing stage
3. If lli test failures > 0, verdict is **FAIL**
4. If native test failures > 0, verdict is **FAIL**
5. If no stages executed at all, verdict is **ERROR**
6. If all stages ok and zero test failures, verdict is **PASS**
7. Otherwise, verdict is **ERROR** (indeterminate)

The verdict is stored in the top-level `verdict` field of the result JSON.
The `gates.policy.ok` field is set to `true` when verdict is PASS and `false`
otherwise. The verdict detail string is appended to `gates.policy.detail`.

This replaced an earlier implementation where verdict was hardcoded to
`"ERROR"` and `gates.policy.ok` was always `false`. The fix was committed
in `8762240` and verified with 8 unit tests covering all verdict branches.

---

## Schema

The result JSON is validated against `irx/experiment1/harness/result_schema.json`
(JSON Schema draft 2020-12). The schema enforces `additionalProperties: false`
at the top level and within all nested objects, preventing undeclared fields
from appearing in the output.

Required top-level fields: experiment, task, candidate_id, run_id, timestamps,
gates, runs, metrics, verdict.

The verdict field is constrained to the enum `["PASS", "FAIL", "ERROR"]`.

Metrics include both lli counters (tests_total, tests_passed, tests_failed,
ret_mismatches, output_mismatches, timeouts, crashes) and native counters
(native_tests_total, native_tests_passed, native_tests_failed,
native_ret_mismatches, native_output_mismatches, native_timeouts,
native_crashes). The native fields were added in commit `a5d84da` when
Step H was implemented.

Each test result records: index, in_hex, out_cap, expected_ret,
expected_out_hex, actual_ret, actual_out_hex, outcome, exit_code, signal,
and detail. The outcome field is constrained to the enum `["PASS",
"RETURN_MISMATCH", "OUTPUT_MISMATCH", "UNEXPECTED_CRASH", "TIMEOUT", "OOM"]`.

---

## Regression Sweep

A regression sweep was executed on 2026-02-16 at HEAD `8563fd2`. The sweep
runs the full pipeline against each of the three tasks, validates the output
JSON against the schema, and checks that verdicts match expectations.

### sum_u32_le: PASS

The known-good candidate passes all seven stages. Both the lli interpreter
and the native harness produce identical results across all 10 test vectors.

| Stage | ok | exit_code |
|---|---|---|
| precheck | true | -- |
| llvm_as_parse | true | 0 |
| opt_verify | true | 0 |
| lli_tests | true | 0 |
| llc_compile | true | 0 |
| clang_link | true | 0 |
| native_tests | true | 0 |

- lli tests: 10/10 passed, 0 failed
- native tests: 10/10 passed, 0 failed
- lli/native match: all 10 tests agree
- verdict: PASS
- gates.policy.ok: true
- schema validation: OK

Work artifacts produced:
- candidate.bc: 1928 bytes (LLVM bitcode)
- candidate.o: 1008 bytes (ELF relocatable, aarch64)
- candidate.exe: 2304 bytes (ELF executable, aarch64)

### hex_encode: FAIL

The sum_u32_le candidate was used as a stub (no hex_encode-specific candidate
exists). The candidate parses and verifies cleanly through Steps A-C because
the IR is structurally valid. At Step D, all 10 hex_encode test vectors fail
because the function implements the wrong algorithm. The pipeline correctly
gates out Steps E-G.

| Stage | ok | exit_code |
|---|---|---|
| precheck | true | -- |
| llvm_as_parse | true | 0 |
| opt_verify | true | 0 |
| lli_tests | false | 1 |
| llc_compile | false | -- |
| clang_link | false | -- |
| native_tests | false | -- |

- lli tests: 0/10 passed, 10 failed
- native tests: 0/0 (gated out)
- verdict: FAIL
- gates.policy.ok: false
- schema validation: OK

### parse_u32_decimal: FAIL

Same stub candidate. Steps A-C pass. At Step D, 8 of 10 test vectors fail.
Two vectors pass by coincidence: the sum_u32_le function happens to return
values that match parse_u32_decimal expectations for those specific inputs.
Steps E-G gated out.

| Stage | ok | exit_code |
|---|---|---|
| precheck | true | -- |
| llvm_as_parse | true | 0 |
| opt_verify | true | 0 |
| lli_tests | false | 1 |
| llc_compile | false | -- |
| clang_link | false | -- |
| native_tests | false | -- |

- lli tests: 2/10 passed, 8 failed
- native tests: 0/0 (gated out)
- verdict: FAIL
- gates.policy.ok: false
- schema validation: OK

### Sweep conclusions

All three JSON artifacts pass schema validation with
`jsonschema.validate()`. Verdicts are correctly computed: PASS for a known-good
candidate against its own task, FAIL for a wrong candidate against different
tasks. The stage gating logic works as designed, preventing compilation and
native execution of candidates that fail interpretation.

---

## Unit Tests

Two test suites validate runner internals without requiring LLVM:

**test_native_tests.py** (13 tests): Validates the native test parsing,
result construction, gating logic, selftest caching, and error handling for
the Step H integration. All tests are hermetic and use mock subprocess
invocations.

**test_verdict.py** (8 tests): Validates every branch of `compute_verdict()`:
all-pass, pass-without-native, stage-failed, precheck-failed, lli-tests-failed,
native-tests-failed, no-stages-executed, and partial-with-upstream-failure.

All 21 tests pass.

---

## Test Vector Correction

Test vector t08 for sum_u32_le originally had `expected_out_hex` set to
`"fffffffe"`. This was big-endian notation for the value 0xFFFFFFFE. Since
the task specifies little-endian byte output, the correct encoding is
`"feffffff"`. The correction was a single-field change in
`tasks/sum_u32_le/tests.json` (commit `31223ce`). No other vectors, fields,
or files were modified.

This was identified during Step F verification when the candidate produced
correct little-endian output but the test vector expected big-endian bytes.

---

## Evidence Logs

All evidence is stored under `irx/experiment1/verification/evidence/logs/`:

| Log file | Date | Content |
|---|---|---|
| `step_h_check_20260215_234036.log` | 2026-02-15 | Phase 2 closure run, all 7 stages PASS |
| `step_h_check_verdictfix_20260215_235338.log` | 2026-02-15 | First verdict fix validation |
| `step_h_check_verdictfix_20260216_000503.log` | 2026-02-16 | Final verdict fix evidence with proof chain |
| `regression_sweep_20260216_003439.log` | 2026-02-16 | Three-task regression sweep |

The final verdict fix evidence log includes a proof chain: JSON path to the
run artifact, extraction of the verdict field showing PASS, grep confirmation,
candidate_id/run_id match verification, and work artifact size listing.

---

## Commit History

Key commits in chronological order:

| Commit | Description |
|---|---|
| `31223ce` | Fix sum_u32_le t08 expected_out_hex endianness |
| `1153420` | Add verification fixture directory |
| `f0a6261` | Add Step F evidence bundle and check script |
| `add9dc8` | Add llc_compile gate (Step F) |
| `960cebf` | Add frozen id_rules authority |
| `b1679b0` | Fix opt syntax, target triple, schema detection, wire lli harness |
| `b0d8cd9` | Implement Step G clang_link |
| `a5d84da` | Implement Step H native_tests |
| `5201dd2` | Phase 2 closure record |
| `8762240` | Fix verdict computation from stage outcomes |

---

## Reproduction

From the repository root on any aarch64-linux-gnu system with LLVM 19 installed:

```bash
# Run the full pipeline on the known-good candidate
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/step_f/sum_u32_le_good.ll \
  --task sum_u32_le

# Validate the output against the schema
python3 -c "
import json, jsonschema
from glob import glob
f = glob('irx/experiment1/runs/*/*/*.json')[0] if False else \
    [p for p in glob('irx/experiment1/runs/*/*.json')][0]
with open(f) as fh: d = json.load(fh)
with open('irx/experiment1/harness/result_schema.json') as fh: s = json.load(fh)
jsonschema.validate(d, s)
print('verdict:', d['verdict'])
"

# Run the Step H evidence check script
bash irx/experiment1/verification/evidence/step_h_check.sh

# Run unit tests
python3 -m pytest runner/phase2/tests/ -q
```

Expected output for the known-good sum_u32_le candidate: verdict PASS,
lli 10/10, native 10/10, all stages ok, schema valid.

---

*Report generated 2026-02-16 on Raspberry Pi 5, HEAD 8563fd2.*
