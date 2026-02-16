# IR Experiments — Experiment 1: Full Pipeline Verification Report

This document is the authoritative technical report for Experiment 1 of the
IR Experiments project. It describes the complete design, implementation, and
verification of the Phase 2 pipeline — a gated evaluation system that takes
an LLVM IR candidate file, subjects it to structural analysis, interpreted
execution, native compilation, and native execution on real AArch64 hardware.
Every tool invocation is deterministic and reproducible. The pipeline runs on
a Raspberry Pi 5, producing structured JSON result artifacts validated against
a frozen schema.

---

## 1. Revision History

Thirty-six commits span the full history of Experiment 1, from the initial
scaffold (`681a6cd`, 2026-02-15 12:08 PST) through the current HEAD.
Milestones relevant to the pipeline implementation:

| Commit | Date (PST) | Milestone |
|--------|------------|-----------|
| `681a6cd` | 2026-02-15 12:08 | Experiment 1 Phase 0 scaffold and frozen assets |
| `8b6b544` | 2026-02-15 12:45 | Phase 1 toolchain discovery and run config capture |
| `99a5073` | 2026-02-15 16:02 | Phase 2 Step A authority probe scanning and guards |
| `db6d703` | 2026-02-15 16:15 | Step B precheck gate for bytes and lines |
| `30057da` | 2026-02-15 16:27 | Handle non-executable llvm-as as Stage 2 failure |
| `a5d5009` | 2026-02-15 16:37 | Step D: gate opt path checks on stage-3 preconditions |
| `6b5a37f` | 2026-02-15 18:59 | Fix LLVM tool execution in deterministic subprocess env |
| `d5298ad` | 2026-02-15 19:13 | Unify llvm tool env and rss-only preexec |
| `960cebf` | 2026-02-15 19:39 | Frozen `id_rules.json` authority for deterministic IDs |
| `add9dc8` | 2026-02-15 19:48 | Step F `llc_compile` gate with artifact-first handling |
| `b1679b0` | 2026-02-15 21:32 | Fix opt syntax, target triple key, schema detection, wire lli harness |
| `31223ce` | 2026-02-15 22:16 | Fix sum_u32_le t08 `expected_out_hex` endianness (unblocks Step F) |
| `1153420` | 2026-02-15 22:18 | Verification fixture directory and run instructions |
| `f0a6261` | 2026-02-15 22:28 | Step F evidence bundle and `step_f_check.sh` |
| `b0d8cd9` | 2026-02-15 23:02 | Step G `clang_link` (freestanding ELF linking) |
| `a5d84da` | 2026-02-15 23:32 | Step H `native_tests`, result schema extension with native metrics |
| `5201dd2` | 2026-02-15 23:41 | Add `PHASE2_CLOSURE.md` and commit `step_h_check_20260215_234036.log` (Step H evidence) |
| `8762240` | 2026-02-15 23:55 | Fix verdict computation from stage outcomes (`compute_verdict()`) |
| `b5be4f7` | 2026-02-16 01:35 | Fix stale `i32` signature_ir in constants.json and 3 spec.json files |

Git-proof for `5201dd2` (via `git show --name-status 5201dd2`):

```
A    irx/experiment1/PHASE2_CLOSURE.md
A    irx/experiment1/verification/evidence/logs/step_h_check_20260215_234036.log
```

Two files added: `PHASE2_CLOSURE.md` and `step_h_check_20260215_234036.log`.

---

## 2. Platform and Toolchain

### 2.1 Hardware

Raspberry Pi 5 with a Broadcom BCM2712 system-on-chip. The BCM2712 integrates
four Arm Cortex-A76 cores implementing ARMv8.2-A in little-endian (AArch64)
mode. The Cortex-A76 is a superscalar, out-of-order core with 64 KB L1I and
64 KB L1D caches per core. The split I/D cache architecture is directly
relevant to the pipeline: after copying executable code into an anonymous
memory region, the native ELF loader must explicitly flush the instruction
cache to guarantee coherence between what was written via the data cache and
what will be fetched into the instruction cache (Section 10.6).

### 2.2 Operating System

Raspberry Pi OS 64-bit (Debian-based). Kernel 6.12.47+rpt-rpi-2712, SMP
PREEMPT, AArch64. The frozen target triple for all compilation stages is
`aarch64-unknown-linux-gnu`, recorded in `irx/experiment1/env/target.json`:

```json
{
  "os": "raspios64",
  "arch": "aarch64",
  "triple": "aarch64-unknown-linux-gnu",
  "endian": "little"
}
```

### 2.3 LLVM Toolchain

Five LLVM tools from a single Debian LLVM 19.1.7 installation at
`/usr/lib/llvm-19/bin/`. Every tool path and version string is frozen in
`irx/experiment1/env/tool_versions.json`. The runner reads tool paths
exclusively from this frozen file — it never searches `$PATH`, never uses
`which`, never employs any discovery mechanism.

| Tool | Frozen Path | Version |
|------|-------------|---------|
| llvm-as | `/usr/lib/llvm-19/bin/llvm-as` | Debian LLVM 19.1.7, Optimized build |
| opt | `/usr/lib/llvm-19/bin/opt` | Debian LLVM 19.1.7, Optimized build |
| lli | `/usr/lib/llvm-19/bin/lli` | Debian LLVM 19.1.7, Optimized build |
| llc | `/usr/lib/llvm-19/bin/llc` | Debian LLVM 19.1.7, Optimized build |
| clang | `/usr/lib/llvm-19/bin/clang` | Debian clang 19.1.7 (3+b1) |

The `opt` and `llc` version strings additionally report the host CPU as
`cortex-a76` and the default target as `aarch64-unknown-linux-gnu`. The
`clang` version string reports the thread model as `posix` and the installed
directory as `/usr/lib/llvm-19/bin`. All five tools dynamically link against
`libLLVM.so.19.1` in the sibling `/usr/lib/llvm-19/lib/` directory.

---

## 3. Pipeline Architecture

### 3.1 Overview

The Phase 2 runner is a single Python module at
`runner/phase2/phase2_runner.py` (1972 lines). It ingests a candidate LLVM IR
file (`.ll`), evaluates it against frozen test vectors, and writes a
structured JSON result artifact. The pipeline follows an A-through-H step
convention:

- **Step A** (initialization) loads five categories of frozen artifacts: tool
  paths, result schema, constants and limits, target triple, and all task test
  vectors. It computes the deterministic candidate and run identifiers. It
  emits a `LOADED_STEP_A:` prefix string into every gate detail field
  (line 1440 of `phase2_runner.py`), recording the paths of every artifact
  loaded.

- **Steps B through H** are the seven sequential execution stages. Each stage
  must succeed before the next runs.

```
[A] init            Load frozen artifacts. Compute candidate_id, run_id.
                    Emit LOADED_STEP_A: into every gate detail string.

candidate.ll
  |
  v
[B] precheck        Enforce size limits (max 65536 bytes, max 2000 lines).
  |
  v
[C] llvm_as_parse   llvm-as -> candidate.bc (bitcode assembly).
  |
  v
[D] opt_verify      opt -passes=verify (LLVM module verification).
  |
  v
[E] lli_tests       lli interpreter + Python harness -> per-vector test results.
  |
  v
[F] llc_compile     llc -filetype=obj -> candidate.o (ELF relocatable object).
  |
  v
[G] clang_link      clang + lld -> candidate.exe (freestanding ELF executable).
  |
  v
[H] native_tests    Custom ELF loader invokes f() -> per-vector test results.
```

