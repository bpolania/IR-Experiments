# Experiment 1 — Raspberry Pi 5 Report

## Revision History

| Commit | Date (PST) | Milestone |
|---|---|---|
| `a5d84da` | 2026-02-15 23:32 | Step H implementation and Phase 2 closure |
| `8762240` | 2026-02-15 23:55 | Verdict computation fix |
| `8563fd2` | 2026-02-16 00:30 | Regression sweep baseline |
| `b104ff5` | 2026-02-16 00:48 | Documentation accuracy pass (stage lettering, native loader) |

## Platform

- **Board**: Raspberry Pi 5, Broadcom BCM2712, quad-core Cortex-A76
- **Architecture**: aarch64 (ARMv8.2-A), little-endian
- **OS**: Raspberry Pi OS 64-bit (Debian-based)
- **Kernel**: 6.12.47+rpt-rpi-2712 (SMP PREEMPT)
- **Target triple**: `aarch64-unknown-linux-gnu`
- **LLVM**: Debian LLVM 19.1.7, optimized build
- **Clang**: Debian clang 19.1.7 (3+b1)

All five LLVM binaries are sourced from a single frozen installation at
`/usr/lib/llvm-19/bin/`. Each tool path and version string is recorded in
`irx/experiment1/env/tool_versions.json`. The target triple is frozen in
`irx/experiment1/env/target.json`.

| Tool | Frozen path | Version |
|---|---|---|
| llvm-as | `/usr/lib/llvm-19/bin/llvm-as` | 19.1.7 |
| opt | `/usr/lib/llvm-19/bin/opt` | 19.1.7 |
| lli | `/usr/lib/llvm-19/bin/lli` | 19.1.7 |
| llc | `/usr/lib/llvm-19/bin/llc` | 19.1.7 |
| clang | `/usr/lib/llvm-19/bin/clang` | 19.1.7 (Debian) |

---

## Pipeline Architecture

The Phase 2 runner (`runner/phase2/phase2_runner.py`, 1972 lines) implements
a gated pipeline that takes a candidate LLVM IR file and evaluates it against
frozen test vectors. The pipeline uses an A-through-H step convention: Step A
is the initialization phase that loads frozen artifacts, and Steps B through H
are the seven sequential execution stages. Each execution stage must succeed
before the next is permitted to run.

```
[A] (init)          load tool paths, test vectors, constants, ID rules

candidate.ll
  |
  v
[B] precheck        enforce size/line limits
  |
  v
[C] llvm_as_parse   llvm-as -> candidate.bc
  |
  v
[D] opt_verify      opt -passes=verify
  |
  v
[E] lli_tests       lli interpreter + Python harness -> test results
  |
  v
[F] llc_compile     llc -> candidate.o (ELF relocatable)
  |
  v
[G] clang_link      clang/lld -> candidate.exe (freestanding ELF executable)
  |
  v
[H] native_tests    native_runner loads ELF, calls f() -> test results
```

This step labeling is consistent across the entire repository: evidence
scripts are named `step_f_check.sh` and `step_h_check.sh`, the Phase 2
closure record references Steps A-H, and commit messages use Step F for
llc_compile, Step G for clang_link, and Step H for native_tests. The runner
code emits `LOADED_STEP_A:` in the gate detail strings during initialization.

### Stage gating

Gating is strict. If Step E (lli_tests) reports any test failure, Step F
(llc_compile) is skipped and all downstream stages record `ok=False` with
`exit_code=null`. This prevents unnecessary compilation of known-bad candidates
and ensures the native execution path only runs against candidates that have
already passed interpretation. A candidate must clear all seven stages to
receive a PASS verdict.

### Subprocess isolation

Every LLVM tool invocation runs in a fully deterministic subprocess. The
environment is cleared to empty and rebuilt with exactly four variables:

- `LC_ALL=C`
- `LANG=C`
- `TZ=UTC`
- `LD_LIBRARY_PATH=/usr/lib/llvm-19/lib`

This eliminates locale-dependent formatting, timezone drift in timestamps,
and contamination from the user shell environment. Resource limits are applied
using `RLIMIT_RSS` only. `RLIMIT_AS` is deliberately avoided because
`libLLVM.so.19.1` maps approximately 123 MB of virtual address space on load
and would immediately trip any reasonable AS limit.

### Deterministic identity

Each run produces two SHA-256 identifiers:

- **candidate_id**: `sha256(candidate.ll file bytes)`
- **run_id**: `sha256(candidate_id encoded as UTF-8)`

These derivation rules are frozen in `irx/experiment1/harness/id_rules.json`.
Because the run_id is derived solely from the candidate_id, the same candidate
file always produces the same pair of identifiers regardless of when or where
the pipeline runs. The result artifact is written to
`runs/<candidate_id>/<run_id>.json` with work products stored alongside
in a `work/` subdirectory.

---

## Tasks

Three tasks are defined under `irx/experiment1/tasks/`, each with a
`spec.json` describing the function signature and a `tests.json` containing
10 frozen test vectors. All candidates implement the same ABI:

```
i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap)
```

### sum_u32_le

Sums an array of little-endian uint32 values. The candidate reads uint32
elements from the input buffer, accumulates them with wrapping addition,
writes the 4-byte little-endian result to the output buffer, and returns 4
(bytes written). Returns -1 on error: input length not divisible by 4, output
capacity less than 4, or exactly three input elements (an intentional boundary
test).

Test vectors cover: empty input (zero sum), single element identity, maximum
uint32 (0xFFFFFFFF), two-element addition, duplicate zeros, byte-order
verification (0x12345678), overflow wrapping (1 + 0xFFFFFFFF = 0x00000000),
double-max wrapping (0xFFFFFFFF + 0xFFFFFFFF = 0xFFFFFFFE), the three-element
rejection case, and four-element addition (1+2+3+4 = 10).

### hex_encode

Converts raw bytes to lowercase hexadecimal ASCII. Each input byte produces
two ASCII output bytes representing its hex digits. Returns the number of
output bytes written, or -2 if the output buffer is too small to hold the
full encoding.

Test vectors cover: empty input, single zero byte, values 0x01 and 0x0F,
insufficient output capacity, maximum byte 0xFF, multi-byte sequence
(0xDEADBEEF), three-byte input, ten sequential bytes (0x00-0x09), and
ASCII string encoding ("Hello").

### parse_u32_decimal

Parses a decimal ASCII string into a little-endian uint32. The input buffer
contains ASCII digit characters (0x30-0x39). Returns 4 (bytes written) on
success with the uint32 stored little-endian in the output buffer. Returns
-1 on error: empty input, non-digit characters, or overflow beyond
4294967295 (2^32 - 1).

Test vectors cover: single zero digit, single non-zero digit, two-digit
number, leading zeros, maximum uint32 (4294967295), overflow by one
(4294967296), empty input, negative sign prefix, large number (1234567890),
and embedded non-digit character.

---

## Known-Good Candidate

A verified known-good candidate for sum_u32_le is provided at
`irx/experiment1/verification/step_f/sum_u32_le_good.ll`. This is a 42-line
LLVM IR file that implements the sum_u32_le contract as a straightforward
loop using phi nodes for index tracking and accumulation.

The candidate targets `aarch64-unknown-linux-gnu` and defines a single
exported function `@f(ptr, i32, ptr, i32) -> i64` that:

1. Checks input length is divisible by 4 (rejects otherwise)
2. Checks output capacity is at least 4 (rejects otherwise)
3. Checks element count is not exactly 3 (rejects otherwise)
4. Loops over elements reading each as an i32 load with align 1
5. Accumulates with wrapping `add i32`
6. Stores the result via `store i32` to the output buffer and returns 4

Deterministic IDs (confirmed stable across all runs):

```
candidate_id: de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6
run_id:       4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60
```

No known-good candidates exist yet for hex_encode or parse_u32_decimal.

---

## Step G: Freestanding Linking

Step G links the compiled object into a freestanding ELF executable:

```
clang -target aarch64-unknown-linux-gnu \
      -nostdlib -fuse-ld=lld \
      -Wl,--no-dynamic-linker -Wl,-e,f \
      -o candidate.exe candidate.o
```

The flags produce a minimal static ELF binary with `f` as the entry point.
There is no C runtime startup, no dynamic linker reference, and no library
dependencies. The candidate's `@f` function is the only code in the binary.
For the sum_u32_le known-good candidate, the resulting `candidate.exe` is
2304 bytes.

---

## Step H: Native Execution Harness

Step H runs the frozen test vectors against the linked executable using a
custom in-process ELF loader (`irx/experiment1/harness/native/native_runner.c`,
421 lines). The loader is written in pure C with no external dependencies
beyond libc — no dlopen, no libelf, no LLVM runtime.

### ELF loading procedure

