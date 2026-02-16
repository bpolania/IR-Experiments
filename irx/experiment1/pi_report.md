# IR Experiments — Experiment 1: Full Pipeline Verification on Raspberry Pi 5

This document is the authoritative technical report for Experiment 1 of the
IR Experiments project. It describes the complete design, implementation, and
verification of the Phase 2 pipeline — a gated evaluation system that takes
an LLVM IR candidate file, subjects it to structural analysis, interpretation,
native compilation, and native execution on real AArch64 hardware. The entire
pipeline runs on a Raspberry Pi 5, and every tool invocation is fully
deterministic and reproducible.

---

## 1. Revision History

| Commit | Date (PST) | Milestone |
|---|---|---|
| `960cebf` | 2026-02-15 19:39 | Add frozen `id_rules.json` authority for deterministic IDs |
| `add9dc8` | 2026-02-15 19:48 | Implement Step F `llc_compile` gate with artifact-first handling |
| `b1679b0` | 2026-02-15 21:32 | Fix opt syntax, target triple key, schema detection, wire lli harness |
| `31223ce` | 2026-02-15 22:16 | Fix sum_u32_le t08 `expected_out_hex` endianness (unblocks Step F) |
| `1153420` | 2026-02-15 22:18 | Add verification fixture directory and run instructions |
| `f0a6261` | 2026-02-15 22:28 | Add Step F evidence bundle and `step_f_check.sh` |
| `b0d8cd9` | 2026-02-15 23:02 | Implement Step G `clang_link` (freestanding ELF linking) |
| `a5d84da` | 2026-02-15 23:32 | Implement Step H `native_tests`, extend result schema with native metrics |
| `5201dd2` | 2026-02-15 23:41 | Add `PHASE2_CLOSURE.md` and `step_h_check_20260215_234036.log` |
| `8762240` | 2026-02-15 23:55 | Fix verdict computation from stage outcomes (`compute_verdict()`) |
| `b104ff5` | 2026-02-16 00:48 | Documentation accuracy pass (stage lettering, native loader description) |
| `d6ebc56` | 2026-02-16 01:02 | Fix milestone attribution, correct evidence log HEAD values |
| `5f55ce6` | 2026-02-16 01:19 | Fix ABI return type documentation (`i32` to `i64`), add `LOADED_STEP_A` example |

---

## 2. Platform and Toolchain

### 2.1 Hardware

The experiment runs on a Raspberry Pi 5 equipped with a Broadcom BCM2712
system-on-chip. The BCM2712 integrates four Arm Cortex-A76 cores implementing
the ARMv8.2-A architecture in little-endian (AArch64) mode. The Cortex-A76 is
a superscalar, out-of-order core with separate L1 instruction and data caches
(64 KB L1I, 64 KB L1D per core). This split-cache architecture has a direct
consequence for the pipeline: after copying executable code into memory, the
native ELF loader must explicitly flush the instruction cache to guarantee
coherence between what was written via the data cache and what will be fetched
into the instruction cache (see Section 8.6).

### 2.2 Operating System

The board runs Raspberry Pi OS 64-bit, a Debian-based distribution. The
kernel is version 6.12.47+rpt-rpi-2712, configured with SMP PREEMPT. The
frozen target triple for all compilation stages is
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

All five LLVM tools are sourced from a single Debian LLVM 19.1.7 installation
at `/usr/lib/llvm-19/bin/`. Each tool path and its version string are frozen
in `irx/experiment1/env/tool_versions.json`. The runner reads tool paths
exclusively from this frozen file — it never searches `$PATH`, never uses
`which`, and never employs any other discovery mechanism.

| Tool | Frozen Path | Version |
|---|---|---|
| llvm-as | `/usr/lib/llvm-19/bin/llvm-as` | Debian LLVM 19.1.7, Optimized build |
| opt | `/usr/lib/llvm-19/bin/opt` | Debian LLVM 19.1.7, Optimized build |
| lli | `/usr/lib/llvm-19/bin/lli` | Debian LLVM 19.1.7, Optimized build |
| llc | `/usr/lib/llvm-19/bin/llc` | Debian LLVM 19.1.7, Optimized build |
| clang | `/usr/lib/llvm-19/bin/clang` | Debian clang 19.1.7 (3+b1) |

