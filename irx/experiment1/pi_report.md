# IR Experiments — Experiment 1 — Raspberry Pi Phase 2 Report

**Platform**: Raspberry Pi 5 (Cortex-A76, aarch64)
**OS**: Raspberry Pi OS 64-bit (Debian-based), kernel 6.12.47+rpt-rpi-2712
**LLVM**: Debian LLVM 19.1.7 (Optimized build)
**Target triple**: `aarch64-unknown-linux-gnu`
**Phase 2 closure**: 2026-02-15, HEAD `5201dd2`
**Current HEAD**: `8762240` (verdict fix)

---

## 1 Executive Summary

This report is the definitive record for Experiment 1, Phase 2 on Raspberry
Pi 5. It traces the project from a runner that could not even load the LLVM
shared library to a fully closed pipeline where interpreted and natively
compiled test results agree bitwise, and where the JSON artifact correctly
records `"verdict": "PASS"` when all stages succeed.

Ten milestones brought the pipeline to its current state:

1. **Environment fix** — llvm-as failed because the cleared subprocess
   lacked `LD_LIBRARY_PATH` and applied `RLIMIT_AS` at 64 MiB, far below
   what the 123 MB `libLLVM.so.19.1` requires for memory mapping. Fixed
   with deterministic library path derivation and RSS-only limiting.

2. **Re-verification** — Confirmed llvm-as and opt could execute, bitcode
   was produced, and runs were deterministic. opt_verify still failed
   (cause not yet identified).

3. **Full sweep** — Diagnosed and patched four gaps: opt's legacy `-verify`
   syntax (LLVM 19 requires `-passes=verify`), target triple key mismatch,
   broken `$ref` resolution in schema per-test detection, and a hardcoded
   lli_tests failure block. Steps A-E verified PASS.

4. **Authority revision** — A known-good candidate exposed a byte-order
   error in test vector t08. The expected value `"fffffffe"` was big-endian
   notation; the correct little-endian encoding is `"feffffff"`.
   Single-field correction applied.

5. **Step F evidence** — 10/10 lli_tests pass, llc_compile produces
   `candidate.o` (1 008 bytes, aarch64 ELF relocatable). Evidence bundle
   committed.

6. **Step G (clang_link)** — Links `candidate.o` into a freestanding ELF
   `candidate.exe` (2 304 bytes) using clang with LLD. Uses `-nostdlib
   -fuse-ld=lld -Wl,--no-dynamic-linker -Wl,-e,f` because the candidate
   exports only `@f` (no `main`, no `_start`).

7. **Step H (native_tests)** — A 421-line C harness loads the freestanding
   ELF in-process with a custom ELF64 loader, finds `f` in `.symtab`, and
   calls it with frozen test vectors. All 10 native tests pass with
   bitwise-identical results to lli. Schema extended with native fields.

8. **Phase 2 closure** — Clean re-run from cleared artifacts. All seven
   stages PASS, lli/native match ALL 10 vectors. Schema extension
   independently verified as committed. Closure record written.

9. **Verdict fix** — The JSON artifact previously hardcoded
   `"verdict": "ERROR"` because verdict was derived from `gates.policy.ok`
   which was always `False`. Replaced with `compute_verdict()`, a pure
   function that derives the verdict from actual stage outcomes and test
   metrics. The artifact now correctly records `"PASS"` when all stages
   succeed, `"FAIL"` when any stage or test fails, and `"ERROR"` when no
   stages execute.

**Final status**: Phase 2 complete. All seven stages PASS. Verdict is
`"PASS"`. Interpreter and native execution agree across all 10 test vectors.

---

## 2 Pipeline Architecture

### 2.1 Overview

The Phase 2 runner (`runner/phase2/phase2_runner.py`) accepts a `.ll`
candidate, derives deterministic SHA-256 IDs, then executes seven stages in
a fixed sequence. Each stage gates on all prior stages passing. Results are
recorded in a schema-validated JSON artifact under
`irx/experiment1/runs/<candidate_id>/<run_id>.json`.

### 2.2 Stage Sequence

