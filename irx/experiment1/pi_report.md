# IR Experiments — Experiment 1 — Raspberry Pi Phase 2 Report

**Platform**: Raspberry Pi 5 (Cortex-A76, aarch64)
**OS**: Raspberry Pi OS 64-bit (Debian-based), kernel 6.12.47+rpt-rpi-2712
**LLVM**: Debian LLVM 19.1.7 (Optimized build)
**Target triple**: `aarch64-unknown-linux-gnu`
**Phase 2 closure**: 2026-02-15 (HEAD `5201dd2`)
**Verdict fix**: 2026-02-15 (HEAD `8762240`)
**Latest evidence run**: 2026-02-16 00:05 PST (HEAD `b00ab95`)

---

## 1 Purpose

This document is the single long-form record for Experiment 1, Phase 2
on Raspberry Pi 5. It traces the project from its first failed run
through Phase 2 closure and a subsequent correctness fix to the verdict
field. The latest clean evidence run confirms that the pipeline produces
a schema-valid JSON artifact recording `"verdict": "PASS"` when every
stage succeeds.

---

## 2 Timeline

| Gen | Milestone | Key change | Commit |
|-----|-----------|------------|--------|
| 1 | Environment fix | `LD_LIBRARY_PATH` derivation, RSS-only limits | `6b5a37f` |
| 2 | Re-verification | Confirmed llvm-as/opt, determinism | `d5298ad` |
| 3 | Full sweep | opt syntax, triple key, schema `$ref`, lli harness | `b1679b0` |
| 4 | Authority revision | t08 `expected_out_hex` corrected to LE | `31223ce` |
| 5 | Step F evidence | llc_compile produces `candidate.o` | `f0a6261` |
| 6 | Step G | clang_link produces `candidate.exe` | `b0d8cd9` |
| 7 | Step H | native_tests: custom ELF loader, 10/10 pass | `a5d84da` |
| 8 | Phase 2 closure | Clean re-run, closure record | `5201dd2` |
| 9 | Verdict fix | `compute_verdict()` replaces hardcoded `"ERROR"` | `8762240` |
| 10 | Final evidence | Preflight + full A-H + verdict proof | `b00ab95` |

---

## 3 Pipeline

### 3.1 Stages

| # | Stage | Tool | Gate |
|---|-------|------|------|
| 0 | `precheck` | static analysis | — |
| 1 | `llvm_as_parse` | `llvm-as` | precheck.ok |
| 2 | `opt_verify` | `opt -passes=verify` | parse.ok, .bc exists |
| 3 | `lli_tests` | `lli` + shim | verify.ok, harness resolved |
| 4 | `llc_compile` | `llc -filetype=obj` | lli.ok, .bc exists |
| 5 | `clang_link` | `clang` + LLD | llc.ok, .o exists |
| 6 | `native_tests` | native harness | clang.ok, .exe exists |

All LLVM tools at `/usr/lib/llvm-19/bin/`. Each stage gates on every
prior stage passing; failure propagates NOT_RUN downstream.

### 3.2 Subprocess Environment

LLVM tools: `LC_ALL=C LANG=C TZ=UTC LD_LIBRARY_PATH=/usr/lib/llvm-19/lib`
(derived from `parent.parent / lib` of frozen tool path).

clang_link adds `-fuse-ld=lld` (env has no `PATH`; clang spawns a child
linker).

native_tests: `LC_ALL=C LANG=C TZ=UTC` only (harness depends on libc
alone).

### 3.3 Resource Limits

`RLIMIT_RSS` at 64 MiB. `RLIMIT_AS` not applied (`libLLVM.so.19.1` is
123 MB and must be memory-mapped).

### 3.4 ID Derivation

```
candidate_id = sha256(file bytes of candidate.ll)
run_id       = sha256(candidate_id as UTF-8 string)
```

Frozen in `harness/id_rules.json`.

### 3.5 Verdict Computation

`compute_verdict(runs, metrics, gates)` derives the verdict from actual
stage outcomes:

| Condition | Verdict | Detail |
|-----------|---------|--------|
| Any executed stage `ok=False` | FAIL | `STAGE_FAILED:<name>` |
| `tests_failed > 0` | FAIL | `LLI_TESTS_FAILED` |
| `native_tests_failed > 0` | FAIL | `NATIVE_TESTS_FAILED` |
| No stages executed | ERROR | `NO_STAGES_EXECUTED` |
| All stages ok, zero failures | PASS | `ALL_STAGES_PASS` |
| Otherwise | ERROR | `INDETERMINATE_VERDICT` |

