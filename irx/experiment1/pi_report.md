# IR Experiments — Experiment 1: Full Pipeline Verification on Raspberry Pi 5

This document is the authoritative technical report for Experiment 1 of the
IR Experiments project. It covers the complete design, implementation, and
verification of the Phase 2 pipeline, from candidate LLVM IR ingestion through
native AArch64 execution, running on a Raspberry Pi 5.

---

## 1. Revision History

| Commit | Date (PST) | Milestone |
|---|---|---|
| `a5d84da` | 2026-02-15 23:32 | Implement Step H native_tests, extend result schema |
| `5201dd2` | 2026-02-15 23:41 | Add `PHASE2_CLOSURE.md` and `step_h_check_20260215_234036.log` |
| `8762240` | 2026-02-15 23:55 | Verdict computation fix |
| `8563fd2` | 2026-02-16 00:30 | Update pi_report.md (regression sweep ran at this HEAD) |
| `b104ff5` | 2026-02-16 00:48 | Documentation accuracy pass (stage lettering, native loader) |
| `d6ebc56` | 2026-02-16 01:02 | Fix milestone attribution, evidence log HEADs, add verification notes |

---

## 2. Platform and Toolchain

### 2.1 Hardware

The experiment runs on a Raspberry Pi 5 board equipped with a Broadcom BCM2712
system-on-chip. The BCM2712 integrates four Arm Cortex-A76 cores implementing
the ARMv8.2-A architecture in little-endian (AArch64) mode. The Cortex-A76 is
a superscalar, out-of-order core with separate L1 instruction and data caches.
This cache architecture is directly relevant to the pipeline: after copying
executable code into memory, the native loader must explicitly flush the
instruction cache to guarantee coherence (see Section 8.6).

### 2.2 Operating System

The board runs Raspberry Pi OS 64-bit, a Debian-based distribution. The kernel
is version 6.12.47+rpt-rpi-2712, configured with SMP PREEMPT. The frozen
target triple for all compilation stages is `aarch64-unknown-linux-gnu`,
recorded in `irx/experiment1/env/target.json`.

### 2.3 LLVM Toolchain

All five LLVM tools come from a single Debian LLVM 19.1.7 installation at
`/usr/lib/llvm-19/bin/`. Each tool path and its version string are frozen in
`irx/experiment1/env/tool_versions.json`. The runner reads tool paths
exclusively from this file — it never searches `$PATH` or uses any
discovery mechanism.

| Tool | Frozen Path | Version String |
|---|---|---|
| llvm-as | `/usr/lib/llvm-19/bin/llvm-as` | Debian LLVM version 19.1.7, Optimized build |
| opt | `/usr/lib/llvm-19/bin/opt` | Debian LLVM version 19.1.7, Optimized build |
| lli | `/usr/lib/llvm-19/bin/lli` | Debian LLVM version 19.1.7, Optimized build |
| llc | `/usr/lib/llvm-19/bin/llc` | Debian LLVM version 19.1.7, Optimized build |
| clang | `/usr/lib/llvm-19/bin/clang` | Debian clang version 19.1.7 (3+b1) |

The `opt` and `llc` version strings additionally report the default target as
`aarch64-unknown-linux-gnu` and the host CPU as `cortex-a76`. The `clang`
version string reports the thread model as `posix` and the installed directory
as `/usr/lib/llvm-19/bin`.

---

## 3. Pipeline Architecture

### 3.1 Overview

The Phase 2 runner is implemented as a single Python module at
`runner/phase2/phase2_runner.py` (1972 lines). It ingests a candidate LLVM IR
file (`.ll`), evaluates it against frozen test vectors, and writes a
structured JSON result artifact. The pipeline uses an A-through-H step
convention:

- **Step A** is the initialization phase. It loads five frozen artifact
  categories: tool paths (`tool_versions.json`), result schema
  (`result_schema.json`), constants and limits (`constants.json`), the
  target triple (`target.json`), and all task test vectors
  (`tasks/*/tests.json`). It also computes the deterministic candidate and
  run identifiers, and emits a `LOADED_STEP_A:` prefix string into every
  gate detail field (line 1440 of `phase2_runner.py`; confirmed present in
  all four `gates.parse.detail`, `gates.verify.detail`, `gates.tests.detail`,
  and `gates.policy.detail` fields of produced result JSON artifacts).

- **Steps B through H** are the seven sequential execution stages. Each
  stage must succeed before the next is permitted to run.

```
[A] init            Load tool paths, test vectors, constants, ID rules.
                    Compute candidate_id and run_id.
                    Emit LOADED_STEP_A: into gate detail strings.

candidate.ll
  |
  v
[B] precheck        Enforce size limits (max 65536 bytes, max 2000 lines).
  |
  v
[C] llvm_as_parse   llvm-as -> candidate.bc (bitcode assembly).
  |
  v
[D] opt_verify      opt -passes=verify (module verification).
  |
  v
[E] lli_tests       lli interpreter + Python harness -> per-vector test results.
  |
  v
[F] llc_compile     llc -filetype=obj -> candidate.o (ELF relocatable).
  |
  v
[G] clang_link      clang + lld -> candidate.exe (freestanding ELF executable).
  |
  v
[H] native_tests    Custom ELF loader invokes f() -> per-vector test results.
```