The `opt` and `llc` version strings additionally report the host CPU as
`cortex-a76` and the default target as `aarch64-unknown-linux-gnu`. The
`clang` version string reports the thread model as `posix` and the installed
directory as `/usr/lib/llvm-19/bin`. All five tools dynamically link against
`libLLVM.so.19.1`, located in the sibling `/usr/lib/llvm-19/lib/` directory.

---

## 3. Pipeline Architecture

### 3.1 Overview

The Phase 2 runner is implemented as a single Python module at
`runner/phase2/phase2_runner.py` (1972 lines). It ingests a candidate LLVM IR
file (`.ll`), evaluates it against frozen test vectors, and writes a
structured JSON result artifact. The pipeline follows an A-through-H step
convention:

- **Step A** (initialization) loads five categories of frozen artifacts: tool
  paths, result schema, constants and limits, target triple, and all task test
  vectors. It computes the deterministic candidate and run identifiers. It
  emits a `LOADED_STEP_A:` prefix string into every gate detail field
  (line 1440 of `phase2_runner.py`), recording the paths of every artifact
  loaded. This prefix is present in all four `gates.parse.detail`,
  `gates.verify.detail`, `gates.tests.detail`, and `gates.policy.detail`
  fields of every produced result JSON.

- **Steps B through H** are the seven sequential execution stages. Each stage
  must succeed before the next is allowed to run.

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

| Stage | Preconditions |
|---|---|
| B (precheck) | Always runs |
| C (llvm_as_parse) | B passed |
| D (opt_verify) | B, C passed; `candidate.bc` exists and non-empty |
| E (lli_tests) | B, C, D passed; `candidate.bc` exists and non-empty |
| F (llc_compile) | B, C, D, E passed; `candidate.bc` exists and non-empty |
| G (clang_link) | B, C, D, E, F passed; `candidate.o` exists and non-empty |
| H (native_tests) | B, C, D, E, F, G passed; `candidate.exe` exists and non-empty |

If any stage fails, all downstream stages are skipped. Their `runs` records
remain at skeleton defaults (`ok=False`, `exit_code=null`, `duration_ms=0`,
`crash=null`), and their detail strings record
`<STAGE>_NOT_RUN:preconditions_failed`. A candidate must clear all seven
execution stages to receive a PASS verdict.

### 3.3 Subprocess Isolation

Every LLVM tool invocation runs in a fully deterministic subprocess. The
environment is cleared to empty and rebuilt with exactly four variables:

```
LC_ALL=C
LANG=C
TZ=UTC
LD_LIBRARY_PATH=/usr/lib/llvm-19/lib
```

The `LD_LIBRARY_PATH` is derived from the frozen tool path by computing the
sibling `lib/` directory (see `_derive_llvm_lib_path` at line 680,
`_build_llvm_tool_env` at line 699). The `LC_ALL=C` and `LANG=C` eliminate
locale-dependent formatting. The `TZ=UTC` eliminates timezone drift in
timestamps. The cleared parent environment prevents shell contamination.

Resource limits use `RLIMIT_RSS` only. `RLIMIT_AS` (virtual address space)
is deliberately avoided because `libLLVM.so.19.1` maps approximately 123 MB
of virtual address space on load and would immediately trip any reasonable AS
limit. The frozen RSS limit is 64 MiB. Each subprocess starts in its own
process group (`start_new_session=True`) for clean timeout kills.

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
encoded as UTF-8. Because the run_id depends solely on the candidate_id, the
same candidate file always produces the same identifier pair regardless of
when, where, or how many times the pipeline runs. The result artifact is
written to `runs/<candidate_id>/<run_id>.json` with work products alongside
in a `work/` subdirectory.

---

## 4. Frozen Artifacts

The pipeline reads five categories of frozen artifacts at initialization.
All are committed to the repository and never modified at runtime.

### 4.1 Tool Versions (`irx/experiment1/env/tool_versions.json`)

Lists the five required LLVM binaries, each with a `detected` entry containing
the frozen filesystem path, a boolean `ok` flag, the raw `version_text`, and
an `error` field (null for all five tools on this platform).