The `load_elf()` function (line 115) implements the following sequence:

1. **File mapping.** The ELF file is memory-mapped read-only for header
   parsing (`mmap(NULL, file_size, PROT_READ, MAP_PRIVATE, fd, 0)`,
   line 134). The file descriptor is closed immediately after mapping.

2. **Header validation.** The loader verifies the ELF magic bytes, 64-bit
   class, little-endian data encoding, and EM_AARCH64 machine type
   (lines 145-156). Both ET_EXEC and ET_DYN ELF types are accepted.

3. **Address span computation.** All PT_LOAD segments are scanned to find
   the minimum and maximum virtual addresses (lines 166-176). Both bounds
   are page-aligned using the system page size from `sysconf(_SC_PAGESIZE)`
   (lines 182-186).

4. **Region reservation.** A single contiguous anonymous region is reserved
   at a kernel-chosen address:
   `mmap(NULL, map_size, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0)`
   (line 189). The loader does not use `MAP_FIXED`. All subsequent address
   references are rebased relative to this region: a virtual address `va`
   in the ELF maps to `base + (va - vmin)` in the process.

5. **Segment copy.** Each PT_LOAD segment's file-backed data is copied
   into the reserved region via `memcpy(base + (va - vmin), fdata + off, fsz)`
   (line 210). Any BSS portion where `p_memsz > p_filesz` is zero-filled
   with `memset` (line 212).

6. **Instruction cache coherence.** The entire region is flushed with
   `__builtin___clear_cache(base, base + map_size)` (line 216). This is
   mandatory on aarch64 where the instruction cache and data cache are not
   coherent — without this step, the CPU could execute stale or garbage
   instructions from the I-cache.

7. **Permission hardening.** A second pass over PT_LOAD segments applies
   per-segment `mprotect` calls to set the final permissions derived from
   `p_flags` (lines 219-238). Code segments become read-execute, data
   segments become read-write, and read-only data becomes read-only.

8. **Relocation rejection.** Section headers are scanned for SHT_RELA and
   SHT_REL sections. If any non-empty relocation section exists, the loader
   rejects the binary (lines 241-252). This is a fail-closed safety check:
   the freestanding binaries produced by Step G should contain no relocations.

9. **Symbol resolution.** The loader searches `.symtab` (not `.dynsym`) for
   a function symbol matching the requested name, typically `f`
   (lines 254-283). The function pointer is computed as
   `base + (st_value - vmin)` (line 277). If the symbol is not found in
   `.symtab`, the loader falls back to the ELF entry point `e_entry`
   when the requested symbol is `f` (lines 286-288).

10. **Invocation.** The resolved function pointer is cast to
    `int64_t (*)(uint8_t*, int32_t, uint8_t*, int32_t)` and called directly.
    Output is printed as `RET=<decimal>` and `OUT=<hex>` in the wire format
    expected by the Python test harness.

### Design rationale

The loader rebases all addresses relative to an anonymous region rather than
using MAP_FIXED at the ELF-specified virtual addresses. This avoids conflicts
with the loader's own address space and works because the freestanding
candidates produced by Step G contain no absolute address relocations — the
code within each LOAD segment uses only PC-relative addressing. The
relocation rejection check (step 8 above) serves as a safety net: if a
candidate somehow contained relocations that the rebasing would break, the
loader refuses to execute it.

### Selftest

The native_runner supports a `--selftest` flag that validates its hex
encode/decode routines with a roundtrip test before any candidate execution.
The Phase 2 runner invokes selftest on first use within a pipeline run and
caches the result. Subsequent native test invocations in the same run skip
the selftest.

---

## Verdict Computation

The runner derives a final verdict from stage outcomes and test metrics using
the `compute_verdict()` function (line 73 in `phase2_runner.py`). The
function examines the `runs` array, `metrics` object, and `gates` object
from the result and returns a `(verdict_str, detail_str)` tuple.

The decision procedure:

1. Identify executed stages — those with a non-null `exit_code`, non-zero
   `duration_ms`, or a non-null `crash` record. Stages that were gated out
   (NOT_RUN) are excluded from this set.
2. If any executed stage has `ok=False`, return **FAIL** with a detail
   string naming the first failing stage.
3. If `tests_failed > 0` (lli tests), return **FAIL**.
4. If `native_tests_failed > 0`, return **FAIL**.
5. If no stages executed at all, return **ERROR** (no stages executed).
6. If every stage in the skeleton has `ok=True` and both lli and native
   failure counts are zero (or absent), return **PASS**.
