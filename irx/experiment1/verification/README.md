# Experiment 1 Verification Fixtures

Test-only fixtures for exercising the Phase 2 pipeline (Steps A-F) on Raspberry Pi.
These are not task submissions.

## Candidates

- `candidates/sum_u32_le_known_good.ll` - Minimal stub (`ret i64 0`) for pipeline wiring checks.

## Running on Pi

From the repository root:

```bash
python3 -m py_compile runner/phase2/phase2_runner.py
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/candidates/sum_u32_le_known_good.ll \
  --task sum_u32_le
```

## Expected Outcomes

- **precheck, llvm_as_parse, opt_verify**: PASS for any syntactically valid IR.
- **lli_tests**: PASS only if the candidate correctly implements the task.
  The stub returns `0` for all inputs, so it will FAIL all 10 test vectors.
- **llc_compile**: Runs only when `lli_tests.ok=true`. A correct `sum_u32_le`
  implementation is required to exercise Step F end-to-end.
- **clang_link, native_tests**: Not yet wired in the runner.

## Step F Evidence

`evidence/step_f_check.sh` reproduces the full A-F pipeline run with the
known-good candidate and prints a summary (IDs, stage results, tests passed,
candidate.o size). See `evidence/STEP_F_EVIDENCE.md` for expected values and
PASS conditions.