### 4.2 Target (`irx/experiment1/env/target.json`)

Records the compilation target. The `triple` field
(`aarch64-unknown-linux-gnu`) is used as the `-mtriple` argument to `llc` in
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
failure. This signature is the authoritative ABI. It is used consistently
across every executable component:

| Location | File | Line | Text |
|---|---|---|---|
| lli shim declaration | `harness/lli_shim/shim.ll` | 366 | `declare i64 @f(ptr noundef, i32 noundef, ptr noundef, i32 noundef)` |
| lli shim call site | `harness/lli_shim/shim.ll` | 158 | `%90 = call i64 @f(...)` |
| lli harness docstring | `harness/lli_abi_runner.py` | 6 | `i64 @f(i8* %in_ptr, i32 %in_len, i8* %out_ptr, i32 %out_cap)` |
| Native harness typedef | `harness/native/native_runner.c` | 32 | `typedef int64_t (*candidate_fn)(uint8_t *, int32_t, uint8_t *, int32_t)` |
| Known-good candidate | `verification/step_f/sum_u32_le_good.ll` | 4 | `define i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap)` |

**Known discrepancy.** The `signature_ir` field inside `constants.json` and
the three `tasks/*/spec.json` files contains a stale `i32` return type from
an earlier draft (`"i32 @f(i8* %in_ptr, i32 %in_len, i8* %out_ptr, i32 %out_cap)"`).
The runner never reads this field — it is purely documentary. No runtime
behavior is affected. The authoritative return type is `i64`, as proven by
the five locations above.

#### 4.3.2 Error Codes

| Code | Name | Meaning |
|---|---|---|
| -1 | ERR_INVALID_INPUT | Malformed, out-of-range, or rejected input |
| -2 | ERR_OUTPUT_TOO_SMALL | Output buffer capacity insufficient |
| -3 | ERR_INTERNAL | Unexpected internal failure |

#### 4.3.3 Resource Limits

| Limit | Value | Used by |
|---|---|---|
| max_ll_bytes | 65536 | Step B precheck |
| max_ll_lines | 2000 | Step B precheck |
| max_basic_blocks | 200 | Reserved, not currently enforced |
| max_instructions | 20000 | Reserved, not currently enforced |
| max_alloca_bytes_total | 4096 | Reserved, not currently enforced |
| timeout_stage_ms | 1000 | Steps C, D, F, G (per-stage timeout) |
| timeout_per_test_ms | 50 | Steps E, H (per-test-vector timeout) |
| max_rss_mib | 64 | All subprocess stages |
| max_input_bytes | 65536 | Input buffer size cap |
| max_output_bytes | 65536 | Output buffer size cap |

#### 4.3.4 Crash Type Taxonomy

Ten categories: `SIGSEGV`, `SIGILL`, `SIGABRT`, `SIGFPE`, `TIMEOUT`, `OOM`,
`SANITIZER_FINDING`, `POLICY_VIOLATION`, `VERIFY_FAIL`, `PARSE_FAIL`. Each
stage maps its failure modes into this taxonomy for uniform reporting in the
`runs[].crash` field.

### 4.4 Result Schema (`irx/experiment1/harness/result_schema.json`)

A JSON Schema (draft 2020-12) validated against every result artifact before
it is written to disk. The schema uses `additionalProperties: false` at every
level, meaning no undeclared fields are permitted.

**Top-level required fields:** `experiment`, `task`, `candidate_id`, `run_id`,
`timestamps`, `gates`, `runs`, `metrics`, `verdict`.

**`verdict`** is constrained to the enum `["PASS", "FAIL", "ERROR"]`.

**`gates`** has four required sub-objects (`parse`, `verify`, `policy`,
`tests`), each with `ok` (boolean) and `detail` (string or null).

**`runs`** is an array of per-stage records: `stage`, `ok`, `exit_code`,
`duration_ms`, `rss_mib`, `crash`. The `crash` field is null or an object
with `type` (constrained to the crash taxonomy), `signal`, and `detail`.

