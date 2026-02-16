# Phase 2 Runner - Step A

This module provides the Phase 2 Step A skeleton for Experiment 1.

Step A behavior:
- Loads frozen artifacts (tool snapshot, limits, schema, and test vectors).
- Discovers candidate `.ll` deterministically using explicit `--candidate`.
- Recovers authoritative `candidate_id` / `run_id` rules using repo evidence precedence:
  - explicit Phase 0/1 derivation rules if present
  - otherwise `irx/experiment1/runs/*/*.json` + `work/candidate.ll` evidence
- If a rule cannot be recovered, requires authoritative fallback CLI values:
  - `--candidate-id` and/or `--run-id`
- Emits seven Phase 2 run stages in NOT_RUN form when IDs are available:
  - `precheck`, `llvm_as_parse`, `opt_verify`, `lli_tests`, `llc_compile`, `clang_link`, `native_tests`
- Copies the candidate byte-for-byte to `irx/experiment1/runs/<candidate_id>/<run_id>/work/candidate.ll`.
- Emits a schema-validated result to `irx/experiment1/runs/<candidate_id>/<run_id>.json`.

No LLVM tools are executed in Step A.

## Run Step A

Run from repository root:

```bash
python3 runner/phase2/phase2_runner.py --candidate /path/to/candidate.ll
```

Authoritative fallback (only if inference cannot recover a rule):

```bash
python3 runner/phase2/phase2_runner.py --candidate /path/to/candidate.ll --candidate-id <id> --run-id <id>
```

## Determinism Check

Run Step A twice on the same candidate.
- Outputs should match except `timestamps.started_at` and `timestamps.finished_at`.