| Index | Stage | Tool | Precondition |
|-------|-------|------|--------------|
| 0 | `precheck` | static analysis | — |
| 1 | `llvm_as_parse` | `llvm-as` | precheck.ok |
| 2 | `opt_verify` | `opt -passes=verify` | llvm_as_parse.ok, candidate.bc exists |
| 3 | `lli_tests` | `lli` + shim harness | opt_verify.ok, harness resolved |
| 4 | `llc_compile` | `llc -filetype=obj` | lli_tests.ok, candidate.bc exists |
| 5 | `clang_link` | `clang` + LLD | llc_compile.ok, candidate.o exists |
| 6 | `native_tests` | native harness | clang_link.ok, candidate.exe exists |

All LLVM tools are at `/usr/lib/llvm-19/bin/`.

### 2.3 ID Derivation

Frozen rules in `harness/id_rules.json`:

- `candidate_id = sha256(candidate.ll file bytes).hexdigest()`
- `run_id = sha256(candidate_id as UTF-8 string).hexdigest()`

### 2.4 Subprocess Environment

LLVM tool subprocesses run with a cleared environment:

```
LC_ALL=C  LANG=C  TZ=UTC  LD_LIBRARY_PATH=/usr/lib/llvm-19/lib
```

`LD_LIBRARY_PATH` derived deterministically from the frozen tool path
(`parent.parent / lib`). No host variables consulted.

The `clang_link` stage adds `-fuse-ld=lld` so clang finds its colocated
LLD linker without `PATH`.

The `native_tests` stage uses three variables only (`LC_ALL=C`, `LANG=C`,
`TZ=UTC`) — no `LD_LIBRARY_PATH` needed since the harness depends only on
libc.

### 2.5 Resource Limits

`RLIMIT_RSS` applied at 64 MiB. `RLIMIT_AS` intentionally not applied
because `libLLVM.so.19.1` (123 MB) requires virtual memory well beyond
64 MiB for its mappings.

### 2.6 Verdict Computation

The `compute_verdict(runs, metrics, gates)` function derives the verdict
from actual stage outcomes:

```
executed = stages where exit_code is not None, duration_ms > 0, or crash is not None

if any executed stage has ok=False     -> ("FAIL", "STAGE_FAILED:<stage>")
if metrics.tests_failed > 0           -> ("FAIL", "LLI_TESTS_FAILED")
if metrics.native_tests_failed > 0    -> ("FAIL", "NATIVE_TESTS_FAILED")
if no stages executed                  -> ("ERROR", "NO_STAGES_EXECUTED")
if all runs ok and zero test failures  -> ("PASS", "ALL_STAGES_PASS")
otherwise                              -> ("ERROR", "INDETERMINATE_VERDICT")
```

The verdict detail string is appended to `gates.policy.detail` (schema is
`additionalProperties: false` at top level, so no new keys can be added).
`gates.policy.ok` is set to `True` when verdict is `"PASS"`.

---

## 3 Frozen Artifact Inventory

### 3.1 Tool Versions (`env/tool_versions.json`)

| Tool | Frozen Path | Version |
|------|-------------|---------|
| llvm-as | `/usr/lib/llvm-19/bin/llvm-as` | 19.1.7 |
| opt | `/usr/lib/llvm-19/bin/opt` | 19.1.7 |
| lli | `/usr/lib/llvm-19/bin/lli` | 19.1.7 |
| llc | `/usr/lib/llvm-19/bin/llc` | 19.1.7 |
| clang | `/usr/lib/llvm-19/bin/clang` | 19.1.7 (Debian) |

All present, executable, owned by root. `opt` and `llc` entries include host
CPU `cortex-a76` and target triple confirmation.

### 3.2 Limits (`harness/constants.json`)

| Limit | Value | Enforced at |
|-------|-------|-------------|
| `max_ll_bytes` | 65 536 | precheck |
| `max_ll_lines` | 2 000 | precheck |
| `max_basic_blocks` | 200 | reserved |
| `max_instructions` | 20 000 | reserved |
| `max_alloca_bytes_total` | 4 096 | reserved |
| `timeout_stage_ms` | 1 000 | llvm_as, opt, llc, clang |
| `timeout_per_test_ms` | 50 | lli_tests, native_tests |
| `max_rss_mib` | 64 | all tool stages |
| `max_input_bytes` | 65 536 | reserved |
| `max_output_bytes` | 65 536 | reserved |