Detail is appended to `gates.policy.detail` as `;verdict=<detail>`.
`gates.policy.ok` is `True` when verdict is PASS.

---

## 4 Frozen Artifacts

### 4.1 Tools (`env/tool_versions.json`)

| Tool | Path | Version |
|------|------|---------|
| llvm-as | `/usr/lib/llvm-19/bin/llvm-as` | 19.1.7 |
| opt | `/usr/lib/llvm-19/bin/opt` | 19.1.7 |
| lli | `/usr/lib/llvm-19/bin/lli` | 19.1.7 |
| llc | `/usr/lib/llvm-19/bin/llc` | 19.1.7 |
| clang | `/usr/lib/llvm-19/bin/clang` | 19.1.7 (Debian) |

### 4.2 Limits (`harness/constants.json`)

| Limit | Value | Where |
|-------|-------|-------|
| `max_ll_bytes` | 65 536 | precheck |
| `max_ll_lines` | 2 000 | precheck |
| `timeout_stage_ms` | 1 000 | llvm_as, opt, llc, clang |
| `timeout_per_test_ms` | 50 | lli_tests, native_tests |
| `max_rss_mib` | 64 | all stages |

Error codes: `ERR_INVALID_INPUT` (-1), `ERR_OUTPUT_TOO_SMALL` (-2),
`ERR_INTERNAL` (-3).

### 4.3 Target (`env/target.json`)

```json
{"os": "raspios64", "arch": "aarch64", "triple": "aarch64-unknown-linux-gnu", "endian": "little"}
```

### 4.4 Schema (`harness/result_schema.json`)

Top-level `additionalProperties: false`. Required keys: `experiment`,
`task`, `candidate_id`, `run_id`, `timestamps`, `gates`, `runs`,
`metrics`, `verdict`. Optional: `test_results`, `native_test_results`.

`verdict` enum: `"PASS"`, `"FAIL"`, `"ERROR"`.

`metrics` carries seven required lli counters and seven optional native
counters (added in `a5d84da`).

### 4.5 ABI

```
i64 @f(ptr %in_ptr, i32 %in_len, ptr %out_ptr, i32 %out_cap)
```

lli harness: `harness/lli_abi_runner.py` + `harness/lli_shim/shim.bc`.
Native harness: `harness/native/native_runner.c` (421 lines, libc only).
Both emit `RET=<i64>` / `OUT=<hex>` on stdout.

---

## 5 Generation 1: Environment Fix

llvm-as failed at runtime:

```
rc=127; error while loading shared libraries: libLLVM.so.19.1:
failed to map segment from shared object
```

Causes: (1) no `LD_LIBRARY_PATH` in cleared env, (2) `RLIMIT_AS` at
64 MiB, too low for the 123 MB library.

Fix: `_derive_llvm_lib_path` derives `LD_LIBRARY_PATH` from
`parent.parent / lib`. `_build_llvm_tool_preexec` applies `RLIMIT_RSS`
only.

---

## 6 Generation 2: Re-verification

Confirmed: py_compile OK, tool paths present, precheck pass,
llvm_as_parse exit=0, `candidate.bc` produced (1 388 bytes), determinism
verified (`IDS_MATCH=True`, `MASKED_JSON_EQUAL=True`). opt_verify failed
(cause identified in Generation 3).

---

## 7 Generation 3: Full Sweep

Four gaps found and patched (all in `phase2_runner.py`, no frozen
artifacts changed):

1. **opt syntax**: `opt -verify` → `opt -passes=verify` (LLVM 19 new
   pass manager)
2. **Triple key**: `target_triple` → accept both `target_triple` and
   `triple`
3. **Schema detection**: Resolve `$ref`, check `index` not `test_id`
4. **lli harness**: Replace hardcoded failure with actual harness
   invocation (`_run_lli_tests`)

Post-patch: Steps A-E PASS. Stub candidate correctly fails 10/10
(RETURN_MISMATCH), gating downstream.

---

## 8 Generation 4: t08 Byte Order

Known-good `sum_u32_le` candidate scored 9/10. Sole failure at t08:

```
expected: "fffffffe"  (BE notation of 0xFFFFFFFE)
actual:   "feffffff"  (LE byte encoding)
```

Every other vector used LE encoding. Single-field correction in
`tests.json` (commit `31223ce`).

Proof: `0xFFFFFFFF + 0xFFFFFFFF = 0xFFFFFFFE mod 2^32`. LE store:
`[FE, FF, FF, FF]` → `"feffffff"`.

---

## 9 Generation 5: Step F — llc_compile