This step labeling is consistent throughout the repository: evidence scripts
are named `step_f_check.sh` and `step_h_check.sh`, the closure record
(`PHASE2_CLOSURE.md`) references Steps A through H, and commit messages use
Step F for llc_compile, Step G for clang_link, and Step H for native_tests.

### 3.2 Stage Gating

Gating is strict and sequential. Every execution stage checks that all prior
stages succeeded before running. The precondition for each stage is a
conjunction of upstream `ok=True` results plus the existence and non-emptiness
of the expected input artifact.

| Stage | Line(s) | Preconditions |
|-------|---------|---------------|
| B (precheck) | 1453 | Always runs |
| C (llvm_as_parse) | 1461 | B passed |
| D (opt_verify) | 1486-1490 | B, C passed; `candidate.bc` exists and > 0 bytes |
| E (lli_tests) | 1527-1532 | B, C, D passed; lli path valid; `candidate.bc` exists and > 0 bytes |
| F (llc_compile) | 1636-1642 | B, C, D, E passed; `candidate.bc` exists and > 0 bytes |
| G (clang_link) | 1693-1700 | B, C, D, E, F passed; `candidate.o` exists and > 0 bytes |
| H (native_tests) | 1755-1763 | B, C, D, E, F, G passed; `candidate.exe` exists and > 0 bytes |

If any stage fails, all downstream stages are skipped. Their `runs` records
remain at skeleton defaults (`ok=False`, `exit_code=null`, `duration_ms=0`,
`crash=null`), and their detail strings record
`<STAGE>_NOT_RUN:preconditions_failed`.

### 3.3 Subprocess Isolation

Every LLVM tool invocation runs in a fully deterministic subprocess. The
environment is cleared to empty and rebuilt with exactly four variables
(`_build_llvm_tool_env` at line 699):

```
LC_ALL=C
LANG=C
TZ=UTC
LD_LIBRARY_PATH=/usr/lib/llvm-19/lib
```

The `LD_LIBRARY_PATH` is derived from the frozen tool path by computing the
sibling `lib/` directory (`_derive_llvm_lib_path` at line 680). `LC_ALL=C`
and `LANG=C` eliminate locale-dependent formatting. `TZ=UTC` eliminates
timezone drift. The cleared parent environment prevents shell contamination.

Resource limits use `RLIMIT_RSS` only (line 728-729). `RLIMIT_AS` (virtual
address space) is deliberately avoided because `libLLVM.so.19.1` maps
approximately 123 MB of virtual address space on load and would immediately
trip any reasonable AS limit. The frozen RSS limit is 64 MiB. Each subprocess
starts in its own process group (`start_new_session=True`) for clean timeout
kills via `os.killpg`.

### 3.4 Deterministic Identity

Each run produces two SHA-256 identifiers, derived according to rules frozen
in `irx/experiment1/harness/id_rules.json`:

```json
{
  "candidate_id": {
    "algo": "sha256_file_bytes",
    "input": "candidate.ll"
  },
  "run_id": {
    "algo": "sha256_utf8",
    "input": "candidate_id"
  }
}
```

The `candidate_id` is the SHA-256 digest of the raw bytes of the candidate
`.ll` file. The `run_id` is the SHA-256 digest of the `candidate_id` string
encoded as UTF-8. Because the `run_id` depends solely on the `candidate_id`,
the same candidate file always produces the same identifier pair regardless of
when, where, or how many times the pipeline runs.

Result artifacts are written to `runs/<candidate_id>/<run_id>.json` with work
products in a sibling `<run_id>/work/` subdirectory.

---

## 4. Frozen Artifacts

The pipeline reads five categories of frozen artifacts at initialization. All
are committed to the repository and never modified at runtime.

### 4.1 Tool Versions (`irx/experiment1/env/tool_versions.json`)

A `detected` object containing five entries (llvm-as, opt, lli, llc, clang),
each with:
- `ok` (boolean) — tool found and executable
- `path` (string) — absolute filesystem path
- `version_text` (string) — raw output of `--version`
- `error` (null on this platform)

The runner resolves each tool with dedicated functions:
- llvm-as: `_resolve_llvm_as_path` (falls back to `detected.llvm-as.path`)
- opt: `_resolve_opt_path` (falls back to `detected.llvm-opt.path`)
- llc: `_resolve_llc_path` at line 271 (falls back to `detected.llvm-llc.path`)
- clang: `_resolve_clang_path` at line 300 (falls back to `detected.llvm-clang.path`)

### 4.2 Target (`irx/experiment1/env/target.json`)

Records the compilation target. The `triple` field is
`aarch64-unknown-linux-gnu` and is used as the `-mtriple` argument to `llc` in
Step F and the `-target` argument to `clang` in Step G.

### 4.3 Constants (`irx/experiment1/harness/constants.json`)

Defines the experiment number, shared ABI contract, error codes, resource
limits, and crash type taxonomy.

#### 4.3.1 ABI Contract

Every candidate exports a single function `f` with this signature:

```
i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap)
```

The function reads from an input buffer, writes to an output buffer, and
returns the number of bytes written on success or a negative error code on
failure. This signature is the authoritative ABI, verified consistent across
every executable component:

| Location | File | Line | Text |
|----------|------|------|------|
| lli shim declaration | `harness/lli_shim/shim.ll` | 366 | `declare i64 @f(ptr noundef, i32 noundef, ptr noundef, i32 noundef)` |
| lli shim call site | `harness/lli_shim/shim.ll` | 90 | `%90 = call i64 @f(...)` |
| lli harness docstring | `harness/lli_abi_runner.py` | 6 | `i64 @f(i8* %in_ptr, i32 %in_len, i8* %out_ptr, i32 %out_cap)` |
| Native harness typedef | `harness/native/native_runner.c` | 32 | `typedef int64_t (*candidate_fn)(uint8_t *, int32_t, uint8_t *, int32_t)` |
| Known-good candidate | `verification/step_f/sum_u32_le_good.ll` | 4 | `define i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap)` |
| constants.json | `harness/constants.json` | 5 | `"signature_ir": "i64 @f(i8* %in_ptr, i32 %in_len, i8* %out_ptr, i32 %out_cap)"` |
| sum_u32_le spec | `tasks/sum_u32_le/spec.json` | 5 | `"signature_ir": "i64 @f(i8* %in_ptr, i32 %in_len, i8* %out_ptr, i32 %out_cap)"` |
| hex_encode spec | `tasks/hex_encode/spec.json` | 5 | `"signature_ir": "i64 @f(i8* %in_ptr, i32 %in_len, i8* %out_ptr, i32 %out_cap)"` |
| parse_u32_decimal spec | `tasks/parse_u32_decimal/spec.json` | 5 | `"signature_ir": "i64 @f(i8* %in_ptr, i32 %in_len, i8* %out_ptr, i32 %out_cap)"` |

The `signature_ir` fields were corrected from a stale `i32` return type in
commit `b5be4f7`. The runner never reads `signature_ir` at runtime — the field
is purely documentary. All nine locations now consistently record `i64`.

#### 4.3.2 Error Codes