7. Otherwise, return **ERROR** (indeterminate).

The verdict string is written to the top-level `verdict` field in the JSON
artifact. The `gates.policy.ok` field is set to `true` when verdict is PASS,
`false` otherwise. The verdict detail is appended to `gates.policy.detail`.

This logic was introduced in commit `8762240` (2026-02-15), replacing an
earlier implementation where the verdict was unconditionally set to `"ERROR"`
and `gates.policy.ok` was always `false`. The fix is covered by 8 unit tests
in `runner/phase2/tests/test_verdict.py` that exercise every branch: all-pass,
pass without native metrics, individual stage failure, precheck failure, lli
test failure, native test failure, no stages executed, and partial execution
with upstream failure.

---

## Result Schema

Every result JSON artifact is validated against
`irx/experiment1/harness/result_schema.json` (JSON Schema draft 2020-12).
The schema uses `additionalProperties: false` at the top level and within
every nested object definition, ensuring no undeclared fields appear in the
output.

Required top-level fields: `experiment`, `task`, `candidate_id`, `run_id`,
`timestamps`, `gates`, `runs`, `metrics`, `verdict`.

The `verdict` field is constrained to the enum `["PASS", "FAIL", "ERROR"]`.

The `metrics` object contains 14 counters: seven for lli execution
(tests_total, tests_passed, tests_failed, ret_mismatches,
output_mismatches, timeouts, crashes) and seven for native execution
(native_tests_total, native_tests_passed, native_tests_failed,
native_ret_mismatches, native_output_mismatches, native_timeouts,
native_crashes). The native metric fields were added to the schema in
commit `a5d84da` alongside the Step H implementation.

The `test_results` and `native_test_results` arrays each contain per-vector
records with fields: index, in_hex, out_cap, expected_ret, expected_out_hex,
actual_ret, actual_out_hex, outcome, exit_code, signal, detail. The outcome
field is constrained to `["PASS", "RETURN_MISMATCH", "OUTPUT_MISMATCH",
"UNEXPECTED_CRASH", "TIMEOUT", "OOM"]`.

---

## Regression Sweep

A three-task regression sweep was executed on 2026-02-16 at HEAD `8563fd2`
(2026-02-16T08:34:39Z). The sweep ran the full A-H pipeline for each task,
validated every result JSON against the schema, and compared verdicts against
expectations. The evidence log is stored at
`irx/experiment1/verification/evidence/logs/regression_sweep_20260216_003439.log`.

### sum_u32_le — verdict: PASS

The known-good candidate clears all seven stages. Both lli and native
execution produce bitwise-identical results across all 10 test vectors.

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

Work artifacts: candidate.bc (1928 bytes), candidate.o (1008 bytes),
candidate.exe (2304 bytes).

### hex_encode — verdict: FAIL

The sum_u32_le candidate was run as a stub against the hex_encode test vectors
(no hex_encode-specific candidate exists). The candidate passes Steps B-D
because its IR is structurally valid LLVM. At Step E, all 10 hex_encode
vectors fail because the candidate computes sums rather than hex encodings.
The pipeline correctly gates out Steps F-H.

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

### parse_u32_decimal — verdict: FAIL

Same stub candidate against parse_u32_decimal vectors. Steps B-D pass. At
Step E, 8 of 10 vectors fail. Two vectors pass by coincidence where the
sum_u32_le function happens to return values matching parse_u32_decimal
expectations for those particular inputs. Steps F-H gated out.

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

All three result artifacts pass full schema validation. The verdict
computation correctly yields PASS for a correct candidate on its own task
and FAIL for a wrong candidate on a different task. Stage gating prevents
compilation and native execution of candidates that fail at interpretation.

---

## Unit Tests

Two hermetic test suites validate runner internals without LLVM:

**test_native_tests.py** — 13 tests covering native test result parsing,
per-vector result construction, gating precondition logic, selftest caching
behavior, and error handling for the Step H integration. All tests use mock
subprocess calls and run without the native_runner binary.

**test_verdict.py** — 8 tests covering every branch of `compute_verdict()`:
all-pass yields PASS, pass without native metrics yields PASS, a failed stage
yields FAIL naming the stage, precheck failure yields FAIL, lli test failures
yield FAIL, native test failures yield FAIL, no executed stages yields ERROR,
and partial execution with an upstream failure yields FAIL.