Error codes: `ERR_INVALID_INPUT` (-1), `ERR_OUTPUT_TOO_SMALL` (-2),
`ERR_INTERNAL` (-3).

### 3.3 Target (`env/target.json`)

```json
{"os": "raspios64", "arch": "aarch64", "triple": "aarch64-unknown-linux-gnu", "endian": "little"}
```

Key is `triple`, not `target_triple`. Runner accepts both.

### 3.4 ID Rules (`harness/id_rules.json`)

```json
{
  "candidate_id": {"algo": "sha256_file_bytes", "input": "candidate.ll"},
  "run_id": {"algo": "sha256_utf8", "input": "candidate_id"}
}
```

### 3.5 Result Schema (`harness/result_schema.json`)

Required top-level keys: `experiment`, `task`, `candidate_id`, `run_id`,
`timestamps`, `gates`, `runs`, `metrics`, `verdict`.

Optional arrays: `test_results` (lli) and `native_test_results` (native),
both of `$defs.testResult` objects with 11 required fields.

The `metrics` object carries seven required lli counters and seven optional
native counters. The schema uses `additionalProperties: false` throughout,
so the native fields required explicit addition (commit `a5d84da`). The
`verdict` field is an enum: `"PASS"`, `"FAIL"`, or `"ERROR"`.

### 3.6 ABI Harness (lli)

- Entrypoint: `harness/lli_abi_runner.py`
- Shim: `harness/lli_shim/shim.bc`
- Candidate ABI: `i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap)`
- Protocol: `RET=<i64>` and `OUT=<hex>` on stdout

### 3.7 Native Harness

- Source: `harness/native/native_runner.c` (421 lines)
- Binary: `harness/native/native_runner` (13 064 bytes, built by runner)
- Protocol: identical to lli shim
- Dependencies: libc only

### 3.8 Test Vectors

| Task | File | Vectors |
|------|------|---------|
| sum_u32_le | `tasks/sum_u32_le/tests.json` | 10 |
| hex_encode | `tasks/hex_encode/tests.json` | present |
| parse_u32_decimal | `tasks/parse_u32_decimal/tests.json` | present |

---

## 4 Generation 1: Environment Fix

### 4.1 Failure

```
rc=127; stderr: error while loading shared libraries: libLLVM.so.19.1:
failed to map segment from shared object
```

Root causes: (1) no `LD_LIBRARY_PATH` in cleared subprocess, (2) `RLIMIT_AS`
at 64 MiB too low for the 123 MB library.

### 4.2 Fix

- `_derive_llvm_lib_path` / `_build_llvm_tool_env` — deterministic
  `LD_LIBRARY_PATH` from `parent.parent / lib`
- `_build_llvm_tool_preexec` — `RLIMIT_RSS` only, not `RLIMIT_AS`

---

## 5 Generation 2: Re-verification

All checks passed: `py_compile`, tool paths, precheck, llvm_as_parse,
candidate.bc production, determinism. opt_verify failed (cause identified
later).

---

## 6 Generation 3: Full Sweep

### 6.1 Four Gaps

1. `opt -verify` — legacy syntax, LLVM 19 requires `-passes=verify`
2. `target_triple` key — frozen file uses `triple`
3. Schema `$ref` resolution — checked `test_id` instead of `index`
4. lli_tests — hardcoded failure block prevented harness invocation

### 6.2 Patches

All four to `phase2_runner.py` only. Steps A-E verified PASS. Stub
candidate correctly fails 10/10 tests, gating downstream.

---

## 7 Generation 4: Authority Revision — t08 Byte Order

For input `ffffffffffffffff`:

```
0xFFFFFFFF + 0xFFFFFFFF = 0xFFFFFFFE (mod 2^32)
LE bytes: [FE, FF, FF, FF] -> "feffffff"
```

Original expected `"fffffffe"` was big-endian. All other vectors used LE.
Single-field correction in `tests.json` (commit `31223ce`).