| Code | Name | Meaning |
|------|------|---------|
| -1 | ERR_INVALID_INPUT | Malformed, out-of-range, or rejected input |
| -2 | ERR_OUTPUT_TOO_SMALL | Output buffer capacity insufficient |
| -3 | ERR_INTERNAL | Unexpected internal failure |

#### 4.3.3 Resource Limits

| Limit | Value | Used by |
|-------|-------|---------|
| max_ll_bytes | 65536 | Step B precheck |
| max_ll_lines | 2000 | Step B precheck |
| max_basic_blocks | 200 | Reserved (not currently enforced) |
| max_instructions | 20000 | Reserved (not currently enforced) |
| max_alloca_bytes_total | 4096 | Reserved (not currently enforced) |
| timeout_stage_ms | 1000 | Steps C, D, F, G (per-stage timeout, 1 second) |
| timeout_per_test_ms | 50 | Steps E, H (per-test-vector timeout, 50 ms) |
| max_rss_mib | 64 | All subprocess stages (64 MB RSS cap) |
| max_input_bytes | 65536 | Input buffer size cap |
| max_output_bytes | 65536 | Output buffer size cap |

#### 4.3.4 Crash Type Taxonomy

Ten categories: `SIGSEGV`, `SIGILL`, `SIGABRT`, `SIGFPE`, `TIMEOUT`, `OOM`,
`SANITIZER_FINDING`, `POLICY_VIOLATION`, `VERIFY_FAIL`, `PARSE_FAIL`. Each
stage maps its failure modes into this taxonomy for uniform reporting in the
`runs[].crash` field. The taxonomy is enforced by the result schema as an enum
on `crash.type` (lines 180-192 of `result_schema.json`).

### 4.4 Result Schema (`irx/experiment1/harness/result_schema.json`)

A JSON Schema (draft 2020-12), 301 lines. Validated against every result
artifact before it is written to disk (line 1905 of `phase2_runner.py`). The
schema uses `additionalProperties: false` at every level, meaning no
undeclared fields are permitted.

**Top-level required fields** (lines 7-16): `experiment`, `task`,
`candidate_id`, `run_id`, `timestamps`, `gates`, `runs`, `metrics`, `verdict`.

**`verdict`** (lines 154-157): enum `["PASS", "FAIL", "ERROR"]`.

**`gates`** (lines 46-63): four required sub-objects (`parse`, `verify`,
`policy`, `tests`), each a `gateStatus` with `ok` (boolean) and `detail`
(string or null).

**`runs`** (lines 65-69): array of `runRecord` objects (lines 202-234), each
with six required fields: `stage` (string), `ok` (boolean), `exit_code`
(integer or null), `duration_ms` (integer >= 0), `rss_mib` (number or null),
`crash` (crash object or null). The `crash` object requires `type` (crash
taxonomy enum or null), `signal` (integer or null), `detail` (string or null).

**`metrics`** (lines 71-140): 14 required counters — seven for lli execution
(`tests_total`, `tests_passed`, `tests_failed`, `ret_mismatches`,
`output_mismatches`, `timeouts`, `crashes`) and seven mirrored for native
execution (`native_tests_total` through `native_crashes`). The native counters
and the `native_test_results` array were added in commit `a5d84da`.

**`test_results`** and **`native_test_results`** (lines 142-152): arrays of
`testResult` objects (lines 236-299), each with 11 required fields: `index`,
`in_hex`, `out_cap`, `expected_ret`, `expected_out_hex`, `actual_ret`,
`actual_out_hex`, `outcome`, `exit_code`, `signal`, `detail`. The `outcome`
field is enum `["PASS", "RETURN_MISMATCH", "OUTPUT_MISMATCH",
"UNEXPECTED_CRASH", "TIMEOUT", "OOM"]`. The `signal` field is enum
`["SIGSEGV", "SIGILL", "SIGABRT", "SIGFPE", null]`. The `detail` field has
`maxLength: 200`.

### 4.5 ID Rules (`irx/experiment1/harness/id_rules.json`)

Defines the two derivation rules described in Section 3.4. When this file
exists, the runner uses it as the authoritative ID computation method and
skips the runtime inference probe entirely (`inference_status:
SKIPPED_FROZEN_ID_RULES`).

---

## 5. Tasks and Test Vectors

Three tasks are defined under `irx/experiment1/tasks/`, each with a
`spec.json` describing the function contract and a `tests.json` containing
10 frozen test vectors. All candidates implement the shared ABI:

```
i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap)
```

Every task's `spec.json` declares the same memory rules: input is immutable,
input and output buffers do not overlap, no alignment assumptions may be made
(all loads and stores use `align 1`), and no output writes occur on error
paths.

### 5.1 sum_u32_le

**Contract.** Reads an array of little-endian uint32 values from the input
buffer, accumulates them with wrapping (mod 2^32) addition, writes the 4-byte
little-endian result to the output buffer, and returns 4 (bytes written).
Returns -1 if the input length is not divisible by 4, the output capacity is
less than 4, or the element count is exactly 3 (an intentional boundary
rejection embedded in the known-good candidate).

**Test vectors (10):**

| ID | Input (hex) | out_cap | Expected ret | Expected output (hex) | Purpose |
|----|-------------|---------|--------------|----------------------|---------|
| t01 | (empty) | 4 | 4 | `00000000` | Zero elements, sum = 0 |
| t02 | `01000000` | 4 | 4 | `01000000` | Single element, value = 1 |
| t03 | `ffffffff` | 4 | 4 | `ffffffff` | Maximum uint32 (0xFFFFFFFF) |
| t04 | `0100000002000000` | 4 | 4 | `03000000` | Two-element addition (1 + 2 = 3) |
| t05 | `0000000000000000` | 4 | 4 | `00000000` | Two zero elements |
| t06 | `78563412` | 4 | 4 | `78563412` | Byte-order verification (0x12345678 LE) |
| t07 | `01000000ffffffff` | 4 | 4 | `00000000` | Overflow wrap (1 + 0xFFFFFFFF = 0 mod 2^32) |
| t08 | `ffffffffffffffff` | 4 | 4 | `feffffff` | Double-max wrap (0xFFFFFFFE LE) |
| t09 | `00000000ffffffff01000000` | 4 | -1 | (empty) | Three-element rejection |
| t10 | `01000000020000000300000004000000` | 4 | 4 | `0a000000` | Four-element sum (1+2+3+4 = 10) |

**Test vector correction.** Vector t08 originally had `expected_out_hex` set
to `"fffffffe"`, which is big-endian for 0xFFFFFFFE. The correct little-endian
encoding is `"feffffff"`. This single-field change in
`tasks/sum_u32_le/tests.json` was committed as `31223ce` (2026-02-15 22:16
PST). No other vectors, fields, or files were modified. The error was
discovered during Step F verification when the candidate produced the correct
little-endian bytes but the vector expected the reversed order.

### 5.2 hex_encode

**Contract.** Converts each input byte to two lowercase hexadecimal ASCII
characters. Output length is exactly `2 * in_len` bytes. Returns the byte
count written on success, or -2 if `out_cap < 2 * in_len`.

**Test vectors (10):**