This step labeling is consistent across the entire repository. The evidence
scripts are named `step_f_check.sh` and `step_h_check.sh`. The Phase 2
closure record (`PHASE2_CLOSURE.md`) references Steps A through H. Commit
messages use Step F for llc_compile, Step G for clang_link, and Step H for
native_tests.

### 3.2 Stage Gating

Gating is strict and sequential. Every execution stage checks that all prior
stages succeeded before running. The precondition for each stage is a
conjunction: for instance, Step F (llc_compile) requires that precheck,
llvm_as_parse, opt_verify, and lli_tests all completed with `ok=True`, and
that the expected input artifact (`candidate.bc`) exists and is non-empty.

If any stage fails, all downstream stages are skipped. Their `runs` records
remain at the skeleton defaults (`ok=False`, `exit_code=null`, `duration_ms=0`,
`crash=null`), and their detail strings record
`<STAGE>_NOT_RUN:preconditions_failed`. This design ensures that the native
execution path (Steps F-H) only runs against candidates that have already
passed interpretation (Step E). A candidate must clear all seven stages to
receive a PASS verdict.

The specific precondition chains are:

| Stage | Preconditions |
|---|---|
| B (precheck) | Always runs |
| C (llvm_as_parse) | B passed |
| D (opt_verify) | B, C passed; `candidate.bc` exists and non-empty |
| E (lli_tests) | B, C, D passed; `candidate.bc` exists and non-empty |
| F (llc_compile) | B, C, D, E passed; `candidate.bc` exists and non-empty |
| G (clang_link) | B, C, D, E, F passed; `candidate.o` exists and non-empty |
| H (native_tests) | B, C, D, E, F, G passed; `candidate.exe` exists and non-empty |

### 3.3 Subprocess Isolation

Every LLVM tool invocation runs in a fully deterministic subprocess
environment. The environment is cleared to empty and rebuilt with exactly four
variables:

```
LC_ALL=C
LANG=C
TZ=UTC
LD_LIBRARY_PATH=/usr/lib/llvm-19/lib
```

The `LD_LIBRARY_PATH` value is derived from the frozen tool path — for a tool
at `/usr/lib/llvm-19/bin/llvm-as`, the runner computes the sibling `lib/`
directory as `/usr/lib/llvm-19/lib` and verifies it exists before adding it
(see `_derive_llvm_lib_path` at line 680, `_build_llvm_tool_env` at line 699).
This is necessary because `libLLVM.so.19.1` is located there and all five
tools dynamically link against it.

The `LC_ALL=C` and `LANG=C` settings eliminate locale-dependent formatting
variations. The `TZ=UTC` setting eliminates timezone-dependent timestamp
differences. The cleared parent environment eliminates any contamination from
the user's shell.

Resource limits are applied via `RLIMIT_RSS` only. `RLIMIT_AS` (virtual
address space) is deliberately avoided because `libLLVM.so.19.1` maps
approximately 123 MB of virtual address space on load and would immediately
trip any reasonable AS limit. The frozen RSS limit is 64 MiB (from
`constants.json`). Each subprocess is started in its own process group
(`start_new_session=True`) to enable clean group kills on timeout.

### 3.4 Deterministic Identity

Each pipeline run produces two SHA-256 identifiers, derived according to rules
frozen in `irx/experiment1/harness/id_rules.json`:

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
the same candidate file always produces the same pair of identifiers regardless
of when, where, or how many times the pipeline runs.

The result artifact is written to a path derived from these identifiers:
`runs/<candidate_id>/<run_id>.json`, with work products stored alongside in a
`work/` subdirectory. This scheme means that rerunning the same candidate
overwrites its previous result, while different candidates never collide.

---

## 4. Frozen Artifacts

The pipeline reads five categories of frozen artifacts at initialization.
These artifacts are committed to the repository and are not modified at
runtime.

### 4.1 Tool Versions (`irx/experiment1/env/tool_versions.json`)

Lists the five required LLVM binaries (`llvm-as`, `opt`, `lli`, `llc`,
`clang`), each with a `detected` entry containing the frozen filesystem path
(`/usr/lib/llvm-19/bin/<tool>`), a boolean `ok` flag, the raw `version_text`
output, and an `error` field (null for all five tools on this platform).

### 4.2 Target (`irx/experiment1/env/target.json`)

Records the compilation target:

```json
{
  "os": "raspios64",
  "arch": "aarch64",
  "triple": "aarch64-unknown-linux-gnu",
  "endian": "little"
}
```

The `triple` field is used by Steps F and G as the `-mtriple` and `-target`
arguments to `llc` and `clang` respectively.

### 4.3 Constants (`irx/experiment1/harness/constants.json`)

Defines the experiment number, the shared ABI contract, error codes, resource
limits, and the crash type taxonomy.

The ABI contract specifies that every candidate exports a single function `f`
with signature `i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap)`.
The function reads from an input buffer, writes to an output buffer, and
returns the number of bytes written on success or a negative error code on
failure.

**Note:** The `signature_ir` field inside `constants.json` and the three
`tasks/*/spec.json` files still contains a stale `i32` return type
(`"i32 @f(i8* ...)"`) from an earlier draft. The runner never reads this
field — it is purely documentary. Every executable artifact in the repository
uses `i64`: the lli shim (`shim.ll:366`), the lli harness
(`lli_abi_runner.py:6`), the native harness typedef (`native_runner.c:32`),
and the known-good candidate (`sum_u32_le_good.ll:4`). The authoritative
return type is `i64`.