---

## 8 Generation 5: Step F — llc_compile

Known-good candidate `sum_u32_le_good.ll` (42 lines, 1 232 bytes) achieved
10/10 lli_tests. llc produced `candidate.o` (1 008 bytes).

```
llc -filetype=obj -mtriple=aarch64-unknown-linux-gnu -O0 -o candidate.o candidate.bc
```

---

## 9 Generation 6: Step G — clang_link

### 9.1 Challenge

Candidate exports only `@f`. A bare `clang -o` fails: no `_start`.

### 9.2 Solution

```
clang -target aarch64-unknown-linux-gnu -fuse-ld=lld -nostdlib \
      -Wl,--no-dynamic-linker -Wl,-e,f -o candidate.exe candidate.o
```

`-fuse-ld=lld` required because the deterministic environment has no `PATH`.
Clang spawns a child linker and needs to find it — with this flag it uses
its colocated `ld.lld`.

### 9.3 Result

`candidate.exe` produced (2 304 bytes), minimal freestanding ELF with `f`
as entry point.

---

## 10 Generation 7: Step H — native_tests

### 10.1 Challenge

`dlopen`/`dlsym` cannot work: `f` is in `.symtab` only, not `.dynsym`.
A custom ELF loader was required.

### 10.2 Native Harness (`native_runner.c`)

421-line C program:

1. Memory-maps the ELF read-only for header parsing
2. Validates: ELF64, LSB, aarch64, no relocations
3. Accepts both `ET_EXEC` and `ET_DYN` (PIE) types
4. Computes `PT_LOAD` extent, reserves anonymous memory, copies segments
5. `__builtin___clear_cache` — aarch64 has non-coherent I/D caches; newly
   loaded code must be flushed to the instruction fetch unit
6. `mprotect` per-segment from `p_flags`
7. Symbol lookup in `.symtab` via linked string table; entry point fallback
8. Casts to `int64_t (*)(uint8_t*, int32_t, uint8_t*, int32_t)`, calls,
   prints `RET=`/`OUT=`

### 10.3 Build

```
clang -O2 -Wall -Wextra -Werror -std=c11 -fno-omit-frame-pointer \
      -fuse-ld=lld -o native_runner native_runner.c
```

Cached (mtime-based), selftest after every build or cache hit.

### 10.4 Runner Integration

Five functions: `_resolve_native_harness_source`,
`_ensure_native_harness_built`, `_parse_native_runner_output`,
`_run_single_native_test`, `_run_native_tests`.

Stage 7 gated on all six prior stages and `candidate.exe` existing.

### 10.5 Schema Extension

`native_test_results` array and seven native metric fields added to
`result_schema.json` (commit `a5d84da`). All optional. Verified committed:

```
$ python3 -c "... print('native_test_results' in j['properties'])"
True
$ git show a5d84da --stat | grep result_schema
  irx/experiment1/harness/result_schema.json | 34 ++
```

### 10.6 Result

All 10 native tests pass, bitwise-identical to lli.

---

## 11 Generation 8: Phase 2 Closure

Clean re-run from cleared artifact directory (2026-02-15 23:40 PST):

- All 7 stages PASS
- lli 10/10, native 10/10
- lli/native match: ALL 10 vectors agree
- IDs stable: `de499765...` / `4254c627...`
- Schema extension independently verified
- Unit tests: 13/13 passed

Closure record committed as `PHASE2_CLOSURE.md` (commit `5201dd2`).

---

## 12 Generation 9: Verdict Fix

### 12.1 Problem

The JSON artifact hardcoded `"verdict": "ERROR"` regardless of stage
outcomes. The verdict was derived from `gates.policy.ok`, which was always
`False`. This meant a fully passing run was recorded as `ERROR`.

### 12.2 Solution

Added `compute_verdict(runs, metrics, gates)` — a pure function at line 73
of `phase2_runner.py`:

```python
def compute_verdict(runs, metrics, gates) -> tuple[str, str]:
    executed = [r for r in runs
                if r["exit_code"] is not None
                or r["duration_ms"] > 0
                or r["crash"] is not None]

    for r in executed:
        if not r["ok"]:
            return ("FAIL", "STAGE_FAILED:" + r["stage"])

    if metrics.get("tests_failed", 0) > 0:
        return ("FAIL", "LLI_TESTS_FAILED")
    if metrics.get("native_tests_failed", 0) > 0:
        return ("FAIL", "NATIVE_TESTS_FAILED")

    if not executed:
        return ("ERROR", "NO_STAGES_EXECUTED")

    if all(r["ok"] for r in runs) and ...:
        return ("PASS", "ALL_STAGES_PASS")

    return ("ERROR", "INDETERMINATE_VERDICT")
```

The verdict detail is appended to `gates.policy.detail` as
`;verdict=ALL_STAGES_PASS` (or the corresponding failure/error reason).
`gates.policy.ok` is set to `True` when verdict is `"PASS"`.

No schema changes were needed: the `verdict` field was already an enum of
`["PASS", "FAIL", "ERROR"]`, and `gates.policy.detail` is a string.

### 12.3 What Changed

- `phase2_runner.py`: added `compute_verdict()`, replaced hardcoded
  `"verdict": "ERROR"` with computed verdict, updated `gates.policy`
- `tests/test_verdict.py`: 8 new hermetic unit tests covering PASS, FAIL
  (stage, lli, native), and ERROR (no stages) cases
- No frozen artifacts, schema, stage pipeline, env, limits, or per-test
  logic modified

### 12.4 Verification

Post-fix evidence run:

```
verdict: PASS
candidate_id: de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6
run_id:       4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60
policy.ok: True
policy.detail (tail): verdict=ALL_STAGES_PASS
jsonschema: VALID
```

All stage results, test outcomes, IDs, and work artifact sizes unchanged.
The only field that changed in the JSON output is `verdict` (`"ERROR"` →
`"PASS"`) and `gates.policy` (`.ok` now `True`, `.detail` has
`;verdict=ALL_STAGES_PASS` appended).

---

## 13 lli vs. Native Result Agreement

All 10 vectors produce bitwise-identical results:

| Vector | ret | out_hex | Description |
|--------|-----|---------|-------------|
| t01 | 4 | `00000000` | empty input, sum=0 |
| t02 | 4 | `01000000` | single value: 1 |
| t03 | 4 | `ffffffff` | single value: max |
| t04 | 4 | `03000000` | 1+2=3 |
| t05 | 4 | `00000000` | 0+0=0 |
| t06 | 4 | `78563412` | 0x12345678 |
| t07 | 4 | `00000000` | overflow to 0 |
| t08 | 4 | `feffffff` | overflow (corrected) |
| t09 | -1 | *(empty)* | ERR_INVALID_INPUT |
| t10 | 4 | `0a000000` | 1+2+3+4=10 |

---

## 14 Metrics Summary

```
lli:    10/10 passed, 0 failed, 0 mismatches, 0 timeouts, 0 crashes
native: 10/10 passed, 0 failed, 0 mismatches, 0 timeouts, 0 crashes
verdict: PASS (ALL_STAGES_PASS)
```

### 14.1 Deterministic IDs

```
candidate_id: de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6
run_id:       4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60
```

Stable across every run throughout the project.

---

## 15 Work Artifacts

| File | Size | Format |
|------|------|--------|
| `work/candidate.ll` | 1 232 bytes | LLVM IR text |
| `work/candidate.bc` | 1 928 bytes | LLVM bitcode |
| `work/candidate.o` | 1 008 bytes | aarch64 ELF relocatable |
| `work/candidate.exe` | 2 304 bytes | aarch64 ELF freestanding |
| `harness/native/native_runner` | 13 064 bytes | aarch64 ELF harness |

---

## 16 Stub Candidate Baseline

Minimal stub (`ret i64 0`) confirms gate behavior:

| Stage | ok | Notes |
|-------|----|-------|
| precheck | true | |
| llvm_as_parse | true | exit=0 |
| opt_verify | true | exit=0 |
| lli_tests | false | 0/10, all RETURN_MISMATCH |
| llc_compile | false | NOT_RUN |
| clang_link | false | NOT_RUN |
| native_tests | false | NOT_RUN |