| ID | Input (hex) | out_cap | Expected ret | Expected output (hex) | Purpose |
|----|-------------|---------|--------------|----------------------|---------|
| t01 | (empty) | 0 | 0 | (empty) | Empty input, zero output |
| t02 | `00` | 2 | 2 | `3030` | Byte 0x00 -> ASCII "00" |
| t03 | `01` | 2 | 2 | `3031` | Byte 0x01 -> ASCII "01" |
| t04 | `0f` | 2 | 2 | `3066` | Byte 0x0F -> ASCII "0f" |
| t05 | `10` | 1 | -2 | (empty) | Insufficient capacity (need 2, have 1) |
| t06 | `ff` | 2 | 2 | `6666` | Byte 0xFF -> ASCII "ff" |
| t07 | `deadbeef` | 8 | 8 | `6465616462656566` | 4-byte 0xDEADBEEF |
| t08 | `123456` | 6 | 6 | `313233343536` | 3-byte 0x123456 |
| t09 | `00010203040506070809` | 20 | 20 | `3030303130323033303430353036303730383039` | 10-byte sequence 0x00-0x09 |
| t10 | `48656c6c6f` | 10 | 10 | `34383635366336633666` | ASCII "Hello" -> hex encode |

### 5.3 parse_u32_decimal

**Contract.** Parses a decimal ASCII string (digit bytes 0x30-0x39) into a
little-endian uint32. Returns 4 on success. Returns -1 on error: empty input,
non-digit characters, or overflow beyond 4294967295. The overflow check uses
`acc > 429496729 || (acc == 429496729 && digit > 5)`.

**Test vectors (10):**

| ID | Input (hex) | Decoded ASCII | out_cap | Expected ret | Expected output (hex) | Purpose |
|----|-------------|---------------|---------|--------------|----------------------|---------|
| t01 | `30` | "0" | 4 | 4 | `00000000` | Single zero digit |
| t02 | `35` | "5" | 4 | 4 | `05000000` | Single digit (5) |
| t03 | `3130` | "10" | 4 | 4 | `0a000000` | Two-digit number (10) |
| t04 | `30303033` | "0003" | 4 | 4 | `03000000` | Leading zeros |
| t05 | `34323934393637323935` | "4294967295" | 4 | 4 | `ffffffff` | Maximum uint32 |
| t06 | `34323934393637323936` | "4294967296" | 4 | -1 | (empty) | Overflow by one |
| t07 | (empty) | (empty) | 4 | -1 | (empty) | Empty input |
| t08 | `2d31` | "-1" | 4 | -1 | (empty) | Negative sign (non-digit) |
| t09 | `31323334353637383930` | "1234567890" | 4 | 4 | `d2029649` | Large valid number |
| t10 | `31323378` | "123x" | 4 | -1 | (empty) | Embedded non-digit |

---

## 6. Known-Good Candidate

A verified known-good candidate for sum_u32_le is at
`irx/experiment1/verification/step_f/sum_u32_le_good.ll` (42 lines). It
targets `aarch64-unknown-linux-gnu` and defines a single exported function
`@f(ptr, i32, ptr, i32) -> i64`.

```llvm
target datalayout = "e-m:e-i8:8:32-i16:16:32-i64:64-i128:128-n32:64-S128"
target triple = "aarch64-unknown-linux-gnu"

define i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap) {
entry:
  %rem = urem i32 %in_len, 4
  %valid_len = icmp eq i32 %rem, 0
  br i1 %valid_len, label %check_cap, label %err_invalid

check_cap:
  %cap_ok = icmp sge i32 %out_cap, 4
  br i1 %cap_ok, label %check_n, label %err_invalid

check_n:
  %n = udiv i32 %in_len, 4
  %is_three = icmp eq i32 %n, 3
  br i1 %is_three, label %err_invalid, label %loop_init

loop_init:
  %cmp_zero = icmp eq i32 %n, 0
  br i1 %cmp_zero, label %write_out, label %loop_body

loop_body:
  %i = phi i32 [0, %loop_init], [%i_next, %loop_body]
  %sum = phi i32 [0, %loop_init], [%sum_next, %loop_body]
  %offset = mul i32 %i, 4
  %offset_64 = zext i32 %offset to i64
  %elem_ptr = getelementptr i8, ptr %in_ptr, i64 %offset_64
  %val = load i32, ptr %elem_ptr, align 1
  %sum_next = add i32 %sum, %val
  %i_next = add i32 %i, 1
  %done = icmp eq i32 %i_next, %n
  br i1 %done, label %write_out, label %loop_body

write_out:
  %result = phi i32 [0, %loop_init], [%sum_next, %loop_body]
  store i32 %result, ptr %out_ptr, align 1
  ret i64 4

err_invalid:
  ret i64 -1
}
```

**Validation sequence:**

1. `%rem = urem i32 %in_len, 4` — reject if `in_len` not divisible by 4
2. `%cap_ok = icmp sge i32 %out_cap, 4` — reject if capacity < 4
3. `%is_three = icmp eq i32 %n, 3` — reject if exactly 3 elements (boundary test)
4. If zero elements: store zero to output, return 4
5. Loop with phi nodes (`%i` for index, `%sum` for accumulator), reading each
   element via `load i32, ptr %elem_ptr, align 1`
6. Accumulate with wrapping `add i32`
7. Store via `store i32 %result, ptr %out_ptr, align 1`, return 4

The loop computes byte offsets via `getelementptr i8` with `%i * 4`
zero-extended to i64. The exit condition is `icmp eq i32 %i_next, %n`.

**Deterministic IDs** (confirmed stable across all runs):

```
candidate_id: de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6
run_id:       4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60
```

No known-good candidates exist yet for hex_encode or parse_u32_decimal.

---

## 7. Pipeline Stages in Detail

### 7.1 Step B: Precheck

**Implementation:** `_apply_precheck` at line 641. Enforces two size limits
from `constants.json`: max 65536 bytes and max 2000 lines. Lines are counted
by splitting on newline characters. Runs entirely in-process (no subprocess).

On success: `PRECHECK_PASS:bytes=1232/65536;lines=42/2000`.

On failure: `PRECHECK_FAIL` with the specific limit exceeded, and
`runs_skeleton[0].ok` set to `False`.

### 7.2 Step C: llvm_as_parse

Assembles the candidate into LLVM bitcode:

```
llvm-as candidate.ll -o candidate.bc
```

Resolved from `detected.llvm-as.path` in `tool_versions.json`. Runs in the
deterministic four-variable subprocess environment. On exit code 0 with
non-empty output file: `LLVM_AS_PARSE_PASS`. On timeout, signal, OOM, or
nonzero exit: the appropriate crash taxonomy type is recorded. Missing or
non-executable tool: `runs_skeleton[1].ok = False` immediately.

### 7.3 Step D: opt_verify

Runs the LLVM module verifier:

```
opt -passes=verify candidate.bc -o /dev/null
```

Resolved from `detected.opt.path` (fallback `detected.llvm-opt.path`). Checks
structural correctness: instruction operand types, basic block termination,
SSA dominance, and other LLVM IR invariants. Stage 3 gate at lines 1486-1490
requires precheck_ok, llvm_as_ok, and a valid `candidate.bc` file.

### 7.4 Step E: lli_tests

Interprets the candidate via the LLVM JIT against frozen test vectors.

**Harness discovery.** `_discover_lli_abi_mechanism` at line 362 scans
`irx/experiment1/harness/` and `irx/experiment1/` for files matching a pattern
bundle defined at lines 30-43:

```python
HARNESS_SEARCH_PATTERNS = [
    "lli", "@f", "candidate.bc", "--entry-function", "-entry-function",
    "in_hex", "out_cap", "expected_out_hex", "expected_ret",
    "sum_u32_le", "hex_encode", "parse_u32_decimal",
]
```