Known-good candidate (`verification/step_f/sum_u32_le_good.ll`, 42 lines,
1 232 bytes) achieved 10/10 lli pass. llc produced `candidate.o`
(1 008 bytes, aarch64 ELF relocatable):

```
llc -filetype=obj -mtriple=aarch64-unknown-linux-gnu -O0 -o candidate.o candidate.bc
```

---

## 10 Generation 6: Step G — clang_link

The candidate exports only `@f` (no `main`, no `_start`). Bare
`clang -o candidate.exe candidate.o` fails (undefined `_start`).

Solution:

```
clang -target aarch64-unknown-linux-gnu -fuse-ld=lld -nostdlib \
      -Wl,--no-dynamic-linker -Wl,-e,f -o candidate.exe candidate.o
```

`-fuse-ld=lld` required because the env has no `PATH` — clang needs to
find its colocated `ld.lld`. Output: `candidate.exe` (2 304 bytes),
freestanding ELF with `f` as entry point.

---

## 11 Generation 7: Step H — native_tests

### 11.1 Problem

`dlopen`/`dlsym` cannot work: `f` is in `.symtab` only (`.dynsym` has
only the null entry).

### 11.2 Native Harness

`native_runner.c` (421 lines) implements a minimal ELF64 loader:

- Validates ELF64/LSB/aarch64, rejects relocations
- Maps `PT_LOAD` segments into anonymous memory
- `__builtin___clear_cache` for aarch64 icache coherence
- `.symtab` symbol lookup; entry-point fallback for `"f"`
- Calls `f(in_buf, in_len, out_buf, out_cap)`, prints `RET=`/`OUT=`

Build (cached, mtime-based):

```
clang -O2 -Wall -Wextra -Werror -std=c11 -fno-omit-frame-pointer \
      -fuse-ld=lld -o native_runner native_runner.c
```

Selftest validates hex roundtrip after every build or cache hit.

### 11.3 Runner Integration

Five functions: `_resolve_native_harness_source`,
`_ensure_native_harness_built`, `_parse_native_runner_output`,
`_run_single_native_test`, `_run_native_tests`. Stage 7 gated on all
prior stages and `candidate.exe` existing.

### 11.4 Schema Extension

`native_test_results` array and seven native metric fields added
(commit `a5d84da`, `result_schema.json | 34 ++`). All optional;
pre-Step-H artifacts remain valid.

---

## 12 Generation 8: Phase 2 Closure

Clean re-run (2026-02-15 23:40 PST) from cleared artifact directory:

- All 7 stages PASS
- lli 10/10, native 10/10
- lli/native match: ALL 10 vectors agree
- IDs stable
- Schema extension independently verified as committed
- 13 unit tests pass

Closure record: `PHASE2_CLOSURE.md` (commit `5201dd2`).

---

## 13 Generation 9: Verdict Fix

### 13.1 Problem

The JSON artifact hardcoded `"verdict": "ERROR"` because it was derived
from `gates.policy.ok`, which was always `False`. A fully passing run
was incorrectly recorded as ERROR.

### 13.2 Fix

Added `compute_verdict(runs, metrics, gates)` at line 73 of
`phase2_runner.py`. Pure function, no side effects:

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
    if all(r["ok"] for r in runs) and zero test failures:
        return ("PASS", "ALL_STAGES_PASS")
    return ("ERROR", "INDETERMINATE_VERDICT")
```

Verdict detail appended to `gates.policy.detail` as
`;verdict=ALL_STAGES_PASS`. `gates.policy.ok` set to `True` when PASS.

No schema changes. No stage pipeline, env, limit, or per-test logic
changes. 8 unit tests added (`test_verdict.py`).

### 13.3 Before/After

| Field | Before | After |
|-------|--------|-------|
| `verdict` | `"ERROR"` (hardcoded) | `"PASS"` (computed) |
| `gates.policy.ok` | `False` (hardcoded) | `True` (when all pass) |
| `gates.policy.detail` tail | stage details only | `...;verdict=ALL_STAGES_PASS` |

---

## 14 Generation 10: Final Evidence Run

Preflight on Pi (2026-02-16 00:05 PST):

```
Branch: main, HEAD: b00ab95
py_compile: OK
compute_verdict_present: True
Unit tests: 13 native + 8 verdict = 21/21 pass
Toolchain: llvm-as/opt/lli/llc/clang all 19.1.7
```

Clean A-H run:

```
precheck             ok=True
llvm_as_parse        ok=True   exit=0
opt_verify           ok=True   exit=0
lli_tests            ok=True   exit=0
llc_compile          ok=True   exit=0
clang_link           ok=True   exit=0
native_tests         ok=True   exit=0

