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