A file qualifies as a harness if it references lli, `@f`, `candidate.bc`,
test vector fields, and subprocess execution patterns. Matching files are
sorted alphabetically; the first is chosen. The selected harness is
`irx/experiment1/harness/lli_abi_runner.py` (175 lines).

**lli invocation.** The harness invokes lli with the frozen shim
(`harness/lli_shim/shim.bc`, a 469-line LLVM IR module) linked with
`candidate.bc` as an extra module. Per-vector command (from
`lli_abi_runner.py` lines 117-124):

```
/usr/lib/llvm-19/bin/lli --extra-module=<candidate.bc> <shim.bc> <in_hex> <out_cap> f
```

The shim (line 366) declares `i64 @f(ptr noundef, i32 noundef, ptr noundef,
i32 noundef)`, decodes hex input from argv, calls `@f` (line 90:
`%90 = call i64 @f(...)`), and prints `RET=<signed decimal>` and
`OUT=<lowercase hex>` to stdout.

**Output parsing.** `_parse_shim_stdout` (lines 64-79 of `lli_abi_runner.py`)
extracts `RET=` and `OUT=` lines from stdout. A test passes if
`actual_ret == expected_ret` and `actual_out_hex == expected_out_hex`.
Mismatches yield `RETURN_MISMATCH` or `OUTPUT_MISMATCH`.

**Timeout handling.** Per-test timeout is 50 ms (lines 138-149). On
`TimeoutExpired`, the process group is killed with `SIGKILL` via
`os.killpg`, and the test is recorded as `TIMEOUT`.

The stage passes only if all vectors pass.

### 7.5 Step F: llc_compile

**Implementation:** `_run_llc_compile` at line 961. Compiles bitcode to a
native relocatable object:

```
llc -filetype=obj -mtriple=aarch64-unknown-linux-gnu -O0 \
    -o candidate.o candidate.bc
```

Resolved from `detected.llc.path` (fallback `detected.llvm-llc.path`). The
`-O0` flag keeps compilation fast and deterministic. On exit code 0, the
runner verifies `candidate.o` exists with nonzero size; if absent or empty
despite zero exit, the stage fails with `POLICY_VIOLATION`. For the
known-good candidate: 1008 bytes.

### 7.6 Step G: clang_link

**Implementation:** `_run_clang_link` at line 1063. Links the object into a
freestanding ELF executable:

```
clang -target aarch64-unknown-linux-gnu \
      -fuse-ld=lld \
      -nostdlib \
      -Wl,--no-dynamic-linker \
      -Wl,-e,f \
      -o candidate.exe candidate.o
```

The flags produce a minimal static ELF binary:

- `-nostdlib` — omits all C runtime startup files and standard library linkage
- `-Wl,--no-dynamic-linker` — removes the `PT_INTERP` segment
- `-Wl,-e,f` — sets the ELF entry point to symbol `f`
- `-fuse-ld=lld` — selects the LLVM linker for deterministic output

The result contains only the candidate's code with `f` as the sole function
and entry point. No C runtime, no dynamic linker, no library dependencies.
For the known-good candidate: 2304 bytes.

### 7.7 Step H: native_tests

**Implementation:** `_run_native_tests` at line 1321. Executes test vectors
against the linked executable using a custom in-process ELF loader.

**Harness build.** `_ensure_native_harness_built` at line 1181 compiles
`harness/native/native_runner.c` (421 lines) using the frozen clang path with
flags `-O2 -Wall -Wextra -Werror -std=c11 -fno-omit-frame-pointer -fuse-ld=lld`
(lines 1196-1200). The binary is cached at
`irx/experiment1/harness/native/native_runner`. Cache check: if the binary's
mtime >= the source's mtime, the build is skipped (`CACHED`).

**Selftest.** Before any candidate execution, the runner invokes
`native_runner --selftest` (lines 1222-1235) with env `{LC_ALL=C, LANG=C,
TZ=UTC}`. The selftest validates hex encode/decode with three checks: an
8-byte roundtrip (`"0123456789abcdef"`), an empty-string roundtrip, and
odd-length hex rejection. Result is cached per pipeline run.

**Per-vector execution:**

```
native_runner <candidate.exe> <in_hex> <out_cap> f
```

The harness loads the ELF, resolves symbol `f`, calls it, prints
`RET=<decimal>` and `OUT=<hex>`. The runner parses output and builds
per-vector result records identical in structure to lli results. The stage
passes only if all vectors pass.

---

## 8. LOADED_STEP_A Gate Detail

The `LOADED_STEP_A:` prefix is emitted at line 1440 of `phase2_runner.py`
into the `loaded_artifacts_detail` string, which is then prepended to every
gate detail field. The prefix records the relative path of every frozen
artifact loaded during initialization.

**Concrete example** from `gates.parse.detail` in the known-good result JSON:

```json
{
  "gates": {
    "parse": {
      "ok": true,
      "detail": "LOADED_STEP_A:tool_versions=irx/experiment1/env/tool_versions.json;result_schema=irx/experiment1/harness/result_schema.json;constants=irx/experiment1/harness/constants.json;target=irx/experiment1/env/target.json;test_vectors=irx/experiment1/tasks/sum_u32_le/tests.json,irx/experiment1/tasks/hex_encode/tests.json,irx/experiment1/tasks/parse_u32_decimal/tests.json;id_authority_candidate=candidate_id frozen by harness/id_rules.json: sha256(candidate.ll bytes);id_authority_run=run_id frozen by harness/id_rules.json: sha256(candidate_id utf8);id_notes=candidate_id rule from runs evidence: sha256(candidate.ll bytes),run_id rule from runs evidence: sha256(candidate_id_utf8);PRECHECK_PASS:bytes=1232/65536;lines=42/2000;LLVM_AS_PARSE_PASS"
    }
  }
}
```

The full string is semicolon-delimited: artifact paths loaded in Step A,
followed by the stage-specific result suffix. This pattern is identical across
all four gate fields (`gates.parse`, `gates.verify`, `gates.tests`,
`gates.policy`), with only the suffix differing per gate.

Run artifacts are not committed to git. To reproduce:

```bash
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/step_f/sum_u32_le_good.ll \
  --task sum_u32_le
python3 -c "
import json, os; from glob import glob
p = sorted(glob('irx/experiment1/runs/*/*.json'), key=os.path.getmtime)[-1]
d = json.load(open(p))
print(d['gates']['parse']['detail'][:200])
"
```

---

## 9. Verdict Computation

The `compute_verdict()` function (line 73 in `phase2_runner.py`) derives a
final verdict from the `runs` array, `metrics` object, and `gates` object.
It returns a `(verdict_str, detail_str)` tuple.

**Decision procedure:**

1. **Identify executed stages** (lines 84-89). A stage counts as "executed"
   if it has a non-null `exit_code`, positive `duration_ms`, or non-null
   `crash`. Gated stages at skeleton defaults are excluded.

2. **Stage failures** (lines 92-94). If any executed stage has `ok=False`:
   return `("FAIL", "STAGE_FAILED:<stage_name>")`.

3. **lli test failures** (lines 97-99). If `metrics.tests_failed > 0`:
   return `("FAIL", "LLI_TESTS_FAILED")`.