**`metrics`** contains 14 counters — seven for lli execution (`tests_total`,
`tests_passed`, `tests_failed`, `ret_mismatches`, `output_mismatches`,
`timeouts`, `crashes`) and seven mirrored for native execution
(`native_tests_total` through `native_crashes`). The native counters and the
`native_test_results` array were added in commit `a5d84da` with the Step H
implementation.

**`test_results`** and **`native_test_results`** are arrays of per-vector
records: `index`, `in_hex`, `out_cap`, `expected_ret`, `expected_out_hex`,
`actual_ret`, `actual_out_hex`, `outcome`, `exit_code`, `signal`, `detail`.
The `outcome` field is constrained to `["PASS", "RETURN_MISMATCH",
"OUTPUT_MISMATCH", "UNEXPECTED_CRASH", "TIMEOUT", "OOM"]`.

### 4.5 ID Rules (`irx/experiment1/harness/id_rules.json`)

Defines the two derivation rules described in Section 3.4.

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
rejection).

**Test vectors (10):**

| ID | Input (hex) | out_cap | Expected ret | Expected output (hex) | Purpose |
|---|---|---|---|---|---|
| t01 | (empty) | 4 | 4 | `00000000` | Zero elements, zero sum |
| t02 | `01000000` | 4 | 4 | `01000000` | Single element identity |
| t03 | `ffffffff` | 4 | 4 | `ffffffff` | Maximum uint32 |
| t04 | `0100000002000000` | 4 | 4 | `03000000` | Two-element addition (1+2=3) |
| t05 | `0000000000000000` | 4 | 4 | `00000000` | Two zero elements |
| t06 | `78563412` | 4 | 4 | `78563412` | Byte-order verification (0x12345678 LE) |
| t07 | `01000000ffffffff` | 4 | 4 | `00000000` | Overflow wrap (1 + 0xFFFFFFFF = 0) |
| t08 | `ffffffffffffffff` | 4 | 4 | `feffffff` | Double-max wrap (0xFFFFFFFE LE) |
| t09 | `00000000ffffffff01000000` | 4 | -1 | (empty) | Three-element rejection |
| t10 | `01000000020000000300000004000000` | 4 | 4 | `0a000000` | Four-element sum (1+2+3+4=10) |

**Test vector correction.** Vector t08 originally had `expected_out_hex` set
to `"fffffffe"`, which is big-endian for 0xFFFFFFFE. The correct little-endian
encoding is `"feffffff"`. This was a single-field change in
`tasks/sum_u32_le/tests.json`, committed as `31223ce` (2026-02-15 22:16 PST).
No other vectors, fields, or files were modified. The error was discovered
during Step F verification when the candidate produced the correct
little-endian bytes but the vector expected the reversed order.

### 5.2 hex_encode

**Contract.** Converts each input byte to two lowercase hexadecimal ASCII
characters. Output length is exactly `2 * in_len` bytes. Returns the byte
count written on success, or -2 if `out_cap < 2 * in_len`.

**Test vectors (10):** Empty input (returns 0), single zero byte (0x00 ->
ASCII "00" = `3030`), 0x01 -> `3031`, 0x0F -> `3066`, insufficient output
capacity (returns -2), 0xFF -> `6666`, 4-byte DEADBEEF, 3-byte 0x123456,
10-byte sequence 0x00-0x09, and 5-byte ASCII "Hello" (0x48656c6c6f).

### 5.3 parse_u32_decimal

**Contract.** Parses a decimal ASCII string (digits 0x30-0x39) into a
little-endian uint32. Returns 4 on success. Returns -1 on error: empty input,
non-digit characters, or overflow beyond 4294967295. The overflow check uses
`acc > 429496729 || (acc == 429496729 && digit > 5)`.

**Test vectors (10):** Single zero digit, single non-zero digit ("5"),
two-digit number ("10"), leading zeros ("0003"), maximum uint32
("4294967295"), overflow by one ("4294967296"), empty input, negative sign
prefix ("-1"), large valid number ("1234567890"), embedded non-digit ("123x").

---

## 6. Known-Good Candidate