lli tests:    10/10 passed, 0 failed
native tests: 10/10 passed, 0 failed
lli/native match: ALL 10 tests agree
```

Verdict proof from newest artifact:

```
verdict: PASS
gates.policy.ok: True
gates.policy.detail_tail: ...;verdict=ALL_STAGES_PASS
candidate_id_match: True
run_id_match: True
```

Work artifact sizes: `candidate.bc` 1 928, `candidate.o` 1 008,
`candidate.exe` 2 304 bytes — unchanged from all prior runs.

Evidence log: `verification/evidence/logs/step_h_check_verdictfix_20260216_000503.log`

---

## 15 lli / Native Agreement

| Vector | ret | out_hex | Description |
|--------|-----|---------|-------------|
| t01 | 4 | `00000000` | empty input, sum=0 |
| t02 | 4 | `01000000` | single 1 |
| t03 | 4 | `ffffffff` | single max |
| t04 | 4 | `03000000` | 1+2=3 |
| t05 | 4 | `00000000` | 0+0=0 |
| t06 | 4 | `78563412` | 0x12345678 |
| t07 | 4 | `00000000` | overflow to 0 |
| t08 | 4 | `feffffff` | overflow (corrected) |
| t09 | -1 | *(empty)* | ERR_INVALID_INPUT |
| t10 | 4 | `0a000000` | 1+2+3+4=10 |

All 10 vectors bitwise-identical between lli and native. The LLVM
compilation pipeline (llvm-as → opt → llc → clang/lld) preserves
candidate semantics on aarch64 for the tested domain.

---

## 16 Metrics

```
lli:    10/10 passed, 0 failed, 0 mismatches, 0 timeouts, 0 crashes
native: 10/10 passed, 0 failed, 0 mismatches, 0 timeouts, 0 crashes
verdict: PASS (ALL_STAGES_PASS)
```

### 16.1 Deterministic IDs

```
candidate_id: de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6
run_id:       4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60
```

Stable across every run throughout the project.

---

## 17 Work Artifacts

| File | Size | Format |
|------|------|--------|
| `work/candidate.ll` | 1 232 bytes | LLVM IR text |
| `work/candidate.bc` | 1 928 bytes | LLVM bitcode |
| `work/candidate.o` | 1 008 bytes | aarch64 ELF relocatable |
| `work/candidate.exe` | 2 304 bytes | aarch64 ELF freestanding |
| `harness/native/native_runner` | 13 064 bytes | aarch64 ELF harness |

---

## 18 Stub Candidate Baseline

Minimal stub (`ret i64 0`) confirms gate behavior and verdict logic:

| Stage | ok | Notes |
|-------|----|-------|
| precheck | true | |
| llvm_as_parse | true | exit=0 |
| opt_verify | true | exit=0 |
| lli_tests | false | 0/10, RETURN_MISMATCH |
| llc_compile | false | NOT_RUN |
| clang_link | false | NOT_RUN |
| native_tests | false | NOT_RUN |

Verdict: `"FAIL"` (`STAGE_FAILED:lli_tests`).

---

## 19 Unit Tests

21 hermetic tests, two files, no Pi toolchain required:

**`test_native_tests.py`** (13):
- Output parsing: success, negative ret, missing ret/out, invalid format,
  empty, error code, uppercase normalization
- Harness resolution: missing source
- Gating: skeleton shape, all-stage gate, exe requirement, missing harness

**`test_verdict.py`** (8):
- PASS: all ok; pass without native metrics
- FAIL: stage failure (opt_verify, precheck); lli failures; native failures
- ERROR: no stages executed
- FAIL: partial execution with upstream failure

All 21 pass (< 0.01s).

---

## 20 Evidence and Reproduction

### 20.1 Evidence Logs

| Log | Date | Context |
|-----|------|---------|
| `step_h_check_20260215_234036.log` | 2026-02-15 | Phase 2 closure |
| `step_h_check_verdictfix_20260215_235338.log` | 2026-02-15 | Verdict fix validation |
| `step_h_check_verdictfix_20260216_000503.log` | 2026-02-16 | Final preflight + evidence |

### 20.2 Reproduction Commands

```bash
# Full A-H evidence check
rm -rf irx/experiment1/runs/*
bash irx/experiment1/verification/evidence/step_h_check.sh

# Unit tests
python3 -m unittest runner/phase2/tests/test_native_tests.py
python3 -m unittest runner/phase2/tests/test_verdict.py

# Manual invocation
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/step_f/sum_u32_le_good.ll \
  --task sum_u32_le

# Verify verdict in newest artifact
python3 -c "import json, glob, os
p = sorted(glob.glob('irx/experiment1/runs/*/*.json'),
           key=os.path.getmtime)[-1]