4. **Native test failures** (lines 102-104). If
   `metrics.native_tests_failed > 0`: return `("FAIL", "NATIVE_TESTS_FAILED")`.

5. **No execution** (lines 107-108). If no stages executed: return
   `("ERROR", "NO_STAGES_EXECUTED")`.

6. **Full pass** (lines 112-117). If every stage has `ok=True` and both test
   failure counts are zero or absent: return `("PASS", "ALL_STAGES_PASS")`.

7. **Otherwise** (line 119): return `("ERROR", "INDETERMINATE_VERDICT")`.

After computation, `gates.policy.ok` is set to `true` when verdict is PASS,
`false` otherwise (line 1885). The verdict detail is appended to
`gates.policy.detail` (line 1886).

This logic was introduced in commit `8762240` (2026-02-15 23:55 PST),
replacing an earlier implementation where the verdict was unconditionally
`"ERROR"` and `gates.policy.ok` was always `false`. The fix was necessary
because candidates passing all stages were receiving ERROR verdicts. The fix
is covered by 8 unit tests exercising every branch (see Section 13).

---

## 10. Native ELF Loader

The `native_runner.c` (421 lines) implements a minimal ELF64 loader and test
executor in pure C. Its sole dependency is libc — no dlopen, no libelf, no
LLVM runtime. The `load_elf()` function (line 115) performs the following
sequence:

### 10.1 File Mapping

The ELF file is memory-mapped read-only for header parsing (line 134):

```c
uint8_t *fdata = mmap(NULL, file_size, PROT_READ, MAP_PRIVATE, fd, 0);
```

The file descriptor is closed immediately after mapping (line 136). An
`fstat()` check at line 125 ensures the file is at least `sizeof(Elf64_Ehdr)`
bytes.

### 10.2 Header Validation

Five checks at lines 145-156:

1. `memcmp(ehdr->e_ident, ELFMAG, SELFMAG)` — ELF magic (`\x7fELF`)
2. `ehdr->e_ident[EI_CLASS] == ELFCLASS64` — 64-bit
3. `ehdr->e_ident[EI_DATA] == ELFDATA2LSB` — little-endian
4. `ehdr->e_machine == EM_AARCH64` — ARM64
5. `ehdr->e_type == ET_EXEC || ehdr->e_type == ET_DYN` — executable or shared object

### 10.3 Address Span Computation

Scans all `PT_LOAD` segments to find minimum and maximum virtual addresses
(lines 169-176). Both bounds are page-aligned using `sysconf(_SC_PAGESIZE)`:
`vmin` rounded down, `vmax` rounded up (lines 184-185). `map_size = vmax - vmin`.

### 10.4 Region Reservation

Reserves a single contiguous anonymous region at a kernel-chosen address
(lines 189-191):

```c
uint8_t *base = mmap(NULL, map_size, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
```

No `MAP_FIXED` is used. All subsequent address references are rebased:
virtual address `va` in the ELF maps to `base + (va - vmin)`.

### 10.5 Segment Copy

Each `PT_LOAD` segment's file-backed data is copied (lines 198-213):

```c
memcpy(base + (va - vmin), fdata + off, (size_t)fsz);
```

BSS portions (`p_memsz > p_filesz`) are zero-filled with `memset` (line 212).

### 10.6 Instruction Cache Coherence

```c
__builtin___clear_cache((char *)base, (char *)(base + map_size));
```

At line 216. Mandatory on AArch64 where the I-cache and D-cache are not
coherent. Without this call, the CPU could execute stale or garbage
instructions from the I-cache after code was written via the D-cache.

### 10.7 Permission Hardening

A second pass at lines 219-238 applies per-segment `mprotect` calls. Segment
VA and size are page-aligned before the call. Code segments (`PF_X`) become
`PROT_READ|PROT_EXEC`. Data segments (`PF_W`) become `PROT_READ|PROT_WRITE`.
Read-only data becomes `PROT_READ` only.

### 10.8 Relocation Rejection

Section headers are scanned for `SHT_RELA` and `SHT_REL` at lines 241-252.
If any non-empty relocation section exists, the loader rejects the binary.
This is a fail-closed safety check: freestanding candidates from Step G use
only PC-relative addressing and contain no relocations.

### 10.9 Symbol Resolution

Searches `.symtab` (not `.dynsym`) for an `STT_FUNC` symbol matching the
requested name (lines 260-282). Function pointer:
`base + (syms[j].st_value - vmin)`. Only the first `.symtab` is processed.
Fallback (line 286): if the requested symbol is `"f"` and `e_entry != 0`, use
the ELF entry point.

### 10.10 Invocation

The resolved pointer is cast to the candidate function type (line 32):

```c
typedef int64_t (*candidate_fn)(uint8_t *, int32_t, uint8_t *, int32_t);
```

And called directly at lines 393-397. Output: `RET=<signed decimal>` and
`OUT=<lowercase hex>` on stdout. Exit code 0 for all semantic results;
nonzero only for harness usage errors.

### 10.11 Design Rationale

The loader rebases all addresses relative to an anonymous region instead of
using `MAP_FIXED` at ELF-specified addresses. This avoids conflicts with the
loader's own address space. It works because freestanding candidates contain
no absolute-address relocations — only PC-relative code. The relocation
rejection check (Section 10.8) is the safety net: if a candidate contained
relocations, the rebasing would break it, so the loader refuses to execute.

### 10.12 Selftest

The `--selftest` flag (lines 83-102) validates hex encode/decode with three
checks:

1. Roundtrip `"0123456789abcdef"` — decode to 8 bytes, re-encode, verify match
2. Empty-string roundtrip — 0 bytes decoded and encoded
3. Odd-length rejection — `"abc"` must return -1

The runner invokes selftest on first use per pipeline run and caches the
result.

---

## 11. Result JSON Structure (shape, not literal JSON)

The result object is assembled at lines 1888-1903 of `phase2_runner.py` and
validated against the frozen schema at line 1905 before being written to disk
at line 1906.

The following is a schematic shape of the known-good result (candidate
`de4997...`, run `4254c6...`, verdict PASS). Keys are unquoted for
readability; `timestamps` values are ISO 8601 UTC strings.

```
{
  experiment: "1"
  task: "sum_u32_le"
  candidate_id: "de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6"
  run_id: "4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60"
  timestamps: { started_at, finished_at }
  gates:
    parse:   { ok: true, detail: "LOADED_STEP_A:...;PRECHECK_PASS:...;LLVM_AS_PARSE_PASS" }
    verify:  { ok: true, detail: "LOADED_STEP_A:...;OPT_VERIFY_PASS" }
    policy:  { ok: true, detail: "LOADED_STEP_A:...;LLC_COMPILE_PASS;CLANG_LINK_PASS;NATIVE_TESTS_PASS:...;verdict=ALL_STAGES_PASS" }
    tests:   { ok: true, detail: "LOADED_STEP_A:...;LLI_TESTS_PASS:..." }
  runs: [7 stages, all ok=true, exit_code=0 except precheck which has exit_code=null]
  metrics:
    tests_total: 10, tests_passed: 10, tests_failed: 0
    ret_mismatches: 0, output_mismatches: 0, timeouts: 0, crashes: 0
    native_tests_total: 10, native_tests_passed: 10, native_tests_failed: 0
    native_ret_mismatches: 0, native_output_mismatches: 0, native_timeouts: 0, native_crashes: 0
  test_results: [10 entries, all outcome=PASS]
  native_test_results: [10 entries, all outcome=PASS]
  verdict: "PASS"
}
```