Verdict: `"FAIL"` (STAGE_FAILED:lli_tests).

---

## 17 Unit Tests

21 hermetic tests across two files:

**`test_native_tests.py`** (13 tests):
- TestParseNativeRunnerOutput (8): success, negative, missing, invalid,
  empty, error, uppercase normalization
- TestResolveNativeHarnessSource (1): missing source
- TestNativeTestsGating (3): skeleton shape, all-stage gate, exe requirement
- TestNativeTestsNotRunWhenHarnessMissing (1): mocked resolve

**`test_verdict.py`** (8 tests):
- TestComputeVerdictPass (2): all pass, pass without native
- TestComputeVerdictFailStage (2): opt_verify fail, precheck fail
- TestComputeVerdictFailLliTests (1): lli failures
- TestComputeVerdictFailNativeTests (1): native failures
- TestComputeVerdictError (1): no stages executed
- TestComputeVerdictNotRunDownstream (1): partial with upstream failure

All 21 pass (< 0.01s).

---

## 18 Verification Fixtures and Evidence

### 18.1 Layout

```
irx/experiment1/
  PHASE2_CLOSURE.md                              Closure record
  pi_report.md                                   This report
  verification/
    README.md                                    Run instructions
    candidates/
      sum_u32_le_known_good.ll                   Stub for wiring checks
    evidence/
      STEP_F_EVIDENCE.md                         Step F/H PASS conditions
      step_f_check.sh                            A-F check
      step_h_check.sh                            A-H check
      logs/
        step_h_check_20260215_234036.log         Closure evidence
        step_h_check_verdictfix_20260215_235338.log  Verdict fix evidence
    step_f/
      sum_u32_le_good.ll                         Known-good candidate
  harness/native/
    native_runner.c                              Harness source
```

### 18.2 Reproduction

```bash
# Full A-H check
rm -rf irx/experiment1/runs/*
bash irx/experiment1/verification/evidence/step_h_check.sh

# Unit tests
python3 -m unittest runner/phase2/tests/test_native_tests.py
python3 -m unittest runner/phase2/tests/test_verdict.py

# Manual invocation
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/step_f/sum_u32_le_good.ll \
  --task sum_u32_le
```

---

## 19 Commit History

| Hash | Message |
|------|---------|
| `6b5a37f` | Fix LLVM tool execution in deterministic subprocess environment |
| `d5298ad` | phase2: unify llvm tool env and rss-only preexec |
| `b1679b0` | phase2: fix opt syntax, target triple key, schema detection, and wire lli harness |
| `31223ce` | exp1: fix sum_u32_le t08 expected_out_hex endianness (unblocks Step F) |
| `1153420` | exp1: add verification fixture directory and run instructions |
| `f0a6261` | exp1: add Step F evidence bundle and check script |
| `89e6f50` | docs: rewrite pi_report with Step F evidence and full verification history |
| `b0d8cd9` | exp1: implement Step G clang_link and rewrite pi_report |
| `a5d84da` | exp1: implement Step H native_tests and rewrite pi_report |
| `5201dd2` | exp1: Phase 2 closure record and Step H reproduction evidence |
| `8762240` | phase2: fix verdict computation from stage outcomes |

---

## 20 Properties Verified

1. **Determinism**: Subprocess environments derived from frozen artifacts.
   No host variables. Repeated runs produce identical IDs and
   (timestamp-masked) output.

2. **Isolation**: LLVM tools see four variables. Native harness sees three.
   No user environment leaks. clang_link and harness build use `-fuse-ld=lld`
   to avoid `PATH` dependency.

3. **Resource Limits**: `RLIMIT_RSS` at 64 MiB. `RLIMIT_AS` not applied.

4. **Schema Compliance**: All artifacts validate against the frozen schema.
   `jsonschema.validate()` confirms. No schema changes for the verdict fix.

5. **Gate Ordering**: Failure propagates NOT_RUN downstream. Confirmed with
   stub and known-good candidate.

6. **Artifact Integrity**: Each stage produces expected output at
   deterministic paths, verified non-empty before downstream proceeds.