The three defined error codes are:

| Code | Name | Meaning |
|---|---|---|
| -1 | ERR_INVALID_INPUT | Malformed, out-of-range, or rejected input |
| -2 | ERR_OUTPUT_TOO_SMALL | Output buffer capacity insufficient |
| -3 | ERR_INTERNAL | Unexpected internal failure |

The frozen resource limits are:

| Limit | Value | Used by |
|---|---|---|
| max_ll_bytes | 65536 | Step B precheck |
| max_ll_lines | 2000 | Step B precheck |
| max_basic_blocks | 200 | (reserved, not currently enforced) |
| max_instructions | 20000 | (reserved, not currently enforced) |
| max_alloca_bytes_total | 4096 | (reserved, not currently enforced) |
| timeout_stage_ms | 1000 | Steps C, D, F, G (per-stage timeout) |
| timeout_per_test_ms | 50 | Steps E, H (per-test-vector timeout) |
| max_rss_mib | 64 | All subprocess stages |
| max_input_bytes | 65536 | Input buffer size cap |
| max_output_bytes | 65536 | Output buffer size cap |

The crash type taxonomy defines ten categories: `SIGSEGV`, `SIGILL`,
`SIGABRT`, `SIGFPE`, `TIMEOUT`, `OOM`, `SANITIZER_FINDING`,
`POLICY_VIOLATION`, `VERIFY_FAIL`, and `PARSE_FAIL`. Each stage maps its
failure modes into this taxonomy for uniform reporting in the `runs[].crash`
field.

### 4.4 Result Schema (`irx/experiment1/harness/result_schema.json`)

A JSON Schema (draft 2020-12) that every result artifact is validated against
before being written to disk. The schema uses `additionalProperties: false` at
every level, ensuring no undeclared fields appear in the output. This means
that any structural change to the result format requires a corresponding schema
update.

Required top-level fields: `experiment`, `task`, `candidate_id`, `run_id`,
`timestamps`, `gates`, `runs`, `metrics`, `verdict`.

The `verdict` field is constrained to the enum `["PASS", "FAIL", "ERROR"]`.

The `gates` object has four required sub-objects: `parse`, `verify`, `policy`,
and `tests`, each with `ok` (boolean) and `detail` (string or null) fields.

The `runs` array contains per-stage records with fields: `stage`, `ok`,
`exit_code`, `duration_ms`, `rss_mib`, and `crash`. The `crash` field is
either null or an object with `type` (constrained to the crash taxonomy enum),
`signal` (integer or null), and `detail` (string or null).

The `metrics` object contains 14 counters: seven for lli execution
(`tests_total`, `tests_passed`, `tests_failed`, `ret_mismatches`,
`output_mismatches`, `timeouts`, `crashes`) and seven mirrored for native
execution (`native_tests_total`, `native_tests_passed`, etc.). The seven
native metric fields and the `native_test_results` array were added in commit
`a5d84da` alongside the Step H implementation.

The `test_results` and `native_test_results` arrays contain per-vector records
with fields: `index`, `in_hex`, `out_cap`, `expected_ret`,
`expected_out_hex`, `actual_ret`, `actual_out_hex`, `outcome`, `exit_code`,
`signal`, `detail`. The `outcome` field is constrained to `["PASS",
"RETURN_MISMATCH", "OUTPUT_MISMATCH", "UNEXPECTED_CRASH", "TIMEOUT", "OOM"]`.
The `detail` field has a maximum length of 200 characters.

### 4.5 ID Rules (`irx/experiment1/harness/id_rules.json`)

Defines the two derivation rules described in Section 3.4.

---

## 5. Tasks and Test Vectors

Three tasks are defined under `irx/experiment1/tasks/`, each with a
`spec.json` describing the function contract and a `tests.json` containing 10
frozen test vectors. All candidates implement the shared ABI:

```
i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap)
```

Every task's `spec.json` declares the same memory rules: input is immutable,
input and output buffers do not overlap, no alignment assumptions may be made
(all loads and stores use `align 1`), and no output writes occur on error.

### 5.1 sum_u32_le

**Contract.** Reads an array of little-endian uint32 values from the input
buffer, accumulates them with wrapping (mod 2^32) addition, writes the 4-byte
little-endian result to the output buffer, and returns 4 (bytes written).
Returns -1 (ERR_INVALID_INPUT) if the input length is not divisible by 4, the
output capacity is less than 4, or the element count is exactly 3 (an
intentional boundary rejection case). Returns -2 (ERR_OUTPUT_TOO_SMALL) if
the output capacity is insufficient (though in practice the spec requires
`out_cap >= 4`).

**Test vectors (10):**

