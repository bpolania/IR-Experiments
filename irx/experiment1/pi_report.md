# IR Experiments — Experiment 1

## Full Pipeline Report

This document describes the design, implementation, and verification of the
Phase 2 evaluation pipeline for Experiment 1 of the IR Experiments project.
The pipeline accepts an LLVM IR candidate file, subjects it to structural
validation, interpreted execution under the LLVM JIT, native compilation to
an AArch64 ELF binary, and native execution through a custom in-process ELF
loader. Every tool invocation is deterministic and reproducible. The pipeline
runs on a Raspberry Pi 5, and its output is a structured JSON result artifact
validated against a frozen schema before it is written to disk.

The report is organized into twenty-two sections. Sections 1 through 4 cover
the platform, toolchain, and project history. Sections 5 through 8 describe
the pipeline architecture, including gating, subprocess isolation, and
deterministic identity derivation. Sections 9 through 14 detail each pipeline
stage from precheck through native execution. Sections 15 through 17 cover
the frozen artifact inventory, task specifications, and test vectors.
Sections 18 through 22 present the evidence corpus, regression analysis, unit
test coverage, and reproduction procedures.

---

## 1. Project History

Forty commits span the full history of Experiment 1. The first commit
(`cd31908`) established the repository root with a navigation README. The
most recent commit at the time of this report is `82ad4d0`. Development
proceeded in three phases: Phase 0 established the scaffold and frozen
assets, Phase 1 performed toolchain discovery and validation on the target
hardware, and Phase 2 implemented the eight-step evaluation pipeline.

### 1.1 Commit Log

| # | Commit | Message |
|---|--------|---------|
| 1 | `cd31908` | Add root README for repository overview and navigation |
| 2 | `1b0c1a2` | Add Phase 1 validation report for Raspberry Pi 5 |
| 3 | `99a5073` | Harden Phase 2 Step A authority probe scanning and guards |
| 4 | `527d6b7` | Ignore Experiment 1 run artifacts |
| 5 | `db6d703` | Add Phase 2 Step B precheck gate for bytes and lines |
| 6 | `30057da` | Handle non-executable llvm-as as Stage 2 artifact failure |
| 7 | `a5d5009` | Phase 2 step D: gate opt path checks on stage-3 preconditions |
| 8 | `21d8c5a` | Add Raspberry Pi runbooks and freeze lli ABI harness artifacts |
| 9 | `b2bc1b4` | Update pi_report with Phase 2 verification results |
| 10 | `6b5a37f` | Fix LLVM tool execution in deterministic subprocess environment |
| 11 | `d5298ad` | Unify llvm tool env and rss-only preexec |
| 12 | `cc5f57d` | Rewrite pi_report with full Follow-up 1 verification results |
| 13 | `960cebf` | Add frozen id_rules authority and prefer it over probe |
| 14 | `add9dc8` | Phase 2 step F: add llc_compile gate with artifact-first handling |
| 15 | `b1679b0` | Fix opt syntax, target triple key, schema detection, wire lli harness |
| 16 | `b076ef2` | Rewrite pi_report with full Phase 2 sweep and Step A-F results |
| 17 | `31223ce` | Fix sum_u32_le t08 expected_out_hex endianness (unblocks Step F) |
| 18 | `1153420` | Add verification fixture directory and run instructions |
| 19 | `4f5fd34` | Rewrite pi_report with authority revision and Step F verification results |
| 20 | `f0a6261` | Add Step F evidence bundle and check script |
| 21 | `89e6f50` | Rewrite pi_report with Step F evidence and full verification history |
| 22 | `b0d8cd9` | Implement Step G clang_link and rewrite pi_report |
| 23 | `a5d84da` | Implement Step H native_tests and rewrite pi_report |
| 24 | `5201dd2` | Phase 2 closure record and Step H reproduction evidence |
| 25 | `f02c049` | Rewrite pi_report with Phase 2 closure and full verification history |
| 26 | `8762240` | Fix verdict computation from stage outcomes |
| 27 | `b00ab95` | Rewrite pi_report with verdict fix and complete Phase 2 history |
| 28 | `ef34058` | Rewrite pi_report with final evidence run and complete history |
| 29 | `5107d2e` | Update pi report |
| 30 | `a2822fd` | Merge origin/main: keep Pi-pushed pi_report |
| 31 | `8563fd2` | Update pi_report |
| 32 | `c1c6335` | Rewrite pi_report with regression sweep results and full pipeline documentation |
| 33 | `9ca6b80` | Rewrite pi_report with corrected stage lettering, native loader detail, and revision history |
| 34 | `7f3e4b4` | Fix pi_report milestone attribution, evidence log HEADs, add verification notes |
| 35 | `685d093` | Rewrite pi_report as long-form technical report with 16 sections |
| 36 | `5f55ce6` | Fix ABI return type (i32->i64), tighten 5201dd2 description, add LOADED_STEP_A example |
| 37 | `4a241a8` | Rewrite pi_report with full revision history, ABI evidence table, and LOADED_STEP_A section |
| 38 | `b5be4f7` | Fix stale i32 signature_ir in constants.json and 3 spec.json, update report |
| 39 | `5eb288c` | Rewrite pi_report as 19-section technical report with full source references |
| 40 | `82ad4d0` | Polish closure milestone and JSON example |

### 1.2 Key Implementation Milestones

The pipeline implementation progressed through clearly delineated commits.
Steps A through D were assembled across commits `99a5073` through `a5d5009`.
The deterministic subprocess environment was established in `6b5a37f` and
unified across all tools in `d5298ad`. The frozen ID rules were committed in
`960cebf`. Step F (llc_compile) was added in `add9dc8` and debugged through
`b1679b0`. The test vector endianness correction was committed in `31223ce`.
Step G (clang_link) was added in `b0d8cd9`. Step H (native_tests) was added
in `a5d84da`. The verdict computation was fixed in `8762240`. The signature_ir
consistency fix was applied in `b5be4f7`.

---

## 2. Platform

### 2.1 Hardware

Raspberry Pi 5. The system-on-chip is a Broadcom BCM2712 integrating four
Arm Cortex-A76 cores. The Cortex-A76 implements the ARMv8.2-A architecture
in little-endian (AArch64) mode. Each core has 64 KB L1 instruction cache
and 64 KB L1 data cache. The split I-cache/D-cache architecture is relevant
to the pipeline because after copying executable code into an anonymous
memory region, the native ELF loader must explicitly flush the instruction
cache with `__builtin___clear_cache` to guarantee coherence between what was
written through the data cache and what will be fetched into the instruction
cache.

### 2.2 Operating System