7. **End-to-End**: Correct candidate traverses all seven stages.
   Interpreter and native results agree bitwise.

8. **Correct Verdict**: `compute_verdict` derives verdict from stage
   outcomes and test metrics, not from a hardcoded value. PASS when all
   stages succeed, FAIL when any fails, ERROR when no stages execute.

9. **Linker Determinism**: Both clang_link and harness build use
   `-fuse-ld=lld`, same output regardless of host `PATH`.

10. **Interpreter-Native Equivalence**: All 10 vectors produce identical
    results between lli and native, confirming the compilation pipeline
    preserves semantics on aarch64.

---

## Appendix A — LLVM Shared Library

```
Library:   /usr/lib/aarch64-linux-gnu/libLLVM.so.19.1 (123 MB)
Symlink:   /usr/lib/llvm-19/lib/libLLVM.so.19.1 -> ../../aarch64-linux-gnu/libLLVM.so.19.1
Derivation: frozen tool parent.parent / lib
```

## Appendix B — LLVM 19 Pass Manager

```
Legacy:  opt -verify -disable-output         -> Exit 1 (unsupported in LLVM 19)
New:     opt -passes=verify -disable-output   -> Exit 0
```

## Appendix C — t08 Byte Order Proof

```
Input:  ffffffffffffffff -> two u32: 0xFFFFFFFF + 0xFFFFFFFF
Sum:    0xFFFFFFFE (mod 2^32)
LE:     [FE, FF, FF, FF] -> "feffffff"  (correct)
BE:     [FF, FF, FF, FE] -> "fffffffe"  (original, incorrect)
```

## Appendix D — clang_link Flags

| Flag | Purpose |
|------|---------|
| `-target aarch64-unknown-linux-gnu` | From frozen `target.json` |
| `-fuse-ld=lld` | Colocated LLD; no PATH needed |
| `-nostdlib` | No CRT objects |
| `-Wl,--no-dynamic-linker` | No PT_INTERP |
| `-Wl,-e,f` | Entry point = `f` |

## Appendix E — Native Harness Flow

```
native_runner <exe> <in_hex> <out_cap> f
  -> open + mmap(PROT_READ)
  -> validate ELF64/LE/aarch64, reject relocations
  -> compute PT_LOAD extent, mmap(MAP_ANONYMOUS), memcpy, zero BSS
  -> __builtin___clear_cache (aarch64 icache coherence)
  -> mprotect per-segment
  -> .symtab lookup for "f" (fallback: e_entry)
  -> call fn(in_buf, in_len, out_buf, out_cap)
  -> printf RET=/OUT=
```

## Appendix F — Test Vectors (sum_u32_le)

```
t01: in=""                                 ret=4   out="00000000"
t02: in="01000000"                         ret=4   out="01000000"
t03: in="ffffffff"                         ret=4   out="ffffffff"
t04: in="0100000002000000"                 ret=4   out="03000000"
t05: in="0000000000000000"                 ret=4   out="00000000"
t06: in="78563412"                         ret=4   out="78563412"
t07: in="01000000ffffffff"                 ret=4   out="00000000"
t08: in="ffffffffffffffff"                 ret=4   out="feffffff"
t09: in="00000000ffffffff01000000"         ret=-1  out=""
t10: in="01000000020000000300000004000000" ret=4   out="0a000000"
```

## Appendix G — Verdict Logic (Before and After)

Before (hardcoded):
```python
"verdict": "ERROR",
# gates.policy.ok always False
```

After (computed):
```python
verdict_str, verdict_detail = compute_verdict(runs_skeleton, metrics_obj, gates_obj)
gates_obj["policy"]["ok"] = verdict_str == "PASS"
gates_obj["policy"]["detail"] = policy_base_detail + ";verdict=" + verdict_detail
# ...
"verdict": verdict_str,
```

---

*Verified on Raspberry Pi 5 — Raspberry Pi OS 64-bit — LLVM 19.1.7*
*Phase 2 complete through Step H: PASS*
*Verdict: PASS (ALL_STAGES_PASS)*
*lli/native agreement: ALL 10 vectors match*