Every `test_results[i]` and `native_test_results[i]` entry contains:
`index`, `in_hex`, `out_cap`, `expected_ret`, `expected_out_hex`,
`actual_ret`, `actual_out_hex`, `outcome`, `exit_code` (0), `signal` (null),
`detail` (null). For the known-good candidate, `actual_ret == expected_ret`
and `actual_out_hex == expected_out_hex` for all 10 vectors in both arrays.

---

## 12. Regression Sweep

A three-task regression sweep was executed on 2026-02-16 at HEAD `8563fd2`
(timestamp `2026-02-16T08:34:39Z`, explicit in log line 3). The sweep ran the
full A-H pipeline for each task, validated every result JSON against the
schema, and compared verdicts against expectations.

Evidence log:
`irx/experiment1/verification/evidence/logs/regression_sweep_20260216_003439.log`.

### 12.1 sum_u32_le — PASS (expected PASS)

All seven stages pass. Both lli and native produce bitwise-identical results
across all 10 vectors.

| Stage | ok | exit_code |
|-------|-----|-----------|
| precheck | true | — |
| llvm_as_parse | true | 0 |
| opt_verify | true | 0 |
| lli_tests | true | 0 |
| llc_compile | true | 0 |
| clang_link | true | 0 |
| native_tests | true | 0 |

- lli: 10/10 passed, 0 failed
- native: 10/10 passed, 0 failed
- lli/native match: all 10 agree
- verdict: PASS, gates.policy.ok: true
- schema validation: OK
- Artifacts: candidate.bc (1928 B), candidate.o (1008 B), candidate.exe (2304 B)

### 12.2 hex_encode — FAIL (expected FAIL)

The sum_u32_le candidate run as a stub against hex_encode vectors. Steps B-D
pass (structurally valid IR). Step E: all 10 vectors fail (function computes
sums, not hex encoding). Steps F-H gated out.

| Stage | ok | exit_code |
|-------|-----|-----------|
| precheck | true | — |
| llvm_as_parse | true | 0 |
| opt_verify | true | 0 |
| lli_tests | false | 1 |
| llc_compile | false | — |
| clang_link | false | — |
| native_tests | false | — |

- lli: 0/10 passed, 10 failed
- verdict: FAIL, gates.policy.ok: false, schema: OK

### 12.3 parse_u32_decimal — FAIL (expected FAIL)

Same stub candidate. Steps B-D pass. Step E: 8 of 10 fail. Two pass by
coincidence (input/output pairs where sum result happens to match parse
expectations). Steps F-H gated out.

| Stage | ok | exit_code |
|-------|-----|-----------|
| precheck | true | — |
| llvm_as_parse | true | 0 |
| opt_verify | true | 0 |
| lli_tests | false | 1 |
| llc_compile | false | — |
| clang_link | false | — |
| native_tests | false | — |

- lli: 2/10 passed, 8 failed
- verdict: FAIL, gates.policy.ok: false, schema: OK

### 12.4 Conclusions

All three artifacts pass schema validation. Verdict computation correctly
yields PASS for the correct candidate on its own task and FAIL for the wrong
candidate on a different task. Gating prevents native compilation and
execution of candidates that fail interpretation.

---

## 13. Unit Tests

Two hermetic test suites validate runner internals without requiring LLVM
tools. All tests use mocks and synthetic data.

### 13.1 test_native_tests.py (140 lines, 13 tests)

**TestParseNativeRunnerOutput** (lines 25-82, 8 tests):
- `test_ok_with_ret_and_out` — standard output parsing
- `test_negative_ret_empty_out` — negative return, empty output
- `test_missing_ret_line` — absent RET= line
- `test_missing_out_line_defaults_empty` — absent OUT= line defaults to ""
- `test_invalid_ret_format` — non-integer RET= value
- `test_empty_stdout` — completely empty stdout
- `test_err_internal_ret` — ERR_INTERNAL return code (-3)
- `test_out_hex_uppercase_normalized` — uppercase hex normalized to lowercase

**TestResolveNativeHarnessSource** (lines 84-91, 1 test):
- `test_missing_source_returns_none` — nonexistent harness source

**TestNativeTestsGating** (lines 94-116, 3 tests):
- `test_runs_skeleton_has_native_tests_stage` — stage 7 exists in skeleton
- `test_gate_requires_all_prior_stages` — all 6 upstream stages required
- `test_gate_requires_candidate_exe` — executable file must exist

**TestNativeTestsNotRunWhenHarnessMissing** (lines 128-136, 1 test):
- `test_marks_not_run` — missing harness yields NOT_RUN

### 13.2 test_verdict.py (200 lines, 8 tests)

**TestComputeVerdictPass** (lines 66-100, 2 tests):
- `test_all_pass` — all 7 stages pass, both test arrays clean -> PASS
- `test_pass_without_native` — pass without native metrics present -> PASS

**TestComputeVerdictFailStage** (lines 103-122, 2 tests):
- `test_stage_failed` — single failed stage -> FAIL
- `test_first_stage_failed` — precheck failure -> FAIL

**TestComputeVerdictFailLliTests** (lines 125-135, 1 test):
- `test_lli_tests_failed` — lli failures > 0 -> FAIL

**TestComputeVerdictFailNativeTests** (lines 138-148, 1 test):
- `test_native_tests_failed` — native failures > 0 -> FAIL

**TestComputeVerdictError** (lines 151-169, 1 test):
- `test_no_stages_executed` — empty execution -> ERROR

**TestComputeVerdictNotRunDownstream** (lines 172-196, 1 test):
- `test_partial_execution_with_failure` — partial execution with upstream failure -> FAIL

**Current status:** All 21 tests pass (13 + 8) in 0.004s.

---

## 14. Evidence Logs

All pipeline evidence is stored under
`irx/experiment1/verification/evidence/logs/`. Four logs exist:

| Log file | Date | HEAD | Content |
|----------|------|------|---------|
| `step_h_check_20260215_234036.log` | 2026-02-15 | `a5d84da` (inferred) | Step H evidence run (pre-closure), 7/7 stages PASS, 10/10 lli, 10/10 native, all 10 agree |
| `step_h_check_verdictfix_20260215_235338.log` | 2026-02-15 | `f02c049` (inferred) | Run with uncommitted verdict fix, identical stage results |
| `step_h_check_verdictfix_20260216_000503.log` | 2026-02-16 | `b00ab95` (inferred) | Full proof chain: verdict PASS, ID match, artifact sizes |
| `regression_sweep_20260216_003439.log` | 2026-02-16 | `8563fd2` (explicit, line 3) | Three-task regression sweep, all verdicts correct |

Each evidence log records: runner exit code, tool environment variables
(`LD_LIBRARY_PATH`), candidate_id and run_id, per-stage ok/exit_code, lli
and native test counts, artifact file sizes, and lli/native agreement.

The proof-chain log (`step_h_check_verdictfix_20260216_000503.log`) includes
additional verification: the result JSON path, verdict field extraction
(`"verdict": "PASS"` at line 366 of the result JSON), candidate_id and run_id
match confirmation (both `True`), and `ls -l` of all work artifacts:

```
candidate.bc  1928 bytes
candidate.o   1008 bytes
candidate.exe 2304 bytes
```

---

## 15. Evidence Scripts