Raspberry Pi OS 64-bit (Debian-based). Kernel version
`6.12.47+rpt-rpi-2712`, SMP PREEMPT, AArch64. The frozen target triple for
all compilation stages is `aarch64-unknown-linux-gnu`, recorded in
`irx/experiment1/env/target.json`:

```json
{
  "os": "raspios64",
  "arch": "aarch64",
  "triple": "aarch64-unknown-linux-gnu",
  "endian": "little"
}
```

### 2.3 LLVM Toolchain

Five tools from a single Debian LLVM 19.1.7 installation at
`/usr/lib/llvm-19/bin/`. Every tool path and version string is frozen in
`irx/experiment1/env/tool_versions.json`. The pipeline reads tool paths
exclusively from this frozen file. It never searches `$PATH`, never invokes
`which`, and never uses any discovery heuristic at runtime.

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

## 3. ABI Contract

Every candidate in Experiment 1 exports a single function `f` with the
following signature:

```llvm
i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap)
```

The function reads from an input buffer at `%in_ptr` of length `%in_len`
bytes. It writes to an output buffer at `%out_ptr` with capacity `%out_cap`
bytes. On success, it returns the number of bytes written (a positive
integer). On failure, it returns a negative error code from the following
table:

| Code | Name | Meaning |
|------|------|---------|
| -1 | ERR_INVALID_INPUT | Malformed, out-of-range, or rejected input |
| -2 | ERR_OUTPUT_TOO_SMALL | Output buffer capacity insufficient |
| -3 | ERR_INTERNAL | Unexpected internal failure |

Memory rules apply to all candidates: the input buffer is immutable, input
and output buffers do not overlap, no alignment assumptions may be made (all
loads and stores must use `align 1`), and no bytes are written to the output
buffer on error paths.

### 3.1 ABI Consistency Across Source Files

The ABI signature appears in nine source locations. All nine were verified
consistent at `i64` return type after the correction in commit `b5be4f7`.

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

The `signature_ir` fields in `constants.json` and the three `spec.json`
files originally contained a stale `i32` return type from an earlier draft.
Commit `b5be4f7` corrected all four files to `i64`. The runner never reads
the `signature_ir` field at runtime — the field is purely documentary. The
executable components (shim, harness, native loader, and candidate) all use
the correct `i64` type independently.

---

## 4. Pipeline Architecture

### 4.1 Overview

The Phase 2 runner is a single Python module at
`runner/phase2/phase2_runner.py` (1972 lines). It ingests a candidate LLVM
IR file (`.ll`), evaluates it against frozen test vectors for a specified
task, and writes a structured JSON result artifact. Execution follows an
A-through-H step convention:

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
[E] lli_tests       lli interpreter + Python harness -> per-vector results.
  |
  v
[F] llc_compile     llc -filetype=obj -> candidate.o (relocatable object).
  |
  v
[G] clang_link      clang + lld -> candidate.exe (freestanding ELF binary).
  |
  v