| ID | Input (hex) | out_cap | Expected ret | Expected output (hex) | Purpose |
|---|---|---|---|---|---|
| t01 | (empty) | 4 | 4 | `00000000` | Zero elements, zero sum |
| t02 | `01000000` | 4 | 4 | `01000000` | Single element identity |
| t03 | `ffffffff` | 4 | 4 | `ffffffff` | Maximum uint32 |
| t04 | `0100000002000000` | 4 | 4 | `03000000` | Two-element addition (1+2=3) |
| t05 | `0000000000000000` | 4 | 4 | `00000000` | Two zero elements |
| t06 | `78563412` | 4 | 4 | `78563412` | Byte-order verification (0x12345678) |
| t07 | `01000000ffffffff` | 4 | 4 | `00000000` | Overflow wrap (1+0xFFFFFFFF=0) |
| t08 | `ffffffffffffffff` | 4 | 4 | `feffffff` | Double-max wrap (0xFFFFFFFE) |
| t09 | `00000000ffffffff01000000` | 4 | -1 | (empty) | Three-element rejection |
| t10 | `01000000020000000300000004000000` | 4 | 4 | `0a000000` | Four-element sum (1+2+3+4=10) |

**Test vector correction.** Vector t08 originally had `expected_out_hex` set
to `"fffffffe"`, which is a big-endian representation of the value 0xFFFFFFFE.
The correct little-endian byte encoding is `"feffffff"`. This was a
single-field change in `tasks/sum_u32_le/tests.json`, committed as `31223ce`
(2026-02-15 22:16 PST). No other test vectors, fields, or files were modified.
The error was discovered during Step F verification when the candidate
produced the correct little-endian bytes but the test vector expected the
reversed byte order.

### 5.2 hex_encode

**Contract.** Converts each input byte to two lowercase hexadecimal ASCII
characters. Output length is exactly `2 * in_len` bytes. Returns the number
of bytes written on success, or -2 (ERR_OUTPUT_TOO_SMALL) if `out_cap <
2 * in_len`.

**Test vectors (10):** Empty input, single zero byte (0x00 -> "00"), 0x01 ->
"01", 0x0F -> "0f", insufficient output capacity (returns -2), 0xFF -> "ff",
4-byte sequence 0xDEADBEEF, 3-byte sequence 0x123456, 10-byte sequence
0x00-0x09, and 5-byte ASCII string "Hello" (0x48656c6c6f).

### 5.3 parse_u32_decimal

**Contract.** Parses a decimal ASCII string (digits 0x30-0x39) into a
little-endian uint32. Returns 4 (bytes written) on success with the parsed
value stored little-endian in the output buffer. Returns -1
(ERR_INVALID_INPUT) on error: empty input, non-digit characters, or overflow
beyond 4294967295 (2^32 - 1). The overflow check uses the threshold
`acc > 429496729 || (acc == 429496729 && digit > 5)`.

**Test vectors (10):** Single zero digit ("0"), single non-zero digit ("5"),
two-digit number ("10"), leading zeros ("0003"), maximum uint32
("4294967295"), overflow by one ("4294967296"), empty input, negative sign
prefix ("-1"), large valid number ("1234567890"), and embedded non-digit
character ("123x").

---

## 6. Known-Good Candidate

A verified known-good candidate for sum_u32_le is provided at
`irx/experiment1/verification/step_f/sum_u32_le_good.ll`. This is a 42-line
LLVM IR file targeting `aarch64-unknown-linux-gnu`. It defines a single
exported function `@f(ptr, i32, ptr, i32) -> i64` that:

1. Checks `in_len % 4 == 0` (rejects with `ret i64 -1` otherwise)
2. Checks `out_cap >= 4` (rejects otherwise)
3. Checks element count is not exactly 3 (rejects otherwise)
4. If zero elements, writes zero to the output buffer and returns 4
5. Otherwise, loops over elements using phi nodes (`%i` for index, `%sum`
   for accumulator), reading each as `load i32, ptr %elem_ptr, align 1`
6. Accumulates with wrapping `add i32`
7. Stores the result via `store i32 %result, ptr %out_ptr, align 1` and
   returns 4

The loop uses `getelementptr i8` with a byte offset computed as `%i * 4`,
zero-extended to i64. The loop exit condition is `icmp eq i32 %i_next, %n`.

Deterministic IDs (confirmed stable across all runs):

```
candidate_id: de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6
run_id:       4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60
```

No known-good candidates exist yet for hex_encode or parse_u32_decimal.

---

## 7. Pipeline Stages in Detail

### 7.1 Step B: Precheck

The precheck stage enforces two size limits from `constants.json`: the
candidate file must not exceed `max_ll_bytes` (65536) bytes and must not
exceed `max_ll_lines` (2000) lines. Lines are counted by the number of
newline characters in the file bytes, plus one if the file does not end with
a newline. The precheck runs entirely in-process with no subprocess.

On success, the detail string records the actual counts and limits:
`PRECHECK_PASS:bytes=1232/65536;lines=42/2000` (for the known-good
candidate). On failure, it records which limits were exceeded.

### 7.2 Step C: llvm_as_parse

Assembles the candidate `.ll` file into LLVM bitcode:

```
llvm-as candidate.ll -o candidate.bc
```

The runner resolves `llvm-as` from `tool_versions.json` under the key
`detected.llvm-as.path`, verifies the path is an existing executable file,
then invokes it in a clean subprocess with the deterministic environment. The
subprocess runs in the `work/` directory with stdin redirected to `/dev/null`.

On exit code 0 with a non-empty `candidate.bc` output, the stage records
`ok=True` and `LLVM_AS_PARSE_PASS`. On timeout, signal death, OOM heuristic
match, or nonzero exit, it records the appropriate crash type from the
taxonomy.