A verified known-good candidate for sum_u32_le is provided at
`irx/experiment1/verification/step_f/sum_u32_le_good.ll`. This is a 42-line
LLVM IR file targeting `aarch64-unknown-linux-gnu`. It defines a single
exported function `@f(ptr, i32, ptr, i32) -> i64` that:

1. Validates `in_len % 4 == 0` (rejects with `ret i64 -1` otherwise)
2. Validates `out_cap >= 4` (rejects otherwise)
3. Validates element count is not exactly 3 (rejects otherwise)
4. If zero elements, stores zero to the output buffer and returns 4
5. Otherwise loops with phi nodes (`%i` for index, `%sum` for accumulator),
   reading each element as `load i32, ptr %elem_ptr, align 1`
6. Accumulates with wrapping `add i32`
7. Stores the result via `store i32 %result, ptr %out_ptr, align 1` and
   returns 4

The loop computes byte offsets via `getelementptr i8` with `%i * 4`
zero-extended to i64. The exit condition is `icmp eq i32 %i_next, %n`.

Deterministic IDs (confirmed stable across all runs):

```
candidate_id: de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6
run_id:       4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60
```

No known-good candidates exist yet for hex_encode or parse_u32_decimal.

---

## 7. Pipeline Stages in Detail

### 7.1 Step B: Precheck

Enforces two size limits from `constants.json`: max 65536 bytes and max 2000
lines. Lines are counted by newline characters plus one if the file does not
end with a newline. Runs entirely in-process (no subprocess). On success for
the known-good candidate: `PRECHECK_PASS:bytes=1232/65536;lines=42/2000`.

### 7.2 Step C: llvm_as_parse

Assembles the candidate into LLVM bitcode:

```
llvm-as candidate.ll -o candidate.bc
```

Resolved from `tool_versions.json` key `detected.llvm-as.path`. Runs in a
clean subprocess with the deterministic four-variable environment. On exit
code 0 with non-empty output: `LLVM_AS_PARSE_PASS`. On timeout, signal,
OOM, or nonzero exit: appropriate crash taxonomy type.

### 7.3 Step D: opt_verify

Runs the LLVM module verifier:

```
opt -passes=verify candidate.bc -o /dev/null
```

Resolved from `detected.opt.path` (fallback `detected.llvm-opt.path`).
Checks structural correctness: instruction operand types, basic block
termination, SSA dominance, and other LLVM IR invariants.

### 7.4 Step E: lli_tests

Interprets the candidate via the LLVM JIT against frozen test vectors. The
runner discovers the lli ABI harness by scanning `irx/experiment1/harness/`
and `irx/experiment1/` for a pattern bundle (references to `lli`, `@f`,
`candidate.bc`, test vector fields, subprocess patterns). The chosen harness
is `irx/experiment1/harness/lli_abi_runner.py`, which invokes the frozen lli
shim (`harness/lli_shim/shim.bc`) linked with `candidate.bc` as an extra
module.

For each vector, lli executes the shim which calls `@f` with the decoded
input, captures `RET=<decimal>` and `OUT=<hex>` from stdout. A test passes
if `actual_ret == expected_ret` and `actual_out_hex == expected_out_hex`.
Mismatches yield `RETURN_MISMATCH` or `OUTPUT_MISMATCH`. Per-test timeout
is 50 ms. The stage passes only if all vectors pass.

### 7.5 Step F: llc_compile

Compiles bitcode to a native relocatable object:

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

Links the object into a freestanding ELF executable:

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

Executes test vectors against the linked executable using a custom in-process
ELF loader. This proves that the candidate produces correct native AArch64
machine code — not just correct results under interpretation.

The runner locates the harness source at
`irx/experiment1/harness/native/native_runner.c` (421 lines). If not already
built, it compiles the harness using the frozen clang path. The binary is
cached at `irx/experiment1/harness/native/native_runner`. A selftest
(`--selftest`) validates hex encode/decode before any candidate execution.

For each vector:

```
native_runner <candidate.exe> <in_hex> <out_cap> f
```

The harness loads the ELF, resolves symbol `f`, calls it, prints
`RET=<decimal>` and `OUT=<hex>`. The runner parses output and builds
per-vector result records identical in structure to lli results. The stage
passes only if all vectors pass.

---

## 8. Native ELF Loader