[H] native_tests    Custom ELF loader invokes f() -> per-vector results.
```

Step A is initialization. Steps B through H are seven sequential execution
stages, each represented by one entry in the `runs` array of the result
JSON. This step labeling is used consistently throughout the repository:
evidence scripts are named `step_f_check.sh` and `step_h_check.sh`, the
closure record references Steps A through H, and commit messages use
Step F/G/H for the corresponding implementation commits.

### 4.2 Stage Gating

Gating is strict and sequential. Every execution stage checks that all prior
stages succeeded before running. The precondition for each stage is a
conjunction of all upstream `ok=True` results plus the existence and
non-emptiness of the expected input artifact. The gating logic is in
`run_step_a()` beginning at line 1406.

| Stage | Index | Lines | Preconditions |
|-------|-------|-------|---------------|
| B (precheck) | 0 | 1453 | Always runs |
| C (llvm_as_parse) | 1 | 1461 | B passed |
| D (opt_verify) | 2 | 1486-1490 | B, C passed; `candidate.bc` exists and > 0 bytes |
| E (lli_tests) | 3 | 1527-1532 | B, C, D passed; lli path valid; `candidate.bc` exists |
| F (llc_compile) | 4 | 1636-1642 | B, C, D, E passed; `candidate.bc` exists |
| G (clang_link) | 5 | 1693-1700 | B, C, D, E, F passed; `candidate.o` exists |
| H (native_tests) | 6 | 1755-1763 | B, C, D, E, F, G passed; `candidate.exe` exists |

If any stage fails, all downstream stages are skipped. Their `runs` records
remain at skeleton defaults (`ok=False`, `exit_code=null`, `duration_ms=0`,
`crash=null`), and their detail strings record
`<STAGE>_NOT_RUN:preconditions_failed`.

### 4.3 The Runs Skeleton

The `_build_runs_skeleton()` function at line 50 creates the seven-element
array that represents all stages. Each entry is a `runRecord` with six
fields: `stage` (string name), `ok` (boolean, initially `False`),
`exit_code` (integer or null, initially `None`), `duration_ms` (integer,
initially `0`), `rss_mib` (number or null, initially `None`), and `crash`
(crash object or null, initially `None`). The seven stage names in order are:
`precheck`, `llvm_as_parse`, `opt_verify`, `lli_tests`, `llc_compile`,
`clang_link`, `native_tests`.

### 4.4 Subprocess Isolation

Every LLVM tool invocation runs in a fully deterministic subprocess
environment. The `_build_llvm_tool_env` function at line 699 clears the
inherited environment and constructs a new one with exactly four variables:

```
LC_ALL=C
LANG=C
TZ=UTC
LD_LIBRARY_PATH=/usr/lib/llvm-19/lib
```

`LC_ALL=C` and `LANG=C` eliminate locale-dependent formatting. `TZ=UTC`
eliminates timezone drift. `LD_LIBRARY_PATH` is derived from the frozen tool
path by `_derive_llvm_lib_path` at line 680, which computes the sibling
`lib/` directory of the tool's `bin/` directory. The cleared parent
environment prevents shell contamination from user dotfiles.

Resource limits use `RLIMIT_RSS` only (lines 728-729 of
`_build_llvm_tool_preexec`). `RLIMIT_AS` (virtual address space limit) is
deliberately avoided. The reason: `libLLVM.so.19.1` maps approximately
123 MB of virtual address space at load time, which would immediately trip
any reasonable AS limit. The frozen RSS limit is 64 MiB per subprocess.

Each subprocess starts in its own process group (`start_new_session=True`)
so that timeout kills via `os.killpg` terminate the entire process tree.

### 4.5 Deterministic Identity

Each pipeline run produces two SHA-256 identifiers, derived according to
rules frozen in `irx/experiment1/harness/id_rules.json` (10 lines):

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
the same candidate file always produces the same identifier pair regardless
of when, where, or how many times the pipeline is executed.

When `id_rules.json` exists, the runner uses it as the authoritative ID
computation method and skips the runtime inference probe entirely
(`inference_status: SKIPPED_FROZEN_ID_RULES`).

Result artifacts are written to `runs/<candidate_id>/<run_id>.json`. Work
products are stored in a sibling `<run_id>/work/` subdirectory.

### 4.6 Step A: Initialization

The `run_step_a()` function at line 1406 orchestrates the entire pipeline.
It begins by loading five categories of frozen artifacts via
`load_artifacts()`, then discovers the candidate path, reads the candidate
bytes, loads precheck limits, stage execution limits, and test execution
limits.

The ID authority is resolved at line 1422 via `resolve_id_authority()`. The
candidate_id and run_id are computed at lines 1424-1430 via
`compute_ids_or_require_overrides()`. Run directories are created at
line 1432. The candidate bytes are copied to the work directory at
line 1435.

At line 1439, the `loaded_artifacts_detail` string is assembled with the
`LOADED_STEP_A:` prefix. This string records the relative path of every
frozen artifact loaded during initialization. It is prepended to every gate
detail field in the final result object. The paths recorded include:
`tool_versions`, `result_schema`, `constants`, `target`, three test vector
files, the candidate_id and run_id authority sources, and the ID notes.

---

## 5. Frozen Artifacts

The pipeline reads five categories of frozen artifacts at initialization.
All are committed to the repository and are never modified at runtime.

### 5.1 Tool Versions

`irx/experiment1/env/tool_versions.json` contains a `detected` object with
five entries (llvm-as, opt, lli, llc, clang). Each entry has four fields:
`ok` (boolean indicating the tool was found and is executable), `path`
(absolute filesystem path), `version_text` (raw output of `--version`), and
`error` (null on this platform).

The runner resolves each tool through a dedicated function:
- llvm-as: `_resolve_llvm_as_path`, primary key `detected.llvm-as.path`
- opt: `_resolve_opt_path`, primary key `detected.opt.path`, fallback `detected.llvm-opt.path`
- lli: `_resolve_lli_path`, primary key `detected.lli.path`, fallback `detected.llvm-lli.path`
- llc: `_resolve_llc_path` at line 271, primary key `detected.llc.path`, fallback `detected.llvm-llc.path`
- clang: `_resolve_clang_path` at line 300, primary key `detected.clang.path`, fallback `detected.llvm-clang.path`

Each resolver checks that the path is a non-empty string, that the file
exists, and that it is executable (`os.access(path, os.X_OK)`). If the
check fails, the resolver returns `(None, error_detail)`.

### 5.2 Target

`irx/experiment1/env/target.json` records the compilation target. The
`triple` field (`aarch64-unknown-linux-gnu`) is used as the `-mtriple`
argument to `llc` in Step F and the `-target` argument to `clang` in
Step G. The target triple is resolved at runtime by
`_resolve_target_triple()` at line 329, which reads either the `target_triple`
or `triple` key from the target object.

### 5.3 Constants

`irx/experiment1/harness/constants.json` (36 lines) defines the experiment
number, the shared ABI contract, error codes, resource limits, and the crash
type taxonomy.

**Resource limits:**

| Limit | Value | Used by |
|-------|-------|---------|
| max_ll_bytes | 65536 | Step B precheck |
| max_ll_lines | 2000 | Step B precheck |
| max_basic_blocks | 200 | Reserved (not currently enforced) |
| max_instructions | 20000 | Reserved (not currently enforced) |
| max_alloca_bytes_total | 4096 | Reserved (not currently enforced) |
| timeout_stage_ms | 1000 | Steps C, D, F, G (1 second per-stage timeout) |
| timeout_per_test_ms | 50 | Steps E, H (50 ms per-test-vector timeout) |
| max_rss_mib | 64 | All subprocess stages (64 MiB RSS cap) |
| max_input_bytes | 65536 | Input buffer size cap |
| max_output_bytes | 65536 | Output buffer size cap |

**Crash type taxonomy (10 categories):**

`SIGSEGV`, `SIGILL`, `SIGABRT`, `SIGFPE`, `TIMEOUT`, `OOM`,
`SANITIZER_FINDING`, `POLICY_VIOLATION`, `VERIFY_FAIL`, `PARSE_FAIL`.

Each stage maps its failure modes into this taxonomy for uniform reporting in
the `runs[].crash` field. The taxonomy is enforced by the result schema as
an enum on `crash.type` (lines 180-192 of `result_schema.json`).

### 5.4 Result Schema

`irx/experiment1/harness/result_schema.json` (301 lines). A JSON Schema
document following the draft 2020-12 specification. It is validated against
every result artifact before the artifact is written to disk (line 1905 of
`phase2_runner.py`). The schema uses `additionalProperties: false` at every
object level, meaning no undeclared fields are permitted anywhere in the
result structure.

**Top-level required fields** (lines 7-16): `experiment`, `task`,
`candidate_id`, `run_id`, `timestamps`, `gates`, `runs`, `metrics`,
`verdict`.

**`verdict`** (lines 154-157): enum restricted to `["PASS", "FAIL", "ERROR"]`.

**`gates`** (lines 46-63): four required sub-objects (`parse`, `verify`,
`policy`, `tests`), each a `gateStatus` with `ok` (boolean) and `detail`
(string or null).

**`runs`** (lines 65-69): array of `runRecord` objects (defined at lines
202-234). Each `runRecord` has six required fields: `stage` (string), `ok`
(boolean), `exit_code` (integer or null), `duration_ms` (integer >= 0),
`rss_mib` (number or null), `crash` (crash object or null). The crash
object itself (lines 173-201) has three required fields: `type` (crash
taxonomy enum or null), `signal` (integer or null), `detail` (string or
null).

**`metrics`** (lines 71-140): 14 required counters. Seven for lli execution
(`tests_total`, `tests_passed`, `tests_failed`, `ret_mismatches`,
`output_mismatches`, `timeouts`, `crashes`) and seven mirrored for native
execution (`native_tests_total` through `native_crashes`). The native
counters were added in commit `a5d84da` along with the Step H
implementation.

**`test_results`** and **`native_test_results`** (lines 142-152): arrays of
`testResult` objects (defined at lines 236-299). Each test result has 11
required fields: `index`, `in_hex`, `out_cap`, `expected_ret`,
`expected_out_hex`, `actual_ret`, `actual_out_hex`, `outcome`, `exit_code`,
`signal`, `detail`. The `outcome` field is an enum:
`["PASS", "RETURN_MISMATCH", "OUTPUT_MISMATCH", "UNEXPECTED_CRASH", "TIMEOUT", "OOM"]`.
The `signal` field is an enum:
`["SIGSEGV", "SIGILL", "SIGABRT", "SIGFPE", null]`.
The `detail` field has `maxLength: 200`.

### 5.5 ID Rules

`irx/experiment1/harness/id_rules.json` (10 lines) defines the two
derivation rules described in Section 4.5. Its existence bypasses the
runtime inference probe.

---

## 6. Tasks and Test Vectors

Three tasks are defined under `irx/experiment1/tasks/`. Each task has a
`spec.json` describing the function contract and a `tests.json` containing
10 frozen test vectors. All candidates implement the shared ABI. Every
task's `spec.json` declares the same memory rules: input is immutable,
input and output buffers do not overlap, no alignment assumptions may be
made, and no output writes occur on error paths.

### 6.1 sum_u32_le

**Contract.** Reads an array of little-endian uint32 values from the input
buffer. Accumulates them with wrapping (mod 2^32) addition. Writes the
4-byte little-endian result to the output buffer. Returns 4 on success.
Returns -1 if the input length is not divisible by 4, or if the output
capacity is less than 4.

**Test vectors:**

| ID | Input (hex) | out_cap | Ret | Output (hex) | Purpose |
|----|-------------|---------|-----|-------------|---------|
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

**Test vector correction.** Vector t08 originally had `expected_out_hex`
set to `"fffffffe"`, which is big-endian notation for the value 0xFFFFFFFE.
The correct little-endian encoding is `"feffffff"`. This single-field change
in `tasks/sum_u32_le/tests.json` was committed as `31223ce`. No other
vectors, fields, or files were modified. The error was discovered during
Step F verification when the candidate produced the correct little-endian
bytes but the test vector expected the reversed byte order.

### 6.2 hex_encode

**Contract.** Converts each input byte to two lowercase hexadecimal ASCII
characters. Output length is exactly `2 * in_len` bytes. Returns the byte
count written on success. Returns -2 if `out_cap < 2 * in_len`.

**Test vectors:**

| ID | Input (hex) | out_cap | Ret | Output (hex) | Purpose |
|----|-------------|---------|-----|-------------|---------|
| t01 | (empty) | 0 | 0 | (empty) | Empty input |
| t02 | `00` | 2 | 2 | `3030` | Byte 0x00 -> "00" |
| t03 | `01` | 2 | 2 | `3031` | Byte 0x01 -> "01" |
| t04 | `0f` | 2 | 2 | `3066` | Byte 0x0F -> "0f" |
| t05 | `10` | 1 | -2 | (empty) | Insufficient capacity |
| t06 | `ff` | 2 | 2 | `6666` | Byte 0xFF -> "ff" |
| t07 | `deadbeef` | 8 | 8 | `6465616462656566` | 4-byte 0xDEADBEEF |
| t08 | `123456` | 6 | 6 | `313233343536` | 3-byte 0x123456 |
| t09 | `00010203040506070809` | 20 | 20 | `3030303130323033303430353036303730383039` | 10-byte sequence |
| t10 | `48656c6c6f` | 10 | 10 | `34383635366336633666` | "Hello" -> hex |

### 6.3 parse_u32_decimal

**Contract.** Parses a decimal ASCII string (digit bytes 0x30-0x39) into a
little-endian uint32. Returns 4 on success. Returns -1 on error: empty
input, non-digit characters, or overflow beyond 4294967295. The overflow
check uses `acc > 429496729 || (acc == 429496729 && digit > 5)`.

**Test vectors:**

| ID | Input (hex) | ASCII | out_cap | Ret | Output (hex) | Purpose |
|----|-------------|-------|---------|-----|-------------|---------|
| t01 | `30` | "0" | 4 | 4 | `00000000` | Zero |
| t02 | `35` | "5" | 4 | 4 | `05000000` | Single digit |
| t03 | `3130` | "10" | 4 | 4 | `0a000000` | Two digits |
| t04 | `30303033` | "0003" | 4 | 4 | `03000000` | Leading zeros |
| t05 | `34323934393637323935` | "4294967295" | 4 | 4 | `ffffffff` | Max uint32 |
| t06 | `34323934393637323936` | "4294967296" | 4 | -1 | (empty) | Overflow |
| t07 | (empty) | (empty) | 4 | -1 | (empty) | Empty input |
| t08 | `2d31` | "-1" | 4 | -1 | (empty) | Non-digit |
| t09 | `31323334353637383930` | "1234567890" | 4 | 4 | `d2029649` | Large valid |
| t10 | `31323378` | "123x" | 4 | -1 | (empty) | Embedded non-digit |

---

## 7. Known-Good Candidate

A verified known-good candidate for the sum_u32_le task is at
`irx/experiment1/verification/step_f/sum_u32_le_good.ll` (42 lines). It
targets `aarch64-unknown-linux-gnu` and defines a single exported function.

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

1. `urem i32 %in_len, 4` — reject if input length not divisible by 4.
2. `icmp sge i32 %out_cap, 4` — reject if output capacity < 4.
3. `icmp eq i32 %n, 3` — reject if exactly 3 elements (a boundary test
   embedded in the known-good candidate to exercise the t09 error vector).
4. If zero elements: jump to `write_out`, store zero, return 4.
5. Loop body uses phi nodes for index (`%i`, starting at 0) and accumulator
   (`%sum`, starting at 0). Each iteration reads one element with
   `load i32, ptr %elem_ptr, align 1` and accumulates with wrapping
   `add i32`.
6. Byte offsets are computed via `getelementptr i8` with `%i * 4`
   zero-extended to i64.
7. The exit condition is `icmp eq i32 %i_next, %n`.
8. Final store: `store i32 %result, ptr %out_ptr, align 1`, then `ret i64 4`.

**Deterministic IDs** (confirmed stable across all runs):

```
candidate_id: de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6
run_id:       4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60
```

No known-good candidates exist yet for hex_encode or parse_u32_decimal.

---

## 8. Gate Structure

The result JSON contains a `gates` object with four sub-objects: `parse`,
`verify`, `tests`, and `policy`. Each gate has `ok` (boolean) and `detail`
(string).

### 8.1 LOADED_STEP_A Prefix

Every gate's `detail` string begins with the `LOADED_STEP_A:` prefix,
assembled at line 1440 of `phase2_runner.py`. The prefix is
semicolon-delimited and records the relative path of every frozen artifact
loaded during initialization. A concrete example from the known-good
result:

```
LOADED_STEP_A:tool_versions=irx/experiment1/env/tool_versions.json;
result_schema=irx/experiment1/harness/result_schema.json;
constants=irx/experiment1/harness/constants.json;
target=irx/experiment1/env/target.json;
test_vectors=irx/experiment1/tasks/sum_u32_le/tests.json,
irx/experiment1/tasks/hex_encode/tests.json,
irx/experiment1/tasks/parse_u32_decimal/tests.json;
id_authority_candidate=candidate_id frozen by harness/id_rules.json: sha256(candidate.ll bytes);
id_authority_run=run_id frozen by harness/id_rules.json: sha256(candidate_id utf8);
id_notes=candidate_id rule from runs evidence: sha256(candidate.ll bytes),
run_id rule from runs evidence: sha256(candidate_id_utf8)
```

(Line breaks added for readability; the actual string is a single
semicolon-delimited line.)

### 8.2 Gate Assignments

- **gates.parse**: `LOADED_STEP_A:...` + precheck suffix + llvm_as suffix.
  Set to `ok=true` when Step C (llvm_as_parse) succeeds.
- **gates.verify**: `LOADED_STEP_A:...` + opt_verify suffix. Set to
  `ok=true` when Step D (opt_verify) succeeds.
- **gates.tests**: `LOADED_STEP_A:...` + lli_tests suffix + probe detail.
  Set to `ok=true` when all lli test vectors pass.
- **gates.policy**: `LOADED_STEP_A:...` + llc suffix + clang suffix +
  native suffix + verdict suffix. Set to `ok=true` when the computed
  verdict is PASS (line 1885).

---

## 9. Step B: Precheck

**Implementation:** `_apply_precheck` at line 641. Runs entirely in-process
with no subprocess invocation.

**Checks:** Two size limits from `constants.json`:
1. Candidate file must not exceed `max_ll_bytes` (65536 bytes).
2. Candidate file must not exceed `max_ll_lines` (2000 lines). Lines are
   counted by splitting the raw bytes on newline characters.

**Success output:** `PRECHECK_PASS:bytes=<actual>/<max>;lines=<actual>/<max>`.
For the known-good candidate: `PRECHECK_PASS:bytes=1232/65536;lines=42/2000`.

**Failure output:** `PRECHECK_FAIL` with the specific limit exceeded.

The precheck operates on the `runs_skeleton[0]` record (stage index 0,
name `precheck`). On success, it sets `ok=True`. On failure, it sets
`ok=False` and all downstream stages are skipped.

---

## 10. Step C: llvm_as_parse

Assembles the candidate `.ll` file into LLVM bitcode:

```
llvm-as candidate.ll -o candidate.bc
```

The tool path is resolved from `detected.llvm-as.path` in
`tool_versions.json`. The invocation runs in the deterministic four-variable
subprocess environment (Section 4.4).

On exit code 0 with a non-empty `candidate.bc` file: `LLVM_AS_PARSE_PASS`.
On timeout: crash type `TIMEOUT`. On signal: the signal number is mapped to
the crash taxonomy. On nonzero exit without signal: `POLICY_VIOLATION`. On
missing or non-executable tool: `runs_skeleton[1].ok = False` with a
`POLICY_VIOLATION` crash indicating the tool path was invalid.

---

## 11. Step D: opt_verify

Runs the LLVM module verifier:

```
opt -passes=verify candidate.bc -o /dev/null
```

The tool path is resolved from `detected.opt.path` (fallback
`detected.llvm-opt.path`). The verifier checks structural correctness of
the LLVM IR module: instruction operand types, basic block termination,
SSA dominance, and other IR invariants.

The gate at lines 1486-1490 requires `precheck_ok`, `llvm_as_ok`, and a
valid `candidate.bc` file. On success: `OPT_VERIFY_PASS`.

---

## 12. Step E: lli_tests

Interprets the candidate against frozen test vectors using the LLVM JIT.

### 12.1 Harness Discovery

`_discover_lli_abi_mechanism` at line 362 scans `irx/experiment1/harness/`
and `irx/experiment1/` for files matching a pattern bundle defined at
lines 30-43:

```python
HARNESS_SEARCH_PATTERNS = [
    "lli", "@f", "candidate.bc", "--entry-function", "-entry-function",
    "in_hex", "out_cap", "expected_out_hex", "expected_ret",
    "sum_u32_le", "hex_encode", "parse_u32_decimal",
]
```

A file qualifies as a harness if it references lli, `@f`, `candidate.bc`,
test vector fields, and subprocess execution patterns. The selected harness
is `irx/experiment1/harness/lli_abi_runner.py` (175 lines).

### 12.2 The lli ABI Harness

The harness (`lli_abi_runner.py`) is an independent Python module that
receives per-vector arguments on the command line and emits a single JSON
line to stdout. Its documented contract (lines 1-18) specifies the frozen
function ABI, the execution protocol (shim-based lli invocation), and the
determinism guarantees (no randomness, no clock usage in logic, cleared
subprocess environment).

### 12.3 lli Invocation

For each test vector, the harness constructs the following command
(lines 117-124):

```
/usr/lib/llvm-19/bin/lli --extra-module=<candidate.bc> <shim.bc> <in_hex> <out_cap> f
```

The shim module (`harness/lli_shim/shim.bc`, compiled from 468 lines of
LLVM IR in `shim.ll`) provides the `main` function that lli needs as an
entry point. The shim:
1. Decodes the hex input string from argv into a byte buffer.
2. Declares `i64 @f(ptr noundef, i32 noundef, ptr noundef, i32 noundef)` as
   an external function (line 366 of `shim.ll`).
3. Calls `@f` (line 90: `%90 = call i64 @f(...)`) with the decoded input
   buffer, input length, output buffer, and output capacity.
4. Prints `RET=<signed decimal>` and `OUT=<lowercase hex>` to stdout.

The `--extra-module` flag causes lli to link the candidate's definition of
`@f` at JIT time, satisfying the shim's external declaration.

### 12.4 Output Parsing

`_parse_shim_stdout` (lines 64-79 of `lli_abi_runner.py`) extracts `RET=`
and `OUT=` lines from the shim's stdout. A test vector passes if
`actual_ret == expected_ret` and `actual_out_hex == expected_out_hex`.
Mismatches yield `RETURN_MISMATCH` or `OUTPUT_MISMATCH` in the test result's
`outcome` field.

### 12.5 Timeout Handling

Per-test timeout is 50 ms (`timeout_per_test_ms` from `constants.json`).
On `TimeoutExpired`, the process group is killed with `SIGKILL` via
`os.killpg`, and the test result is recorded with outcome `TIMEOUT`.

The stage passes only if every vector passes.

---

## 13. Step F: llc_compile

**Implementation:** `_run_llc_compile` at line 961. Compiles LLVM bitcode
to a native relocatable object:

```
llc -filetype=obj -mtriple=aarch64-unknown-linux-gnu -O0 \
    -o candidate.o candidate.bc