### 7.3 Step D: opt_verify

Runs the LLVM module verifier on the bitcode:

```
opt -passes=verify candidate.bc -o /dev/null
```

This checks the module for structural correctness: valid instruction operand
types, proper basic block termination, SSA dominance, and other LLVM IR
invariants. The runner resolves `opt` from `tool_versions.json` under
`detected.opt.path` (with a fallback key `detected.llvm-opt.path`). The
same deterministic environment and error mapping apply.

### 7.4 Step E: lli_tests

Interprets the candidate using the LLVM JIT interpreter against the frozen
test vectors for the specified task.

The runner first discovers the lli ABI harness by scanning files under
`irx/experiment1/harness/` and `irx/experiment1/` for a pattern bundle that
includes references to `lli`, `@f`, `candidate.bc`, test vector field names,
and subprocess invocation patterns. The chosen harness
(`irx/experiment1/harness/lli_abi_runner.py`) is recorded in the
`gates.tests.detail` string with its discovery status.

For each test vector, the runner invokes lli with the harness, passing the
input hex string, output capacity, expected return value, and expected output
hex. The harness executes `lli --entry-function=f candidate.bc` with
appropriately marshalled arguments and captures the return value and output
buffer contents.

Results are compared per-vector. A test passes if `actual_ret ==
expected_ret` and `actual_out_hex == expected_out_hex`. Mismatches are
classified as `RETURN_MISMATCH` or `OUTPUT_MISMATCH`. Process crashes and
timeouts are recorded with the appropriate taxonomy types. Per-test timeout
is 50 ms (from `constants.json`).

The stage passes if and only if all vectors pass (zero failures).

### 7.5 Step F: llc_compile

Compiles the bitcode to a native relocatable object:

```
llc -filetype=obj -mtriple=aarch64-unknown-linux-gnu -O0 \
    -o candidate.o candidate.bc
```

The runner resolves `llc` from `tool_versions.json` under `detected.llc.path`
(with fallback `detected.llvm-llc.path`) and the target triple from
`target.json`. The `-O0` flag disables optimization to keep compilation fast
and deterministic; the candidate IR is already in final form.

On exit code 0, the runner verifies that `candidate.o` exists and has nonzero
size. If the file is missing or empty despite a zero exit code, the stage
fails with `POLICY_VIOLATION`. For the known-good sum_u32_le candidate,
`candidate.o` is 1008 bytes.

### 7.6 Step G: clang_link

Links the relocatable object into a freestanding ELF executable:

```
clang -target aarch64-unknown-linux-gnu \
      -fuse-ld=lld \
      -nostdlib \
      -Wl,--no-dynamic-linker \
      -Wl,-e,f \
      -o candidate.exe candidate.o
```

The flags produce a minimal static ELF binary. The `-nostdlib` flag omits
all C runtime startup files and standard library linkage. The
`-Wl,--no-dynamic-linker` flag removes the `PT_INTERP` segment so the
binary has no dynamic linker reference. The `-Wl,-e,f` flag sets the ELF
entry point to the symbol `f`, which is the candidate's exported function.
The `-fuse-ld=lld` flag selects the LLVM linker for deterministic output.

The result is a minimal ELF binary containing only the candidate's code with
`f` as both the only function and the entry point. There is no C runtime, no
dynamic linker, and no library dependencies. For the known-good sum_u32_le
candidate, `candidate.exe` is 2304 bytes.

The runner resolves `clang` from `tool_versions.json` under
`detected.clang.path` (with fallback `detected.llvm-clang.path`). The same
deterministic environment, timeout, and error mapping apply as in Step F.

### 7.7 Step H: native_tests

Executes the frozen test vectors against the linked executable using a custom
in-process ELF loader. This stage is the culmination of the pipeline: it
proves that the candidate not only produces correct results under
interpretation (Step E) but also produces correct native AArch64 machine code
that executes correctly when loaded and called directly.

The runner first locates the native harness source at
`irx/experiment1/harness/native/native_runner.c` (421 lines). If not already
built, the runner compiles it using the frozen clang path. The compiled binary
is cached at `irx/experiment1/harness/native/native_runner` and reused across
test vectors within a run. A selftest (`--selftest` flag) validates the
harness's hex encode/decode routines before any candidate execution.

For each test vector, the runner invokes:

```
native_runner <candidate.exe> <in_hex> <out_cap> f
```

The harness loads the ELF, resolves the symbol `f`, calls it with the
decoded input buffer, and prints `RET=<decimal>` and `OUT=<hex>` on stdout.
The runner parses these lines, compares against expected values, and builds
per-vector result records identical in structure to the lli test results.

The stage passes if and only if all vectors pass.

---

## 8. Native ELF Loader

The native harness (`irx/experiment1/harness/native/native_runner.c`, 421
lines) implements a minimal ELF64 loader and test executor written in pure C.
Its only dependency is libc — no dlopen, no libelf, no LLVM runtime.

### 8.1 File Mapping

The `load_elf()` function (line 115) begins by opening the ELF file and
mapping it read-only for header parsing:

```c
uint8_t *fdata = mmap(NULL, file_size, PROT_READ, MAP_PRIVATE, fd, 0);
```

The file descriptor is closed immediately after mapping (line 136).

### 8.2 Header Validation