The `native_runner.c` (421 lines) implements a minimal ELF64 loader and test
executor in pure C. Its sole dependency is libc — no dlopen, no libelf, no
LLVM runtime. The `load_elf()` function (line 115) performs the following
sequence:

### 8.1 File Mapping

The ELF file is memory-mapped read-only for header parsing:

```c
uint8_t *fdata = mmap(NULL, file_size, PROT_READ, MAP_PRIVATE, fd, 0);
```

The file descriptor is closed immediately after mapping (line 136).

### 8.2 Header Validation

Verifies ELF magic (`\x7fELF`), 64-bit class (`ELFCLASS64`), little-endian
encoding (`ELFDATA2LSB`), and machine type (`EM_AARCH64`) at lines 145-148.
Both `ET_EXEC` and `ET_DYN` types are accepted (line 152).

### 8.3 Address Span Computation

Scans all `PT_LOAD` segments to find minimum and maximum virtual addresses
(lines 166-176). Both bounds are page-aligned using `sysconf(_SC_PAGESIZE)`:
`vmin` rounded down, `vmax` rounded up (lines 182-186).

### 8.4 Region Reservation

Reserves a single contiguous anonymous region at a kernel-chosen address:

```c
uint8_t *base = mmap(NULL, map_size, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
```

No `MAP_FIXED` is used (line 189). All subsequent address references are
rebased: virtual address `va` in the ELF maps to `base + (va - vmin)`.

### 8.5 Segment Copy

Each `PT_LOAD` segment's file-backed data is copied:

```c
memcpy(base + (va - vmin), fdata + off, (size_t)fsz);
```

BSS portions (`p_memsz > p_filesz`) are zero-filled with `memset` (line 212).

### 8.6 Instruction Cache Coherence

```c
__builtin___clear_cache((char *)base, (char *)(base + map_size));
```

Mandatory on AArch64 where the I-cache and D-cache are not coherent. Without
this call, the CPU could execute stale or garbage instructions from the
I-cache after code was written via the D-cache.

### 8.7 Permission Hardening

A second pass applies per-segment `mprotect` calls (lines 219-238). Segment
VA and size are page-aligned before the call. Code segments (`PF_X`) become
`PROT_READ|PROT_EXEC`. Data segments (`PF_W`) become `PROT_READ|PROT_WRITE`.
Read-only data becomes `PROT_READ` only.

### 8.8 Relocation Rejection

Section headers are scanned for `SHT_RELA` and `SHT_REL`. If any non-empty
relocation section exists, the loader rejects the binary (lines 241-252).
This is a fail-closed safety check: freestanding candidates from Step G use
only PC-relative addressing and contain no relocations.

### 8.9 Symbol Resolution

Searches `.symtab` (not `.dynsym`) for an `STT_FUNC` symbol matching the
requested name (lines 254-283). Function pointer: `base + (st_value - vmin)`.
Only the first `.symtab` is processed. Fallback: ELF entry point `e_entry`
when the symbol is `f` (lines 286-288).

### 8.10 Invocation

The resolved pointer is cast to `int64_t (*)(uint8_t*, int32_t, uint8_t*, int32_t)` and called directly (lines 393-397). Output: `RET=<signed decimal>`
and `OUT=<lowercase hex>` on stdout. Exit code 0 for all semantic results;
nonzero only for harness usage errors.

### 8.11 Design Rationale

The loader rebases all addresses relative to an anonymous region instead of
using `MAP_FIXED` at ELF-specified addresses. This avoids conflicts with the
loader's own address space. It works because freestanding candidates contain
no absolute-address relocations — only PC-relative code. The relocation
rejection check (Section 8.8) is the safety net: if a candidate contained
relocations the rebasing would break, the loader refuses to execute it.

### 8.12 Selftest

The `--selftest` flag validates hex encode/decode with a roundtrip test:
decode `"0123456789abcdef"` to bytes, re-encode, verify match. Also tests
empty-string roundtrip and odd-length rejection. The runner invokes selftest
on first use per pipeline run and caches the result.

---

## 9. Verdict Computation