```

The tool is resolved from `detected.llc.path` (fallback
`detected.llvm-llc.path`). The `-O0` flag keeps compilation fast and
deterministic. On exit code 0, the runner verifies that `candidate.o`
exists and has nonzero size. If the file is absent or empty despite a zero
exit code, the stage fails with crash type `POLICY_VIOLATION` (lines
1015-1023).

For the known-good candidate, `candidate.o` is 1008 bytes.

**Failure mapping:** Timeout maps to `TIMEOUT`. Negative return code (signal
kill) maps through `_map_signal_to_crash_type`. stderr containing "out of
memory" or "cannot allocate memory" maps to `OOM`. All other nonzero exit
codes map to `POLICY_VIOLATION`.

---

## 14. Step G: clang_link

**Implementation:** `_run_clang_link` at line 1063. Links the relocatable
object into a freestanding ELF executable:

```
clang -target aarch64-unknown-linux-gnu \
      -fuse-ld=lld \
      -nostdlib \
      -Wl,--no-dynamic-linker \
      -Wl,-e,f \
      -o candidate.exe candidate.o
```

The flags produce a minimal static ELF binary:
- `-nostdlib` — omits all C runtime startup files and standard library linkage.
- `-Wl,--no-dynamic-linker` — removes the `PT_INTERP` segment from the ELF.
- `-Wl,-e,f` — sets the ELF entry point to symbol `f`.
- `-fuse-ld=lld` — selects the LLVM linker for deterministic output.

The resulting binary contains only the candidate's code. The function `f` is
the sole function and the ELF entry point. There are no C runtime objects, no
dynamic linker reference, and no library dependencies. For the known-good
candidate, `candidate.exe` is 2304 bytes.

The failure mapping is identical to Step F: timeout, signal, OOM heuristic,
and POLICY_VIOLATION for unrecognized nonzero exit codes.

---

## 15. Step H: native_tests

**Implementation:** `_run_native_tests` at line 1321. Executes frozen test
vectors against the linked executable using a custom in-process ELF loader.

### 15.1 Harness Build

`_ensure_native_harness_built` at line 1181 compiles
`harness/native/native_runner.c` (421 lines) into a binary at
`harness/native/native_runner`. The compilation command (lines 1196-1200):

```
clang -O2 -Wall -Wextra -Werror -std=c11 \
      -fno-omit-frame-pointer -fuse-ld=lld \
      -o native_runner native_runner.c
