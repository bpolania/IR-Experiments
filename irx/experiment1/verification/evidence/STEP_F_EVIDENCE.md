# Step F Evidence — Experiment 1

Proves that the Phase 2 pipeline produces `candidate.o` from a correct
`sum_u32_le` candidate on Raspberry Pi (aarch64, LLVM 19).

## Reproduction

From the repository root:

```bash
rm -rf irx/experiment1/runs/*
python3 -m py_compile runner/phase2/phase2_runner.py
python3 runner/phase2/phase2_runner.py \
  --candidate irx/experiment1/verification/step_f/sum_u32_le_good.ll \
  --task sum_u32_le
```

Or use the automated script:

```bash
bash irx/experiment1/verification/evidence/step_f_check.sh
```

## PASS Conditions

- `lli_tests`: `tests_passed == tests_total` (10/10)
- `llc_compile.ok == true`, `exit_code == 0`
- `work/candidate.o` exists and size > 0

## Expected IDs (deterministic)

- `candidate_id`: `de499765dfe2e94002b34a27d113273ffe5c4345c6463f665f87cc5b2fb610b6`
- `run_id`: `4254c62717bfc6fbabf0ca1cf107b9519e030649890ea8b3d8acf9c9367f5d60`

---

## Step H Addendum — native_tests

Step H extends the pipeline through native execution. After `clang_link`
produces `candidate.exe`, a native harness loads the ELF in-process,
calls `f()` with the same frozen test vectors, and validates outputs.

### Reproduction

```bash
bash irx/experiment1/verification/evidence/step_h_check.sh
```

### Additional PASS Conditions

- `native_tests.ok == true`, `exit_code == 0`
- `native_tests_passed == native_tests_total` (10/10)
- `work/candidate.exe` exists and size > 0
- All 10 native test results match the corresponding lli test results
  (same `actual_ret`, `actual_out_hex`, and `outcome` for each vector)
- Deterministic IDs unchanged from Step F