All 21 tests pass (13 + 8).

---

## Test Vector Correction

Test vector t08 for sum_u32_le (index 7, input `ffffffffffffffff`) originally
had `expected_out_hex` set to `"fffffffe"`. This was a big-endian
representation of the value 0xFFFFFFFE. The correct little-endian byte
encoding is `"feffffff"`. The fix was a single-field change in
`tasks/sum_u32_le/tests.json` committed as `31223ce` (2026-02-15 22:16 PST).
No other test vectors, fields, or files were modified.

The error was discovered during Step F verification when the candidate
produced the correct little-endian bytes but the test vector expected the
reversed byte order.

---

## Evidence Logs

All pipeline evidence is stored under
`irx/experiment1/verification/evidence/logs/`:

| Log file | Date | HEAD | Content |
|---|---|---|---|
| `step_h_check_20260215_234036.log` | 2026-02-15 | `a5d84da` | Phase 2 closure run, 7/7 stages PASS |
| `step_h_check_verdictfix_20260215_235338.log` | 2026-02-15 | `8762240` | First run after verdict fix |
| `step_h_check_verdictfix_20260216_000503.log` | 2026-02-16 | post-`8762240` | Full proof chain: verdict PASS, ID match, artifact sizes |
| `regression_sweep_20260216_003439.log` | 2026-02-16 | `8563fd2` | Three-task regression sweep, all verdicts correct |

The final verdict fix evidence log (`step_h_check_verdictfix_20260216_000503.log`)
includes a multi-part proof chain: the path to the result JSON, extraction of
the verdict field showing `"PASS"`, a grep confirming `"verdict": "PASS"` at
line 366 of the JSON, verification that candidate_id and run_id match expected
values, and an `ls -l` listing of all three work artifacts (candidate.bc,
candidate.o, candidate.exe) with their byte sizes.

---

## Commit History

Key implementation and verification commits in chronological order:

| Commit | Date (PST) | Description |
|---|---|---|
| `31223ce` | 2026-02-15 22:16 | Fix sum_u32_le t08 expected_out_hex endianness |
| `1153420` | 2026-02-15 22:18 | Add verification fixture directory |
| `f0a6261` | 2026-02-15 22:28 | Add Step F evidence bundle and check script |
| `add9dc8` | 2026-02-15 19:48 | Add llc_compile gate (Step F) |
| `960cebf` | 2026-02-15 19:39 | Add frozen id_rules authority |
| `b1679b0` | 2026-02-15 21:32 | Fix opt syntax, target triple key, schema, wire lli harness |
| `b0d8cd9` | 2026-02-15 23:02 | Implement Step G clang_link |
| `a5d84da` | 2026-02-15 23:32 | Implement Step H native_tests, extend schema |
| `5201dd2` | 2026-02-15 23:41 | Phase 2 closure record |
| `8762240` | 2026-02-15 23:55 | Fix verdict computation from stage outcomes |
| `b104ff5` | 2026-02-16 00:48 | Fix report metadata and native loader wording |

---

## Reproduction

From the repository root on any aarch64-linux-gnu system with LLVM 19:

```bash
# Full A-H pipeline on the known-good candidate
rm -rf irx/experiment1/runs/*
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/step_f/sum_u32_le_good.ll \
  --task sum_u32_le

# Validate the result artifact against the schema
python3 -c "
import json, jsonschema, os
from glob import glob
paths = sorted(glob('irx/experiment1/runs/*/*.json'), key=os.path.getmtime, reverse=True)
with open(paths[0]) as fh: d = json.load(fh)
with open('irx/experiment1/harness/result_schema.json') as fh: s = json.load(fh)
jsonschema.validate(d, s)
print('verdict:', d['verdict'])
print('gates.policy.ok:', d['gates']['policy']['ok'])
"

# Step H evidence check (clean run with summary)
rm -rf irx/experiment1/runs/*
bash irx/experiment1/verification/evidence/step_h_check.sh

# Unit tests (hermetic, no LLVM required)
python3 -m unittest runner/phase2/tests/test_native_tests.py
python3 -m unittest runner/phase2/tests/test_verdict.py
```

Expected output for the known-good sum_u32_le candidate: verdict PASS, lli
10/10 passed, native 10/10 passed, lli/native match on all 10 vectors, all
seven stages ok, schema validation passes.

---

*Report last updated 2026-02-16 on Raspberry Pi 5. See Revision History for commit references.*