j = json.load(open(p))
print('verdict:', j['verdict'])"
```

### 20.3 Key Files

```
irx/experiment1/
  PHASE2_CLOSURE.md                  Closure record
  pi_report.md                       This report
  verification/
    evidence/
      step_f_check.sh                A-F check
      step_h_check.sh                A-H check
      logs/                          Evidence logs
    step_f/
      sum_u32_le_good.ll             Known-good candidate
  harness/
    native/native_runner.c           ELF loader harness
    result_schema.json               Frozen schema
    constants.json                   Frozen limits
    id_rules.json                    ID derivation rules
  env/
    tool_versions.json               Frozen tool paths
    target.json                      Target triple
runner/phase2/
  phase2_runner.py                   Pipeline runner
  tests/
    test_native_tests.py             13 harness/gating tests
    test_verdict.py                  8 verdict logic tests
```

---

## 21 Commit History

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
| `b00ab95` | docs: rewrite pi_report with verdict fix and complete Phase 2 history |

---

## 22 Properties Verified

1. **Determinism** — Environments derived from frozen artifacts. No host
   variables. Repeated runs produce identical IDs and output.

2. **Isolation** — LLVM tools: 4 env vars. Native harness: 3 env vars.
   clang_link and harness build use `-fuse-ld=lld` to avoid `PATH`.

3. **Resource Limits** — RSS at 64 MiB. AS not applied.

4. **Schema Compliance** — `jsonschema.validate()` confirms every
   artifact. No schema changes for the verdict fix.

5. **Gate Ordering** — Failure propagates NOT_RUN downstream. Confirmed
   with stub (0/10 → downstream NOT_RUN, verdict FAIL) and known-good
   (10/10 → all PASS, verdict PASS).

6. **Artifact Integrity** — `.bc`, `.o`, `.exe` produced at deterministic
   paths, verified non-empty before downstream stages.

7. **Interpreter-Native Equivalence** — All 10 vectors bitwise-identical
   between lli and native execution.

8. **Correct Verdict** — Computed from stage outcomes and test metrics.
   PASS when all succeed, FAIL when any fails, ERROR when no stages run.

9. **Linker Determinism** — `-fuse-ld=lld` for both clang_link and
   harness build. Same output regardless of host `PATH`.

10. **Authority Revision** — t08 correction was a single field in one
    file. No other vectors or semantics altered.

---

## Appendix A — clang_link Flags

| Flag | Why |
|------|-----|
| `-target aarch64-unknown-linux-gnu` | From `target.json` |
| `-fuse-ld=lld` | No `PATH` in env; colocated LLD |
| `-nostdlib` | No CRT objects (candidate has no `main`) |
| `-Wl,--no-dynamic-linker` | No PT_INTERP |
| `-Wl,-e,f` | Entry point = `f` |

## Appendix B — Native Harness Flow

```
native_runner <exe> <in_hex> <out_cap> f
  -> mmap file, validate ELF64/LE/aarch64
  -> reject relocations (fail closed)
  -> map PT_LOAD segments, zero BSS
  -> __builtin___clear_cache (aarch64 I/D cache incoherence)
  -> mprotect per-segment
  -> .symtab lookup "f" (fallback: e_entry)
  -> fn(in_buf, in_len, out_buf, out_cap)
  -> print RET=<ret> / OUT=<hex>
```

## Appendix C — t08 Byte Order

```
0xFFFFFFFF + 0xFFFFFFFF = 0xFFFFFFFE mod 2^32
LE: [FE,FF,FF,FF] -> "feffffff"  (correct)
BE: [FF,FF,FF,FE] -> "fffffffe"  (original, wrong)
```

## Appendix D — Test Vectors (sum_u32_le)

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

## Appendix E — LLVM 19 Pass Manager

```
opt -verify -disable-output         -> Exit 1 (unsupported)
opt -passes=verify -disable-output  -> Exit 0
```

## Appendix F — LLVM Shared Library

```
/usr/lib/aarch64-linux-gnu/libLLVM.so.19.1 (123 MB)
Symlink: /usr/lib/llvm-19/lib/libLLVM.so.19.1
Derived from: frozen tool path parent.parent / lib
```

---

*Raspberry Pi 5 — Raspberry Pi OS 64-bit — LLVM 19.1.7*
*Phase 2 complete through Step H — verdict: PASS (ALL_STAGES_PASS)*
*lli/native agreement: ALL 10 vectors match*
*Last verified: 2026-02-16 00:05 PST*