The `compute_verdict()` function (line 73 in `phase2_runner.py`) derives a
final verdict from the `runs` array, `metrics` object, and `gates` object.
It returns a `(verdict_str, detail_str)` tuple.

**Decision procedure:**

1. **Identify executed stages.** A stage counts as "executed" if it has a
   non-null `exit_code`, positive `duration_ms`, or non-null `crash`. Gated
   stages at skeleton defaults are excluded.

2. **Stage failures.** If any executed stage has `ok=False`: **FAIL** with
   `STAGE_FAILED:<stage_name>`.

3. **lli test failures.** If `metrics.tests_failed > 0`: **FAIL** with
   `LLI_TESTS_FAILED`.

4. **Native test failures.** If `metrics.native_tests_failed > 0`: **FAIL**
   with `NATIVE_TESTS_FAILED`.

5. **No execution.** If no stages executed: **ERROR** with
   `NO_STAGES_EXECUTED`.

6. **Full pass.** If every stage has `ok=True` and both test failure counts
   are zero or absent: **PASS** with `ALL_STAGES_PASS`.

7. **Otherwise:** **ERROR** with `INDETERMINATE_VERDICT`.

After computation, `gates.policy.ok` is set to `true` when verdict is PASS,
`false` otherwise (line 1885). The verdict detail is appended to
`gates.policy.detail` (line 1886).

This logic was introduced in commit `8762240` (2026-02-15 23:55 PST),
replacing an earlier implementation where the verdict was unconditionally
`"ERROR"` and `gates.policy.ok` was always `false`. The fix was necessary
because even candidates passing all stages received ERROR verdicts. The fix
is covered by 8 unit tests exercising every branch.

---

## 10. Regression Sweep

A three-task regression sweep was executed on 2026-02-16 at HEAD `8563fd2`
(timestamp `2026-02-16T08:34:39Z`). The sweep ran the full A-H pipeline for
each task, validated every result JSON against the schema, and compared
verdicts against expectations. Evidence log:
`irx/experiment1/verification/evidence/logs/regression_sweep_20260216_003439.log`.

### 10.1 sum_u32_le — PASS (expected PASS)

All seven stages pass. Both lli and native produce bitwise-identical results
across all 10 vectors.

| Stage | ok | exit_code |
|---|---|---|
| precheck | true | -- |
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

### 10.2 hex_encode — FAIL (expected FAIL)

The sum_u32_le candidate run as a stub against hex_encode vectors. Steps B-D
pass (structurally valid IR). Step E: all 10 vectors fail (sums, not hex).
Steps F-H gated out.

| Stage | ok | exit_code |
|---|---|---|
| precheck | true | -- |
| llvm_as_parse | true | 0 |
| opt_verify | true | 0 |
| lli_tests | false | 1 |
| llc_compile | false | -- |
| clang_link | false | -- |
| native_tests | false | -- |

- lli: 0/10 passed, 10 failed
- verdict: FAIL, gates.policy.ok: false, schema: OK

### 10.3 parse_u32_decimal — FAIL (expected FAIL)

Same stub candidate. Steps B-D pass. Step E: 8 of 10 fail. Two pass by
coincidence (input/output pairs where sum happens to match parse expectations).
Steps F-H gated out.

| Stage | ok | exit_code |
|---|---|---|
| precheck | true | -- |
| llvm_as_parse | true | 0 |
| opt_verify | true | 0 |
| lli_tests | false | 1 |
| llc_compile | false | -- |
| clang_link | false | -- |
| native_tests | false | -- |

- lli: 2/10 passed, 8 failed
- verdict: FAIL, gates.policy.ok: false, schema: OK

### 10.4 Conclusions

All three artifacts pass schema validation. Verdict computation correctly
yields PASS for correct candidate on its own task and FAIL for wrong candidate
on a different task. Gating prevents native compilation and execution of
candidates that fail interpretation.

---

## 11. Unit Tests

Two hermetic suites validate runner internals without LLVM installed.

**test_native_tests.py** (140 lines, 13 tests) — Native result parsing,
per-vector construction, gating preconditions, selftest caching, error
handling. All mock-based.