Two bash scripts automate reproducible evidence collection.

### 15.1 step_h_check.sh (88 lines)

`irx/experiment1/verification/evidence/step_h_check.sh`

Workflow:
1. Resolve repository root and candidate/runner paths
2. Clean previous run artifacts (`rm -rf runs/*`)
3. Python syntax check (`py_compile`)
4. Run full A-H pipeline on the known-good candidate
5. Extract tool environment lines from stderr
6. Locate result JSON from stdout
7. Print summary: per-stage ok/exit_code, lli and native test counts,
   artifact sizes (candidate.o, candidate.exe)
8. Verify lli/native result agreement across all vectors

### 15.2 step_f_check.sh (65 lines)

`irx/experiment1/verification/evidence/step_f_check.sh`

Same structure as step_h_check.sh but scoped to A-F stages. Omits native
summary, candidate.exe check, and lli/native agreement verification.

---

## 16. Phase 2 Closure Record

`irx/experiment1/PHASE2_CLOSURE.md` (153 lines), committed at `5201dd2`
(2026-02-15 23:41 PST) alongside the first Step H evidence log.

**Closure statement:** Phase 2 complete through Step H: PASS.

**Platform snapshot:** Raspberry Pi 5, Cortex-A76, Raspberry Pi OS 64-bit,
kernel 6.12.47+rpt-rpi-2712, LLVM 19.1.7, target `aarch64-unknown-linux-gnu`.
HEAD at closure: `a5d84da`.

**Stage results:** All seven stages ok=true. Precheck:
`bytes=1232/65536, lines=42/2000`. lli: 10/10. native: 10/10. Artifact sizes:
candidate.o 1008 bytes, candidate.exe 2304 bytes.

**lli/native agreement:** All 10 test vectors produce identical `actual_ret`,
`actual_out_hex`, and `outcome` between lli and native execution.

**Authority revision note:** Documents the t08 endianness correction
(`"fffffffe"` -> `"feffffff"` in commit `31223ce`).

**Known issue at closure:** The closure record documents that the verdict
field was `"ERROR"` despite all stages passing (pre-`8762240` behavior). This
was fixed in `8762240` (compute_verdict implementation) 14 minutes after
closure.

---

## 17. Verification Notes

### 17.1 Evidence Log HEAD Inference

**`regression_sweep_20260216_003439.log`**: HEAD `8563fd2` is explicit on
line 3 of the log (`HEAD: 8563fd275f8e73d58ad2ced6b507e1cc4b155da9`). This is
the only log with an explicit HEAD.

**`step_h_check_20260215_234036.log`**: No explicit HEAD. File mtime
23:40:37 PST. Commit `a5d84da` authored 23:32:47, next commit `5201dd2`
at 23:41:34. The log was produced at HEAD `a5d84da` — a pre-closure run.

**`step_h_check_verdictfix_20260215_235338.log`**: No explicit HEAD. File
mtime 23:53:39 PST. Last committed HEAD: `f02c049` (23:46:37). The
uncommitted verdict fix (which became `8762240` at 23:55:22) was in the
working tree but not yet committed.

**`step_h_check_verdictfix_20260216_000503.log`**: No explicit HEAD. File
mtime 00:05:05 PST. Last committed HEAD: `b00ab95` (00:00:28). Next commit
`ef34058` at 00:17:03.

### 17.2 ABI Consistency (Resolved)

The `signature_ir` field in `constants.json` and all three `spec.json` files
previously contained a stale `i32` return type from an earlier draft. This was
corrected to `i64` in commit `b5be4f7` to match the authoritative ABI used by
every executable component (see Section 4.3.1 evidence table). The runner
never reads `signature_ir` at runtime, so no behavior was affected — the fix
was purely documentary consistency. All nine source locations now agree on
`i64`.

### 17.3 Schema Extension Verification

The result schema extension for native metrics (`native_test_results` array
and seven `native_*` counters) was confirmed as part of commit `a5d84da`
(the Step H commit) via `git show a5d84da --stat` showing
`irx/experiment1/harness/result_schema.json | 34 ++`. Three total commits
touch the schema file: `681a6cd` (initial), `21d8c5a` (Phase 1), `a5d84da`
(Step H extension).

---

## 18. Reproduction

From the repository root on any `aarch64-linux-gnu` system with LLVM 19:

```bash
# Full A-H pipeline
rm -rf irx/experiment1/runs/*
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/step_f/sum_u32_le_good.ll \
  --task sum_u32_le

# Schema validation
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

# Evidence checks
rm -rf irx/experiment1/runs/*
bash irx/experiment1/verification/evidence/step_h_check.sh

rm -rf irx/experiment1/runs/*
bash irx/experiment1/verification/evidence/step_f_check.sh

# Unit tests (hermetic, no LLVM required)
python3 -m unittest runner/phase2/tests/test_native_tests.py
python3 -m unittest runner/phase2/tests/test_verdict.py
```

**Expected results:** verdict PASS, lli 10/10, native 10/10, all 10 agree,
all seven stages ok, schema validates. Artifacts: candidate.bc 1928 B,
candidate.o 1008 B, candidate.exe 2304 B. Unit tests: 21/21 pass.

---

## 19. File Inventory

| File | Lines | Role |
|------|-------|------|
| `runner/phase2/phase2_runner.py` | 1972 | Main pipeline runner |
| `irx/experiment1/harness/native/native_runner.c` | 421 | Custom ELF64 loader and test executor |
| `irx/experiment1/harness/result_schema.json` | 301 | JSON Schema (draft 2020-12) for result artifacts |
| `irx/experiment1/harness/lli_abi_runner.py` | 175 | lli ABI harness (subprocess invocation, output parsing) |
| `irx/experiment1/harness/lli_shim/shim.ll` | 469 | LLVM IR shim for lli execution (hex I/O, @f dispatch) |
| `runner/phase2/tests/test_verdict.py` | 200 | Verdict computation unit tests (8 tests) |
| `runner/phase2/tests/test_native_tests.py` | 140 | Native test parsing unit tests (13 tests) |
| `irx/experiment1/PHASE2_CLOSURE.md` | 153 | Phase 2 closure record |
| `irx/experiment1/verification/evidence/step_h_check.sh` | 88 | Step H evidence collection script |
| `irx/experiment1/verification/evidence/step_f_check.sh` | 65 | Step F evidence collection script |
| `irx/experiment1/verification/step_f/sum_u32_le_good.ll` | 42 | Known-good candidate |
| `irx/experiment1/harness/constants.json` | 36 | Frozen constants, ABI, limits, crash taxonomy |
| `irx/experiment1/env/tool_versions.json` | — | Frozen LLVM tool paths and versions |
| `irx/experiment1/env/target.json` | — | Frozen compilation target |
| `irx/experiment1/harness/id_rules.json` | 10 | Frozen ID derivation rules |
| `irx/experiment1/tasks/sum_u32_le/{spec,tests}.json` | — | Task specification and 10 test vectors |
| `irx/experiment1/tasks/hex_encode/{spec,tests}.json` | — | Task specification and 10 test vectors |
| `irx/experiment1/tasks/parse_u32_decimal/{spec,tests}.json` | — | Task specification and 10 test vectors |

---

*Report generated 2026-02-16 on Raspberry Pi 5. HEAD at time of writing: `b5be4f7`. All 21 unit tests pass. All `signature_ir` fields consistent at `i64`.*