The loader verifies the ELF magic bytes (`\x7fELF`), 64-bit class
(`ELFCLASS64`), little-endian data encoding (`ELFDATA2LSB`), and machine type
(`EM_AARCH64`) at lines 145-148. Both `ET_EXEC` and `ET_DYN` ELF types are
accepted (line 152). Any mismatch causes immediate failure.

### 8.3 Address Span Computation

All `PT_LOAD` segments are scanned to find the minimum and maximum virtual
addresses (`vmin`, `vmax`) at lines 166-176. Both bounds are page-aligned
using the system page size from `sysconf(_SC_PAGESIZE)`: `vmin` is rounded
down and `vmax` is rounded up (lines 182-186). The total map size is
`vmax - vmin`.

### 8.4 Region Reservation

A single contiguous anonymous region is reserved at a kernel-chosen address:

```c
uint8_t *base = mmap(NULL, map_size, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
```

The loader does not use `MAP_FIXED` (line 189). All subsequent address
references are rebased: a virtual address `va` in the ELF maps to
`base + (va - vmin)` in the host process.

### 8.5 Segment Copy

Each `PT_LOAD` segment's file-backed data is copied into the reserved region:

```c
memcpy(base + (va - vmin), fdata + off, (size_t)fsz);
```

Any BSS portion where `p_memsz > p_filesz` is zero-filled with `memset`
(line 212).

### 8.6 Instruction Cache Coherence

The entire region is flushed:

```c
__builtin___clear_cache((char *)base, (char *)(base + map_size));
```

This is mandatory on AArch64 where the instruction cache and data cache are
not coherent. Without this call, the CPU could execute stale or garbage
instructions from the I-cache after writing executable code via the D-cache.
The Cortex-A76 implements separate 64 KB L1I and 64 KB L1D caches, making
this flush essential.

### 8.7 Permission Hardening

A second pass over `PT_LOAD` segments applies per-segment `mprotect` calls
to set final permissions derived from `p_flags` (lines 219-238). The segment
virtual address and size are page-aligned before the `mprotect` call. Code
segments (`PF_X`) become read-execute. Data segments (`PF_W`) become
read-write. Read-only data becomes read-only. This hardens the memory layout
after the initial read-write copy phase.

### 8.8 Relocation Rejection

Section headers are scanned for `SHT_RELA` and `SHT_REL` sections. If any
non-empty relocation section exists, the loader rejects the binary (lines
241-252). This is a fail-closed safety check. The freestanding binaries
produced by Step G contain no relocations because the code within each LOAD
segment uses only PC-relative addressing. If a candidate somehow contained
relocations that the rebasing would break, the loader refuses to execute it.

### 8.9 Symbol Resolution

The loader searches `.symtab` (not `.dynsym`) for a function symbol
(`STT_FUNC`) matching the requested name, typically `f` (lines 254-283).
The function pointer is computed as `base + (st_value - vmin)` (line 277).
Only the first `.symtab` section is processed. If the symbol is not found,
the loader falls back to the ELF entry point `e_entry` when the requested
symbol is `f` (lines 286-288).

### 8.10 Invocation and Output

The resolved function pointer is cast to
`int64_t (*)(uint8_t*, int32_t, uint8_t*, int32_t)` and called directly
(lines 393-397). Output is printed as `RET=<signed decimal>` and
`OUT=<lowercase hex>` on stdout in the wire format expected by the Python
test harness. The exit code is always 0 for semantic results (both success
and failure return values from the candidate); non-zero exit codes indicate
harness usage errors.

### 8.11 Design Rationale

The loader rebases all addresses relative to an anonymous region rather than
using `MAP_FIXED` at the ELF-specified virtual addresses. This avoids
conflicts with the loader's own address space and works because the
freestanding candidates produced by Step G contain no absolute address
relocations — the code uses only PC-relative addressing. The relocation
rejection check (Section 8.8) serves as a safety net: if a candidate somehow
contained relocations that the rebasing would break, the loader refuses to
execute it rather than silently producing wrong results.

### 8.12 Selftest

The `native_runner` supports a `--selftest` flag that validates its hex
encode/decode routines with a roundtrip test: it decodes `"0123456789abcdef"`
to bytes, re-encodes to hex, and verifies the result matches. It also tests
empty-string roundtrip and odd-length rejection. The Phase 2 runner invokes
selftest on first use within a pipeline run and caches the result. Subsequent
native test invocations in the same run skip the selftest.

---

## 9. Verdict Computation

The runner derives a final verdict from stage outcomes and test metrics using
`compute_verdict()` (line 73 in `phase2_runner.py`). The function examines
the `runs` array, `metrics` object, and `gates` object and returns a
`(verdict_str, detail_str)` tuple.

The decision procedure:

1. **Identify executed stages.** A stage is considered "executed" if it has a
   non-null `exit_code`, a positive `duration_ms`, or a non-null `crash`
   record. Stages that were gated out remain at skeleton defaults and are
   excluded.

2. **Check for stage failures.** If any executed stage has `ok=False`, return
   **FAIL** with `STAGE_FAILED:<stage_name>`.

3. **Check lli test failures.** If `metrics.tests_failed > 0`, return
   **FAIL** with `LLI_TESTS_FAILED`.

4. **Check native test failures.** If `metrics.native_tests_failed > 0`,
   return **FAIL** with `NATIVE_TESTS_FAILED`.