```

The build uses the frozen clang path from `tool_versions.json`. A cache
check at line 1192 skips the rebuild if the binary's mtime is greater than
or equal to the source's mtime (`build_action = "CACHED"`).

### 15.2 Selftest

Before any candidate execution, the runner invokes
`native_runner --selftest` (lines 1222-1235) with environment
`{LC_ALL=C, LANG=C, TZ=UTC}`. The selftest validates the hex encode/decode
utilities internal to the harness with three checks:

1. Roundtrip `"0123456789abcdef"` — decode 8 bytes, re-encode, verify match.
2. Empty-string roundtrip — 0 bytes decoded and encoded.
3. Odd-length hex rejection — `"abc"` must return -1.

The selftest result is cached per pipeline run.

### 15.3 Per-Vector Execution

For each test vector, the runner calls (via `_run_single_native_test` at
line 1259):

```
native_runner <candidate.exe> <in_hex> <out_cap> f
```

The harness loads the candidate ELF, resolves symbol `f`, calls it with the
decoded input, and prints `RET=<signed decimal>` and `OUT=<lowercase hex>`
to stdout. The runner parses the output via `_parse_native_runner_output`
(line 1241) and builds per-vector result records with the same structure as
lli test results.

The stage passes only if every vector passes.

---

## 16. The Native ELF Loader

`native_runner.c` (421 lines) implements a minimal ELF64 loader and test
executor in pure C. Its sole dependency is libc — no dlopen, no libelf, no
LLVM runtime. The `load_elf()` function beginning at line 115 performs the
following sequence.

### 16.1 File Mapping

The ELF file is memory-mapped read-only for header parsing (line 134):

```c
uint8_t *fdata = mmap(NULL, file_size, PROT_READ, MAP_PRIVATE, fd, 0);
```

The file descriptor is closed immediately after mapping. An `fstat()` check
at line 125 ensures the file is at least `sizeof(Elf64_Ehdr)` bytes.

### 16.2 Header Validation

Five checks at lines 145-156:
1. ELF magic bytes (`\x7fELF`) via `memcmp(ehdr->e_ident, ELFMAG, SELFMAG)`.
2. 64-bit class: `ehdr->e_ident[EI_CLASS] == ELFCLASS64`.
3. Little-endian data: `ehdr->e_ident[EI_DATA] == ELFDATA2LSB`.
4. AArch64 machine: `ehdr->e_machine == EM_AARCH64`.
5. Executable or shared object type: `ehdr->e_type == ET_EXEC || ET_DYN`.

### 16.3 Address Span Computation

Scans all `PT_LOAD` segments (lines 169-176) to find the minimum and
maximum virtual addresses. Both bounds are page-aligned using
`sysconf(_SC_PAGESIZE)` at lines 184-185: `vmin` rounded down, `vmax`
rounded up. The total mapped size is `vmax - vmin`.

### 16.4 Region Reservation

A single contiguous anonymous region is reserved at a kernel-chosen address
(lines 189-191):

```c
uint8_t *base = mmap(NULL, map_size, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
```

No `MAP_FIXED` is used. All subsequent address references are rebased:
virtual address `va` in the ELF maps to `base + (va - vmin)`.

### 16.5 Segment Copy

Each `PT_LOAD` segment's file-backed data is copied into the reserved
region (lines 198-213):

```c
memcpy(base + (va - vmin), fdata + off, (size_t)fsz);
```

BSS portions where `p_memsz > p_filesz` are zero-filled with `memset`
(line 212).

### 16.6 Instruction Cache Coherence

```c
__builtin___clear_cache((char *)base, (char *)(base + map_size));
```

At line 216. This is mandatory on AArch64 where the instruction cache and
data cache are not coherent. Without this call, the CPU could execute stale
or garbage instructions from the I-cache after code was written through the
D-cache.

### 16.7 Permission Hardening

A second pass over `PT_LOAD` segments (lines 219-238) applies per-segment
`mprotect` calls. Segment virtual address and size are page-aligned before
the call. Code segments with `PF_X` become `PROT_READ|PROT_EXEC`. Data
segments with `PF_W` become `PROT_READ|PROT_WRITE`. Read-only data becomes
`PROT_READ` only.

### 16.8 Relocation Rejection

Section headers are scanned for `SHT_RELA` and `SHT_REL` at lines 241-252.
If any non-empty relocation section is found, the loader rejects the binary.
This is a fail-closed safety check: freestanding candidates from Step G use
only PC-relative addressing and contain no relocations. If a candidate
somehow contained relocations, the address rebasing would produce incorrect
code, so the loader refuses to execute it.

### 16.9 Symbol Resolution

The `.symtab` section (not `.dynsym`) is searched for an `STT_FUNC` symbol
matching the requested name (lines 260-282). The function pointer is
computed as `base + (syms[j].st_value - vmin)`. Only the first `.symtab`
encountered is processed.

If the requested symbol is `"f"` and `e_entry != 0`, the ELF entry point
is used as a fallback (line 286). This works because Step G sets `f` as
the ELF entry point via `-Wl,-e,f`.

### 16.10 Invocation

The resolved pointer is cast to the candidate function type (line 32):

```c
typedef int64_t (*candidate_fn)(uint8_t *, int32_t, uint8_t *, int32_t);
```

The function is called directly at lines 393-397 with the decoded input
buffer, input length, output buffer, and output capacity. The result is
printed as `RET=<signed decimal>` and `OUT=<lowercase hex>` to stdout. The
harness exit code is always 0 for semantic results; nonzero only for harness
usage errors.

### 16.11 Design Rationale

The loader rebases all addresses relative to an anonymous region at a
kernel-chosen address instead of using `MAP_FIXED` at the ELF-specified
virtual addresses. This avoids conflicts with the loader's own address
space and works because freestanding candidates contain only PC-relative
code with no absolute-address references. The relocation rejection check
(Section 16.8) is the safety net: if a candidate contained absolute
relocations, the rebasing would silently break them, so the loader refuses
to load such binaries.

---

## 17. Verdict Computation

The `compute_verdict()` function at line 73 of `phase2_runner.py` derives
the final verdict from the `runs` array, `metrics` object, and `gates`
object. It returns a `(verdict_str, detail_str)` tuple.

**Decision procedure (7 branches):**

1. **Identify executed stages** (lines 84-89). A stage counts as "executed"
   if it has a non-null `exit_code`, positive `duration_ms`, or non-null
   `crash`. Stages left at skeleton defaults are excluded.

2. **Stage failures** (lines 92-94). If any executed stage has `ok=False`:
   return `("FAIL", "STAGE_FAILED:<stage_name>")`.

3. **lli test failures** (lines 97-99). If `metrics.tests_failed > 0`:
   return `("FAIL", "LLI_TESTS_FAILED")`.

4. **Native test failures** (lines 102-104). If
   `metrics.native_tests_failed > 0`:
   return `("FAIL", "NATIVE_TESTS_FAILED")`.

5. **No execution** (lines 107-108). If no stages executed at all:
   return `("ERROR", "NO_STAGES_EXECUTED")`.

6. **Full pass** (lines 112-117). If every stage in the runs array has
   `ok=True` and both test failure counts are zero or absent:
   return `("PASS", "ALL_STAGES_PASS")`.

7. **Otherwise** (line 119): return `("ERROR", "INDETERMINATE_VERDICT")`.

After verdict computation, `gates.policy.ok` is set to `true` if the
verdict is `"PASS"`, `false` otherwise (line 1885). The verdict detail
string is appended to `gates.policy.detail` (line 1886).

This logic was introduced in commit `8762240`, replacing an earlier
implementation where the verdict was unconditionally `"ERROR"` and
`gates.policy.ok` was always `false`. The fix was necessary because
candidates passing all seven stages were receiving ERROR verdicts. The
closure record (`PHASE2_CLOSURE.md`) documents this pre-fix state.

---

## 18. Result Assembly and Validation

The complete result object is assembled at lines 1888-1903 of
`phase2_runner.py`:

```python
result_obj = {
    "experiment": str(artifacts["constants"].get("experiment", "1")),
    "task": task,
    "candidate_id": candidate_id,
    "run_id": run_id,
    "timestamps": {"started_at": started, "finished_at": finished},
    "gates": gates_obj,
    "runs": runs_skeleton,
    "metrics": metrics_obj,
    "test_results": test_results_list,
    "native_test_results": native_test_results_list,
    "verdict": verdict_str,
}
```

At line 1905, the result is validated against the frozen schema via
`validate_json_schema_instance(result_obj, artifacts["result_schema"])`.
If validation fails, a `SchemaValidationError` is raised and the result is
not written to disk. On success, the result is written at line 1906 via
`write_json()`.

The known-good result (candidate `de4997...`, run `4254c6...`) has verdict
`PASS`, all seven stages `ok=true`, lli 10/10, native 10/10, all 14 metric
counters at their expected values, and both `test_results` and
`native_test_results` arrays containing 10 entries with outcome `PASS`.

---

## 19. Regression Sweep

A three-task regression sweep was executed on 2026-02-16. The sweep ran the
full A-H pipeline for each task using the sum_u32_le known-good candidate,
validated every result JSON against the frozen schema, and compared verdicts
against expectations.

Evidence log:
`irx/experiment1/verification/evidence/logs/regression_sweep_20260216_003439.log`.

### 19.1 sum_u32_le — PASS

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

Metrics: lli 10/10, native 10/10, all 10 lli/native pairs agree. Artifacts:
candidate.bc 1928 bytes, candidate.o 1008 bytes, candidate.exe 2304 bytes.
Verdict: PASS. Schema validation: OK.

### 19.2 hex_encode — FAIL

The sum_u32_le candidate is structurally valid IR that can be assembled and
verified, but computes the wrong function. Steps B-D pass. Step E: all 10
vectors fail (the function computes sums, not hex encoding). Steps F-H are
gated out because Step E failed.

Metrics: lli 0/10 passed, 10 failed. Verdict: FAIL. Schema validation: OK.

### 19.3 parse_u32_decimal — FAIL

Same structural validity, wrong function. Steps B-D pass. Step E: 8 of 10
vectors fail. Two vectors pass by coincidence (input/output pairs where the
sum result happens to match the expected parse output). Steps F-H gated out.

Metrics: lli 2/10 passed, 8 failed. Verdict: FAIL. Schema validation: OK.

### 19.4 Conclusions

All three result artifacts pass schema validation. The verdict computation
correctly yields PASS for the correct candidate on its own task and FAIL
for the wrong candidate on a different task. Gating correctly prevents
native compilation and execution of candidates that fail interpretation.

---

## 20. Unit Tests

Two hermetic test suites validate runner internals without requiring LLVM
tools. All tests use mocks and synthetic data.

### 20.1 test_native_tests.py

`runner/phase2/tests/test_native_tests.py` (140 lines, 13 tests).

**TestParseNativeRunnerOutput** (8 tests):
- `test_ok_with_ret_and_out` — standard `RET=` and `OUT=` parsing.
- `test_negative_ret_empty_out` — negative return value, empty output hex.
- `test_missing_ret_line` — absent `RET=` line.
- `test_missing_out_line_defaults_empty` — absent `OUT=` line defaults to `""`.
- `test_invalid_ret_format` — non-integer `RET=` value.
- `test_empty_stdout` — completely empty stdout.
- `test_err_internal_ret` — ERR_INTERNAL return code (-3).
- `test_out_hex_uppercase_normalized` — uppercase hex normalized to lowercase.

**TestResolveNativeHarnessSource** (1 test):
- `test_missing_source_returns_none` — nonexistent source file returns None.

**TestNativeTestsGating** (3 tests):
- `test_runs_skeleton_has_native_tests_stage` — stage 7 exists in skeleton.
- `test_gate_requires_all_prior_stages` — all 6 upstream stages required.
- `test_gate_requires_candidate_exe` — executable file must exist.

**TestNativeTestsNotRunWhenHarnessMissing** (1 test):
- `test_marks_not_run` — missing harness yields NOT_RUN.

### 20.2 test_verdict.py

`runner/phase2/tests/test_verdict.py` (200 lines, 8 tests).

**TestComputeVerdictPass** (2 tests):
- `test_all_pass` — all 7 stages pass, both test arrays clean -> PASS.
- `test_pass_without_native` — pass without native metrics present -> PASS.

**TestComputeVerdictFailStage** (2 tests):
- `test_stage_failed` — single failed stage -> FAIL.
- `test_first_stage_failed` — precheck failure -> FAIL.

**TestComputeVerdictFailLliTests** (1 test):
- `test_lli_tests_failed` — lli failures > 0 -> FAIL.

**TestComputeVerdictFailNativeTests** (1 test):
- `test_native_tests_failed` — native failures > 0 -> FAIL.

**TestComputeVerdictError** (1 test):
- `test_no_stages_executed` — empty execution -> ERROR.

**TestComputeVerdictNotRunDownstream** (1 test):
- `test_partial_execution_with_failure` — partial execution with upstream failure -> FAIL.

**Status:** All 21 tests (13 + 8) pass in 0.004 seconds.

---

## 21. Evidence Corpus

### 21.1 Evidence Logs

All pipeline evidence is stored under
`irx/experiment1/verification/evidence/logs/`. Four logs exist:

| Log | Date | HEAD | Content |
|-----|------|------|---------|
| `step_h_check_20260215_234036.log` | 2026-02-15 | `a5d84da` (inferred) | Step H evidence: 7/7 PASS, 10/10 lli, 10/10 native |
| `step_h_check_verdictfix_20260215_235338.log` | 2026-02-15 | `f02c049` (inferred) | Verdictfix run with uncommitted fix |
| `step_h_check_verdictfix_20260216_000503.log` | 2026-02-16 | `b00ab95` (inferred) | Full proof chain: verdict PASS, ID match, artifact sizes |
| `regression_sweep_20260216_003439.log` | 2026-02-16 | `8563fd2` (explicit) | Three-task regression sweep |

The regression sweep log is the only one with an explicit HEAD recorded
in the log content itself (line 3:
`HEAD: 8563fd275f8e73d58ad2ced6b507e1cc4b155da9`). The other three logs
have their HEAD inferred from file mtime and surrounding commit timestamps.

Each evidence log records: runner exit code, tool environment variables
(`LD_LIBRARY_PATH`), candidate_id and run_id, per-stage ok/exit_code,
lli and native test counts, artifact file sizes, and lli/native agreement.

The proof-chain log (`step_h_check_verdictfix_20260216_000503.log`)
additionally records the result JSON path, verdict field extraction, ID
match confirmation, and `ls -l` of all work artifacts:

```
candidate.bc  1928 bytes
candidate.o   1008 bytes
candidate.exe 2304 bytes
```

### 21.2 Evidence Scripts

Two bash scripts automate reproducible evidence collection.

**step_h_check.sh** (88 lines) at
`irx/experiment1/verification/evidence/step_h_check.sh`:
1. Resolves repository root and candidate/runner paths.
2. Cleans previous run artifacts.
3. Runs Python syntax check via `py_compile`.
4. Executes the full A-H pipeline on the known-good candidate.
5. Extracts tool environment lines from stderr.
6. Locates the result JSON from stdout.
7. Prints per-stage summary, lli and native test counts, artifact sizes.
8. Verifies lli/native result agreement across all vectors.

**step_f_check.sh** (65 lines) at
`irx/experiment1/verification/evidence/step_f_check.sh`:
Same structure, scoped to Steps A-F. Omits native summary, candidate.exe
check, and lli/native agreement.

### 21.3 Closure Record

`irx/experiment1/PHASE2_CLOSURE.md` (153 lines), committed at `5201dd2`
alongside the first Step H evidence log.

The closure record states: **Phase 2 complete through Step H: PASS.** It
documents the platform snapshot (Pi 5, Cortex-A76, kernel
6.12.47+rpt-rpi-2712, LLVM 19.1.7), the HEAD at closure (`a5d84da`), all
seven stage results, the lli/native agreement across all 10 vectors, the
t08 authority revision, and the known issue at closure time (verdict was
`"ERROR"` despite all stages passing, fixed 14 minutes later in `8762240`).

---

## 22. Reproduction

From the repository root on any `aarch64-linux-gnu` system with LLVM 19:

```bash
# Full A-H pipeline on the known-good candidate
rm -rf irx/experiment1/runs/*
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/step_f/sum_u32_le_good.ll \
  --task sum_u32_le

# Schema validation of the most recent result
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

# Evidence check scripts
rm -rf irx/experiment1/runs/*
bash irx/experiment1/verification/evidence/step_h_check.sh

rm -rf irx/experiment1/runs/*
bash irx/experiment1/verification/evidence/step_f_check.sh

# Unit tests (hermetic, no LLVM tools required)
python3 -m unittest runner/phase2/tests/test_native_tests.py
python3 -m unittest runner/phase2/tests/test_verdict.py
```

**Expected results:**
- Verdict: PASS
- lli: 10/10 passed
- native: 10/10 passed
- lli/native agreement: all 10 vectors
- All seven stages: ok=true
- Schema validation: passes
- Artifacts: candidate.bc 1928 bytes, candidate.o 1008 bytes, candidate.exe 2304 bytes
- Unit tests: 21/21 pass

---

## Appendix: File Inventory

| File | Lines | Role |
|------|-------|------|
| `runner/phase2/phase2_runner.py` | 1972 | Main pipeline runner |
| `irx/experiment1/harness/native/native_runner.c` | 421 | Custom ELF64 loader and test executor |
| `irx/experiment1/harness/result_schema.json` | 301 | JSON Schema (draft 2020-12) for result artifacts |
| `irx/experiment1/harness/lli_abi_runner.py` | 175 | lli ABI harness |
| `irx/experiment1/harness/lli_shim/shim.ll` | 468 | LLVM IR shim for lli execution |
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