**test_verdict.py** (200 lines, 8 tests) — Every `compute_verdict()` branch:
all-pass -> PASS, pass without native metrics -> PASS, failed stage -> FAIL,
precheck failure -> FAIL, lli failures -> FAIL, native failures -> FAIL, no
stages -> ERROR, partial execution -> FAIL.

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

The proof-chain log (`step_h_check_verdictfix_20260216_000503.log`) includes:
the result JSON path, verdict field extraction (`"verdict": "PASS"` at line
366), candidate_id and run_id match confirmation (both `True`), and `ls -l`
of all work artifacts (candidate.bc 1928 B, candidate.o 1008 B,
candidate.exe 2304 B).

---

## 13. Evidence Scripts

Two bash scripts automate reproducible evidence collection.

**step_h_check.sh** (`irx/experiment1/verification/evidence/step_h_check.sh`):
cleans run artifacts, syntax-checks the runner, runs the full A-H pipeline on
the known-good candidate, extracts tool environment lines, locates the result
JSON, prints a summary (per-stage ok/exit_code, lli and native counts, artifact
sizes, lli/native agreement).

**step_f_check.sh** (`irx/experiment1/verification/evidence/step_f_check.sh`):
same structure, limited to A-F evidence (no native summary, no candidate.exe).

---

## 14. LOADED_STEP_A Gate Detail

The `LOADED_STEP_A:` prefix is emitted at line 1440 of `phase2_runner.py`
into the `loaded_artifacts_detail` string, which is then prepended to every
gate detail field. The prefix records the relative path of every frozen
artifact loaded during initialization.

**Concrete example** from `gates.parse.detail` in a produced result artifact
(truncated):

```json
{
  "gates": {
    "parse": {
      "ok": true,
      "detail": "LOADED_STEP_A:tool_versions=irx/experiment1/env/tool_versions.json;result_schema=irx/experiment1/harness/result_schema.json;constants=irx/experiment1/harness/constants.json;target=irx/experiment1/env/target.json;test_vectors=...;PRECHECK_PASS:bytes=1232/65536;lines=42/2000;LLVM_AS_PARSE_PASS"
    }
  }
}
```

The full string is semicolon-delimited: artifact paths loaded in Step A,
followed by the stage-specific result suffix. This pattern is identical across
all four gate fields, with only the suffix differing per gate.

Run artifacts are not committed to git. To verify, reproduce with:

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

## 15. Verification Notes

### 15.1 Evidence Log HEAD Inference

**`regression_sweep_20260216_003439.log`**: HEAD `8563fd2` is explicit on
line 3 of the log (`HEAD: 8563fd275f8e73d58ad2ced6b507e1cc4b155da9`).

**`step_h_check_20260215_234036.log`**: No explicit HEAD. File mtime
23:40:37 PST. Commit `a5d84da` authored 23:32:47, next commit `5201dd2`
at 23:41:34. Log produced at HEAD `a5d84da` — a pre-closure run.

**`step_h_check_verdictfix_20260215_235338.log`**: No explicit HEAD. File
mtime 23:53:39 PST. Last committed HEAD: `f02c049` (23:47:29). The
uncommitted verdict fix (which became `8762240` at 23:55:29) was in the
working tree. Previous reports attributed this to `8762240`, but that commit
did not yet exist.

**`step_h_check_verdictfix_20260216_000503.log`**: No explicit HEAD. File
mtime 00:05:05 PST. Last committed HEAD: `b00ab95` (00:00:28). Next commit
`ef34058` at 00:17:03. Previous reports listed "post-`8762240`", imprecise.

### 15.2 ABI Discrepancy

The `signature_ir` field in `constants.json` and all three `spec.json` files
contains `i32 @f(...)`. Every executable artifact uses `i64 @f(...)`. The
runner never reads `signature_ir`. No runtime impact. The stale field should
be updated in a future housekeeping commit, but this is cosmetic.

---

## 16. Reproduction

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

Expected: verdict PASS, lli 10/10, native 10/10, all 10 agree, all seven
stages ok, schema passes. Artifacts: candidate.bc 1928 B, candidate.o 1008 B,
candidate.exe 2304 B.

---

*Report generated 2026-02-16 on Raspberry Pi 5. Latest commit at time of writing: `5f55ce6`.*