5. **Check for no execution.** If no stages executed at all (empty executed
   set), return **ERROR** with `NO_STAGES_EXECUTED`.

6. **Check for full pass.** If every stage in the skeleton has `ok=True` and
   both lli and native failure counts are zero (or absent), return **PASS**
   with `ALL_STAGES_PASS`.

7. **Indeterminate.** Otherwise, return **ERROR** with
   `INDETERMINATE_VERDICT`.

The verdict string is written to the top-level `verdict` field in the JSON
artifact. After verdict computation, `gates.policy.ok` is set to `true` when
the verdict is PASS, `false` otherwise (line 1885). The verdict detail is
appended to `gates.policy.detail` (line 1886).

This logic was introduced in commit `8762240` (2026-02-15 23:55 PST),
replacing an earlier implementation where the verdict was effectively always
`"ERROR"` and `gates.policy.ok` was always `false`. The fix was necessary
because the original code set `gates.policy.ok = False` unconditionally and
relied on the unconditionally-false policy gate to determine the verdict,
which meant even candidates that passed all stages received ERROR verdicts.

---

## 10. Regression Sweep

A three-task regression sweep was executed on 2026-02-16 at HEAD `8563fd2`.
The sweep ran the full A-H pipeline for each task, validated every result
JSON against the schema, and compared verdicts against expectations. The
evidence log is stored at
`irx/experiment1/verification/evidence/logs/regression_sweep_20260216_003439.log`.

### 10.1 sum_u32_le — PASS (expected PASS)

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
- Work artifacts: candidate.bc (1928 bytes), candidate.o (1008 bytes),
  candidate.exe (2304 bytes)

### 10.2 hex_encode — FAIL (expected FAIL)

The sum_u32_le candidate was run as a stub against the hex_encode test
vectors (no hex_encode-specific candidate exists). The candidate passes
Steps B-D because its IR is structurally valid LLVM. At Step E, all 10
hex_encode vectors fail because the candidate computes sums rather than hex
encodings. The pipeline correctly gates out Steps F-H.

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

### 10.3 parse_u32_decimal — FAIL (expected FAIL)

Same stub candidate against parse_u32_decimal vectors. Steps B-D pass. At
Step E, 8 of 10 vectors fail. Two vectors pass by coincidence — the
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

### 10.4 Sweep Conclusions

All three result artifacts pass full schema validation. The verdict
computation correctly yields PASS for a correct candidate on its own task and
FAIL for a wrong candidate on a different task. Stage gating prevents
compilation and native execution of candidates that fail at interpretation.
The two coincidental passes in parse_u32_decimal are expected — they reflect
input/output pairs where the sum operation happens to produce the same bytes
as the parse operation, not a pipeline error.

---

## 11. Unit Tests

Two hermetic test suites validate runner internals without requiring LLVM
tools to be installed.

### 11.1 test_native_tests.py (140 lines, 13 tests)

Covers native test result parsing, per-vector result construction, gating
precondition logic, selftest caching behavior, and error handling for the
Step H integration. All tests use mock subprocess calls and run without the
native_runner binary.

### 11.2 test_verdict.py (200 lines, 8 tests)

Covers every branch of `compute_verdict()`: all-pass yields PASS, pass
without native metrics yields PASS, a failed stage yields FAIL naming the
stage, precheck failure yields FAIL, lli test failures yield FAIL, native
test failures yield FAIL, no executed stages yields ERROR, and partial
execution with an upstream failure yields FAIL.

All 21 tests pass (13 + 8).

---

## 12. Evidence Logs

All pipeline evidence is stored under
`irx/experiment1/verification/evidence/logs/`. Four logs exist:

| Log file | Date | HEAD | Content |
|---|---|---|---|
| `step_h_check_20260215_234036.log` | 2026-02-15 | `a5d84da` (inferred) | Step H evidence run (pre-closure), 7/7 stages PASS |
| `step_h_check_verdictfix_20260215_235338.log` | 2026-02-15 | `f02c049` (inferred) | First run with uncommitted verdict fix |
| `step_h_check_verdictfix_20260216_000503.log` | 2026-02-16 | `b00ab95` (inferred) | Full proof chain: verdict PASS, ID match, artifact sizes |
| `regression_sweep_20260216_003439.log` | 2026-02-16 | `8563fd2` (explicit) | Three-task regression sweep, all verdicts correct |

The final verdict-fix evidence log (`step_h_check_verdictfix_20260216_000503.log`)
includes a multi-part proof chain: the path to the result JSON, extraction of
the verdict field showing `"PASS"`, a grep confirming `"verdict": "PASS"` at
line 366 of the JSON, verification that candidate_id and run_id match expected
values (`candidate_id_match: True`, `run_id_match: True`), and an `ls -l`
listing of all three work artifacts with byte sizes (candidate.bc = 1928,
candidate.o = 1008, candidate.exe = 2304).

---

## 13. Evidence Scripts

Two bash scripts automate reproducible evidence collection.

### 13.1 step_h_check.sh

Located at `irx/experiment1/verification/evidence/step_h_check.sh`. Performs:

1. Clean all previous run artifacts (`rm -rf irx/experiment1/runs/*`)
2. Syntax-check the runner (`python3 -m py_compile`)
3. Run the full A-H pipeline on the known-good candidate
4. Extract tool environment lines from stderr
5. Locate the result JSON from stdout
6. Print a summary: candidate_id, run_id, per-stage ok/exit_code,
   lli and native test counts, work artifact sizes, and lli/native agreement

### 13.2 step_f_check.sh

Located at `irx/experiment1/verification/evidence/step_f_check.sh`. Same
structure as step_h_check.sh but limited to Steps A-F evidence (no native
test summary, no candidate.exe check). Produces the same runner invocation
and result JSON extraction.

---

## 14. Commit History

Key implementation and verification commits in chronological order:

| Commit | Date (PST) | Description |
|---|---|---|
| `960cebf` | 2026-02-15 19:39 | Add frozen id_rules authority |
| `add9dc8` | 2026-02-15 19:48 | Add llc_compile gate (Step F) |
| `b1679b0` | 2026-02-15 21:32 | Fix opt syntax, target triple key, schema, wire lli harness |
| `31223ce` | 2026-02-15 22:16 | Fix sum_u32_le t08 expected_out_hex endianness |
| `1153420` | 2026-02-15 22:18 | Add verification fixture directory |
| `f0a6261` | 2026-02-15 22:28 | Add Step F evidence bundle and check script |
| `b0d8cd9` | 2026-02-15 23:02 | Implement Step G clang_link |
| `a5d84da` | 2026-02-15 23:32 | Implement Step H native_tests, extend schema |
| `5201dd2` | 2026-02-15 23:41 | Phase 2 closure record |
| `8762240` | 2026-02-15 23:55 | Fix verdict computation from stage outcomes |
| `b104ff5` | 2026-02-16 00:48 | Fix report metadata and native loader wording |
| `d6ebc56` | 2026-02-16 01:02 | Fix milestone attribution and evidence log HEADs |

---

## 15. Reproduction

From the repository root on any `aarch64-linux-gnu` system with LLVM 19:

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

# Step H evidence check (clean run with full summary)
rm -rf irx/experiment1/runs/*
bash irx/experiment1/verification/evidence/step_h_check.sh

# Step F evidence check (A-F subset)
rm -rf irx/experiment1/runs/*
bash irx/experiment1/verification/evidence/step_f_check.sh

# Unit tests (hermetic, no LLVM required)
python3 -m unittest runner/phase2/tests/test_native_tests.py
python3 -m unittest runner/phase2/tests/test_verdict.py
```

Expected output for the known-good sum_u32_le candidate: verdict PASS, lli
10/10 passed, native 10/10 passed, lli/native match on all 10 vectors, all
seven stages ok=True, schema validation passes, candidate.bc = 1928 bytes,
candidate.o = 1008 bytes, candidate.exe = 2304 bytes.

---

## 16. Verification Notes

Evidence log HEAD values were determined as follows:

**`regression_sweep_20260216_003439.log`**: HEAD `8563fd2` is recorded
explicitly on line 3 of the log
(`HEAD: 8563fd275f8e73d58ad2ced6b507e1cc4b155da9`).

**`step_h_check_20260215_234036.log`**: No explicit HEAD in the log. File
mtime is 23:40:37 PST. Commit `a5d84da` was authored at 23:32:47 and the
next commit `5201dd2` at 23:41:34. The log was therefore produced at HEAD
`a5d84da`. This was a pre-closure run — the closure record was committed
one minute later as `5201dd2`.

**`step_h_check_verdictfix_20260215_235338.log`**: No explicit HEAD. File
mtime is 23:53:39 PST. The last committed HEAD before this time was `f02c049`
(23:47:29). The uncommitted verdict fix changes (which became commit `8762240`
at 23:55:29) were present in the working tree when the runner executed.
Previous report versions attributed this log to `8762240`, but `8762240` did
not exist yet — the runner ran against uncommitted changes on top of `f02c049`.

**`step_h_check_verdictfix_20260216_000503.log`**: No explicit HEAD. File
mtime is 00:05:05 PST on 2026-02-16. The last committed HEAD before this
time was `b00ab95` (00:00:28). The next commit `ef34058` was authored at
00:17:03. Previous report versions listed this as "post-`8762240`" which was
imprecise.

The `LOADED_STEP_A:` prefix claim was verified by grep against both the
runner source (`runner/phase2/phase2_runner.py` line 1440) and the produced
result JSON artifact, where it appears in all four `gates.parse.detail`,
`gates.verify.detail`, `gates.tests.detail`, and `gates.policy.detail`
strings. Concrete example from `gates.parse.detail` in the result artifact
at `runs/<candidate_id>/<run_id>.json` (truncated for readability):

```json
{
  "gates": {
    "parse": {
      "ok": true,
      "detail": "LOADED_STEP_A:tool_versions=irx/experiment1/env/tool_versions.json;result_schema=irx/experiment1/harness/result_schema.json;constants=irx/experiment1/harness/constants.json;target=irx/experiment1/env/target.json;test_vectors=...;PRECHECK_PASS:...;LLVM_AS_PARSE_PASS"
    }
  }
}
```

The full detail string is a semicolon-delimited trace of every artifact loaded
during Step A, followed by the stage-specific suffix. Run artifacts are not
committed to git; reproduce via:

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

*Report last updated 2026-02-16 on Raspberry Pi 5. HEAD at time of writing: `d6ebc56`.*
