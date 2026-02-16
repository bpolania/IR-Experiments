# Phase 2 Closure Record — Experiment 1

**Date**: 2026-02-15 23:40 PST
**Platform**: Raspberry Pi 5 (Cortex-A76, aarch64)
**OS**: Raspberry Pi OS 64-bit (Debian-based)
**Kernel**: 6.12.47+rpt-rpi-2712 (SMP PREEMPT, aarch64)
**LLVM**: Debian LLVM 19.1.7 (Optimized build)
**Target triple**: `aarch64-unknown-linux-gnu`
**HEAD at closure**: `a5d84da1b8ce89e9e38f3edb82192fd7fef5b1a5` (branch: `main`)

---

## Closure Statement

**Phase 2 complete through Step H: PASS**

All seven pipeline stages executed successfully on the known-good
`sum_u32_le` candidate. The LLVM interpreter (lli) and native execution
produce bitwise-identical results across all 10 frozen test vectors.

---

## Known-Good Candidate

**Path**: `irx/experiment1/verification/step_f/sum_u32_le_good.ll`

Deterministic IDs (confirmed across multiple independent runs):

```
candidate_id: de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6
run_id:       4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60
```

---

## Pipeline Stage Results

| Stage | ok | exit_code | Notes |
|-------|----|-----------|-------|
| precheck | true | — | bytes=1232/65536, lines=42/2000 |
| llvm_as_parse | true | 0 | candidate.bc produced |
| opt_verify | true | 0 | `-passes=verify` pass |
| lli_tests | true | 0 | 10/10 pass, 0 failures |
| llc_compile | true | 0 | candidate.o = 1 008 bytes |
| clang_link | true | 0 | candidate.exe = 2 304 bytes |
| native_tests | true | 0 | 10/10 pass, 0 failures |

---

## lli / Native Agreement

All 10 test vectors produce identical `actual_ret`, `actual_out_hex`, and
`outcome` between lli and native execution.

**lli/native match: ALL 10 tests agree**

---

## Authority Revision Note

Test vector t08 (`sum_u32_le`, index 7) had an incorrect `expected_out_hex`
value. The original `"fffffffe"` was big-endian notation; the correct
little-endian byte encoding is `"feffffff"`. This was a single-field
correction in `tasks/sum_u32_le/tests.json` (commit `31223ce`). No other
vectors, fields, or files were modified.

---

## Reproduction Commands

From the repository root:

```bash
# Full A-H evidence check (clean run)
rm -rf irx/experiment1/runs/*
bash irx/experiment1/verification/evidence/step_h_check.sh

# A-F subset check
rm -rf irx/experiment1/runs/*
bash irx/experiment1/verification/evidence/step_f_check.sh

# Unit tests (hermetic, no LLVM required)
python3 -m unittest runner/phase2/tests/test_native_tests.py

# Manual pipeline invocation
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/step_f/sum_u32_le_good.ll \
  --task sum_u32_le
```

---

## Tool Versions (frozen)

| Tool | Path | Version |
|------|------|---------|
| llvm-as | `/usr/lib/llvm-19/bin/llvm-as` | 19.1.7 |
| opt | `/usr/lib/llvm-19/bin/opt` | 19.1.7 |
| lli | `/usr/lib/llvm-19/bin/lli` | 19.1.7 |
| llc | `/usr/lib/llvm-19/bin/llc` | 19.1.7 |
| clang | `/usr/lib/llvm-19/bin/clang` | 19.1.7 (Debian) |

---

## Evidence Log

The clean re-run log is stored at:

```
irx/experiment1/verification/evidence/logs/step_h_check_20260215_234036.log
```

Unit test result: 13/13 passed (0.003s).

---

## Known Issues / Inconsistencies

### Schema Extension Claim

The pi_report states that `harness/result_schema.json` was extended in
Step H to add `native_test_results` and seven native metric fields.

**Verification result: CONFIRMED — no inconsistency.**

Evidence:

1. `result_schema.json` contains `native_test_results` in `properties` → `True`
2. Native metrics present in `properties.metrics.properties`:
   `native_tests_total`, `native_tests_passed`, `native_tests_failed`,
   `native_ret_mismatches`, `native_output_mismatches`, `native_timeouts`,
   `native_crashes`
3. The schema modification is part of commit `a5d84da` (the Step H commit),
   confirmed via `git show a5d84da --stat` showing
   `irx/experiment1/harness/result_schema.json | 34 ++`
4. `git log -n 20 -- irx/experiment1/harness/result_schema.json` shows three
   commits touching the file: `a5d84da`, `21d8c5a`, `681a6cd`

The report's claim is accurate and the schema extension is committed.

### Verdict Field

The result artifact records `"verdict": "ERROR"` despite all stages passing
and all tests succeeding (lli 10/10, native 10/10). The verdict logic in
the runner uses `gates.policy.ok` which is hardcoded `False` in the current
implementation. This is pre-existing behavior, not a regression from Step H.
The stage-level `ok` fields and test metrics are the authoritative pass/fail
indicators.

---

*Closure record generated on Raspberry Pi 5 at 2026-02-15 23:40 PST*
